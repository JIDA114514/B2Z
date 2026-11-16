#!/usr/bin/env python3
"""N5 task-rule ablation on two independently decoded saved receiver streams.

All changed deadlines, availability times and reference bounds are synthetic.
No IQ, receiver packet file, board log or existing analysis is modified.
"""
from __future__ import annotations

import argparse
import binascii
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess

from .analyze import discover
from .control_engine import EngineConfig, SideControlEngine
from .holdover_analyze import write_csv
from .immediate_engine import ImmediateControlEngine
from .n5_analyze import check_plan
from .n5_config import generate, load
from .packet_adapter import control_payload
from .plan_analyze import load_side, read_plan, summarize
from .protocol import control_record


SIDES = ("ble", "zigbee")
BOUNDS = (("uncalibrated", None), ("synthetic_bound_1ms", 1.0))


def ratio(n: int, d: int) -> dict:
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mutate_v1(payload: bytes, *, execute_at_ms: int, valid_until_ms: int) -> bytes:
    """Change only the two v1 deadline fields and recompute the application CRC."""
    record = control_record(payload)
    if record["version"] != 1 or not record["flags"]:
        raise ValueError("deadline mutation requires a v1 command record")
    if not record["ref_tick_ms"] <= valid_until_ms < execute_at_ms <= 0xffffffff:
        raise ValueError("synthetic deadline violates v1 semantics")
    data = bytearray(payload)
    data[25:29] = execute_at_ms.to_bytes(4, "little")
    data[29:33] = valid_until_ms.to_bytes(4, "little")
    data[33:35] = binascii.crc_hqx(data[:33], 0xffff).to_bytes(2, "little")
    changed = bytes(data)
    control_record(changed)
    return changed


def read_inputs(root: Path, config_path: Path, run_id: int) -> dict:
    c = load(config_path, run_id)
    board = root / "board" / "serial.log"
    if not board.is_file():
        board = root / "board.board.log"
    plan = read_plan(board, run_id)
    check_plan(c, plan)
    paths = {"config": config_path, "board": board}
    streams, receivers, observations = {}, {}, {}
    for side in SIDES:
        path = discover(root, side)
        if path is None:
            raise ValueError(f"one complete {side} capture is required")
        paths[side + "_packets"] = path
        summary_path = path.with_name("rx.summary.json")
        events_path = path.with_name("rx.control.events.jsonl")
        if not events_path.is_file():
            raise ValueError(f"{side}: live control events are required")
        paths[side + "_summary"] = summary_path
        paths[side + "_events"] = events_path
        receiver = json.loads(summary_path.read_text())
        receivers[side] = receiver
        rate = receiver.get("config", {}).get("sample_rate")
        total = receiver.get("counts", {}).get("samples_processed")
        if (receiver.get("status") != "complete" or receiver.get("error") or
                receiver.get("capture_stats", {}).get("queue_overflow") or
                type(rate) is not int or rate <= 0 or type(total) is not int or total <= 0):
            raise ValueError(f"{side}: incomplete capture or invalid sample axis")
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        registration = [e for e in events if e.get("event") == "registration"]
        if len(registration) != 1 or registration[0].get("registration") != c:
            raise ValueError(f"{side}: N5 live registration differs from configuration")
        if any(e.get("event") == "timeline_anomaly" for e in events):
            raise ValueError(f"{side}: timeline anomaly; do not replay as continuous IQ")
        stream = load_side(path, side, run_id, {0, *[t["command_id"] for t in c["tasks"]]})
        streams[side] = stream
        rows, previous = [], -1
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            packet = json.loads(line)
            start, available = packet.get("sample_start"), packet.get("available_sample")
            if (not isinstance(start, (int, float)) or not math.isfinite(start) or
                    type(available) is not int or not 0 <= start <= available <= total or
                    available < previous):
                raise ValueError(f"{side}: invalid availability at row {line_no}")
            previous = available
            payload = control_payload(packet, side)
            if payload is None:
                continue
            try:
                record = control_record(payload, side)
            except (TypeError, ValueError):
                record = None
            if record and record["run_id"] == run_id:
                slot = record["slot_index"]
                if (slot not in plan["slots"] or
                        plan["slots"][slot]["command_id"] != record["command_id"] or
                        record["version"] != 1 or record["period_ms"] != c["period_ms"]):
                    raise ValueError(f"{side}: decoded record differs from board plan")
            rows.append({"payload": payload, "record": record, "start": start,
                         "available": available, "line_no": line_no})
        observations[side] = rows
    integrity, _, _ = summarize(plan, streams["ble"], streams["zigbee"])
    try:
        windows = [(datetime.fromisoformat(receivers[s]["start_utc"]),
                    datetime.fromisoformat(receivers[s]["end_utc"])) for s in SIDES]
    except (KeyError, ValueError) as exc:
        raise ValueError("both capture windows are required") from exc
    if max(start for start, _ in windows) >= min(end for _, end in windows):
        raise ValueError("independent receiver capture windows do not overlap")
    return {"config": c, "plan": plan, "receivers": receivers,
            "observations": observations, "paths": paths, "integrity": integrity}


