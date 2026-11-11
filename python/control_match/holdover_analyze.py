#!/usr/bin/env python3
"""Predefined two-receiver holdover replay for the 300-slot time-only plan.

The held-out packets are used only to score independently fitted clocks.
No per-packet cross-receiver alignment or validation-slot fitting is done.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

try:
    from .analyze import SHARED_FIELDS, capture_interval, read_side
    from .sync_replay import fit, quantile
except ImportError:
    from analyze import SHARED_FIELDS, capture_interval, read_side
    from sync_replay import fit, quantile


SLOTS = 300
PERIOD_MS = 200
VALIDATION = tuple(s for s in range(20, SLOTS) if s % 5 in (2, 3, 4))
SIZES = (1, 2, 5, 10)
INTERVAL_SLOTS = (None, 5, 25, 50)
THRESHOLDS_US = (1000, 5000, 10000, 20000)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_side(side: dict, label: str) -> None:
    slots = side["by_slot"]
    if any(s not in range(SLOTS) for s in slots):
        raise ValueError(f"{label}: slot outside 0..299")
    if any(e["record"]["ref_tick_ms"] != PERIOD_MS * s or
           e["record"]["period_ms"] != PERIOD_MS for s, e in slots.items()):
        raise ValueError(f"{label}: packet time fields disagree with plan")
    if side["counts"]["duplicates"] or side["counts"]["invalid"]:
        raise ValueError(f"{label}: duplicate or invalid control records")


def candidate_slots(mode: str, side: str, interval: int | None) -> list[int]:
    parity = 1 if mode == "disjoint" and side == "zigbee" else 0
    if interval is None:
        return list(range(parity, 20, 2))
    return list(range(parity, 20, 2)) + list(range(20 + parity, SLOTS, interval))


def model_at(slots: dict, sample_rate: int, candidates: list[int],
             size: int, probe_slot: int) -> tuple[tuple[float, float] | None, list[int]]:
    history = [s for s in candidates if s < probe_slot and s in slots]
    selected = history[-size:]
    if len(selected) < size:
        return None, selected
    return fit({s: slots[s] for s in selected}, sample_rate), selected


def summarize(errors: list[float]) -> dict:
    if not errors:
        return {"conditional_count": 0}
    absolute = [abs(v) for v in errors]
    return {"conditional_count": len(errors),
            "mean_signed_us": statistics.fmean(errors),
            "median_abs_us": quantile(absolute, .5),
            "p95_abs_us": quantile(absolute, .95),
            "p99_abs_us": quantile(absolute, .99),
            "max_abs_us": max(absolute),
            **{f"within_{t}_us": sum(v <= t for v in absolute) for t in THRESHOLDS_US}}


def evaluate(ble: dict, zigbee: dict, rates: dict[str, int]) -> tuple[list[dict], list[dict]]:
    streams = {"ble": ble["by_slot"], "zigbee": zigbee["by_slot"]}
    summaries, rows = [], []
    for mode in ("common", "disjoint"):
        for interval in INTERVAL_SLOTS:
            for size in SIZES:
                policy = "freeze" if interval is None else f"periodic_{interval * PERIOD_MS // 1000}s"
                candidate = {side: candidate_slots(mode, side, interval) for side in streams}
                errors = []
                for slot in VALIDATION:
                    observed = {side: slot in streams[side] for side in streams}
                    models = {side: model_at(streams[side], rates[side], candidate[side], size, slot)
                              for side in streams}
                    training_ready = all(models[side][0] is not None for side in streams)
                    row = {"mode": mode, "policy": policy, "packets_per_side": size,
                           "validation_slot": slot, "ref_tick_ms": slot * PERIOD_MS,
                           "ble_valid": int(observed["ble"]),
                           "zigbee_valid": int(observed["zigbee"]),
                           "training_ready": int(training_ready)}
                    for side in streams:
                        selected = models[side][1]
                        row[f"{side}_training_slots"] = ";".join(map(str, selected))
                        row[f"{side}_latest_update_slot"] = selected[-1] if selected else ""
                        row[f"{side}_update_age_ms"] = ((slot - selected[-1]) * PERIOD_MS
                                                         if selected else "")
                        row[f"{side}_slope_ppm"] = ((models[side][0][1] - 1) * 1e6
                                                     if models[side][0] else "")
                    if training_ready and all(observed.values()):
                        estimates = {side: ((streams[side][slot]["sample_start"] / rates[side]
                                             - models[side][0][0]) / models[side][0][1])
                                     for side in streams}
                        error = (estimates["ble"] - estimates["zigbee"]) * 1e6
                        row["relative_error_us"] = error
                        row["abs_error_us"] = abs(error)
                        errors.append(error)
                    else:
                        row["relative_error_us"] = row["abs_error_us"] = ""
                    rows.append(row)
                summary = {"mode": mode, "policy": policy, "packets_per_side": size,
                           "planned_validation_slots": len(VALIDATION),
                           "ble_valid_validation": sum(s in streams["ble"] for s in VALIDATION),
                           "zigbee_valid_validation": sum(s in streams["zigbee"] for s in VALIDATION),
                           "joint_valid_validation": sum(s in streams["ble"] and s in streams["zigbee"]
                                                         for s in VALIDATION),
                           **summarize(errors)}
                summary["training_insufficient_slots"] = sum(
                    not r["training_ready"] for r in rows[-len(VALIDATION):])
                summaries.append(summary)
    return summaries, rows


def timing_quality(records: dict, rates: dict[str, int]) -> tuple[dict, list[dict]]:
    """Diagnostic only; never realign either receiver from these differences."""
    rows, quality = [], {}
    for side, result in records.items():
        last = None
        deviations = []
        for slot, event in sorted(result["by_slot"].items()):
            if last is None:
                last = (slot, event)
                continue
            previous_slot, previous = last
            expected_ms = (slot - previous_slot) * PERIOD_MS
            observed_ms = (event["sample_start"] - previous["sample_start"]) / rates[side] * 1000
            deviation_ms = observed_ms - expected_ms
            deviations.append(deviation_ms)
            rows.append({"side": side, "previous_slot": previous_slot, "slot": slot,
                         "expected_ms": expected_ms, "observed_ms": observed_ms,
                         "deviation_ms": deviation_ms})
            last = (slot, event)
        quality[side] = {"adjacent_observations": len(deviations),
                         "max_abs_interval_deviation_ms": max(map(abs, deviations), default=None),
                         "over_1ms_intervals": sum(abs(x) > 1 for x in deviations),
                         "over_5ms_intervals": sum(abs(x) > 5 for x in deviations)}
    return quality, rows


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ble-packets", type=Path, required=True)
    parser.add_argument("--zigbee-packets", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="explicit N3 config; omit to retain legacy 300-slot/200-ms replay")
    parser.add_argument("--experiment-dir", type=Path)
    parser.add_argument("--board-log", type=Path)
    parser.add_argument("--allow-legacy-timing", action="store_true")
    args = parser.parse_args()
    if args.config:
        try:
            from .n3_analyze import run_analysis
        except ImportError:
            from n3_analyze import run_analysis
        if not args.experiment_dir:
            parser.error("N3 --config requires --experiment-dir")
        run_analysis(args.experiment_dir,args.run_id,args.config,
                     args.board_log or args.experiment_dir / "board.board.log",
                     {"ble":args.ble_packets,"zigbee":args.zigbee_packets},args.output_dir,args.allow_legacy_timing)
        return 0
    if args.output_dir.exists():
        parser.error("output directory already exists")
    sources = {"ble": args.ble_packets, "zigbee": args.zigbee_packets}
    intervals = [capture_interval(path) for path in sources.values()]
    if max(t[0] for t in intervals) >= min(t[1] for t in intervals):
        parser.error("capture intervals do not overlap")
    records = {side: read_side(path, side, args.run_id, 0) for side, path in sources.items()}
    for side in sources:
        check_side(records[side], side)
    for slot in records["ble"]["by_slot"].keys() & records["zigbee"]["by_slot"].keys():
        b, z = records["ble"]["by_slot"][slot]["record"], records["zigbee"]["by_slot"][slot]["record"]
        if any(b[key] != z[key] for key in SHARED_FIELDS):
            parser.error(f"shared time fields disagree at slot {slot}")
    receiver_summaries = {side: json.loads(path.with_name("rx.summary.json").read_text())
                          for side, path in sources.items()}
    rates = {side: summary["config"]["sample_rate"] for side, summary in receiver_summaries.items()}
    summaries, rows = evaluate(records["ble"], records["zigbee"], rates)
    timing, timing_rows = timing_quality(records, rates)
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "holdover.summary.csv", summaries)
    write_csv(args.output_dir / "holdover.validation.csv", rows)
    write_csv(args.output_dir / "timing.qc.csv", timing_rows)
    result = {"schema": "b2z_holdover_replay_v1", "run_id": args.run_id,
              "plan": "doc/independent_sync_holdover_experiment_plan.md",
              "method": "fixed validation slots, independent historical clock fits, no probe fitting",
              "planned_slots": SLOTS, "validation_slots": VALIDATION,
              "sample_rates": rates, "sources": {side: {"path": str(path.resolve()), "sha256": sha256(path)}
                                              for side, path in sources.items()},
              "capture_config_run_ids": {side: summary["config"]["run_id"]
                                         for side, summary in receiver_summaries.items()},
              "decoded_slots": {side: sorted(records[side]["by_slot"]) for side in sources},
              "timing_quality": timing,
              "summary": summaries,
              "limitations": ["offline holdover replay using truly decoded probes; masked training is simulated loss",
                              "no absolute RF-start or physical execution timestamp",
                              "actual board RF launch is unmeasured; sample continuity needs independent check"]}
    (args.output_dir / "holdover.summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"run={args.run_id} ble={len(records['ble']['by_slot'])} "
          f"zigbee={len(records['zigbee']['by_slot'])} validation={len(VALIDATION)} "
          f"policies={len(summaries)} output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
