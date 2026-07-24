#!/usr/bin/env python3
"""Plan, run, and summarize BlueBee scans without consuming board logs."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time


PAYLOAD_LENGTHS = (10, 16, 24, 32, 40, 46)
TESTS = ("pure", "exadv")
MODES = {"realtime": 0, "double": 2}
MANIFEST_SCHEMA = "bluebee-throughput-scan-v1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_csv_ints(text, label):
    try:
        values = tuple(int(item, 10) for item in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be decimal CSV") from error
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError(f"{label} values must be positive")
    return values


def parse_payloads(text):
    values = parse_csv_ints(text, "payload lengths")
    invalid = [value for value in values if value not in PAYLOAD_LENGTHS]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"payload lengths must be selected from {PAYLOAD_LENGTHS}"
        )
    return values


def parse_intervals(text):
    return parse_csv_ints(text, "intervals")


def json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unsupported manifest schema in {path}")
    return data


def build_cases(args, output_dir):
    receiver_script = Path(__file__).with_name("zigbee_perf_rx.py").resolve()
    tests = TESTS if args.test == "both" else (args.test,)
    modes = tuple(MODES) if args.mode == "both" else (args.mode,)
    case_count = len(tests) * len(modes) * len(args.payloads) * len(args.intervals_us)
    if case_count > 0x10000:
        raise ValueError("scan has more cases than the 16-bit Run ID space")

    base_run_id = (
        args.base_run_id
        if args.base_run_id is not None
        else int(time.time_ns() ^ (time.time_ns() >> 32)) & 0xFFFF
    )
    cases = []
    used_run_ids = set()
    for test in tests:
        for mode in modes:
            for payload_len in args.payloads:
                for interval_us in args.intervals_us:
                    run_id = (base_run_id + len(cases)) & 0xFFFF
                    if run_id in used_run_ids:
                        raise ValueError("Run ID wrapped within one scan")
                    used_run_ids.add(run_id)
                    stem = (
                        f"{len(cases):04d}_{test}_{mode}_p{payload_len}_"
                        f"i{interval_us}_r{run_id}"
                    )
                    csv_path = (output_dir / f"{stem}.csv").resolve()
                    json_path = (output_dir / f"{stem}.json").resolve()
                    receiver_duration = args.tx_duration_s + args.guard_s
                    receiver_command = [
                        sys.executable,
                        str(receiver_script),
                        "--chip-source",
                        "standard",
                        "--standard-keep-offset",
                        "auto",
                        "--standard-offset-policy",
                        "adaptive",
                        "--duration",
                        str(receiver_duration),
                        "--tx-duration-s",
                        str(args.tx_duration_s),
                        "--tx-interval-us",
                        str(interval_us),
                        "--run-id",
                        str(run_id),
                        "--payload-len",
                        str(payload_len),
                        "--csv-out",
                        str(csv_path),
                        "--json-out",
                        str(json_path),
                    ]
                    board_command = (
                        f"bluebee_{test}_perf_start? {payload_len} "
                        f"{interval_us} {args.tx_duration_s} {run_id} "
                        f"{MODES[mode]}"
                    )
                    cases.append(
                        {
                            "index": len(cases),
                            "test": test,
                            "mode": mode,
                            "mode_id": MODES[mode],
                            "payload_len": payload_len,
                            "interval_us": interval_us,
                            "tx_duration_s": args.tx_duration_s,
                            "receiver_duration_s": receiver_duration,
                            "run_id": run_id,
                            "receiver_command": receiver_command,
                            "board_command": board_command,
                            "csv_result": str(csv_path),
                            "json_result": str(json_path),
                            "status_result": str(
                                (output_dir / f"{stem}.status.json").resolve()
                            ),
                        }
                    )
    return cases


def command_plan(args):
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases(args, output_dir)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "created_utc": utc_now(),
        "policy": {
            "receiver_first": True,
            "board_start_window_s": 5,
            "reads_board_log": False,
            "validity_statement": (
                "Receiver timeout means observation complete only; it does not "
                "prove the board transmitted every planned packet."
            ),
            "loss_limitation": (
                "Without tx_completed, board-side omissions and wireless loss "
                "cannot be separated."
            ),
            "acceptance_metric": "planned_end_to_end_receive",
            "wireless_prr": None,
        },
        "cases": cases,
    }
    json_write(args.manifest.resolve(), manifest)
    print(f"Wrote {len(cases)} cases: {args.manifest.resolve()}")
    for case in cases:
        print(
            f"[{case['index']:04d}] RX: "
            f"{shlex.join(case['receiver_command'])}"
        )
        print(f"       BOARD: {case['board_command']}")


def select_case(manifest, index):
    cases = manifest["cases"]
    if not 0 <= index < len(cases):
        raise IndexError(f"case index must be in [0, {len(cases) - 1}]")
    case = cases[index]
    if case["index"] != index:
        raise ValueError("manifest case indexes are inconsistent")
    return case


def command_run(args):
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    case = select_case(manifest, args.case_index)
    print(f"Starting receiver first for case {case['index']:04d}:")
    print(f"  {shlex.join(case['receiver_command'])}")
    receiver = subprocess.Popen(case["receiver_command"])
    start_epoch = time.time()
    print("\nExecute this board command now, within about 5 seconds:")
    print(f"  {case['board_command']}\n")
    return_code = receiver.wait()
    end_epoch = time.time()
    status = {
        "schema": "bluebee-throughput-case-status-v1",
        "case_index": case["index"],
        "run_id": case["run_id"],
        "receiver_start_utc": datetime.fromtimestamp(
            start_epoch, timezone.utc
        ).isoformat(),
        "receiver_end_utc": datetime.fromtimestamp(
            end_epoch, timezone.utc
        ).isoformat(),
        "receiver_return_code": return_code,
        "receiver_observation_complete": return_code == 0,
        "board_completion_inferred": False,
        "board_log_read": False,
    }
    json_write(Path(case["status_result"]), status)
    if return_code:
        raise SystemExit(return_code)
    print(
        "Receiver observation completed. Board completion was not inferred; "
        f"status: {case['status_result']}"
    )


def result_row(case, result):
    ratios = result.get("ratios", {})
    planned = ratios.get("planned_end_to_end_receive", {})
    throughput = result.get("throughput", {})
    receiver = result.get("receiver", {})
    sequences = result.get("planned_sequences") or {}
    rate = planned.get("value")
    return {
        "case_index": case["index"],
        "test": case["test"],
        "mode": case["mode"],
        "payload_len": case["payload_len"],
        "interval_us": case["interval_us"],
        "tx_duration_s": case["tx_duration_s"],
        "run_id": case["run_id"],
        "expected_packets": sequences.get("expected_packets"),
        "in_range_unique": sequences.get("in_range_unique"),
        "missing": sequences.get("missing"),
        "out_of_range_count": sequences.get("out_of_range_count"),
        "planned_end_to_end_receive": rate,
        "gross_bit_s": throughput.get("gross_bit_s"),
        "gross_byte_s": throughput.get("gross_byte_s"),
        "application_bit_s": throughput.get("application_bit_s"),
        "application_byte_s": throughput.get("application_byte_s"),
        "time_basis": throughput.get("time_basis"),
        "crc_failure": receiver.get("crc_failure"),
        "duplicate": receiver.get("duplicate"),
        "out_of_order": receiver.get("out_of_order"),
        "longest_loss_burst": receiver.get("longest_loss_burst"),
        "stable_planned_99": rate is not None and rate >= 0.99,
        "wireless_prr": None,
        "json_result": case["json_result"],
    }


def command_report(args):
    manifest = load_manifest(args.manifest.resolve())
    rows = []
    missing = []
    for case in manifest["cases"]:
        result_path = Path(case["json_result"])
        if not result_path.exists():
            missing.append(case["index"])
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        rows.append(result_row(case, result))

    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(result_row(manifest["cases"][0], {}).keys())
    with args.csv_out.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    best = {}
    for row in rows:
        if not row["stable_planned_99"]:
            continue
        key = (row["test"], row["mode"], row["payload_len"])
        rank = (
            row["application_bit_s"] or 0.0,
            row["gross_bit_s"] or 0.0,
            -row["interval_us"],
        )
        if key not in best or rank > best[key][0]:
            best[key] = (rank, row)

    report = {
        "schema": "bluebee-throughput-report-v1",
        "created_utc": utc_now(),
        "manifest": str(args.manifest.resolve()),
        "metric_name": "planned_end_to_end_receive",
        "stable_threshold": 0.99,
        "wireless_prr": None,
        "deadline_miss_verified": False,
        "dma_timeout_verified": False,
        "loss_limitation": (
            "Board-side omissions and wireless loss are not distinguishable "
            "because board logs and tx_completed were not consumed."
        ),
        "complete_curve": rows,
        "best_stable": [
            value[1] for _, value in sorted(best.items(), key=lambda item: item[0])
        ],
        "missing_result_case_indexes": missing,
    }
    json_write(args.json_out, report)
    print(f"Curve rows: {len(rows)} -> {args.csv_out}")
    print(f"Report: {args.json_out}")
    if report["best_stable"]:
        print("Best >=99% planned end-to-end points:")
        for row in report["best_stable"]:
            print(
                f"  {row['test']}/{row['mode']} payload={row['payload_len']} "
                f"interval={row['interval_us']} us "
                f"planned={row['planned_end_to_end_receive'] * 100:.3f}% "
                f"gross={row['gross_bit_s']:.3f} bit/s "
                f"app={row['application_bit_s']:.3f} bit/s"
            )
    else:
        print(
            "No completed point meets the 99% planned end-to-end threshold; "
            "the full curve is retained."
        )
    print(
        "Wireless PRR is N/A: board omissions and wireless losses remain "
        "indistinguishable without tx_completed."
    )
    if missing:
        print(f"Missing results for {len(missing)} cases: {missing}")


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "BlueBee throughput scans using planned TX accounting only; "
            "never reads board serial logs"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Generate scan cases and commands")
    plan.add_argument("--test", choices=("pure", "exadv", "both"), default="both")
    plan.add_argument(
        "--mode", choices=("realtime", "double", "both"), default="both"
    )
    plan.add_argument(
        "--payloads",
        type=parse_payloads,
        default=PAYLOAD_LENGTHS,
        help="Comma-separated subset of 10,16,24,32,40,46",
    )
    plan.add_argument(
        "--intervals-us",
        type=parse_intervals,
        required=True,
        help="Comma-separated planned slot intervals, in microseconds",
    )
    plan.add_argument("--tx-duration-s", type=int, default=60)
    plan.add_argument(
        "--guard-s",
        type=int,
        default=10,
        help="Receiver time before/after TX combined (default: 10 s)",
    )
    plan.add_argument("--base-run-id", type=int)
    plan.add_argument(
        "--output-dir",
        type=Path,
        default=Path("bluebee_scan_results"),
    )
    plan.add_argument(
        "--manifest",
        type=Path,
        default=Path("bluebee_scan_results/scan_manifest.json"),
    )
    plan.set_defaults(handler=command_plan)

    run = subparsers.add_parser(
        "run",
        help="Start one receiver case, then display the board command",
    )
    run.add_argument("manifest", type=Path)
    run.add_argument("case_index", type=int)
    run.set_defaults(handler=command_run)

    report = subparsers.add_parser(
        "report",
        help="Build the complete planned-rate/goodput curve",
    )
    report.add_argument("manifest", type=Path)
    report.add_argument(
        "--csv-out",
        type=Path,
        default=Path("bluebee_scan_results/curve.csv"),
    )
    report.add_argument(
        "--json-out",
        type=Path,
        default=Path("bluebee_scan_results/report.json"),
    )
    report.set_defaults(handler=command_report)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "plan":
        if not 30 <= args.tx_duration_s <= 600:
            parser.error("--tx-duration-s must be in [30, 600]")
        if args.guard_s < 10:
            parser.error("--guard-s must be at least 10")
        if args.base_run_id is not None and not 0 <= args.base_run_id <= 0xFFFF:
            parser.error("--base-run-id must be in [0, 65535]")
    args.handler(args)


if __name__ == "__main__":
    main()
