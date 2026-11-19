"""One receiver's sample-domain clock and v1 software-control state machine.

Input bytes must come from this side's own CRC/FCS-valid PHY decoder. A caller
supplies the sample index at which the decoded record became available; packet
start alone is not a valid command-decision time. No wall-clock or other-side
observation is used here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Literal

try:
    from .protocol import control_record
except ImportError:
    from protocol import control_record


Side = Literal["ble", "zigbee"]
_TASK_FIELDS = ("version", "flags", "run_id", "period_ms", "command_id",
                "target_id", "opcode", "arg", "execute_at_ms", "valid_until_ms")
_UC1_TASK_FIELDS = _TASK_FIELDS + ("extra_len", "extra_hex")


@dataclass(frozen=True)
class EngineConfig:
    side: Side
    run_id: int
    sample_rate: int
    target_ids: frozenset[int]
    sender_id: str = "configured_board"
    accept_broadcast: bool = False
    supported_opcodes: frozenset[int] = frozenset((0, 1, 2))
    # This must include the unknown planned-TX-to-RF and receiver marker bias.
    # None means the time reference is uncalibrated: timed processing is denied.
    external_reference_bound_ms: float | None = None
    max_uncertainty_ms: float = 50.0
    drift_bound_ppm: float = 100.0
    min_rate_span_ms: int = 1000
    max_rate_ppm: float = 2000.0
    max_innovation_ms: float = 50.0
    history_size: int = 16
    guard_ms: float = 10.0
    freeze_ms: float = 100.0
    max_processing_late_ms: float = 50.0
    n5_registration: dict | None = None
    uc1_config: dict | None = None

    def __post_init__(self) -> None:
        if self.side not in ("ble", "zigbee") or not 1 <= self.run_id <= 65535:
            raise ValueError("side and run_id must identify one receiver run")
        if self.sample_rate <= 0 or not self.sender_id:
            raise ValueError("sample_rate and sender_id are required")
        if self.n5_registration is not None and self.uc1_config is not None:
            raise ValueError("cannot combine n5_registration and uc1_config")
        if any(not 1 <= target <= 0xfffe for target in self.target_ids):
            raise ValueError("target_ids must be configured v1 node/group IDs")
        if not self.supported_opcodes <= {0, 1, 2}:
            raise ValueError("unsupported opcode configuration")
        for value in (self.max_uncertainty_ms, self.drift_bound_ppm,
                      self.max_rate_ppm, self.max_innovation_ms, self.guard_ms,
                      self.freeze_ms, self.max_processing_late_ms):
            if not math.isfinite(value) or value < 0:
                raise ValueError("time policy values must be finite and nonnegative")
        if (self.external_reference_bound_ms is not None and
                (not math.isfinite(self.external_reference_bound_ms) or
                 self.external_reference_bound_ms < 0)):
            raise ValueError("external reference bound must be finite and nonnegative")
        if self.history_size < 2 or self.min_rate_span_ms <= 0:
            raise ValueError("history and rate span must be positive")


class _LocalClock:
    """Fit sender planned milliseconds to this receiver's IQ sample index."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.points: dict[int, tuple[int, float]] = {}
        self.version = 0
        self.nominal_slope = config.sample_rate / 1000.0
        self.slope = self.nominal_slope
        self.intercept = 0.0
        self.residual_ms = 0.0
        self.rate_fitted = False
        if config.uc1_config is not None:
            layout = config.uc1_config.get("layout") or {}
            if layout.get("marker_offset_valid") and layout.get("marker_offset_us") is not None:
                self.marker_offset_us: int | None = int(layout["marker_offset_us"])
                self.marker_offset_samples: float | None = (
                    0.0 if config.side == "ble" else config.sample_rate * self.marker_offset_us / 1_000_000
                )
            else:
                self.marker_offset_us = None
                self.marker_offset_samples = None
        elif config.n5_registration is not None:
            self.marker_offset_us = int(config.n5_registration.get("ieee_marker_offset_us", 472))
            self.marker_offset_samples = (
                0.0 if config.side == "ble" else config.sample_rate * self.marker_offset_us / 1_000_000
            )
        else:
            # The ZigBee PHY preamble begins 472 us after the BLE preamble in v1.
            self.marker_offset_us = 472
            self.marker_offset_samples = (0.0 if config.side == "ble" else
                                          config.sample_rate * 472 / 1_000_000)

    @property
    def latest_ref_ms(self) -> int | None:
        return max((ref for ref, _ in self.points.values()), default=None)

    def predict_sample(self, sender_ms: float) -> float:
        return self.intercept + self.slope * sender_ms

    def sender_ms(self, sample: float) -> float:
        return (sample - self.intercept) / self.slope

    def uncertainty_ms(self, sender_ms: float) -> float | None:
        bound = self.config.external_reference_bound_ms
        if bound is None or not self.points:
            return None
        age = max(0.0, sender_ms - self.latest_ref_ms)
        return bound + self.residual_ms + age * self.config.drift_bound_ppm / 1_000_000

    def observe(self, slot: int, ref_ms: int, packet_start_sample: float) -> str:
        if self.marker_offset_samples is None:
            return "clock_layout_unavailable"
        sample = packet_start_sample - self.marker_offset_samples
        if slot in self.points:
            old_ref, old_sample = self.points[slot]
            return "clock_duplicate" if (old_ref, old_sample) == (ref_ms, sample) else "conflicting_slot"
        if self.points:
            innovation_ms = abs(sample - self.predict_sample(ref_ms)) / self.nominal_slope
            if innovation_ms > self.config.max_innovation_ms:
                return "clock_outlier"
        candidate = dict(self.points)
        candidate[slot] = (ref_ms, sample)
        # Keep the most recently observed distinct slots. Arrival, not slot,
        # determines when a point can influence the model.
        candidate = dict(list(candidate.items())[-self.config.history_size:])
        ordered = sorted(candidate.values())
        if len(ordered) > 1 and ordered[-1][0] - ordered[0][0] >= self.config.min_rate_span_ms:
            mean_x = sum(x for x, _ in ordered) / len(ordered)
            mean_y = sum(y for _, y in ordered) / len(ordered)
            variance = sum((x - mean_x) ** 2 for x, _ in ordered)
            slope = sum((x - mean_x) * (y - mean_y) for x, y in ordered) / variance
            if abs(slope / self.nominal_slope - 1) * 1_000_000 > self.config.max_rate_ppm:
                return "clock_rate_outlier"
            intercept = mean_y - slope * mean_x
            rate_fitted = True
        else:
            slope = self.nominal_slope
            intercept = sum(y - slope * x for x, y in ordered) / len(ordered)
            rate_fitted = False
        self.points = candidate
        self.slope = slope
        self.intercept = intercept
        self.rate_fitted = rate_fitted
        self.residual_ms = max(abs(y - self.predict_sample(x)) / self.nominal_slope
                               for x, y in ordered)
        self.version += 1
        return "clock_updated"

    def details(self) -> dict:
        return {"model_version": self.version, "training_packets": len(self.points),
                "latest_ref_ms": self.latest_ref_ms,
                "training_span_ms": (max(x for x, _ in self.points.values()) -
                                     min(x for x, _ in self.points.values())) if self.points else 0,
                "rate_fitted": self.rate_fitted,
                "rate_ppm": (self.slope / self.nominal_slope - 1) * 1_000_000,
                "residual_ms": self.residual_ms}


