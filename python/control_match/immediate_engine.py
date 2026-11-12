"""Decode and process one receiver's first valid command at availability.

This is the no-synchronization software baseline. It does not estimate sender
time, enforce a time deadline, or represent a physical actuator event.
"""
from __future__ import annotations

import math

try:
    from .control_engine import EngineConfig
    from .protocol import control_record
except ImportError:
    from control_engine import EngineConfig
    from protocol import control_record


_TASK_FIELDS = ("version", "flags", "run_id", "period_ms", "command_id",
                "target_id", "opcode", "arg", "execute_at_ms", "valid_until_ms")


class ImmediateControlEngine:
    """Use the same decoded record and target rules, without a time model."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.current_sample = 0
        self.signatures: dict[int, tuple] = {}
        self.status: dict[int, str] = {}
        self.state: dict[int, int] = {}
        self.triggers: list[dict] = []

    def _event(self, kind: str, sample: int, record: dict | None = None, **extra) -> dict:
        event = {"event": kind, "side": self.config.side,
                 "sender_id": self.config.sender_id, "run_id": self.config.run_id,
                 "local_sample": sample, "timeline": "local_iq_sample_domain",
                 "software_only": True, "policy": "immediate_no_sync"}
        if record is not None:
            event.update(command_id=record["command_id"], slot_index=record["slot_index"],
                         target_id=record["target_id"], opcode=record["opcode"],
                         arg=record["arg"], ref_tick_ms=record["ref_tick_ms"],
                         execute_at_ms=record["execute_at_ms"],
                         valid_until_ms=record["valid_until_ms"])
        event.update(extra)
        return event

    def advance(self, current_sample: int) -> list[dict]:
        if not isinstance(current_sample, int) or current_sample < self.current_sample:
            raise ValueError("current_sample must advance monotonically")
        self.current_sample = current_sample
        return []

    def observe(self, payload: bytes, packet_start_sample: float,
                available_sample: int) -> list[dict]:
        if (not isinstance(available_sample, int) or available_sample < self.current_sample or
                not math.isfinite(packet_start_sample) or packet_start_sample < 0 or
                packet_start_sample > available_sample):
            raise ValueError("invalid packet or availability sample")
        self.advance(available_sample)
        try:
            record = control_record(payload, self.config.side)
        except (ValueError, TypeError) as exc:
            return [self._event("invalid_record", available_sample, reason=str(exc))]
        if record["run_id"] != self.config.run_id:
            return [self._event("foreign_run", available_sample, record,
                                observed_run_id=record["run_id"])]
        events = [self._event("decoded", available_sample, record,
                              packet_start_sample=packet_start_sample)]
        if record["version"]==2:
            events.append(self._event("rejected", available_sample, record, reason="capacity_decode_only"))
            return events
        if record["flags"] == 0:
            events.append(self._event("time_update_ignored", available_sample, record))
            return events
        command_id = record["command_id"]
        signature = tuple(record[key] for key in _TASK_FIELDS)
        if command_id in self.signatures and self.signatures[command_id] != signature:
            events.append(self._event("rejected", available_sample, record,
                                      reason="conflicting_task"))
            return events
        self.signatures[command_id] = signature
        if command_id in self.status:
            events.append(self._event("duplicate", available_sample, record,
                                      task_status=self.status[command_id]))
            return events
        if (record["target_id"] not in self.config.target_ids and
                not (record["target_id"] == 0xffff and self.config.accept_broadcast)):
            events.append(self._event("rejected", available_sample, record,
                                      reason="wrong_target"))
            return events
        if record["opcode"] not in self.config.supported_opcodes:
            events.append(self._event("rejected", available_sample, record,
                                      reason="unsupported"))
            return events
        self.status[command_id] = "processed"
        events.append(self._event("accepted", available_sample, record,
                                  deadline_status="not_evaluated_no_time_reference"))
        if record["opcode"] == 1:
            self.state[record["target_id"]] = record["arg"]
        elif record["opcode"] == 2:
            self.triggers.append({"target_id": record["target_id"], "arg": record["arg"],
                                  "local_sample": available_sample})
        events.append(self._event("software_processed", available_sample, record,
                                  packet_start_sample=packet_start_sample,
                                  availability_delay_ms=(available_sample - packet_start_sample) *
                                                        1000 / self.config.sample_rate,
                                  deadline_status="not_evaluated_no_time_reference"))
        return events

    def snapshot(self) -> dict:
        return {"side": self.config.side, "run_id": self.config.run_id,
                "current_sample": self.current_sample,
                "task_status": {str(key): value for key, value in self.status.items()},
                "software_state": dict(self.state), "software_triggers": list(self.triggers),
                "time_model": None, "deadline_policy": "not_evaluated_no_time_reference"}
