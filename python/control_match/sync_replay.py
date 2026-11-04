#!/usr/bin/env python3
"""Single-run, chronological replay of independent B2Z receiver clock fits."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

try:
    from .analyze import analyze, capture_interval, discover, read_side
except ImportError:
    from analyze import analyze, capture_interval, discover, read_side


def fit(events: dict, sample_rate: float) -> tuple[float, float]:
    """Return local IQ seconds = intercept + slope * sender planned seconds."""
    points = [(v["record"]["ref_tick_ms"] / 1000, v["sample_start"] / sample_rate)
              for _, v in sorted(events.items())]
    if len(points) == 1:
        return points[0][1] - points[0][0], 1.0  # nominal sample rate
    center_t = statistics.fmean(t for t, _ in points)
    center_x = statistics.fmean(x for _, x in points)
    variance = sum((t - center_t) ** 2 for t, _ in points)
    if variance == 0:
        raise ValueError("training points have no time span")
    slope = sum((t - center_t) * (x - center_x) for t, x in points) / variance
    if not 0.99 < slope < 1.01:
        raise ValueError(f"implausible fitted clock slope: {slope}")
    return center_x - slope * center_t, slope


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)


def replay(ble: dict, zigbee: dict, ble_rate: float, zigbee_rate: float,
           cut_slot: int, sizes: tuple[int, ...]) -> tuple[list[dict], list[dict]]:
    sides = (ble["by_slot"], zigbee["by_slot"])
    histories = [sorted(k for k in side if k < cut_slot) for side in sides]
    validation = sorted(k for k in sides[0].keys() & sides[1].keys() if k >= cut_slot)
    if not validation:
        raise ValueError("no jointly received held-out packets")
    if any(sides[0][k]["record"]["ref_tick_ms"] != sides[1][k]["record"]["ref_tick_ms"]
           for k in validation):
        raise ValueError("validation reference timestamps disagree")
    summaries, details = [], []
    for mode in ("natural", "disjoint"):
        for size in sizes:
            bkeys = histories[0][-size:]
            zpool = [k for k in histories[1] if mode != "disjoint" or k not in bkeys]
            zkeys = zpool[-size:]
            if len(bkeys) != size or len(zkeys) != size:
                summaries.append({"mode": mode, "packets_per_side": size, "status": "insufficient_training",
                                  "validation_count": len(validation)})
                continue
            bfit = fit({k: sides[0][k] for k in bkeys}, ble_rate)
            zfit = fit({k: sides[1][k] for k in zkeys}, zigbee_rate)
            errors = []
            for slot in validation:
                bt = (sides[0][slot]["sample_start"] / ble_rate - bfit[0]) / bfit[1]
                zt = (sides[1][slot]["sample_start"] / zigbee_rate - zfit[0]) / zfit[1]
                error_us = (bt - zt) * 1e6
                errors.append(error_us)
                details.append({"mode": mode, "packets_per_side": size, "validation_slot": slot,
                                "ref_tick_ms": sides[0][slot]["record"]["ref_tick_ms"],
                                "ble_estimated_s": bt, "zigbee_estimated_s": zt,
                                "relative_error_us": error_us, "abs_error_us": abs(error_us)})
            absolute = [abs(value) for value in errors]
            summaries.append({"mode": mode, "packets_per_side": size, "status": "complete",
                              "ble_train_slots": ";".join(map(str, bkeys)),
                              "zigbee_train_slots": ";".join(map(str, zkeys)),
                              "train_overlap": len(set(bkeys) & set(zkeys)),
                              "ble_latest_slot": bkeys[-1], "zigbee_latest_slot": zkeys[-1],
                              "ble_first_validation_age_ms": sides[0][validation[0]]["record"]["ref_tick_ms"] - sides[0][bkeys[-1]]["record"]["ref_tick_ms"],
                              "zigbee_first_validation_age_ms": sides[1][validation[0]]["record"]["ref_tick_ms"] - sides[1][zkeys[-1]]["record"]["ref_tick_ms"],
                              "ble_span_ms": sides[0][bkeys[-1]]["record"]["ref_tick_ms"] - sides[0][bkeys[0]]["record"]["ref_tick_ms"],
                              "zigbee_span_ms": sides[1][zkeys[-1]]["record"]["ref_tick_ms"] - sides[1][zkeys[0]]["record"]["ref_tick_ms"],
                              "ble_slope_ppm": (bfit[1] - 1) * 1e6,
                              "zigbee_slope_ppm": (zfit[1] - 1) * 1e6,
                              "validation_count": len(validation),
                              "mean_signed_us": statistics.fmean(errors),
                              "median_abs_us": quantile(absolute, .5),
                              "p95_abs_us": quantile(absolute, .95),
                              "p99_abs_us": quantile(absolute, .99),
                              "max_abs_us": max(absolute)})
    return summaries, details


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--command-id", type=int, required=True)
    parser.add_argument("--cut-slot", type=int, default=60)
    parser.add_argument("--sizes", default="1,2,4,8,16,32")
    parser.add_argument("--analysis-id", default=None)
    args = parser.parse_args()
    sizes = tuple(int(value) for value in args.sizes.split(","))
    if args.cut_slot <= 0 or not sizes or any(size <= 0 for size in sizes) or len(set(sizes)) != len(sizes):
        parser.error("cut-slot and sizes must be positive; sizes must be unique")
    sources = {side: discover(args.experiment_dir, side) for side in ("ble", "zigbee")}
    if not all(sources.values()):
        parser.error("one complete BLE and one complete ZigBee capture are required")
    intervals = [capture_interval(path) for path in sources.values()]
    if max(start for start, _ in intervals) >= min(end for _, end in intervals):
        parser.error("capture intervals do not overlap")
    records = {side: read_side(path, side, args.run_id, args.command_id) for side, path in sources.items()}
    matched, _ = analyze(records["ble"], records["zigbee"], None, args.run_id, args.command_id, True)
    if matched["shared_field_mismatches"] or not matched["cross_side_task_fields_match"]:
        parser.error("independently recovered shared control fields disagree")
    rates = {side: json.loads(path.with_name("rx.summary.json").read_text())["config"]["sample_rate"]
             for side, path in sources.items()}
    summaries, details = replay(records["ble"], records["zigbee"], rates["ble"], rates["zigbee"],
                                args.cut_slot, sizes)
    analysis = args.analysis_id or datetime.now(timezone.utc).strftime("sync_replay_%Y%m%dT%H%M%S_%fZ")
    if Path(analysis).name != analysis or analysis in (".", ".."):
        parser.error("analysis-id must be one directory name")
    output = args.experiment_dir / "analyses" / analysis
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "sync.sweep.csv", summaries)
    write_csv(output / "sync.validation.csv", details)
    result = {"schema": "b2z_sync_replay_v1", "run_id": args.run_id, "command_id": args.command_id,
              "cut_slot": args.cut_slot, "sizes": sizes,
              "sources": {side: {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for side, path in sources.items()},
              "sample_rates": rates, "summary": summaries,
              "measurement": "difference between independently fitted sender-time estimates at later common RF events",
              "limitations": ["single-run offline replay; masked packets simulate loss",
                              "fixed BLE/ZigBee marker and path biases are not independently calibrated",
                              "sender ref_tick is planned, not measured RF-start time",
                              "does not measure software execution or absolute time accuracy"]}
    (output / "sync.summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 单轮离线同步回放", "", f"Run {args.run_id}，Command {args.command_id}；训练时隙 `<{args.cut_slot}`，验证时隙 `≥{args.cut_slot}`。",
             "两侧独立用各自历史有效包拟合本地采样时间与包内计划时间的线性关系；1 包时只估计偏移，速率采用标称值。训练结束后冻结模型。",
             "natural 使用各侧最近的包；disjoint 从 ZigBee 训练集中排除 BLE 训练时隙，模拟两侧收到完全不同的包。验证只使用更晚的共同有效包。", "",
             "| 模式 | 每侧训练包 | 训练重合 | 验证包 | 绝对差中位数 (μs) | P95 (μs) | 最大 (μs) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for item in summaries:
        if item["status"] != "complete":
            lines.append(f"| {item['mode']} | {item['packets_per_side']} | N/A | {item['validation_count']} | 训练不足 | N/A | N/A |")
        else:
            lines.append(f"| {item['mode']} | {item['packets_per_side']} | {item['train_overlap']} | {item['validation_count']} | {item['median_abs_us']:.3f} | {item['p95_abs_us']:.3f} | {item['max_abs_us']:.3f} |")
    lines += ["", "完整训练时隙、更新时间、拟合速率及逐验证包误差见 [sync.sweep.csv](sync.sweep.csv) 和 [sync.validation.csv](sync.validation.csv)。", "",
              "同一验证包的两侧时间估计差可检验相对一致性。固定前导码/接收路径偏差尚未独立校准，结果不能称为绝对同步精度或执行时差。",
              "只有一轮录制；P95/P99 是探索性描述，不能作为稳定尾部误差界。发送时刻使用计划值，板端实际 RF 起点仍未知。", ""]
    (output / "sync.report.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"结果：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
