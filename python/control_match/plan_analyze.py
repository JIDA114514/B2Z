#!/usr/bin/env python3
"""Join independently decoded control tasks against a complete board plan log."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

try:
    from .analyze import SHARED_FIELDS, TASK_FIELDS, capture_interval, discover, read_side
except ImportError:
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
    for metric in ("generated", "primary_completed", "tx_completed", "deadline_miss", "dma_timeout"):
        if sum(int(r[metric]) for r in slots) != int(stats[metric]):
            raise ValueError(f"board per-slot {metric} total disagrees with final stats")
        if sum(int(r[metric]) for r in tasks) != int(stats[metric]):
            raise ValueError(f"board per-task {metric} total disagrees with final stats")
    return {"stats": stats, "tasks": tasks, "slots": by_slot}


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
    return {"path": path, "by_slot": by_slot, "counts": counts,
            "live": live, "live_path": summary_path if live else None}


def summarize(plan: dict, ble: dict, zigbee: dict) -> tuple[dict, list[dict], list[dict]]:
    sides = {"ble": ble, "zigbee": zigbee}
    slot_rows = []
    for slot, board in sorted(plan["slots"].items()):
        events = {side: data["by_slot"].get(slot) for side, data in sides.items()}
        for side, event in events.items():
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
                "ble_live_status": live["ble"]["status"] if live["ble"] else "not_decoded",
                "zigbee_live_status": live["zigbee"]["status"] if live["zigbee"] else "not_decoded",
                "ble_software_processed": int(bool(live["ble"] and live["ble"].get("processed_sample"))),
                "zigbee_software_processed": int(bool(live["zigbee"] and live["zigbee"].get("processed_sample")))}
        tasks.append(task)
    if any(r["shared_fields_match"] == 0 for r in slot_rows):
        raise ValueError("shared fields disagree in a jointly decoded slot")
    if any(slot not in plan["slots"] for data in sides.values() for slot in data["by_slot"]):
        raise ValueError("decoded slot is outside board plan")
    summary = {"schema": "b2z_plan_match_v1", "run_id": int(plan["stats"]["run_id"]),
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
               "joint_software_processed_tasks": sum(r["ble_software_processed"] and
                                                     r["zigbee_software_processed"] for r in tasks),
               "board": plan["stats"], "tasks": tasks,
               "limitations": ["software processing is not physical actuator execution",
                               "independent IQ sample origins are not subtracted",
                               "DMA completion is a transmit proxy, not measured RF airtime"]}
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
    parser.add_argument("--ble-packets", type=Path)
    parser.add_argument("--zigbee-packets", type=Path)
    parser.add_argument("--analysis-id", default="plan_match")
    args = parser.parse_args()
    if Path(args.analysis_id).name != args.analysis_id or args.analysis_id in (".", ".."):
        parser.error("analysis-id must be one directory name")
    paths = {"ble": args.ble_packets or discover(args.experiment_dir, "ble"),
             "zigbee": args.zigbee_packets or discover(args.experiment_dir, "zigbee")}
    if not all(paths.values()):
        parser.error("two complete receiver packet streams are required")
    intervals = [capture_interval(p) for p in paths.values()]
    if max(a for a, _ in intervals) >= min(b for _, b in intervals):
        parser.error("receiver capture intervals do not overlap")
    board_path = args.board_log or args.experiment_dir / "board.board.log"
    plan = read_plan(board_path, args.run_id)
    commands = {int(row["command_id"]) for row in plan["tasks"]}
    sides = {side: load_side(path, side, args.run_id, commands) for side, path in paths.items()}
    summary, slot_rows, task_rows = summarize(plan, sides["ble"], sides["zigbee"])
    summary["sources"] = {"board": {"path": str(board_path.resolve()),
                                     "sha256": hashlib.sha256(board_path.read_bytes()).hexdigest()},
                          **{side: {"path": str(path.resolve()),
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                             for side, path in paths.items()}}
    for side, data in sides.items():
        for kind, path in (("receiver_summary", paths[side].with_name("rx.summary.json")),
                           ("live_control_summary", data["live_path"])):
            if path is not None:
                summary["sources"][f"{side}_{kind}"] = {
                    "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    output = args.experiment_dir / "analyses" / args.analysis_id
    if output.exists():
        parser.error(f"output already exists: {output}")
    output.mkdir(parents=True)
    write_csv(output / "plan.slots.metrics.csv", slot_rows)
    write_csv(output / "plan.tasks.metrics.csv", task_rows)
    (output / "plan.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 多任务共包联合分析", "",
             f"- Run ID：{args.run_id}；计划控制任务：{len(task_rows)}；板端 secondary DMA 完成：{summary['board_tx_completed']}/{summary['planned_slots']}",
             f"- BLE / IEEE 有效解码尝试：{summary['ble_valid_attempts']}/{summary['planned_slots']} / {summary['zigbee_valid_attempts']}/{summary['planned_slots']}",
             f"- 同尝试联合有效解码：{summary['joint_valid_attempts']}/{summary['planned_slots']}",
             f"- 逐任务联合有效解析：{summary['joint_decoded_tasks']}/{len(task_rows)}" if task_rows else
             "- 逐任务联合有效解析：N/A（零任务）",
             f"- 两侧软件处理事件均出现：{summary['joint_software_processed_tasks']}/{len(task_rows)}" if task_rows else
             "- 两侧软件处理事件均出现：N/A（零任务）",
             "", "| Command ID | 计划发送 | BLE 有效 | IEEE 有效 | 同尝试双方有效 | 双方解析任务 | BLE/IEEE 实时状态 |",
             "|---:|---:|---:|---:|---:|---:|---|"]
    for row in task_rows:
        lines.append(f"| {row['command_id']} | {row['planned_attempts']} | {row['ble_valid_attempts']} | "
                     f"{row['zigbee_valid_attempts']} | {row['same_attempt_joint_valid']} | "
                     f"{row['joint_task_decoded']} | {row['ble_live_status']} / {row['zigbee_live_status']} |")
    lines += ["", "逐槽及逐任务数据见 [plan.slots.metrics.csv](plan.slots.metrics.csv)、[plan.tasks.metrics.csv](plan.tasks.metrics.csv) 和 [plan.summary.json](plan.summary.json)。",
              "软件处理事件不等于物理执行；两台 IQ 的独立采样零点未校准，不能由此计算执行时差。", ""]
    (output / "plan.report.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
