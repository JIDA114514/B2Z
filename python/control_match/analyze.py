#!/usr/bin/env python3
"""Validate v1 B2 43 control records in saved independent receiver packets."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

try:
    from .protocol import control_record
except ImportError:  # Direct execution: python3 python/control_match/analyze.py
    from protocol import control_record


SHARED_FIELDS = ("version", "flags", "run_id", "slot_index", "ref_tick_ms",
                 "period_ms", "command_id", "execute_at_ms", "valid_until_ms")
TASK_FIELDS = ("version", "flags", "run_id", "period_ms", "command_id",
               "execute_at_ms", "valid_until_ms")


def extract_ble(packet: dict) -> bytes | None:
    if not packet.get("crc_ok") or packet.get("kind") not in ("auxiliary", "same_channel_auxiliary_diagnostic"):
        return None
    for ad in packet.get("extended", {}).get("ad_structures", []):
        if ad.get("type") != 255 or ad.get("company_id") != 0xffff:
            continue
        data = bytes.fromhex(ad["data_hex"])
        if data[2:4] == b"\xb2\x43":
            if packet.get("pdu_length") != 224 or len(data) != 209:
                raise ValueError("control_wire_budget")
            return data[2:37]
    return None


def extract_zigbee(packet: dict) -> bytes | None:
    if not packet.get("fcs_ok"):
        return None
    data = bytes.fromhex(packet["payload_hex"])
    return data if data[:2] == b"\xb2\x43" else None


def read_side(path: Path, side: str, run_id: int, command_id: int) -> dict:
    extract = extract_ble if side == "ble" else extract_zigbee
    counts = {"rows": 0, "control_candidates": 0, "valid_records": 0,
              "duplicates": 0, "foreign_run_or_command": 0, "invalid": {}}
    by_slot = {}
    with path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            counts["rows"] += 1
            try:
                packet = json.loads(line)
                data = extract(packet)
            except (KeyError, TypeError, ValueError) as exc:
                reason = f"packet:{type(exc).__name__}"
                counts["invalid"][reason] = counts["invalid"].get(reason, 0) + 1
                continue
            if data is None:
                continue
            counts["control_candidates"] += 1
            try:
                record = control_record(data)
                if side == "ble" and packet.get("extended", {}).get("adi", {}).get("did") != (record["slot_index"] & 0xfff):
                    raise ValueError("adi_slot")
            except ValueError as exc:
                reason = str(exc)
                counts["invalid"][reason] = counts["invalid"].get(reason, 0) + 1
                continue
            if (record["run_id"], record["command_id"]) != (run_id, command_id):
                counts["foreign_run_or_command"] += 1
                continue
            counts["valid_records"] += 1
            slot = record["slot_index"]
            event = {"record": record, "packet_no": packet.get("packet_no"),
                     "sample_start": packet.get("sample_start"),
                     "sample_time_s": packet.get("sample_time_s"), "line_no": line_no}
            if slot in by_slot:
                counts["duplicates"] += 1
                if record != by_slot[slot]["record"]:
                    raise ValueError(f"conflicting {side} records at slot {slot}")
            else:
                by_slot[slot] = event
    counts["unique_slots"] = len(by_slot)
    return {"side": side, "path": str(path), "counts": counts, "by_slot": by_slot}


def discover(experiment_dir: Path, side: str) -> Path | None:
    paths = sorted(experiment_dir.glob(f"captures/{side}/**/*.packets.jsonl"))
    usable = []
    for path in paths:
        summary_path = path.with_name(path.name.replace(".packets.jsonl", ".summary.json"))
        if summary_path.exists() and json.loads(summary_path.read_text()).get("status") == "complete":
            usable.append(path)
    if len(usable) > 1:
        raise ValueError(f"multiple complete {side} captures; specify --{side}-packets")
    return usable[0] if usable else None


def read_board(path: Path | None, run_id: int, command_id: int) -> dict | None:
    if path is None:
        return None
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("CONTROL_STATS "):
            continue
        fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
        if (fields.get("final"), fields.get("run_id"), fields.get("command_id")) == ("1", str(run_id), str(command_id)):
            matches.append(fields)
    if len(matches) != 1:
        raise ValueError("board log needs exactly one matching final CONTROL_STATS")
    fields = matches[0]
    if fields.get("state") != "complete":
        raise ValueError("board run did not complete")
    for key in ("scheduled", "generated", "primary_completed", "tx_completed", "deadline_miss", "dma_timeout"):
        fields[key] = int(fields[key])
    if not 0 <= fields["tx_completed"] <= fields["scheduled"]:
        raise ValueError("invalid board secondary completion count")
    return fields


def capture_interval(path: Path) -> tuple[datetime, datetime]:
    summary_path = path.with_name(path.name.replace(".packets.jsonl", ".summary.json"))
    summary = json.loads(summary_path.read_text())
    if summary.get("status") != "complete":
        raise ValueError(f"capture not complete: {summary_path}")
    return (datetime.fromisoformat(summary["start_utc"]), datetime.fromisoformat(summary["end_utc"]))


def analyze(ble: dict | None, zigbee: dict | None, board: dict | None,
            run_id: int, command_id: int, same_transmission: bool) -> tuple[dict, list[dict]]:
    if same_transmission and (ble is None or zigbee is None):
        raise ValueError("--same-transmission requires both receiver files")
    if same_transmission:
        b0, b1 = capture_interval(Path(ble["path"]))
        z0, z1 = capture_interval(Path(zigbee["path"]))
        if max(b0, z0) >= min(b1, z1):
            raise ValueError("receiver capture wall-time intervals do not overlap")
    bslots = ble["by_slot"] if ble else {}
    zslots = zigbee["by_slot"] if zigbee else {}
    task_keys = [{tuple(event["record"][key] for key in TASK_FIELDS) for event in slots.values()}
                 for slots in (bslots, zslots)]
    task_semantics_consistent = all(len(keys) <= 1 for keys in task_keys)
    if not task_semantics_consistent:
        raise ValueError("same run_id/command_id has conflicting task fields across slots")
    cross_side_task_match = (task_semantics_consistent and bool(task_keys[0]) and bool(task_keys[1])
                             and task_keys[0] == task_keys[1]) if ble and zigbee else None
    scheduled = board["scheduled"] if board else None
    if scheduled is not None and any(slot >= scheduled for slot in set(bslots) | set(zslots)):
        raise ValueError("received slot outside board scheduled range")
    slots = range(scheduled) if scheduled is not None else sorted(set(bslots) | set(zslots))
    rows = []
    for slot in slots:
        b, z = bslots.get(slot), zslots.get(slot)
        shared_match = (all(b["record"][key] == z["record"][key] for key in SHARED_FIELDS)
                        if b and z else None)
        rows.append({"slot_index": slot, "ble_valid": int(b is not None),
                     "zigbee_valid": int(z is not None),
                     "shared_fields_match": "" if shared_match is None else int(shared_match),
                     "ble_packet_no": b["packet_no"] if b else "",
                     "zigbee_packet_no": z["packet_no"] if z else "",
                     "ble_sample_start": b["sample_start"] if b else "",
                     "zigbee_sample_start": z["sample_start"] if z else ""})
    both = sum(row["ble_valid"] and row["zigbee_valid"] and row["shared_fields_match"] == 1 for row in rows)
    summary = {
        "schema": "b2z_control_match_v1", "run_id": run_id, "command_id": command_id,
        "same_transmission_asserted": same_transmission,
        "sources": {side: {"path": result["path"],
                           "sha256": hashlib.sha256(Path(result["path"]).read_bytes()).hexdigest()}
                    for side, result in (("ble", ble), ("zigbee", zigbee)) if result},
        "board": board,
        "sides": {side: result["counts"] for side, result in (("ble", ble), ("zigbee", zigbee)) if result},
        "planned_slots": scheduled, "observed_union_slots": len(set(bslots) | set(zslots)),
        "identifier_overlap_slots": both if ble and zigbee else None,
        "joint_valid_decode_slots": both if same_transmission else None,
        "joint_valid_decode_denominator": scheduled if same_transmission else None,
        "joint_command_recovered": bool(cross_side_task_match) if same_transmission else None,
        "task_semantics_consistent": task_semantics_consistent,
        "cross_side_task_fields_match": cross_side_task_match,
        "shared_field_mismatches": sum(row["shared_fields_match"] == 0 for row in rows),
        "ble_only_slots": sum(row["ble_valid"] and not row["zigbee_valid"] for row in rows) if ble and zigbee else None,
        "zigbee_only_slots": sum(row["zigbee_valid"] and not row["ble_valid"] for row in rows) if ble and zigbee else None,
        "neither_slots": sum(not row["ble_valid"] and not row["zigbee_valid"] for row in rows) if scheduled is not None and ble and zigbee else None,
        "limitations": ["Receiver records prove decoding, not command execution.",
                        "Board tx_completed is a DMA-completion proxy, not measured RF airtime.",
                        "Independent HackRF sample times have separate origins and are not subtracted.",
                        "Same-channel diagnostic packets do not prove standards-compliant AuxPtr following."],
    }
    return summary, rows


def report(summary: dict) -> str:
    sides = summary["sides"]
    lines = ["# B2Z v1 控制包匹配", "",
             f"- Run ID：{summary['run_id']}；Command ID：{summary['command_id']}",
             f"- 计划时隙：{summary['planned_slots'] if summary['planned_slots'] is not None else 'N/A'}",
             f"- 同次同步录制声明：{'是' if summary['same_transmission_asserted'] else '否'}", "",
             "| 接收侧 | 控制候选 | 记录有效 | 唯一时隙 | 重复 |", "|---|---:|---:|---:|---:|"]
    for side in ("ble", "zigbee"):
        if side in sides:
            c = sides[side]
            lines.append(f"| {side} | {c['control_candidates']} | {c['valid_records']} | {c['unique_slots']} | {c['duplicates']} |")
    if summary["board"]:
        lines.append("")
        completed = summary["board"]["tx_completed"]
        for side in ("ble", "zigbee"):
            if side in sides:
                value = sides[side]["unique_slots"]
                lines.append(f"- {side} 有效解码 / 板端 secondary DMA 完成：{value}/{completed}" if completed else
                             f"- {side} 有效解码 / 板端 secondary DMA 完成：N/A（{value}/0）")
    lines += ["", f"- 跨文件标识重合时隙：{summary['identifier_overlap_slots'] if summary['identifier_overlap_slots'] is not None else 'N/A'}"]
    joint = summary["joint_valid_decode_slots"]
    denom = summary["joint_valid_decode_denominator"]
    if joint is None:
        joint_text = "N/A（未声明同次录制）"
    elif denom is None:
        joint_text = f"{joint}/N/A（缺板端计划时隙数）"
    elif denom == 0:
        joint_text = f"N/A（{joint}/0）"
    else:
        joint_text = f"{joint}/{denom}"
    lines.append(f"- 联合有效解码：{joint_text}")
    if joint is not None:
        if summary["command_id"] == 0:
            lines.append(f"- 同一轮纯时间更新两侧至少各恢复一次：{'是' if summary['joint_command_recovered'] else '否'}（可来自不同发送时隙；不代表控制任务）")
        else:
            lines.append(f"- 同一命令两侧至少各恢复一次：{'是' if summary['joint_command_recovered'] else '否'}（可来自不同重发时隙；仅表示解析）")
        lines.append(f"- 仅 BLE / 仅 ZigBee / 两侧均缺：{summary['ble_only_slots']} / {summary['zigbee_only_slots']} / {summary['neither_slots'] if summary['neither_slots'] is not None else 'N/A'}")
    lines += ["", "`control.slots.metrics.csv` 逐时隙列出两侧独立结果；没有同次录制声明时，标识重合不作为联合成功。",
              "", *["- " + item for item in summary["limitations"]], ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--ble-packets", type=Path)
    parser.add_argument("--zigbee-packets", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--command-id", type=int, required=True)
    parser.add_argument("--board-log", type=Path)
    parser.add_argument("--same-transmission", action="store_true",
                        help="assert both receiver captures observed the same board transmission")
    parser.add_argument("--analysis-id", help="single new directory name under analyses/")
    args = parser.parse_args(argv)
    if not 1 <= args.run_id <= 65535 or not 0 <= args.command_id <= 0x7fffffff:
        parser.error("run-id or command-id out of range")
    if args.analysis_id and (Path(args.analysis_id).name != args.analysis_id or args.analysis_id in (".", "..")):
        parser.error("analysis-id must be a single directory name")
    experiment = args.experiment_dir.resolve()
    if not experiment.is_dir():
        parser.error("experiment directory does not exist")
    ble_path = args.ble_packets or discover(experiment, "ble")
    zigbee_path = args.zigbee_packets or discover(experiment, "zigbee")
    if not ble_path and not zigbee_path:
        parser.error("no complete receiver packet files found")
    board_path = args.board_log or (experiment / "board.board.log" if (experiment / "board.board.log").exists() else None)
    ble = read_side(ble_path, "ble", args.run_id, args.command_id) if ble_path else None
    zigbee = read_side(zigbee_path, "zigbee", args.run_id, args.command_id) if zigbee_path else None
    board = read_board(board_path, args.run_id, args.command_id)
    summary, rows = analyze(ble, zigbee, board, args.run_id, args.command_id, args.same_transmission)
    if board_path:
        summary["sources"]["board_log"] = {"path": str(board_path),
                                              "sha256": hashlib.sha256(board_path.read_bytes()).hexdigest()}
    analysis_id = args.analysis_id or datetime.now(timezone.utc).strftime("control_match_%Y%m%dT%H%M%S_%fZ")
    output = experiment / "analyses" / analysis_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "control.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "control.report.md").write_text(report(summary), encoding="utf-8")
    with (output / "control.slots.metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=("slot_index", "ble_valid", "zigbee_valid",
                                               "shared_fields_match", "ble_packet_no", "zigbee_packet_no",
                                               "ble_sample_start", "zigbee_sample_start"))
        writer.writeheader()
        writer.writerows(rows)
    print(report(summary), end="")
    print(f"结果：{output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
