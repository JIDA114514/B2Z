#!/usr/bin/env python3
"""Independent HackRF IEEE 802.15.4 / BlueBee PHY receiver."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import queue
import signal
import sys
import time
import numpy as np
import scipy

from dsp import IQDCBlocker
from hackrf_capture import Capture
from zigbee_decoder import ZigBeeDecoder
from zigbee_protocol import (SequenceTracker, channel_frequency, parse_board_stats_text,
                             parse_test_payload, ratio)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_tools.reporting import output_prefix, write_receiver_reports
from zigbee_rx.arguments import parse_args




def main(argv=None):
    args = parse_args(argv)
    board = parse_board_stats_text(args.board_log.read_text(), args.run_id) if args.board_log else None
    if args.board_log and board is None:
        raise ValueError("board-log contains no matching final PERF_STATS")
    if board and (not isinstance(board.get("run_id"), int) or not 0 <= board["run_id"] <= 65535):
        raise ValueError("board final PERF_STATS requires a valid run_id")
    run_id = args.run_id if args.run_id is not None else board.get("run_id") if board else None
    tracker = SequenceTracker(run_id, args.payload_len)
    decoder = ZigBeeDecoder(args.sample_rate, args.center_hz, channel_frequency(args.channel),
                            args.demod, args.symbol_order, args.cutoff_hz, args.cfo_hz,
                            args.soft_retry, args.preamble_max_distance)
    dc = IQDCBlocker(args.sample_rate, args.dc_block_hz)
    prefix = output_prefix(args, "zigbee")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    files = {key: Path(str(prefix) + suffix) for key, suffix in
             (("packets", ".packets.jsonl"), ("summary", ".summary.json"),
              ("text", ".summary.txt"), ("report", ".report.md"), ("hackrf", ".hackrf.log"))}
    if args.save_iq:
        files["iq"] = Path(str(prefix) + "." + args.format)
    if any(path.exists() for path in files.values()):
        raise FileExistsError(f"output prefix already exists: {prefix}")
    counts = Counter()
    unique_sizes = {}
    processing = []
    pending = b""
    width = 2 if args.format == "ci8" else 8
    start = time.monotonic()
    start_utc = datetime.now(timezone.utc).isoformat()
    error = None
    interrupted = False
    save = files["iq"].open("xb") if args.save_iq else None
    with files["packets"].open("x") as output, files["hackrf"].open("x") as logs:
        capture = Capture(args, save, logs)

        def process(iq, final=False):
            before = time.monotonic()
            for packet in decoder.feed(dc.feed(iq), final):
                counts["fcs_valid_packets"] += 1
                payload = bytes.fromhex(packet["payload_hex"])
                parsed = parse_test_payload(payload)
                if parsed.valid:
                    parsed, disposition = tracker.observe(payload)
                    if parsed.valid and disposition != "duplicate":
                        unique_sizes[parsed.sequence] = len(payload)
                elif payload.startswith(bytes.fromhex("b25a")):
                    tracker.payload_failure += 1
                    disposition = "invalid_test"
                else:
                    disposition = "non_test"
                counts[disposition] += 1
                packet.update(packet_no=counts["fcs_valid_packets"], channel=args.channel,
                              frequency_hz=channel_frequency(args.channel), test_payload=asdict(parsed),
                              run_id=parsed.run_id, sequence=parsed.sequence, disposition=disposition,
                              timeline="independent_continuous_iq_nominal_rate")
                output.write(json.dumps(packet, ensure_ascii=False) + "\n")
                if not args.quiet:
                    print(f"#{packet['packet_no']} FCS=OK {packet['phy_observation']} "
                          f"{packet['decode_method']} len={len(payload)} run={parsed.run_id} "
                          f"seq={parsed.sequence} {disposition} t={packet['sample_time_s']:.9f}s "
                          f"sample={packet['sample_start']:.3f} ref=zigbee_preamble "
                          f"payload={payload.hex()}", flush=True)
            output.flush()
            processing.append(time.monotonic() - before)
            if len(processing) > 10000:
                del processing[:5000]

        print(f"ZigBee RX ch{args.channel} freq={channel_frequency(args.channel)/1e6:g}MHz "
              f"Fs={args.sample_rate/1e6:g}Msps device={args.serial or 'offline'} "
              f"demod={args.demod} output={prefix}", flush=True)
        last_data = last_status = time.monotonic()
        try:
            capture.start()
            while True:
                try:
                    chunk = capture.queue.get(timeout=.2)
                except queue.Empty:
                    if capture.done.is_set():
                        break
                    if time.monotonic() - last_data > args.stall_timeout:
                        raise RuntimeError("capture stalled")
                    continue
                last_data = time.monotonic()
                raw = pending + chunk
                n = len(raw) // width * width
                pending = raw[n:]
                if args.format == "ci8":
                    values = np.frombuffer(raw[:n], np.int8).astype(np.float32).reshape(-1, 2)
                    iq = (values[:, 0] + 1j * values[:, 1]) / 128
                    counts["clipped_components"] += int(np.count_nonzero(np.abs(values) >= 127))
                else:
                    iq = np.frombuffer(raw[:n], "<c8")
                if not np.all(np.isfinite(iq)):
                    raise RuntimeError("non-finite IQ")
                counts["samples_processed"] += len(iq)
                process(iq)
                if time.monotonic() - last_status >= 5:
                    last_status = time.monotonic()
                    print(f"status samples={counts['samples_processed']} fcs_ok={counts['fcs_valid_packets']} "
                          f"run={tracker.locked_run_id} unique={tracker.unique} duplicate={tracker.duplicate} "
                          f"queue={capture.queue.qsize()}", flush=True)
            if capture.error:
                raise RuntimeError(capture.error)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:
            error = str(exc)
        finally:
            capture.close()
            if save:
                save.close()
            if capture.proc and capture.proc.returncode not in (0, -signal.SIGINT) and not interrupted:
                error = error or f"hackrf_transfer exited {capture.proc.returncode}"
            if pending:
                error = error or "truncated IQ sample"
            process(np.empty(0, np.complex64), final=True)
    observation = counts["samples_processed"] / args.sample_rate
    planned = tracker.planned_range(args.expected_packets)
    ratios = {name: dict(ratio(tracker.unique if name != "scheduling_completion" else 0, None),
                         reason="matching board final counts and full-run coverage required")
              for name in ("wireless_prr", "end_to_end_receive", "scheduling_completion")}
    if board and args.full_run_covered and not error and not interrupted:
        scheduled, completed = board.get("scheduled"), board.get("tx_completed")
        in_range = tracker.planned_range(scheduled) if scheduled is not None else None
        if (in_range is not None and not in_range["out_of_range_count"] and completed is not None
                and completed >= tracker.unique and scheduled >= completed >= 0):
            ratios = {"wireless_prr": ratio(tracker.unique, completed),
                      "end_to_end_receive": ratio(tracker.unique, scheduled),
                      "scheduling_completion": ratio(completed, scheduled)}
    def rate(byte_count):
        return {"byte_s": byte_count / observation if observation else None,
                "bit_s": byte_count * 8 / observation if observation else None}
    here = Path(__file__).resolve().parent
    source_paths = [here / name for name in ("receive.py", "arguments.py", "zigbee_decoder.py", "zigbee_protocol.py", "dsp.py", "hackrf_capture.py")]
    source_paths.append(here.parent / "perf_test" / "bluebee_perf_protocol.py")
    source_paths += [here.parent / "experiment_tools" / name for name in ("receiver_defaults.py", "reporting.py")]
    result = {"schema": "zigbee_rx_v1", "receiver_version": "2026-10-26-independent1",
              "status": "error" if error else "interrupted" if interrupted else "complete", "error": error,
              "start_utc": start_utc, "end_utc": datetime.now(timezone.utc).isoformat(),
              "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
              "capture_command": capture.command, "capture_returncode": capture.proc.returncode if capture.proc else None,
              "capture_stats": dict(capture.stats), "stderr_tail": list(capture.stderr_tail),
              "counts": dict(counts), "decoder": dict(decoder.stats), "run_id": tracker.locked_run_id,
              "receiver": {"unique": tracker.unique, "duplicate": tracker.duplicate,
                           "out_of_order": tracker.out_of_order, "payload_failure": tracker.payload_failure,
                           "run_id_mismatch": tracker.run_id_mismatch,
                           "longest_loss_burst": tracker.longest_loss_burst(args.expected_packets),
                           "loss_scope": "explicit planned range" if planned is not None else "min..max valid received Sequence"},
              "planned_sequences": planned, "board": board, "ratios": ratios,
              "observation": {"sample_duration_s": observation, "wall_duration_s": time.monotonic() - start,
                              "scope": "all processed capture samples, including pre/post experiment silence"},
              "throughput": {"gross": rate(sum(unique_sizes.values())),
                             "application": rate(sum(max(0, size - 10) for size in unique_sizes.values())),
                             "scope": "unique valid test payloads of selected Run ID only"},
              "processing_ms_recent": {"samples": len(processing), "mean": float(np.mean(processing)*1000) if processing else None,
                                       "p99": float(np.percentile(processing, 99)*1000) if processing else None,
                                       "max": max(processing)*1000 if processing else None},
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "sources_sha256": {str(path.relative_to(here.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
              "files": {key: str(path) for key, path in files.items()},
              "limitations": ["independent SDR PHY decoder, not commercial ZigBee stack compatibility",
                              "FCS failures are candidate counts, not unique physical packet losses",
                              "relative nominal sample timing; USB gaps and sample clock errors not ruled out",
                              "two HackRF captures have independent time origins; do not subtract their timestamps as synchronization error",
                              "no command execution or common control command schema implemented"]}
    text = write_receiver_reports(result, files, args.experiment_dir)
    print(text, end="")
    if error and capture.stderr_tail:
        print("\n".join(capture.stderr_tail), file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