@dataclass
class _Task:
    record: dict
    signature: tuple
    target_sample: int
    frozen: bool = False
    status: str = "pending"


class SideControlEngine:
    """Pure sample-domain engine; returned events are software-only evidence."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.registration = (
            config.n5_registration
            if config.n5_registration is not None
            else config.uc1_config
            if (
                config.uc1_config is not None
                and config.uc1_config.get("profile") == "time"
                and (config.uc1_config.get("layout") or {}).get("marker_offset_valid")
            )
            else None
        )
        self.clock = _LocalClock(config)
        if self.registration is not None:
            try:
                from .n5_observation import ObservationClock
            except ImportError:
                from control_match.n5_observation import ObservationClock
            self.clock = ObservationClock(config, self.registration)
        self.current_sample = 0
        self.tasks: dict[int, _Task] = {}
        self.signatures: dict[int, tuple] = {}
        self.conflicted_tasks: set[int] = set()
        self.state: dict[int, int] = {}
        self.triggers: list[dict] = []

    def _event(self, event: str, sample: int, record: dict | None = None, **fields) -> dict:
        result = {"event": event, "side": self.config.side, "sender_id": self.config.sender_id,
                  "run_id": self.config.run_id, "local_sample": sample,
                  "timeline": "local_iq_sample_domain", "software_only": True,
                  "model_version": self.clock.version}
        if record is not None:
            result.update(command_id=record["command_id"], slot_index=record["slot_index"],
                          target_id=record["target_id"], opcode=record["opcode"], arg=record["arg"])
            if record.get("wire_format") == "UC1":
                result.update(wire_format="UC1", wire_version=record.get("wire_version", 1))
        result.update(fields)
        return result

    def _observation_events(self):
        events = []
        while self.clock.transitions:
            transition = self.clock.transitions.pop(0)
            sample = transition.pop("local_sample")
            events.append(self._event("observation_transition", sample, **transition))
        return events

    def timeline_event(self, reason, *, restart=False):
        if self.registration is None:
            return []
        self.clock.invalidate()
        events = self._observation_events()
        events.append(self._event("timeline_anomaly", self.current_sample, reason=reason,
                                  segment=self.clock.segment))
        for task in self.tasks.values():
            if task.status == "pending":
                task.status = "cancelled"
                events.append(self._event("cancelled", self.current_sample, task.record,
                                          reason="timeline_unverified"))
        if restart:
            self.current_sample = 0
            self.clock.restart()
            events.extend(self._observation_events())
        return events

    def _quality(self, sender_ms: float) -> float | None:
        value = self.clock.uncertainty_ms(sender_ms)
        return value if value is not None and value <= self.config.max_uncertainty_ms else None

    def _refresh_pending(self, sample: int) -> list[dict]:
        events = []
        now_ms = self.clock.sender_ms(sample)
        for task in self.tasks.values():
            if task.status != "pending" or task.frozen:
                continue
            if now_ms >= task.record["execute_at_ms"] - self.config.freeze_ms:
                task.frozen = True
                events.append(self._event("schedule_frozen", sample, task.record,
                                          target_sample=task.target_sample))
                continue
            new_target = round(self.clock.predict_sample(task.record["execute_at_ms"]))
            if new_target != task.target_sample:
                old_target, task.target_sample = task.target_sample, new_target
                events.append(self._event("rescheduled", sample, task.record,
                                          old_target_sample=old_target, target_sample=new_target))
        return events

    def advance(self, current_sample: int) -> list[dict]:
        """Advance one receiver timeline; emit due software action or cancellation."""
        if not isinstance(current_sample, int) or current_sample < self.current_sample:
            raise ValueError("current_sample must advance monotonically")
        self.current_sample = current_sample
        events = []
        if self.registration is not None:
            self.clock.advance(current_sample)
            events.extend(self._observation_events())
        for task in self.tasks.values():
            if task.status != "pending":
                continue
            target_ms = task.record["execute_at_ms"]
            bound = self._quality(target_ms)
            if bound is None:
                task.status = "cancelled"
                events.append(self._event("cancelled", current_sample, task.record,
                                          reason="time_quality_insufficient"))
                continue
            if not task.frozen and self.clock.sender_ms(current_sample) >= target_ms - self.config.freeze_ms:
                task.frozen = True
                events.append(self._event("schedule_frozen", current_sample, task.record,
                                          target_sample=task.target_sample))
            if current_sample < task.target_sample:
                continue
            lateness_ms = (current_sample - task.target_sample) * 1000 / self.config.sample_rate
            if lateness_ms > self.config.max_processing_late_ms:
                task.status = "cancelled"
                events.append(self._event("cancelled", current_sample, task.record,
                                          reason="processing_late", lateness_ms=lateness_ms))
                continue
            task.status = "processed"
            record = task.record
            if record["opcode"] == 1:
                self.state[record["target_id"]] = record["arg"]
            elif record["opcode"] == 2:
                self.triggers.append({"target_id": record["target_id"],
                                      "arg": record["arg"], "local_sample": current_sample})
            events.append(self._event("software_processed", current_sample, record,
                                      target_sample=task.target_sample,
                                      lateness_ms=lateness_ms, uncertainty_ms=bound))
        return events

    def observe(self, payload: bytes, packet_start_sample: float,
                available_sample: int, *, timing_eligible_override: bool | None = None) -> list[dict]:
        """Consume independently decoded application bytes at availability time."""
        if (not isinstance(available_sample, int) or available_sample < self.current_sample or
                not math.isfinite(packet_start_sample) or packet_start_sample < 0 or
                packet_start_sample > available_sample):
            raise ValueError("invalid packet or availability sample")
        events = self.advance(available_sample)
        layout = self.config.uc1_config["layout"] if self.config.uc1_config is not None else None
        try:
            record = control_record(payload, self.config.side, layout=layout)
        except (ValueError, TypeError) as exc:
            events.append(self._event("invalid_record", available_sample, reason=str(exc)))
            return events
        if record["run_id"] != self.config.run_id:
            events.append(self._event("foreign_run", available_sample, record,
                                      observed_run_id=record["run_id"]))
            return events
        is_uc1 = record.get("wire_format") == "UC1"
        timing_eligible = True if not is_uc1 else bool(record.get("timing_eligible"))
        if timing_eligible_override is False:
            timing_eligible = False
        decoded_extra = {"packet_start_sample": packet_start_sample}
        if is_uc1:
            decoded_extra["timing_eligible"] = timing_eligible
            decoded_extra["layout_match"] = record.get("layout_match")
        events.append(self._event("decoded", available_sample, record, **decoded_extra))
        if record["version"] in (2, 3):
            # Capacity blobs have no scheduled application handler. In particular,
            # IEEE cannot infer the BLE record length from its own payload.
            events.append(self._event("rejected", available_sample, record,
                                      reason="capacity_decode_only"))
            return events
        command_id = record["command_id"]
        sig_fields = _UC1_TASK_FIELDS if is_uc1 else _TASK_FIELDS
        signature = tuple(record[key] for key in sig_fields) if record["flags"] else None
        if ((is_uc1 and command_id in self.conflicted_tasks) or
                (signature is not None and command_id in self.signatures and
                 self.signatures[command_id] != signature)):
            self.conflicted_tasks.add(command_id)
            existing = self.tasks.get(command_id)
            if is_uc1 and existing and existing.status == "pending":
                existing.status = "cancelled"
                events.append(self._event("cancelled", available_sample, existing.record,
                                          reason="conflicting_task"))
            extra = {"already_processed": True} if (existing and existing.status == "processed") else {}
            events.append(self._event("rejected", available_sample, record,
                                      reason="conflicting_task", **extra))
            return events

        if is_uc1 and not timing_eligible:
            skip_reason = (
                "layout_missing" if layout is None
                else "layout_mismatch" if record.get("layout_match") is False
                else "layout_not_timing_eligible"
            )
            events.append(self._event("clock_skipped", available_sample, record, reason=skip_reason))
            if record["flags"] == 0:
                return events
            self.signatures[command_id] = signature
            task = self.tasks.get(command_id)
            if task is not None:
                events.append(self._event("duplicate", available_sample, record, task_status=task.status))
                return events
            if (record["target_id"] not in self.config.target_ids and
                    not (record["target_id"] == 0xffff and self.config.accept_broadcast)):
                reason = "wrong_target"
            elif record["opcode"] not in self.config.supported_opcodes:
                reason = "unsupported"
            else:
                reason = "timing_layout_unavailable"
            events.append(self._event("rejected", available_sample, record, reason=reason))
            return events

        if self.registration is not None:
            if record["period_ms"] != self.registration["period_ms"]:
                events.append(self._event("rejected", available_sample, record, reason="registration_period_mismatch"))
                return events
            if record["slot_index"] in self.registration["probes"]:
                events.append(self._event("probe_score", available_sample,
                                          **self.clock.score(record["slot_index"], packet_start_sample)))
        clock_status = self.clock.observe(record["slot_index"], record["ref_tick_ms"],
                                          packet_start_sample)
        events.append(self._event(clock_status, available_sample, record,
                                  sample_start=packet_start_sample, available_sample=available_sample,
                                  **self.clock.details()))
        if self.registration is not None:
            events.extend(self._observation_events())
        if clock_status == "clock_updated":
            events.extend(self._refresh_pending(available_sample))
            events.extend(self.advance(available_sample))
        if record["flags"] == 0:
            return events
        self.signatures[command_id] = signature
        task = self.tasks.get(command_id)
        if task is not None:
            events.append(self._event("duplicate", available_sample, record,
                                      task_status=task.status))
            return events
        if is_uc1 and command_id in self.conflicted_tasks:
            events.append(self._event("rejected", available_sample, record, reason="conflicting_task"))
            return events
        if (record["target_id"] not in self.config.target_ids and
                not (record["target_id"] == 0xffff and self.config.accept_broadcast)):
            reason = "wrong_target"
        elif record["opcode"] not in self.config.supported_opcodes:
            reason = "unsupported"
        elif clock_status in ("clock_outlier", "clock_rate_outlier", "conflicting_slot", "clock_layout_unavailable"):
            reason = "time_quality_insufficient"
        else:
            now_ms = self.clock.sender_ms(available_sample)
            now_bound = self._quality(now_ms)
            execute_bound = self._quality(record["execute_at_ms"])
            if now_bound is None or execute_bound is None:
                reason = "time_quality_insufficient"
            elif now_ms - now_bound > record["valid_until_ms"]:
                reason = "expired"
            elif now_ms + now_bound > record["valid_until_ms"]:
                reason = "time_quality_insufficient"
            elif now_ms + now_bound + self.config.guard_ms >= record["execute_at_ms"]:
                reason = "late"
            else:
                reason = None
        if reason is not None:
            events.append(self._event("rejected", available_sample, record, reason=reason))
            return events
        target_sample = round(self.clock.predict_sample(record["execute_at_ms"]))
        self.tasks[command_id] = _Task(record, signature, target_sample)
        events.append(self._event("accepted", available_sample, record,
                                  target_sample=target_sample, uncertainty_ms=execute_bound))
        events.append(self._event("scheduled", available_sample, record,
                                  target_sample=target_sample))
        return events

    def snapshot(self) -> dict:
        """Expose state for reports without implying physical execution."""
        return {"side": self.config.side, "run_id": self.config.run_id,
                "current_sample": self.current_sample, "clock": self.clock.details(),
                "task_status": {str(key): task.status for key, task in self.tasks.items()},
                "conflicted_tasks": sorted(self.conflicted_tasks),
                "software_state": dict(self.state), "software_triggers": list(self.triggers)}
