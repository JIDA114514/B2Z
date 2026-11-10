#!/usr/bin/env python3
"""Compare N2 fixed-frequency runs without inventing RF or execution timing."""
import argparse
import hashlib
import json
from pathlib import Path


def compare(joint: dict, separate: dict, conditions: dict) -> dict:
    for summary, mode in ((joint, "joint"), (separate, "separate_bluebee")):
        if summary.get("schema") != "b2z_plan_match_v2" or (summary.get("waveform_cost") or {}).get("mode") != mode:
            raise ValueError(f"requires a complete {mode} plan summary with burst costs")
        if "ble_follow" in summary:
            raise ValueError("main N2 comparison requires two fixed-frequency runs; follow verification is separate")
    differences = []
    for key in ("planned_slots", "planned_control_tasks", "planned_task_manifest"):
        if joint.get(key) != separate.get(key):
            differences.append(key)
    if not joint.get("planned_task_manifest") or any(v is None for r in joint["planned_task_manifest"] for v in r.values()):
        differences.append("missing_board_task_configuration")
    for key in ("period_ms", "aux_channel", "aux_offset_us"):
        if joint["board"].get(key) is None or joint["board"].get(key) != separate["board"].get(key):
            differences.append(f"board.{key}")
    for side in ("ble", "zigbee"):
        a = (joint.get("receiver_configs") or {}).get(side) or {}
        b = (separate.get("receiver_configs") or {}).get(side) or {}
        keys = ["sample_rate", "center_hz", "serial", "lna", "vga", "amp", "duration", "block_samples"]
        keys += ["channels", "whitening_channels"] if side == "ble" else ["channel", "demod", "symbol_order"]
        for key in keys:
            if key not in a or key not in b or a[key] != b[key]:
                differences.append(f"receiver.{side}.{key}")
    # Physical setup is a human record; don't infer wiring/power from packet logs.
    for name in ("topology", "tx_power", "firmware_build", "attenuation"):
        a = conditions.get("joint", {}).get(name)
        b = conditions.get("separate", {}).get(name)
        if not a or not b or a != b or str(a).upper() in ("TODO", "UNKNOWN"):
            differences.append(f"conditions.{name}")
    metrics = {}
    for name, summary in (("joint", joint), ("separate", separate)):
        cost = summary["waveform_cost"]
        metrics[name] = {
            "run_id": summary["run_id"],
            "joint_parsed_tasks": {"numerator": summary["joint_decoded_tasks"],
                                   "denominator": summary["planned_control_tasks"],
                                   "value": summary["joint_decoded_tasks"] / summary["planned_control_tasks"] if summary["planned_control_tasks"] else None},
            **{k: cost[k] for k in ("planned_waveform_us", "submitted_waveform_us", "submitted_zero_padding_us", "burst_attempted", "burst_started", "burst_completed", "uncertain_bursts", "per_joint_decoded_task")},
            "quadrants": {k: summary[k] for k in ("joint_valid_attempts", "ble_only_attempts", "zigbee_only_attempts", "neither_attempts")}}
    return {"schema": "b2z_n2_comparison_v1", "recorded_conditions_match": not differences,
            "unresolved_or_different_conditions": differences, "groups": metrics,
            "joint_minus_separate_submitted_waveform_us": metrics["joint"]["submitted_waveform_us"] - metrics["separate"]["submitted_waveform_us"],
            "conditions": conditions,
            "limitations": ["single rounds do not establish reliability superiority",
                            "submitted waveform length is not measured RF occupancy",
                            "cross-device completion latency, deadlines and physical execution are not measured",
                            "fewer submissions caused by sender failure are not an efficiency gain"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint-summary", type=Path, required=True)
    parser.add_argument("--separate-summary", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, required=True, help="JSON with joint/separate topology, tx_power, firmware_build, attenuation")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = {k: getattr(args, k) for k in ("joint_summary", "separate_summary", "conditions")}
    try:
        data = {k: json.loads(p.read_text()) for k, p in paths.items()}
        result = compare(data["joint_summary"], data["separate_summary"], data["conditions"])
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.output_dir.exists():
        parser.error("output directory already exists")
    result["sources"] = {k: {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for k, p in paths.items()}
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["# N2 共包与分别发送比较", "",
             f"已记录条件一致：{result['recorded_conditions_match']}（只核对已记录配置）", "",
             "| 组 | Run | 联合解析任务 | 提交有效波形 µs | padding µs | 提交成功/完成 | µs/成功任务 |",
             "|---|---:|---|---:|---:|---|---|"]
    for name, row in result["groups"].items():
        rate = row["joint_parsed_tasks"]
        unit = row["per_joint_decoded_task"]["value_us"]
        lines.append(f"| {name} | {row['run_id']} | {rate['numerator']}/{rate['denominator']} | {row['submitted_waveform_us']} | {row['submitted_zero_padding_us']} | {row['burst_started']}/{row['burst_completed']} | {unit if unit is not None else 'N/A'} |")
    lines += ["", "差异/未记录项：" + (", ".join(result["unresolved_or_different_conditions"]) or "无"), "",
              "包含全轮时间更新、失败及重发。波形长度不等于实测 RF 占用；发送失败造成的成本减少不能称为效率提升。跨机完成时延、同步精度和执行器动作未测。"]
    (args.output_dir / "comparison.md").write_text("\n".join(lines) + "\n")
    print(f"recorded_conditions_match={result['recorded_conditions_match']} output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