def conditions() -> list[dict]:
    rows = [{"name": "immediate_original", "kind": "immediate", "bound": None,
             "evidence": "saved_decode_immediate_replay"}]
    for label, bound in BOUNDS:
        for name, kind, value in (("original", "original", None),
                                  ("repeat_first1", "repeat", 1),
                                  ("repeat_first3", "repeat", 3),
                                  ("repeat_all", "repeat", None),
                                  ("lead_500ms", "lead", 500),
                                  ("lead_2000ms", "lead", 2000),
                                  ("lead_5000ms", "lead", 5000),
                                  ("delay_0ms", "delay", 0),
                                  ("delay_10ms", "delay", 10),
                                  ("delay_100ms", "delay", 100)):
            evidence = ("synthetic_protocol_replay" if kind == "lead" else
                        "synthetic_processing_delay" if kind == "delay" and value else
                        "counterfactual_input_filter" if kind == "repeat" else
                        "saved_decode_sample_replay")
            if bound is not None:
                evidence += "+synthetic_reference_bound"
            rows.append({"name": name + "_" + label, "kind": kind,
                         "value": value, "bound": bound, "evidence": evidence})
    return rows


def select_observations(rows: list[dict], task_map: dict[int, dict], condition: dict,
                        rate: int, total: int) -> tuple[list[dict], dict]:
    selected, filtered, censored = [], 0, 0
    for row in rows:
        record = row["record"]
        task = task_map.get(record["command_id"]) if record and record["flags"] else None
        if task:
            attempt = record["slot_index"] - task["first_slot"]
            limit = (1 if condition["kind"] == "lead" else
                     condition["value"] if condition["kind"] == "repeat" else None)
            if attempt < 0 or attempt >= task["attempts"]:
                raise ValueError("decoded task slot outside plan")
            if limit is not None and attempt >= limit:
                filtered += 1
                continue
        payload = row["payload"]
        if condition["kind"] == "lead" and task:
            first_ms = task["first_slot"] * 500
            payload = mutate_v1(payload, execute_at_ms=first_ms + condition["value"],
                                valid_until_ms=first_ms + 400)
        available = row["available"]
        if condition["kind"] == "delay":
            available += round(condition["value"] * rate / 1000)
        if available > total:
            censored += 1
            continue
        selected.append(dict(row, payload=payload, available=available))
    selected.sort(key=lambda r: (r["available"], r["line_no"]))
    return selected, {"raw_observations": len(rows), "selected_observations": len(selected),
                      "filtered_task_observations": filtered, "right_censored_observations": censored}


