#!/usr/bin/env python3
"""Join independently decoded control tasks against a complete board plan log."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

try:
    from .flow_input import load_flow
    from .burst_cost import read_bursts, cost_summary
    from .analyze import SHARED_FIELDS, TASK_FIELDS, capture_interval, discover, read_side
except ImportError:
    from flow_input import load_flow
    from burst_cost import read_bursts, cost_summary
    from analyze import SHARED_FIELDS, TASK_FIELDS, capture_interval, discover, read_side


def fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=([^\s]+)", line))


def one(items: list[dict], name: str) -> dict:
    if len(items) != 1:
        raise ValueError(f"expected one {name}, found {len(items)}")
    return items[0]


def read_plan(path: Path, run_id: int) -> dict:
    rows = path.read_text(encoding="utf-8").splitlines()
    matching = lambda prefix: [fields(line) for line in rows
                               if line.startswith(prefix + " ") and
                               fields(line).get("run_id") == str(run_id)]
    stats = one([r for r in matching("CONTROL_PLAN_STATS") if r.get("final") == "1"],
                "final CONTROL_PLAN_STATS")
    if stats.get("state") != "complete":
        raise ValueError("board plan did not complete")
    tasks = matching("CONTROL_PLAN_TASK")
    slots = matching("CONTROL_PLAN_SLOT")
    planned = int(stats["planned_slots"])
    if len(tasks) != int(stats["tasks"]) or len(slots) != planned:
        raise ValueError("complete CONTROL_PLAN_TASK and CONTROL_PLAN_SLOT lines are required")
    for key in ("reached_slots", "generated", "primary_completed", "tx_completed"):
        if not 0 <= int(stats[key]) <= planned:
            raise ValueError(f"invalid board {key} count")
    tasks.sort(key=lambda r: int(r["first_slot"]))
    by_slot, commands = {}, set()
    for index, task in enumerate(tasks):
        entry, command, first, repeats = (int(task[k]) for k in
                                           ("entry", "command_id", "first_slot", "repeats"))
        if entry != index or first != len(by_slot) or repeats <= 0:
            raise ValueError("plan entries must cover consecutive slots")
        if command and command in commands:
            raise ValueError("nonzero command_id occurs in multiple plan entries")
        commands.add(command)
        if not 0 <= int(task["tx_completed"]) <= repeats:
            raise ValueError("invalid task DMA completion count")
        for slot in range(first, first + repeats):
            by_slot[slot] = {"entry": entry, "command_id": command,
                             "board_tx_completed": None}
    if len(by_slot) != planned:
        raise ValueError("plan task ranges disagree with planned_slots")
    seen = set()
    for row in slots:
        slot = int(row["slot"])
        if slot not in by_slot or slot in seen:
            raise ValueError("missing, duplicate or out-of-range CONTROL_PLAN_SLOT")
        seen.add(slot)
        if (int(row["entry"]), int(row["command_id"])) != (
                by_slot[slot]["entry"], by_slot[slot]["command_id"]):
            raise ValueError(f"board slot {slot} disagrees with its task")
        completed = int(row["tx_completed"])
        if completed not in (0, 1):
            raise ValueError(f"invalid per-slot DMA completion at {slot}")
        by_slot[slot]["board_tx_completed"] = completed
        by_slot[slot]["board_primary_completed"] = int(row["primary_completed"])
        by_slot[slot]["board_generated"] = int(row["generated"])
    for metric in ("generated", "primary_completed", "tx_completed", "deadline_miss", "dma_timeout"):
        if sum(int(r[metric]) for r in slots) != int(stats[metric]):
            raise ValueError(f"board per-slot {metric} total disagrees with final stats")
        if sum(int(r[metric]) for r in tasks) != int(stats[metric]):
            raise ValueError(f"board per-task {metric} total disagrees with final stats")
    bursts = read_bursts(matching, stats, by_slot)
    return {"stats": stats, "tasks": tasks, "slots": by_slot, "bursts": bursts}


def load_side(path: Path, side: str, run_id: int, commands: set[int]) -> dict:
    by_slot, counts = {}, {}
    for command in commands:
        stream = read_side(path, side, run_id, command)
        counts[command] = stream["counts"]
        for slot, event in stream["by_slot"].items():
            if slot in by_slot:
                raise ValueError(f"{side}: conflicting commands at slot {slot}")
            by_slot[slot] = event
    summary_path = path.with_name("rx.control.summary.json")
    live = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    if live and (live["side"], live["run_id"]) != (side, run_id):
        raise ValueError(f"{side}: live control summary identifies another run")
    receiver_path = path.with_name("rx.summary.json")
    receiver = json.loads(receiver_path.read_text()) if receiver_path.exists() else {}
    return {"receiver_config": receiver.get("config", {}), "path": path, "by_slot": by_slot, "counts": counts,
            "live": live, "live_path": summary_path if live else None,
            "summary_path": path.with_name("rx.summary.json")}


def summarize(plan: dict, ble: dict, zigbee: dict) -> tuple[dict, list[dict], list[dict]]:
    sides = {"ble": ble, "zigbee": zigbee}
    slot_rows = []
    if "followed_slots" in ble:
        if ble["expected_attempts"] != len(plan["slots"]) or ble["period_ms"] != int(plan["stats"]["period_ms"]):
            raise ValueError("flow configuration differs from board plan")
    for slot, board in sorted(plan["slots"].items()):
        events = {side: data["by_slot"].get(slot) for side, data in sides.items()}
        for side, event in events.items():
            if side == "ble" and event and event.get("wire_format") is not None:
                expected = "ble-only" if plan["stats"].get("rf_mode") == "separate_secondary_ch3" else "joint"
                if event["wire_format"] != expected:
                    raise ValueError("BLE wire format disagrees with board RF mode")
            if event and event["record"]["command_id"] != board["command_id"]:
                raise ValueError(f"{side}: decoded command disagrees with board at slot {slot}")
        shared_match = (all(events["ble"]["record"][key] == events["zigbee"]["record"][key]
                            for key in SHARED_FIELDS) if all(events.values()) else None)
        row = {"slot_index": slot, "entry": board["entry"],
               "command_id": board["command_id"],
               "board_tx_completed": board["board_tx_completed"],
               "ble_valid": int(events["ble"] is not None),
               "zigbee_valid": int(events["zigbee"] is not None),
               "shared_fields_match": "" if shared_match is None else int(shared_match)}
        for side, metric in (("ble", "board_ble_tx_completed"), ("ieee", "board_ieee_tx_completed")):
            row[metric] = board.get(metric, board["board_tx_completed"])
        row["ble_followed"] = int(slot in ble["followed_slots"]) if "followed_slots" in ble else None
        row["ble_primary_valid"] = int(slot in ble["primary_slots"]) if "primary_slots" in ble else None
        row["followed_joint_valid"] = (int(bool(row["ble_followed"] and row["zigbee_valid"] and shared_match))
                                        if "followed_slots" in ble else None)
        slot_rows.append(row)
    tasks = []
    for board in plan["tasks"]:
        command = int(board["command_id"])
        if command == 0:
            continue
        first, repeats = int(board["first_slot"]), int(board["repeats"])
        selected = slot_rows[first:first + repeats]
        side_events = {side: [data["by_slot"][r["slot_index"]] for r in selected
                              if r["slot_index"] in data["by_slot"]] for side, data in sides.items()}
        if all(side_events.values()) and any(
                side_events["ble"][0]["record"][key] != side_events["zigbee"][0]["record"][key]
                for key in TASK_FIELDS):
            raise ValueError(f"shared task fields disagree for command {command}")
        for side, events in side_events.items():
            keys = TASK_FIELDS + ("target_id", "opcode", "arg")
            expected_keys = {"target_id": f"{side}_target", "opcode": f"{side}_opcode",
                             "arg": f"{side}_arg", "execute_at_ms": "execute_at_ms", "valid_until_ms": "valid_until_ms"}
            for event in events:
                if any(key in board and event["record"][field] != int(board[key])
                       for field, key in expected_keys.items()):
                    raise ValueError(f"{side}: decoded task differs from board plan for {command}")
            if events and any(any(e["record"].get(k) != events[0]["record"].get(k) for k in keys) for e in events):
                raise ValueError(f"{side}: task fields change across repeats for {command}")
        live = {}
        for side, data in sides.items():
            live_rows = data["live"]["tasks"] if data["live"] else []
            live[side] = next((r for r in live_rows if r["command_id"] == command), None)
        task = {"command_id": command, "first_slot": first, "planned_attempts": repeats,
                "board_tx_completed": int(board["tx_completed"]),
                "ble_valid_attempts": len(side_events["ble"]),
                "zigbee_valid_attempts": len(side_events["zigbee"]),
                "same_attempt_joint_valid": sum(r["ble_valid"] and r["zigbee_valid"] and
                                                r["shared_fields_match"] == 1 for r in selected),
                "ble_first_valid_slot": min((r["record"]["slot_index"] for r in side_events["ble"]),
                                            default=""),
                "zigbee_first_valid_slot": min((r["record"]["slot_index"] for r in side_events["zigbee"]),
                                               default=""),
                "joint_task_decoded": int(all(side_events.values())),
                "ble_live_status": live["ble"]["status"] if live["ble"] else ("not_measured" if sides["ble"]["live"] is None else "not_decoded"),
                "zigbee_live_status": live["zigbee"]["status"] if live["zigbee"] else ("not_measured" if sides["zigbee"]["live"] is None else "not_decoded"),
                "ble_software_processed": int(bool(live["ble"] and live["ble"].get("processed_sample"))),
                "zigbee_software_processed": int(bool(live["zigbee"] and live["zigbee"].get("processed_sample")))}
        for side in sides:
            task[f"{side}_command"] = ({k: side_events[side][0]["record"].get(k) for k in
                                       ("target_id", "opcode", "arg", "execute_at_ms", "valid_until_ms")}
                                      if side_events[side] else None)
            if sides[side]["live"] is None:
                task[f"{side}_software_processed"] = None
        for side in ("ble", "ieee"):
            task[f"board_{side}_tx_completed"] = sum(r[f"board_{side}_tx_completed"] for r in selected)
        task["ble_followed_attempts"] = (sum(r["ble_followed"] for r in selected)
                                           if "followed_slots" in ble else None)
        task["joint_task_with_ble_follow"] = (int(bool(task["joint_task_decoded"] and task["ble_followed_attempts"]))
                                               if "followed_slots" in ble else None)
        tasks.append(task)
    if any(r["shared_fields_match"] == 0 for r in slot_rows):
        raise ValueError("shared fields disagree in a jointly decoded slot")
    if any(slot not in plan["slots"] for data in sides.values() for slot in data["by_slot"]):
        raise ValueError("decoded slot is outside board plan")
    summary = {"schema": "b2z_plan_match_v2", "run_id": int(plan["stats"]["run_id"]),
               "planned_slots": len(slot_rows), "board_tx_completed": int(plan["stats"]["tx_completed"]),
               "planned_control_tasks": len(tasks),
               "ble_valid_attempts": sum(r["ble_valid"] for r in slot_rows),
               "zigbee_valid_attempts": sum(r["zigbee_valid"] for r in slot_rows),
               "joint_valid_attempts": sum(r["ble_valid"] and r["zigbee_valid"] and
                                           r["shared_fields_match"] == 1 for r in slot_rows),
               "ble_only_attempts": sum(r["ble_valid"] and not r["zigbee_valid"] for r in slot_rows),
               "zigbee_only_attempts": sum(r["zigbee_valid"] and not r["ble_valid"] for r in slot_rows),
               "neither_attempts": sum(not r["ble_valid"] and not r["zigbee_valid"] for r in slot_rows),
               "joint_decoded_tasks": sum(r["joint_task_decoded"] for r in tasks),
               "joint_software_processed_tasks": sum(bool(r["ble_software_processed"] and
                                                          r["zigbee_software_processed"]) for r in tasks),
               "board": plan["stats"], "tasks": tasks,
               "planned_task_manifest": [{k: row.get(k) for k in (
                   "command_id", "first_slot", "repeats", "execute_at_ms", "valid_until_ms",
                   "ble_target", "ble_opcode", "ble_arg", "zigbee_target", "zigbee_opcode", "zigbee_arg")}
                   for row in plan["tasks"]],
               "limitations": ["software processing is not physical actuator execution",
                               "independent IQ sample origins are not subtracted",
                               "DMA completion is a transmit proxy, not measured RF airtime"]}
    if any(data["live"] is None for data in sides.values()):
        summary["joint_software_processed_tasks"] = None
    if "followed_slots" in ble:
        n = len(ble["followed_slots"])
        def ratio(num, den):
            return {"numerator": num, "denominator": den, "value": num / den if den else None}
        summary["ble_follow"] = {
            "per_planned_slot": ratio(n, len(slot_rows)),
            "per_valid_primary": ratio(n, len(ble["primary_slots"])),
            "joint_same_slot": ratio(sum(r["followed_joint_valid"] for r in slot_rows), len(slot_rows)),
            "joint_tasks_with_follow": ratio(sum(t["joint_task_with_ble_follow"] for t in tasks), len(tasks)),
            "missing_primary_slots": sorted(set(plan["slots"]) - ble["primary_slots"]),
            "missing_follow_slots": sorted(set(plan["slots"]) - ble["followed_slots"]),
            "source_counts": ble["counts"]}
        summary["limitations"].append("flow callback times are not IQ sample or RF timestamps; BLE scheduling not measured")
    summary["receiver_configs"] = {side: data.get("receiver_config") for side, data in sides.items()}
    summary["local_decode_availability"] = {}
    for side, data in sides.items():
        rate = (data.get("receiver_config") or {}).get("sample_rate")
        delays = [(e["available_sample"] - e["sample_start"]) * 1e6 / rate
                  for e in data["by_slot"].values() if rate and e.get("available_sample") is not None
                  and e.get("sample_start") is not None and e["available_sample"] >= e["sample_start"]]
        summary["local_decode_availability"][side] = {
            "samples": len(delays), "missing": len(data["by_slot"]) - len(delays),
            "min_us": min(delays) if delays else None, "max_us": max(delays) if delays else None,
            "mean_us": sum(delays) / len(delays) if delays else None,
            "scope": "own IQ packet start to decoder availability; block quantized, not host processing or cross-device completion latency"}
    summary["waveform_cost"] = cost_summary(plan["bursts"], summary["joint_decoded_tasks"]) if plan.get("bursts") else None
    return summary, slot_rows, tasks


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--board-log", type=Path)
    ble_source = parser.add_mutually_exclusive_group()
    ble_source.add_argument("--ble-packets", type=Path)
    ble_source.add_argument("--ble-flow", type=Path, help="std_ble flow.events.jsonl with sibling flow.summary.json")
    parser.add_argument("--zigbee-packets", type=Path)
    parser.add_argument("--analysis-id", default="plan_match")
    args = parser.parse_args()
    if Path(args.analysis_id).name != args.analysis_id or args.analysis_id in (".", ".."):
        parser.error("analysis-id must be one directory name")
    paths = {"ble": args.ble_flow or args.ble_packets or discover(args.experiment_dir, "ble"),
             "zigbee": args.zigbee_packets or discover(args.experiment_dir, "zigbee")}
    if not all(paths.values()):
        parser.error("two complete receiver packet streams are required")
    flow = load_flow(args.ble_flow, args.run_id) if args.ble_flow else None
    if flow is not None and flow["interval"] is None:
        parser.error("legacy flow lacks capture UTC interval; usable for standalone review, not same-run joint verification")
    intervals = [flow["interval"] if flow else capture_interval(paths["ble"]), capture_interval(paths["zigbee"])]
    if max(a for a, _ in intervals) >= min(b for _, b in intervals):
        parser.error("receiver capture intervals do not overlap")
    board_path = args.board_log or args.experiment_dir / "board.board.log"
    plan = read_plan(board_path, args.run_id)
    commands = {int(row["command_id"]) for row in plan["tasks"]}
    sides = {side: flow if side == "ble" and flow is not None else load_side(path, side, args.run_id, commands)
             for side, path in paths.items()}
    summary, slot_rows, task_rows = summarize(plan, sides["ble"], sides["zigbee"])
    summary["analysis_version"] = {
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
                                   capture_output=True, text=True).stdout.strip(),
        "module_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("plan_analyze.py", "burst_cost.py", "analyze.py", "flow_input.py")},
        "board_firmware_version": "not_inferred_from_host_checkout"}
    summary["sources"] = {"board": {"path": str(board_path.resolve()),
                                     "sha256": hashlib.sha256(board_path.read_bytes()).hexdigest()},
                          **{side: {"path": str(path.resolve()),
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                             for side, path in paths.items()}}
    for side, data in sides.items():
        for kind, path in (("receiver_summary", data["summary_path"]),
                           ("live_control_summary", data["live_path"])):
            if path is not None:
                summary["sources"][f"{side}_{kind}"] = {
                    "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    output = args.experiment_dir / "analyses" / args.analysis_id
    if output.exists():
        parser.error(f"output already exists: {output}")
    output.mkdir(parents=True)
    if plan.get("bursts"):
        write_csv(output / "plan.bursts.csv", plan["bursts"]["rows"])
    write_csv(output / "plan.slots.metrics.csv", slot_rows)
    write_csv(output / "plan.tasks.metrics.csv", task_rows)
    (output / "plan.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 多任务双端联合分析", "",
             f"- Run ID：{args.run_id}；计划控制任务：{len(task_rows)}；板端 secondary DMA 完成：{summary['board_tx_completed']}/{summary['planned_slots']}",
             f"- BLE / IEEE 有效解码尝试：{summary['ble_valid_attempts']}/{summary['planned_slots']} / {summary['zigbee_valid_attempts']}/{summary['planned_slots']}",
             f"- 同尝试联合有效解码：{summary['joint_valid_attempts']}/{summary['planned_slots']}",
             f"- 逐任务联合有效解析：{summary['joint_decoded_tasks']}/{len(task_rows)}" if task_rows else
             "- 逐任务联合有效解析：N/A（零任务）",
             f"- 两侧软件处理事件均出现：{summary['joint_software_processed_tasks']}/{len(task_rows)}" if task_rows and summary["joint_software_processed_tasks"] is not None else
             "- 两侧软件处理事件均出现：N/A（零任务或缺少软件处理观测）",
             "", "| Command ID | 计划发送 | BLE 有效 | IEEE 有效 | 同尝试双方有效 | 双方解析任务 | BLE/IEEE 实时状态 |",
             "|---:|---:|---:|---:|---:|---:|---|"]
    for row in task_rows:
        lines.append(f"| {row['command_id']} | {row['planned_attempts']} | {row['ble_valid_attempts']} | "
                     f"{row['zigbee_valid_attempts']} | {row['same_attempt_joint_valid']} | "
                     f"{row['joint_task_decoded']} | {row['ble_live_status']} / {row['zigbee_live_status']} |")
    if summary["waveform_cost"] is not None:
        cost = summary["waveform_cost"]
        unit = cost["per_joint_decoded_task"]["value_us"]
        lines += ["", "## 按提交波形长度核算的成本（非实测 RF 占用）", "",
                  f"- 模式：{cost['mode']}；BLE/IEEE DMA 完成：{cost['ble_tx_completed']}/{cost['logical_slots']}、{cost['ieee_tx_completed']}/{cost['logical_slots']}",
                  f"- 突发提交尝试/成功/完成：{cost['burst_attempted']}/{cost['burst_started']}/{cost['burst_completed']}；发送程度不确定：{cost['uncertain_bursts']}",
                  f"- 全轮提交有效波形：{cost['submitted_waveform_us']} µs；零样本 padding：{cost['submitted_zero_padding_us']} µs；提交尝试预算：{cost['attempted_waveform_budget_us']} µs",
                  f"- 每成功联合解析任务：{unit if unit is not None else 'N/A'} µs（分母 {summary['joint_decoded_tasks']}）；包含时间更新、失败与重发。",
                  "- 逐突发及软件 DMA 调用时刻见 plan.bursts.csv；串口及 DMA 时刻不代表实际空口起点。"]
    if "ble_follow" in summary:
        lines += ["", "## BLE 跟随证据", ""]
        for label, value in summary["ble_follow"].items():
            if isinstance(value, dict) and "numerator" in value:
                lines.append(f"- {label}：{value['numerator']}/{value['denominator']}" if value['denominator'] else f"- {label}：N/A（零分母）")
    lines += ["", "逐槽及逐任务数据见 [plan.slots.metrics.csv](plan.slots.metrics.csv)、[plan.tasks.metrics.csv](plan.tasks.metrics.csv) 和 [plan.summary.json](plan.summary.json)。",
              "软件处理事件不等于物理执行；两台 IQ 的独立采样零点未校准，不能由此计算执行时差。", ""]
    (output / "plan.report.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
