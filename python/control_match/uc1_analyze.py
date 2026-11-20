#!/usr/bin/env python3
"""UC1 joint parsing, cost, deadline-audit, time-reference, and cross-mode analysis."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_match.analyze import capture_interval, discover
from control_match.control_engine import EngineConfig
from control_match.holdover_analyze import sha256, write_csv
from control_match.n3_holdover import SIDES, distribution, evaluate
from control_match.n5_analyze import missing_intervals, read_jsonl, recovery_rows
from control_match.plan_analyze import load_side, read_plan, summarize
from control_match.replay_engine import replay_records
from control_match.uc1_config import load as load_uc1_config


def ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (numerator / denominator) if denominator else None,
    }


def _fmt_ratio(r: dict) -> str:
    if not r["denominator"]:
        return f"N/A ({r['numerator']}/0)"
    return f"{r['numerator']}/{r['denominator']} ({100.0 * r['value']:.1f}%)"


def _quadrant(ble_ok: bool, zig_ok: bool) -> str:
    if ble_ok and zig_ok:
        return "both"
    if ble_ok:
        return "ble_only"
    if zig_ok:
        return "zigbee_only"
    return "neither"


def check_board_matches_manifest(cfg: dict, plan: dict, *, reconcile_board_budget: bool = False) -> dict | None:
    uc1 = plan.get("uc1")
    if not uc1:
        raise ValueError("board log does not contain UC1_CONFIG")
    layout = cfg["layout"]
    reconciliation = None
    if reconcile_board_budget:
        if cfg["policy"] != "k" or cfg["profile"] != "core":
            raise ValueError("board budget reconciliation requires a core explicit-K capture manifest")
        actual_budget = int(uc1["budget_us"])
        actual_unused = int(uc1["unused_per_task_us"])
        cost, k = cfg["cost_per_attempt_us"], cfg["k"]
        if (actual_budget <= cfg["budget_us"] or actual_budget // cost != k or
                actual_unused != actual_budget - k * cost):
            raise ValueError("board budget reconciliation cannot prove the recorded K/unused budget")
        reconciliation = {
            "kind": "board_budget_vs_capture_explicit_k",
            "original_manifest_sha256": cfg["sha256"],
            "capture_policy": cfg["policy"],
            "capture_budget_us": cfg["budget_us"],
            "board_budget_us": actual_budget,
            "board_unused_per_task_us": actual_unused,
            "policy_command_proven": False,
        }
    checks = (
        ("run_id", int(uc1["run_id"]), cfg["run_id"]),
        ("mode", int(uc1["mode"]), cfg["mode_code"]),
        ("profile", int(uc1["profile"]), cfg["profile_code"]),
        ("tasks", int(uc1["tasks"]), cfg["tasks_count"]),
        ("slots", int(uc1["slots"]), cfg["planned_slots"]),
        ("k", int(uc1["k"]), cfg["k"]),
        ("budget_us", int(uc1["budget_us"]), cfg["budget_us"]),
        ("cost_per_attempt_us", int(uc1["cost_per_attempt_us"]), cfg["cost_per_attempt_us"]),
        ("unused_per_task_us", int(uc1["unused_per_task_us"]), cfg["unused_per_task_us"]),
        ("ble_extra", int(uc1["ble_extra"]), layout["ble_extra"]),
        ("ieee_extra", int(uc1["ieee_extra"]), layout["ieee_extra"]),
        ("period_ms", int(uc1["period_ms"]), cfg["period_ms"]),
        ("marker_offset_valid", uc1["marker_offset_valid_bool"], layout["marker_offset_valid"]),
        ("marker_offset_us", uc1["ieee_marker_offset_us"], layout["marker_offset_us"]),
    )
    for name, actual, expected in checks:
        if actual != expected and not (reconciliation and name in ("budget_us", "unused_per_task_us")):
            raise ValueError(f"board UC1_CONFIG {name}={actual} differs from manifest {expected}")
    actual_tasks = {int(t["command_id"]): t for t in plan["tasks"]}
    if set(actual_tasks) != {t["command_id"] for t in cfg["tasks"]}:
        raise ValueError("board task IDs differ from UC1 manifest")
    for expected in cfg["tasks"]:
        actual = actual_tasks[expected["command_id"]]
        for key, value in expected.items():
            board_key = "repeats" if key == "attempts" else key
            if int(actual[board_key]) != value:
                raise ValueError(f"board task {expected['command_id']} {key} differs from manifest")
    return reconciliation


def _state_durations_ms(events: list[dict], total_samples: int, sample_rate: int) -> dict[str, float]:
    """Accumulate local-IQ duration spent in each ObservationClock state."""
    durations: dict[str, float] = {}
    state = "acquiring"
    last_sample = 0
    for e in events:
        if e.get("event") != "observation_transition":
            continue
        cur = int(e["local_sample"])
        if cur >= last_sample:
            durations[state] = durations.get(state, 0.0) + (cur - last_sample) * 1000.0 / sample_rate
            last_sample = cur
        state = e["state"]
    if total_samples >= last_sample:
        durations[state] = durations.get(state, 0.0) + (total_samples - last_sample) * 1000.0 / sample_rate
    return durations


def _side_deadline_class(
    decoded: bool,
    live_summary: dict | None,
    live_events: list[dict],
    command_id: int,
) -> tuple[str, str]:
    """Conservative per-side deadline audit; never fabricate from wall clock."""
    if not decoded:
        return "not_decoded", "not_decoded"
    if not live_summary or live_summary.get("external_reference_bound_ms") is None:
        return "unknown", "uncalibrated_reference_bound"
    cmd_events = [e for e in live_events if e.get("command_id") == command_id]
    if any(e.get("event") == "accepted" for e in cmd_events):
        return "on_time", "calibrated_bound_accepted"
    reasons = [e.get("reason") for e in cmd_events if e.get("event") == "rejected"]
    if reasons and all(r in ("expired", "late") for r in reasons):
        return "late", reasons[-1]
    return "unknown", reasons[-1] if reasons else "insufficient_reference_quality"


def _joint_deadline_class(ble_cls: str, zig_cls: str) -> str:
    if ble_cls == "not_decoded" or zig_cls == "not_decoded":
        return "not_decoded"
    if ble_cls == "on_time" and zig_cls == "on_time":
        return "on_time"
    if ble_cls == "late" or zig_cls == "late":
        return "late"
    return "unknown"


def run_analysis(
    root: Path,
    config_path: Path,
    output: Path,
    *,
    paths: dict[str, Path | None] | None = None,
    board: Path | None = None,
    allow_incomplete_board: bool = False,
    reconcile_board_budget: bool = False,
) -> dict:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing analysis directory: {output}")
    raw_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = load_uc1_config(config_path, raw_cfg["run_id"])
    run_id = cfg["run_id"]
    layout = cfg["layout"]
    frag_limits = cfg["fragment_limits"]

    board_path = board or (
        root / "board" / "serial.log" if (root / "board" / "serial.log").exists() else root / "board.board.log"
    )
    if not board_path.is_file():
        raise ValueError(f"missing board log: {board_path}")
    plan = read_plan(board_path, run_id, allow_incomplete=allow_incomplete_board)
    reconciliation = check_board_matches_manifest(cfg, plan,
                                                  reconcile_board_budget=reconcile_board_budget)

    expected_commands = {t["command_id"] for t in cfg["tasks"]}
    if cfg["profile"] == "time":
        expected_commands.add(0)

    sides, receivers, rates, streams, live_events, anomalies = {}, {}, {}, {}, {}, {}
    sources: dict[str, Path] = {"config": config_path, "board": board_path}
    for side in SIDES:
        pkt_path = (paths or {}).get(side) or discover(root, side)
        if pkt_path is None or not pkt_path.is_file():
            raise ValueError(f"missing capture artifact for {side}")
        sources[side] = pkt_path
        summary_path = pkt_path.with_name(pkt_path.name.replace(".packets.jsonl", ".summary.json"))
        if not summary_path.is_file():
            summary_path = pkt_path.with_name("rx.summary.json")
        if not summary_path.is_file():
            raise ValueError(f"missing receiver summary for {side}")
        sources[f"{side}_receiver"] = summary_path
        receiver = receivers[side] = json.loads(summary_path.read_text(encoding="utf-8"))
        recorded_sha = receiver.get("uc1_config_sha256")
        if recorded_sha is not None and recorded_sha != cfg["sha256"]:
            raise ValueError(f"{side} receiver uc1_config_sha256 disagrees with analysis manifest")
        rate = (receiver.get("config") or {}).get("sample_rate")
        if type(rate) is not int or rate <= 0:
            raise ValueError(f"{side}: invalid receiver sample_rate")
        rates[side] = rate
        data = sides[side] = load_side(
            pkt_path,
            side,
            run_id,
            expected_commands,
            layout=layout,
            fragment_limits=frag_limits,
            single_pass=True,
        )
        streams[side] = data["by_slot"]
        if data["live_path"]:
            sources[f"{side}_control_summary"] = data["live_path"]

        total = (receiver.get("counts") or {}).get("samples_processed", 0)
        raw_rows = read_jsonl(pkt_path)
        previous_avail = -1
        for row_idx, packet in enumerate(raw_rows, 1):
            start = packet.get("sample_start")
            avail = packet.get("available_sample")
            if (
                not isinstance(start, (int, float))
                or type(avail) is not int
                or not math.isfinite(start)
                or not 0 <= start <= avail <= total
                or avail < previous_avail
            ):
                raise ValueError(f"{side}: nonmonotonic or out-of-range availability at row {row_idx}")
            previous_avail = avail

        live_path = pkt_path.with_name(pkt_path.name.replace(".packets.jsonl", ".control.events.jsonl"))
        if not live_path.is_file():
            live_path = pkt_path.with_name("rx.control.events.jsonl")
        events = read_jsonl(live_path) if live_path.is_file() else []
        if live_path.is_file():
            sources[f"{side}_events"] = live_path
        regs = [e for e in events if e.get("event") == "registration"]
        if regs and (len(regs) != 1 or regs[0].get("registration") != cfg):
            raise ValueError(f"{side}: capture control registration differs from UC1 manifest")
        live_events[side] = events
        anomalies[side] = [e for e in events if e.get("event") == "timeline_anomaly"]
        if (
            receiver.get("status") != "complete"
            or receiver.get("error")
            or (receiver.get("capture_stats") or {}).get("queue_overflow")
        ):
            anomalies[side].append({"reason": "receiver_incomplete_or_overflow", "local_sample": total})

    # Live capture overlap check (offline IQ flagged explicitly)
    capture_evidence = "offline_input; independent physical reception not established"
    if all(not (receivers[s].get("config") or {}).get("iq_file") for s in SIDES):
        intervals = [capture_interval(sources[s]) for s in SIDES]
        if max(a for a, _ in intervals) >= min(b for _, b in intervals):
            raise ValueError("receiver capture windows do not overlap")
        capture_evidence = "overlapping_live_capture_intervals"

    integrity, slot_rows, base_tasks = summarize(plan, sides["ble"], sides["zigbee"])
    for row in slot_rows:
        slot = row["slot_index"]
        row["silent"] = plan["slots"][slot].get("silent", 0)
        row["quadrant"] = (
            "silent"
            if row["silent"]
            else _quadrant(bool(row["ble_valid"]), bool(row["zigbee_valid"]))
        )

    # Enrich per-task rows with all three required layers (first_attempt, within_planned_attempts, deadline_class)
    enriched_tasks = []
    first_quadrants = Counter()
    planned_quadrants = Counter()
    deadline_counts = Counter()
    ble_attempt_hist = Counter()
    zig_attempt_hist = Counter()

    for task in base_tasks:
        cmd = task["command_id"]
        first_slot = task["first_slot"]
        k = task["planned_attempts"]
        ble_first_ok = first_slot in streams["ble"]
        zig_first_ok = first_slot in streams["zigbee"]
        first_q = _quadrant(ble_first_ok, zig_first_ok)
        first_quadrants[first_q] += 1

        ble_any_ok = task["ble_valid_attempts"] > 0
        zig_any_ok = task["zigbee_valid_attempts"] > 0
        planned_q = _quadrant(ble_any_ok, zig_any_ok)
        planned_quadrants[planned_q] += 1

        ble_first_idx = (task["ble_first_valid_slot"] - first_slot + 1) if task["ble_first_valid_slot"] != "" else ""
        zig_first_idx = (task["zigbee_first_valid_slot"] - first_slot + 1) if task["zigbee_first_valid_slot"] != "" else ""
        if ble_first_idx != "":
            ble_attempt_hist[ble_first_idx] += 1
        if zig_first_idx != "":
            zig_attempt_hist[zig_first_idx] += 1

        ble_dl, ble_dl_reason = _side_deadline_class(ble_any_ok, sides["ble"]["live"], live_events["ble"], cmd)
        zig_dl, zig_dl_reason = _side_deadline_class(zig_any_ok, sides["zigbee"]["live"], live_events["zigbee"], cmd)
        joint_dl = _joint_deadline_class(ble_dl, zig_dl)
        deadline_counts[joint_dl] += 1

        different_slot_joint = int(
            ble_any_ok
            and zig_any_ok
            and task["same_attempt_joint_valid"] == 0
        )
        row = {
            **task,
            "ble_first_attempt_valid": int(ble_first_ok),
            "zigbee_first_attempt_valid": int(zig_first_ok),
            "joint_first_attempt_valid": int(ble_first_ok and zig_first_ok),
            "first_attempt_quadrant": first_q,
            "within_planned_attempts_quadrant": planned_q,
            "ble_first_valid_attempt_index": ble_first_idx,
            "zigbee_first_valid_attempt_index": zig_first_idx,
            "different_slot_joint": different_slot_joint,
            "ble_deadline_class": ble_dl,
            "ble_deadline_reason": ble_dl_reason,
            "zigbee_deadline_class": zig_dl,
            "zigbee_deadline_reason": zig_dl_reason,
            "joint_deadline_class": joint_dl,
        }
        enriched_tasks.append(row)

    n_tasks = len(enriched_tasks)
    joint_first_n = first_quadrants["both"]
    joint_planned_n = planned_quadrants["both"]
    joint_on_time_n = deadline_counts["on_time"]
    joint_late_n = deadline_counts["late"]
    joint_unknown_n = deadline_counts["unknown"]

    # Cost accounting (command vs pure time update vs unused budget)
    burst_rows = (plan.get("bursts") or {}).get("rows", [])
    command_slots = {
        s
        for t in cfg["tasks"]
        for s in range(t["first_slot"], t["first_slot"] + t["attempts"])
    }
    time_update_slots = {
        s for s, b in plan["slots"].items() if not b.get("silent") and s not in command_slots
    }
    cmd_submitted_us = sum(r["air_us"] for r in burst_rows if r["started"] and r["slot"] in command_slots)
    upd_submitted_us = sum(r["air_us"] for r in burst_rows if r["started"] and r["slot"] in time_update_slots)
    budget_us = reconciliation["board_budget_us"] if reconciliation else cfg["budget_us"]
    unused_per_task_us = (reconciliation["board_unused_per_task_us"] if reconciliation
                          else cfg["unused_per_task_us"])
    unused_total_us = cfg["tasks_count"] * unused_per_task_us

    wf_cost = dict(integrity["waveform_cost"])
    wf_cost.update(
        budget_per_task_us=budget_us,
        budget_total_us=cfg["tasks_count"] * budget_us,
        unused_budget_per_task_us=unused_per_task_us,
        unused_budget_total_us=unused_total_us,
        command_submitted_waveform_us=cmd_submitted_us,
        time_update_submitted_waveform_us=upd_submitted_us,
        planned_attempts=cfg["planned_attempts"],
        planned_time_updates=cfg["planned_time_updates"],
        planned_silent_slots=cfg["planned_silent_slots"],
        board_uc1_stats=plan.get("uc1_stats"),
    )

    ble_counts = sides["ble"]["counts"].get("all") or next(iter(sides["ble"]["counts"].values()), {})
    zig_counts = sides["zigbee"]["counts"].get("all") or next(iter(sides["zigbee"]["counts"].values()), {})

    # Optional time-profile support analysis (Section 7 of uc1_paper_experiment_plan.md)
    time_support = None
    extra_csvs: dict[str, list[dict]] = {}
    if cfg["profile"] == "time":
        missing_rows, recoveries, probe_rows, live_pairs = [], [], [], []
        state_durations = {}
        replay_events = []
        stale_ms = (cfg.get("observation_policy") or {}).get("stale_ms", 10000)
        for side in SIDES:
            rate = rates[side]
            total = (receivers[side].get("counts") or {}).get("samples_processed", 0)
            side_rec = recovery_rows(live_events[side], rate, side)
            max_slot = max(streams[side], default=None)
            last_valid_sample = max(
                (e["available_sample"] for e in streams[side].values() if e.get("available_sample") is not None),
                default=None,
            )
            near_plan_end = (
                max_slot is not None
                and (cfg["planned_slots"] - 1 - max_slot) * cfg["period_ms"] < stale_ms
            )
            for r in side_rec:
                is_tail = (
                    r.get("censor_reason") == "capture_end_without_recovery"
                    and last_valid_sample is not None
                    and r["stale_sample"] > last_valid_sample
                    and near_plan_end
                )
                r["scope"] = "post_run_tail" if is_tail else "in_schedule"
            recoveries.extend(side_rec)
            state_durations[side] = _state_durations_ms(live_events[side], total, rate)
            missing_rows.extend(
                dict(r, timeline_anomalies_present=bool(anomalies[side]))
                for r in missing_intervals(plan, streams[side], side)
            )
            for slot in cfg["probes"]:
                found = [e for e in live_events[side] if e.get("event") == "probe_score" and e.get("slot_index") == slot]
                e = found[0] if found else {}
                probe_rows.append(
                    dict(
                        e,
                        side=side,
                        slot_index=slot,
                        duplicates=max(0, len(found) - 1),
                        status=e.get(
                            "status",
                            "probe_missing" if slot not in streams[side] else "live_score_not_recorded",
                        ),
                        observation_mode=e.get("observation_mode", "not_measured"),
                    )
                )
            raw_rows = read_jsonl(sources[side])
            eng_cfg = EngineConfig(
                side=side,
                run_id=run_id,
                sample_rate=rate,
                target_ids=frozenset([1 if side == "ble" else 2]),
                uc1_config=cfg,
            )
            imm, _ = replay_records(raw_rows, eng_cfg, total, policy="immediate")
            replay_events.extend(dict(e, observation_mode="replay", deadline_assessed=False) for e in imm)

        for slot in cfg["probes"]:
            pair = {s: next(r for r in probe_rows if r["side"] == s and r["slot_index"] == slot) for s in SIDES}
            valid = all(r.get("status") == "scored" for r in pair.values())
            live_pairs.append(
                dict(
                    slot=slot,
                    relative_estimate_difference_ms=(
                        pair["ble"]["estimated_ms"] - pair["zigbee"]["estimated_ms"] if valid else None
                    ),
                    ble_status=pair["ble"]["status"],
                    zigbee_status=pair["zigbee"]["status"],
                )
            )

        scored_streams = {s: {} if anomalies[s] else streams[s] for s in SIDES}
        replay_validation, replay_stats = evaluate(cfg, scored_streams, rates)
        for row in replay_validation:
            row["observation_mode"] = "replay"
            for side in SIDES:
                if anomalies[side]:
                    row[side + "_status"] = "timeline_unverified"

        time_support = {
            "marker_offset_us": cfg["ieee_marker_offset_us"],
            "probes_count": len(cfg["probes"]),
            "state_durations_ms": state_durations,
            "recovery": {
                s: ratio(
                    sum(r["recovered_sample"] is not None for r in recoveries if r["side"] == s),
                    sum(r["side"] == s for r in recoveries),
                )
                for s in SIDES
            },
            "recovery_in_schedule": {
                s: ratio(
                    sum(r["recovered_sample"] is not None for r in recoveries if r["side"] == s and r.get("scope") == "in_schedule"),
                    sum(r["side"] == s and r.get("scope") == "in_schedule" for r in recoveries),
                )
                for s in SIDES
            },
            "post_run_tail_stale_events": {
                s: sum(r["side"] == s and r.get("scope") == "post_run_tail" for r in recoveries)
                for s in SIDES
            },
            "live_probe_summary": {
                s: {
                    "coverage": ratio(
                        sum(r.get("status") == "scored" for r in probe_rows if r["side"] == s),
                        len(cfg["probes"]),
                    ),
                    "residual_ms": distribution(
                        [r.get("residual_ms") for r in probe_rows if r["side"] == s]
                    ),
                    "update_age_ms": distribution(
                        [r.get("update_age_ms") for r in probe_rows if r["side"] == s]
                    ),
                }
                for s in SIDES
            },
            "live_pair_diff_ms": distribution([r["relative_estimate_difference_ms"] for r in live_pairs]),
            "replay_summary": replay_stats,
            "live_event_counts": {s: dict(Counter(e["event"] for e in live_events[s])) for s in SIDES},
            "live_rejection_reasons": {
                s: dict(Counter(e["reason"] for e in live_events[s] if "reason" in e)) for s in SIDES
            },
            "immediate_replay_processed": {
                s: sum(e.get("event") == "software_processed" for e in replay_events if e.get("side") == s)
                for s in SIDES
            },
        }
        extra_csvs = {
            "uc1.missing.csv": missing_rows,
            "uc1.recovery.csv": recoveries,
            "uc1.live_probes.csv": probe_rows,
            "uc1.live_pairs.csv": live_pairs,
            "uc1.replay_probes.csv": replay_validation,
            "uc1.replay_summary.csv": replay_stats,
            "uc1.transitions.csv": [
                e for s in SIDES for e in live_events[s] if e.get("event") == "observation_transition"
            ],
        }

    result = {
        "schema": "b2z_uc1_analysis_v1",
        "wire_format": "UC1",
        "wire_version": 1,
        "run_id": run_id,
        "config_sha256": cfg["sha256"],
        "phase": cfg.get("phase"),
        "stage": cfg.get("stage"),
        "rf_condition": cfg.get("rf_condition"),
        "block": cfg.get("block"),
        "point": cfg.get("point"),
        "profile": cfg["profile"],
        "mode": cfg["mode"],
        "policy": "board_budget_reconciled" if reconciliation else cfg["policy"],
        "policy_value": budget_us if reconciliation else cfg["policy_value"],
        "capture_policy": cfg["policy"],
        "reconciliation": reconciliation,
        "k": cfg["k"],
        "period_ms": cfg["period_ms"],
        "layout": layout,
        "capture_evidence": capture_evidence,
        "anomalies": anomalies,
        "first_attempt": {
            "joint": ratio(joint_first_n, n_tasks),
            "quadrants": {q: first_quadrants[q] for q in ("both", "ble_only", "zigbee_only", "neither")},
        },
        "within_planned_attempts": {
            "joint": ratio(joint_planned_n, n_tasks),
            "quadrants": {q: planned_quadrants[q] for q in ("both", "ble_only", "zigbee_only", "neither")},
            "different_slot_joint_tasks": sum(t["different_slot_joint"] for t in enriched_tasks),
            "ble_first_valid_attempt_hist": {str(k_idx): ble_attempt_hist[k_idx] for k_idx in sorted(ble_attempt_hist)},
            "zigbee_first_valid_attempt_hist": {str(k_idx): zig_attempt_hist[k_idx] for k_idx in sorted(zig_attempt_hist)},
        },
        "deadline_class": {
            "joint_on_time": ratio(joint_on_time_n, n_tasks),
            "joint_late": ratio(joint_late_n, n_tasks),
            "joint_unknown": ratio(joint_unknown_n, n_tasks),
            "joint_not_decoded": ratio(deadline_counts["not_decoded"], n_tasks),
            "method": cfg.get("deadline_method"),
            "audit_note": (
                "Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; "
                "decoded tasks without calibrated external reference bounds remain classified as unknown."
            ),
        },
        "joint_software_processed_tasks": integrity.get("joint_software_processed_tasks"),
        "waveform_cost": wf_cost,
        "ble_fragment_reassembly": ble_counts.get("fragment_reassembly"),
        "decode_invalid_counts": {
            "ble": ble_counts.get("invalid", {}),
            "zigbee": zig_counts.get("invalid", {}),
        },
        "receiver_configs": {s: receivers[s].get("config", {}) for s in SIDES},
        "receiver_quality": {
            s: {k: receivers[s].get(k) for k in ("status", "error", "counts", "capture_stats")}
            for s in SIDES
        },
        "board": plan["stats"],
        "uc1_board_config": plan["uc1"],
        "uc1_board_stats": plan["uc1_stats"],
        "time_support": time_support,
        "planned_task_semantics": [
            {key: value for key, value in task.items() if key != "attempts"}
            for task in cfg["tasks"]
        ],
        "tasks": enriched_tasks,
        "sources": {k: {"path": str(p.resolve()), "sha256": sha256(p)} for k, p in sources.items()},
        "analysis_sources": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
        "limitations": ([
            "Board budget reconstructed from serial log; capture manifest remains explicit-K and the original policy command is unproven. Do not treat this as a strictly matched confirmatory budget run."
        ] if reconciliation else []) + [
            "Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.",
            "Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.",
            "Software processing events are not physical actuator execution.",
            "LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.",
        ],
    }

    output.mkdir(parents=True)
    write_csv(output / "uc1.tasks.csv", enriched_tasks)
    write_csv(output / "uc1.slots.csv", slot_rows)
    write_csv(output / "uc1.bursts.csv", burst_rows)
    for fname, rows in extra_csvs.items():
        write_csv(output / fname, rows)
    (output / "uc1.config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "uc1.summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )

    unit_sub = wf_cost["per_joint_decoded_task"]["value_us"]
    unit_plan = wf_cost["per_joint_decoded_task_planned"]["value_us"]
    unit_comp = wf_cost["per_joint_decoded_task_completed"]["value_us"]
    lines = [
        f"# UC1 联合分析报告（Run {run_id}）",
        "",
        f"- 配置：`mode={cfg['mode']}`、`profile={cfg['profile']}`、`point={cfg['point']}`（`b={layout['ble_extra']}, z={layout['ieee_extra']}`）、`policy={cfg['policy']}`、`K={cfg['k']}`、`tasks={n_tasks}`、`slots={cfg['planned_slots']}`",
        f"- 采集证据：`{capture_evidence}`；时间轴异常：`{json.dumps(anomalies, ensure_ascii=False)}`",
        "",
        "## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）",
        "",
        f"1. **首次尝试 (`first_attempt`)**：{_fmt_ratio(result['first_attempt']['joint'])}；四类 `{result['first_attempt']['quadrants']}`",
        f"2. **计划尝试内 (`within_planned_attempts`)**：{_fmt_ratio(result['within_planned_attempts']['joint'])}；四类 `{result['within_planned_attempts']['quadrants']}`；异槽互补成功任务 `{result['within_planned_attempts']['different_slot_joint_tasks']}`",
        f"3. **截止期分类 (`deadline_class`)**：on_time={_fmt_ratio(result['deadline_class']['joint_on_time'])}，late={_fmt_ratio(result['deadline_class']['joint_late'])}，unknown={_fmt_ratio(result['deadline_class']['joint_unknown'])}，not_decoded={_fmt_ratio(result['deadline_class']['joint_not_decoded'])}",
        f"   - 审计说明：{result['deadline_class']['audit_note']}",
        "",
        "## 波形成本代理与预算（非实测 RF 时长）",
        "",
        f"- 计划波形预算：`{wf_cost['planned_waveform_us']} µs`；提交有效波形：`{wf_cost['submitted_waveform_us']} µs`；DMA 完成波形：`{wf_cost['completed_waveform_us']} µs`；零样本 padding：`{wf_cost['submitted_zero_padding_us']} µs`",
        f"- 命令尝试提交波形：`{wf_cost['command_submitted_waveform_us']} µs`；纯时间更新提交波形：`{wf_cost['time_update_submitted_waveform_us']} µs`；未用预算总计：`{wf_cost['unused_budget_total_us']} µs`（每任务 `{wf_cost['unused_budget_per_task_us']} µs`）",
        f"- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`{f'{unit_sub:.1f}' if unit_sub is not None else 'N/A'}` / `{f'{unit_plan:.1f}' if unit_plan is not None else 'N/A'}` / `{f'{unit_comp:.1f}' if unit_comp is not None else 'N/A'}` µs（分母 `{joint_planned_n}`）",
        f"- BLE 分片重组统计（C3）：`{json.dumps(result['ble_fragment_reassembly'], ensure_ascii=False)}`",
    ]
    if reconciliation:
        lines += ["", "## 配置校正审计", "",
                  f"- 接收端原 manifest SHA256：`{cfg['sha256']}`；原策略显式 K，原预算 `{cfg['budget_us']} µs`。",
                  f"- 板端记录预算 `{budget_us} µs`，每任务未用 `{unused_per_task_us} µs`；解析与成本使用原始逐包及板端日志，不改写捕获元数据。",
                  "- 原始板端命令未独立保存，预算策略本身不能追溯为已证明。此报告标记 board_budget_reconciled，不作严格同预算确认性比较。"]
    if time_support is not None:
        lines += [
            "",
            "## 时间参考支撑（固定 secondary JC）",
            "",
            f"- 布局标记位置差：`{time_support['marker_offset_us']} µs`（配置布局值，非 RF 测量校准）",
        ]
        for s in SIDES:
            cov = time_support["live_probe_summary"][s]["coverage"]
            rec = time_support["recovery"][s]
            rec_in = time_support["recovery_in_schedule"][s]
            tail_n = time_support["post_run_tail_stale_events"][s]
            res = time_support["live_probe_summary"][s]["residual_ms"]
            lines.append(
                f"- `{s}`：探测覆盖 {_fmt_ratio(cov)}；计划内恢复 {_fmt_ratio(rec_in)}（全录制含停发尾段 {_fmt_ratio(rec)}，停发尾段 stale={tail_n}）；"
                f"残差绝对值中位/P95/P99/最大 = {res['median_abs']}/{res['p95_abs']}/{res['p99_abs']}/{res['max_abs']} ms（n={res['n']}）"
            )
    lines += [
        "",
        "## 限制与口径",
        "",
        *[f"- {item}" for item in result["limitations"]],
        "",
    ]
    (output / "uc1.report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def compare_uc1(summaries: dict[str, dict], conditions: dict | None = None) -> dict:
    """Compare UC1 runs across modes (e.g. JC vs SC and/or JC vs LC)."""
    if "JC" not in summaries or len(summaries) < 2:
        raise ValueError("compare_uc1 requires JC and at least one baseline mode (SC and/or LC)")
    for mode, s in summaries.items():
        if s.get("schema") != "b2z_uc1_analysis_v1" or s.get("mode") != mode:
            raise ValueError(f"summary for {mode} is not a valid UC1 analysis summary")
    jc = summaries["JC"]
    differences: dict[str, list[str]] = {}
    comparisons: dict[str, dict] = {}
    for other_mode, other in summaries.items():
        if other_mode == "JC":
            continue
        diffs = []
        missing = []
        if jc.get("reconciliation") or other.get("reconciliation"):
            missing.append("reconciliation.policy_command")
        for key in ("profile", "policy", "period_ms", "rf_condition", "point"):
            if jc.get(key) != other.get(key):
                diffs.append(key)
        for key in ("ble_extra", "ieee_extra"):
            if jc["layout"].get(key) != other["layout"].get(key):
                diffs.append(f"layout.{key}")
        if jc["policy"] == "budget" and jc["waveform_cost"]["budget_per_task_us"] != other["waveform_cost"]["budget_per_task_us"]:
            diffs.append("budget_per_task_us")
        if jc["policy"] == "k" and jc["k"] != other["k"]:
            diffs.append("k")
        if len(jc["tasks"]) != len(other["tasks"]):
            diffs.append("tasks_count")
        if not jc.get("planned_task_semantics") or not other.get("planned_task_semantics"):
            missing.append("planned_task_semantics")
        elif jc["planned_task_semantics"] != other["planned_task_semantics"]:
            diffs.append("planned_task_semantics")
        for side in SIDES:
            a = (jc.get("receiver_configs") or {}).get(side) or {}
            b = (other.get("receiver_configs") or {}).get(side) or {}
            keys = ["sample_rate", "lna", "vga", "amp", "duration"]
            if side == "zigbee" or other_mode == "SC":
                keys += ["center_hz"]
            for k_name in keys:
                if a.get(k_name) is None or b.get(k_name) is None:
                    missing.append(f"receiver.{side}.{k_name}")
                elif a[k_name] != b[k_name]:
                    diffs.append(f"receiver.{side}.{k_name}")
        for field in ("topology", "tx_power", "firmware_build", "attenuation"):
            va = ((conditions or {}).get("JC") or {}).get(field)
            vb = ((conditions or {}).get(other_mode) or {}).get(field)
            if any(v is None or str(v).strip().upper() in ("", "TODO", "UNKNOWN") for v in (va, vb)):
                missing.append(f"conditions.{field}")
            elif va != vb:
                diffs.append(f"conditions.{field}")
        differences[f"JC_vs_{other_mode}"] = diffs

        r_jc = jc["within_planned_attempts"]["joint"]["value"]
        r_ot = other["within_planned_attempts"]["joint"]["value"]
        f_jc = jc["first_attempt"]["joint"]["value"]
        f_ot = other["first_attempt"]["joint"]["value"]
        c_jc = jc["waveform_cost"]["submitted_waveform_us"]
        c_ot = other["waveform_cost"]["submitted_waveform_us"]
        u_jc = jc["waveform_cost"]["per_joint_decoded_task"]["value_us"]
        u_ot = other["waveform_cost"]["per_joint_decoded_task"]["value_us"]
        comparisons[f"JC_vs_{other_mode}"] = {
            "recorded_conditions_match": False if diffs else None if missing else True,
            "conditions_status": "mismatch" if diffs else "unknown" if missing else "match",
            "missing_evidence": missing,
            "differences": diffs,
            "channel_confound": other_mode == "LC",
            "reliability_protocol_effect_identifiable": other_mode == "SC" and not diffs and not missing,
            "jc_minus_other_within_planned_rate": (r_jc - r_ot) if (r_jc is not None and r_ot is not None) else None,
            "jc_minus_other_first_attempt_rate": (f_jc - f_ot) if (f_jc is not None and f_ot is not None) else None,
            "jc_minus_other_submitted_waveform_us": c_jc - c_ot,
            "jc_minus_other_unit_cost_us": (u_jc - u_ot) if (u_jc is not None and u_ot is not None) else None,
            "jc_relative_unit_cost_change_pct": ((u_jc - u_ot) / u_ot * 100.0) if (u_jc is not None and u_ot) else None,
        }

    groups = {}
    for mode, s in summaries.items():
        wc = s["waveform_cost"]
        groups[mode] = {
            "run_id": s["run_id"],
            "k": s["k"],
            "first_attempt_joint": s["first_attempt"]["joint"],
            "within_planned_joint": s["within_planned_attempts"]["joint"],
            "deadline_on_time": s["deadline_class"]["joint_on_time"],
            "deadline_unknown": s["deadline_class"]["joint_unknown"],
            "planned_waveform_us": wc["planned_waveform_us"],
            "submitted_waveform_us": wc["submitted_waveform_us"],
            "unused_budget_total_us": wc["unused_budget_total_us"],
            "per_joint_decoded_task_us": wc["per_joint_decoded_task"]["value_us"],
            "ble_channel": s["layout"]["ble_channel"],
        }

    return {
        "schema": "b2z_uc1_comparison_v1",
        "point": jc["point"],
        "policy": jc["policy"],
        "groups": groups,
        "comparisons": comparisons,
        "limitations": [
            "JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.",
            "Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.",
            "Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.",
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment-dir", type=Path)
    p.add_argument("--config", type=Path, help="Frozen UC1 manifest JSON")
    p.add_argument("--analysis-id", help="New analysis subdirectory name under experiment-dir/analyses/")
    p.add_argument("--board-log", type=Path)
    p.add_argument("--ble-packets", type=Path)
    p.add_argument("--zigbee-packets", type=Path)
    p.add_argument("--allow-incomplete-board", action="store_true")
    p.add_argument("--reconcile-board-budget", action="store_true",
                   help="Explicitly audit core explicit-K capture manifest against larger board budget; original files remain unchanged")
    p.add_argument("--compare-jc", type=Path, help="uc1.summary.json for JC")
    p.add_argument("--compare-sc", type=Path, help="uc1.summary.json for SC")
    p.add_argument("--compare-lc", type=Path, help="uc1.summary.json for LC")
    p.add_argument("--conditions", type=Path, help="Physical conditions JSON; omitted evidence leaves comparison fairness unknown")
    p.add_argument("--output-dir", type=Path, help="Output directory for --compare-* mode")
    a = p.parse_args(argv)

    if a.compare_jc is not None:
        if a.output_dir is None:
            p.error("--output-dir is required with --compare-jc")
        if a.output_dir.exists():
            p.error(f"refusing to overwrite {a.output_dir}")
        summaries = {"JC": json.loads(a.compare_jc.read_text(encoding="utf-8"))}
        if a.compare_sc:
            summaries["SC"] = json.loads(a.compare_sc.read_text(encoding="utf-8"))
        if a.compare_lc:
            summaries["LC"] = json.loads(a.compare_lc.read_text(encoding="utf-8"))
        conds = json.loads(a.conditions.read_text(encoding="utf-8")) if a.conditions else None
        comp = compare_uc1(summaries, conds)
        a.output_dir.mkdir(parents=True)
        (a.output_dir / "uc1.comparison.json").write_text(
            json.dumps(comp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        lines = [
            f"# UC1 跨模式对比（点 {comp['point']}，策略 {comp['policy']}）",
            "",
            "| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |",
            "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for mode, row in comp["groups"].items():
            unit = row["per_joint_decoded_task_us"]
            lines.append(
                f"| {mode} | {row['run_id']} | {row['k']} | {_fmt_ratio(row['first_attempt_joint'])} | "
                f"{_fmt_ratio(row['within_planned_joint'])} | {row['submitted_waveform_us']} | "
                f"{row['unused_budget_total_us']} | {f'{unit:.1f}' if unit is not None else 'N/A'} | {row['ble_channel']} |"
            )
        lines += ["", "## 配对差值", ""]
        for label, c_row in comp["comparisons"].items():
            lines.append(
                f"- **{label}**：条件状态={c_row['conditions_status']}，信道混杂={c_row['channel_confound']}，"
                f"具备协议归因条件={c_row['reliability_protocol_effect_identifiable']}，"
                f"计划内解析率差={c_row['jc_minus_other_within_planned_rate']}，"
                f"提交波形差={c_row['jc_minus_other_submitted_waveform_us']} µs，"
                f"差异项={c_row['differences'] or '无'}，缺失证据={c_row['missing_evidence'] or '无'}"
            )
        lines += ["", *[f"- {item}" for item in comp["limitations"]], ""]
        (a.output_dir / "uc1.comparison.md").write_text("\n".join(lines), encoding="utf-8")
        print(json.dumps(comp["comparisons"], ensure_ascii=False))
        return 0

    if not a.experiment_dir or not a.config or not a.analysis_id:
        p.error("--experiment-dir, --config, and --analysis-id are required")
    if Path(a.analysis_id).name != a.analysis_id or a.analysis_id in (".", ".."):
        p.error("analysis-id must be a single directory name")
    out = a.experiment_dir / "analyses" / a.analysis_id
    res = run_analysis(
        a.experiment_dir,
        a.config,
        out,
        paths={"ble": a.ble_packets, "zigbee": a.zigbee_packets},
        board=a.board_log,
        allow_incomplete_board=a.allow_incomplete_board,
        reconcile_board_budget=a.reconcile_board_budget,
    )
    print(
        json.dumps(
            {
                "run_id": res["run_id"],
                "mode": res["mode"],
                "first_attempt": res["first_attempt"]["joint"],
                "within_planned": res["within_planned_attempts"]["joint"],
                "deadline_unknown": res["deadline_class"]["joint_unknown"],
                "output": str(out),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