def replay_selected(selected: list[dict], config: EngineConfig, total: int,
                    step: int, immediate: bool = False) -> tuple[list[dict], dict]:
    if step <= 0:
        raise ValueError("block_samples must be positive")
    engine = ImmediateControlEngine(config) if immediate else SideControlEngine(config)
    events, cursor = [], 0
    for row in selected:
        available = row["available"]
        while (cursor // step + 1) * step < available:
            cursor = (cursor // step + 1) * step
            events.extend(engine.advance(cursor))
        events.extend(engine.observe(row["payload"], row["start"], available))
        cursor = available
    while (cursor // step + 1) * step <= total:
        cursor = (cursor // step + 1) * step
        events.extend(engine.advance(cursor))
    if cursor < total:
        events.extend(engine.advance(total))
    return events, engine.snapshot()


def task_rows(input_data: dict, condition: dict, selected: dict, events: dict) -> list[dict]:
    rows = []
    for task in input_data["config"]["tasks"]:
        command, first, planned = task["command_id"], task["first_slot"], task["attempts"]
        limit = (1 if condition["kind"] == "lead" else
                 condition["value"] if condition["kind"] == "repeat" else None)
        selected_planned = min(planned, limit) if limit is not None else planned
        row = {"condition": condition["name"], "evidence": condition["evidence"],
               "run_id": input_data["config"]["run_id"], "command_id": command,
               "first_slot": first, "planned_attempts": planned,
               "selected_planned_attempts": selected_planned,
               "board_tx_completed_original": sum(input_data["plan"]["slots"][s]["board_tx_completed"]
                                                  for s in range(first, first + planned))}
        for side in SIDES:
            original = [r for r in input_data["observations"][side] if r["record"] and
                        r["record"]["command_id"] == command and r["record"]["run_id"] == row["run_id"]]
            selected_rows = [r for r in selected[side] if r["record"] and
                             r["record"]["command_id"] == command and r["record"]["run_id"] == row["run_id"]]
            ev = [e for e in events[side] if e.get("command_id") == command]
            row.update({side + "_observed_attempts": len({r["record"]["slot_index"] for r in original}),
                        side + "_selected_observed_attempts": len({r["record"]["slot_index"] for r in selected_rows}),
                        side + "_first_valid_slot": min((r["record"]["slot_index"] for r in selected_rows), default=None),
                        side + "_decoded": int(bool(selected_rows)),
                        side + "_accepted": int(any(e["event"] == "accepted" for e in ev)),
                        side + "_processed": int(any(e["event"] == "software_processed" for e in ev)),
                        side + "_duplicates": sum(e["event"] == "duplicate" for e in ev),
                        side + "_reject_reasons": json.dumps(dict(Counter(e.get("reason") for e in ev
                            if e["event"] == "rejected")), sort_keys=True)})
        row["joint_decoded"] = int(bool(row["ble_decoded"] and row["zigbee_decoded"]))
        row["joint_processed_software"] = int(bool(row["ble_processed"] and row["zigbee_processed"]))
        rows.append(row)
    return rows


def synthetic_wire(slot: int, *, run_id: int = 9001, command_id: int = 0,
                   target_id: int = 0, opcode: int = 0, arg: int = 0,
                   execute_at_ms: int = 0, valid_until_ms: int = 0) -> bytes:
    """Construct test-only v1 bytes; intentionally permits malformed opcode cases."""
    data = bytearray(35)
    data[:2] = b"\xb2\x43"
    data[2:4] = bytes((1, int(command_id != 0)))
    for offset, width, value in ((4, 2, run_id), (6, 4, slot), (10, 4, slot * 500),
                                  (14, 2, 500), (16, 4, command_id), (20, 2, target_id),
                                  (23, 2, arg), (25, 4, execute_at_ms),
                                  (29, 4, valid_until_ms)):
        data[offset:offset + width] = value.to_bytes(width, "little")
    data[22] = opcode
    data[33:35] = binascii.crc_hqx(data[:33], 0xffff).to_bytes(2, "little")
    return bytes(data)


def synthetic_rule_cases() -> list[dict]:
    """Run protocol and state-machine rules without changing physical evidence."""
    cases = []

    def add(name, expected, events, *, detail=""):
        actual = [e["event"] + (":" + e["reason"] if e.get("reason") else "") for e in events]
        passed = expected in actual
        cases.append(dict(case=name, input=detail, expected=expected,
                          actual=json.dumps(actual), passed=int(passed),
                          evidence="synthetic_engine_test"))
        if not passed:
            raise ValueError(f"synthetic rule {name}: expected {expected}, got {actual}")

    def engine(*, supported=frozenset((0, 1, 2)), n5=False, bound=1.0):
        config = EngineConfig(side="ble", run_id=9001, sample_rate=1000,
                              target_ids=frozenset({1}), supported_opcodes=supported,
                              external_reference_bound_ms=bound, drift_bound_ppm=0,
                              n5_registration=generate(9001, provenance=False) if n5 else None)
        instance = SideControlEngine(config)
        if not n5:
            instance.observe(synthetic_wire(0), 1000, 1010)
            instance.observe(synthetic_wire(10), 6000, 6010)
        return instance

    normal = dict(command_id=42, target_id=1, opcode=1, arg=7,
                  execute_at_ms=13000, valid_until_ms=12000)
    e = engine()
    add("wrong_target", "rejected:wrong_target",
        e.observe(synthetic_wire(20, **dict(normal, target_id=2)), 11000, 11010),
        detail="valid CRC, target_id=2, local target_id=1")
    e = engine(supported=frozenset((0, 1)))
    add("unsupported_valid_opcode", "rejected:unsupported",
        e.observe(synthetic_wire(20, **dict(normal, opcode=2)), 11000, 11010),
        detail="opcode=2 valid on wire, absent from configured supported set")
    e = engine()
    add("unknown_opcode", "invalid_record:command_semantics",
        e.observe(synthetic_wire(20, **dict(normal, opcode=9)), 11000, 11010),
        detail="opcode=9, CRC rebuilt")
    e = engine()
    damaged = bytearray(synthetic_wire(20, **normal)); damaged[23] ^= 1
    add("app_crc_error", "invalid_record:app_crc16", e.observe(bytes(damaged), 11000, 11010),
        detail="application byte flipped after CRC")
    e = engine()
    e.observe(synthetic_wire(20, **normal), 11000, 11010)
    add("same_command_conflict", "rejected:conflicting_task",
        e.observe(synthetic_wire(21, **dict(normal, arg=8)), 11500, 11510),
        detail="same command_id, changed arg, valid CRC")
    e = engine()
    e.observe(synthetic_wire(20, **normal), 11000, 11010)
    add("same_command_duplicate", "duplicate",
        e.observe(synthetic_wire(21, **normal), 11500, 11510),
        detail="same command_id and task fields in another slot")
    e = engine()
    add("duplicate_slot", "clock_duplicate",
        e.observe(synthetic_wire(10), 6000, 6020), detail="same slot/ref/marker twice")
    e = engine(n5=True)
    e.observe(synthetic_wire(2), 2000, 2010)
    add("out_of_order_training", "out_of_order_training",
        e.observe(synthetic_wire(0), 1000, 2020),
        detail="slot 0 becomes available after slot 2")
    e = engine()
    add("expired", "rejected:expired",
        e.observe(synthetic_wire(20, **dict(normal, execute_at_ms=14000)), 11000, 13010),
        detail="available_sample is after valid_until")
    e = engine()
    add("late", "rejected:late",
        e.observe(synthetic_wire(20, **dict(normal, execute_at_ms=10015, valid_until_ms=10012)),
                  11000, 11010), detail="guard + uncertainty reaches target")
    e = engine()
    add("foreign_run", "foreign_run", e.observe(synthetic_wire(20, **dict(normal, run_id=9002)),
                                                  11000, 11010), detail="run_id=9002")
    e = engine(bound=None)
    add("unknown_reference", "rejected:time_quality_insufficient",
        e.observe(synthetic_wire(20, **normal), 11000, 11010), detail="no reference bound")
    e = engine()
    accepted = e.observe(synthetic_wire(20, **normal), 11000, 11010)
    add("accepted_with_synthetic_bound", "accepted", accepted, detail="synthetic 1 ms reference bound")
    target = next(x["target_sample"] for x in accepted if x["event"] == "accepted")
    add("processing_late", "cancelled:processing_late", e.advance(target + 60),
        detail="advance 60 samples after scheduled target")
    e = engine()
    accepted = e.observe(synthetic_wire(20, **normal), 11000, 11010)
    target = next(x["target_sample"] for x in accepted if x["event"] == "accepted")
    add("schedule_freeze", "schedule_frozen", e.advance(target - 100),
        detail="advance to 100 ms before target under synthetic 1 ms bound")
    e = engine(n5=True)
    add("timeline_anomaly", "timeline_anomaly:synthetic_discontinuity",
        e.timeline_event("synthetic_discontinuity"),
        detail="invalidate N5 sample axis")
    e = engine(n5=True)
    add("explicit_restart", "observation_transition",
        e.timeline_event("synthetic_discontinuity", restart=True),
        detail="restart creates new observation segment")
    e = engine(n5=True)
    for slot in range(0, 16, 2):
        e.observe(synthetic_wire(slot), 1000 + slot * 500, 1010 + slot * 500)
    e.observe(synthetic_wire(20, **normal), 11000, 11010)
    add("pending_cancelled_on_timeline_break", "cancelled:timeline_unverified",
        e.timeline_event("synthetic_discontinuity"),
        detail="accepted task cancelled when N5 sample axis is invalidated")
    cases.append(dict(case="zero_denominator", input="ratio(0, 0)", expected="N/A",
                      actual="N/A" if ratio(0, 0)["value"] is None else "wrong",
                      passed=int(ratio(0, 0)["value"] is None),
                      evidence="synthetic_reporting_test"))
    c = generate(9001, provenance=False)
    empty = {"config": c, "plan": {"slots": {s: {"board_tx_completed": 1} for s in range(300)}},
             "observations": {"ble": [], "zigbee": []}}
    missing = task_rows(empty, dict(name="all_missing", evidence="synthetic", kind="original"),
                        {"ble": [], "zigbee": []}, {"ble": [], "zigbee": []})
    actual = f"{len(missing)}_tasks_{sum(r['joint_decoded'] for r in missing)}_joint"
    cases.append(dict(case="all_tasks_missing", input="no decoded packet on either side",
                      expected="6_tasks_0_joint", actual=actual,
                      passed=int(actual == "6_tasks_0_joint"), evidence="synthetic_reporting_test"))
    if not all(row["passed"] for row in cases):
        raise ValueError("synthetic reporting rule failed")
    return cases


def run_ablation(root: Path, config_path: Path, run_id: int, output: Path) -> dict:
    if output.exists():
        raise ValueError(f"output directory already exists: {output}")
    data = read_inputs(root, config_path, run_id)
    task_map = {t["command_id"]: t for t in data["config"]["tasks"]}
    condition_rows, all_tasks, all_events, traces = [], [], [], {}
    for condition in conditions():
        selected, event_sets, side_stats = {}, {}, {}
        for side in SIDES:
            receiver = data["receivers"][side]
            rate = receiver["config"]["sample_rate"]
            total = receiver["counts"]["samples_processed"]
            selected[side], selection = select_observations(data["observations"][side], task_map,
                                                             condition, rate, total)
            config = EngineConfig(side=side, run_id=run_id, sample_rate=rate,
                                  target_ids=frozenset({1 if side == "ble" else 2}),
                                  external_reference_bound_ms=condition["bound"],
                                  n5_registration=None if condition["kind"] == "immediate" else data["config"])
            events, snapshot = replay_selected(selected[side], config, total,
                                               receiver["config"].get("block_samples") or max(1, rate // 100),
                                               condition["kind"] == "immediate")
            event_sets[side] = events
            all_events.extend(dict(e, condition=condition["name"], evidence=condition["evidence"])
                              for e in events)
            side_stats[side] = dict(selection, events=dict(Counter(e["event"] for e in events)),
                                    reject_reasons=dict(Counter(e.get("reason") for e in events
                                        if e["event"] == "rejected")), snapshot=snapshot)
        traces[condition["name"]] = event_sets
        tasks = task_rows(data, condition, selected, event_sets)
        all_tasks.extend(tasks)
        joint = ratio(sum(t["joint_decoded"] for t in tasks), len(tasks))
        row = dict(condition=condition["name"], kind=condition["kind"], value=condition.get("value"),
                   evidence=condition["evidence"], assumed_reference_bound_ms=condition["bound"],
                   joint_decoded_numerator=joint["numerator"], joint_decoded_denominator=joint["denominator"],
                   joint_decoded_ratio=joint["value"],
                   joint_processed_software_numerator=sum(t["joint_processed_software"] for t in tasks),
                   joint_processed_software_denominator=len(tasks),
                   board_tx_completed_original=data["plan"]["stats"]["tx_completed"],
                   board_submitted_waveform_us_original=data["integrity"]["waveform_cost"]["submitted_waveform_us"],
                   actual_rf_airtime_us=data["integrity"]["waveform_cost"]["actual_rf_airtime_us"],
                   board_rf_cost_policy="original full-run proxy; no synthetic RF claim")
        for side in SIDES:
            row.update({side + "_" + k: json.dumps(v, sort_keys=True) if isinstance(v, dict) else v
                        for k, v in side_stats[side].items() if k != "snapshot"})
        condition_rows.append(row)
    for label, _ in BOUNDS:
        reference = traces["original_" + label]
        for equivalent in ("repeat_all_" + label, "delay_0ms_" + label):
            if traces[equivalent] != reference:
                raise ValueError(f"{equivalent} differs from the original replay")
    original = next(r for r in condition_rows if r["condition"] == "original_uncalibrated")
    expected_joint = sum(t["joint_task_decoded"] for t in data["integrity"]["tasks"])
    if original["joint_decoded_numerator"] != expected_joint:
        raise ValueError("original task parsing differs from N5 integrity analysis")
    sources = {name: {"path": str(path.resolve()), "sha256": sha256(path)}
               for name, path in data["paths"].items()}
    manifest = {"schema": "b2z_n5_task_ablation_v1", "run_id": run_id,
                "generated_utc": datetime.now(timezone.utc).isoformat(),
                "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "tool_sha256": sha256(Path(__file__)), "config_sha256": data["config"]["sha256"],
                "analysis_sources": {p.name: sha256(p) for p in Path(__file__).parent.glob("*.py")},
                "sources": sources, "condition_count": len(condition_rows),
                "task_denominator": len(task_map),
                "board_waveform_cost_original": data["integrity"]["waveform_cost"],
                "limits": ["offline software replay; no new RF trial or actuator action",
                           "1 ms bound is synthetic, not measured synchronization accuracy",
                           "mutated v1 application bytes enter after PHY decode; outer BLE CRC / IEEE FCS is not regenerated",
                           "repeat filters do not change original board RF cost",
                           "immediate policy does not assess deadlines",
                           "DMA completion is not independently measured RF completion"]}
    rule_cases = synthetic_rule_cases()
    output.mkdir(parents=True)
    write_csv(output / "conditions.csv", condition_rows)
    write_csv(output / "tasks.csv", all_tasks)
    write_csv(output / "rule_cases.csv", rule_cases)
    (output / "events.jsonl").write_text("".join(json.dumps(e, allow_nan=False) + "\n" for e in all_events))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    lines = ["# N5 任务规则消融", "", f"Run {run_id}；{len(condition_rows)} 个回放条件；任务分母 {len(task_map)}。",
             "所有结果均为本侧 IQ 样本域软件回放。1 ms 参考界为合成假设。",
             f"原轮全部已提交波形预算 {data['integrity']['waveform_cost']['submitted_waveform_us']} µs；实际 RF 发射时长未测。", "",
             "| 条件 | 联合有效解析 | 联合软件处理 |", "| --- | ---: | ---: |"]
    for row in condition_rows:
        lines.append(f"| {row['condition']} | {row['joint_decoded_numerator']}/{row['joint_decoded_denominator']} | "
                     f"{row['joint_processed_software_numerator']}/{row['joint_processed_software_denominator']} |")
    lines += ["", f"合成规则案例 {sum(r['passed'] for r in rule_cases)}/{len(rule_cases)} 通过。",
              "逐任务、拒绝原因和事件见 CSV/JSONL；原板端成本不随反事实筛选改变。"]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return manifest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment-dir", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        result = run_ablation(a.experiment_dir, a.config, a.run_id, a.output_dir)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        p.error(str(exc))
    print(f"run={a.run_id} conditions={result['condition_count']} output={a.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
