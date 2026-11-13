#!/usr/bin/env python3
"""Live IEEE 802.15.4 PHY receiver with B2 43 control-record analysis."""
from __future__ import annotations

from collections import Counter
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_match.analyze import TASK_FIELDS, read_board
from control_match.protocol import control_record
from control_match.control_engine import EngineConfig
from control_match.live_control import ControlSession
from experiment_tools.reporting import output_prefix, write_receiver_reports
from zigbee_rx.arguments import parse_args
from zigbee_rx.dsp import IQDCBlocker
from zigbee_rx.hackrf_capture import Capture
from zigbee_rx.zigbee_decoder import ZigBeeDecoder
from zigbee_rx.zigbee_protocol import channel_frequency, ratio


class ControlTracker:
    """Count only this receiver's independently decoded, FCS-correct payloads."""

    def __init__(self, run_id: int, command_id: int | None, expected_packets: int | None):
        self.run_id = run_id
        self.command_id = command_id
        self.expected_packets = expected_packets
        self.counts = Counter()
        self.invalid_reasons = Counter()
        self.seen: dict[int, dict] = {}
        self.task_keys: dict[int, tuple] = {}
        self.last_slot = -1

    def observe(self, payload: bytes) -> tuple[dict | None, str, str | None]:
        if payload[:2] != b"\xb2\x43" and payload[:1] != b"\xc1":
            self.counts["non_control"] += 1
            return None, "non_control", None
        self.counts["control_candidates"] += 1
        try:
            record = control_record(payload, "zigbee")
        except ValueError as exc:
            reason = str(exc)
            self.counts["invalid_control"] += 1
            self.invalid_reasons[reason] += 1
            return None, "invalid_control", reason
        self.counts["valid_control_records"] += 1
        if record["run_id"] != self.run_id or (self.command_id is not None and
                                                record["command_id"] != self.command_id):
            self.counts["foreign_control"] += 1
            return record, "foreign_control", None
        self.counts["matching_control_records"] += 1
        slot = record["slot_index"]
        if self.expected_packets is not None and slot >= self.expected_packets:
            self.counts["out_of_range_control"] += 1
            return record, "out_of_range_control", None
        task_key = tuple(record[key] for key in
                         (*TASK_FIELDS, "target_id", "opcode", "arg"))
        prior_task = self.task_keys.get(record["command_id"])
        if prior_task is not None and task_key != prior_task:
            self.counts["conflicting_task_fields"] += 1
            return record, "conflicting_task_fields", None
        if slot in self.seen:
            if self.seen[slot] == record:
                self.counts["duplicate"] += 1
                return record, "duplicate", None
            self.counts["conflicting_slot"] += 1
            return record, "conflicting_slot", None
        if prior_task is None:
            self.task_keys[record["command_id"]] = task_key
        if slot < self.last_slot:
            self.counts["out_of_order"] += 1
        self.last_slot = slot
        self.seen[slot] = record
        self.counts["unique"] += 1
        return record, "unique", None

    def longest_loss_burst(self) -> int:
        if self.expected_packets is not None:
            slots = range(self.expected_packets)
        elif self.seen:
            slots = range(min(self.seen), max(self.seen) + 1)
        else:
            return 0
        longest = current = 0
        for slot in slots:
            current = 0 if slot in self.seen else current + 1
            longest = max(longest, current)
        return longest


def main(argv=None) -> int:
    args = parse_args(argv, control_mode=True)
    board = read_board(args.board_log, args.run_id, args.command_id) if args.board_log else None
    if board and args.expected_packets is not None and args.expected_packets != board["scheduled"]:
        raise ValueError("--expected-packets differs from board scheduled count")
    planned = args.expected_packets if args.expected_packets is not None else (board["scheduled"] if board else None)
    tracker = ControlTracker(args.run_id, args.command_id, planned)
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
    control_config = None
    if args.control_target_id:
        control_config = EngineConfig(side="zigbee", run_id=args.run_id, sample_rate=args.sample_rate,
                                      target_ids=frozenset(args.control_target_id),
                                      sender_id=args.control_sender_id,
                                      accept_broadcast=args.control_accept_broadcast,
                                      external_reference_bound_ms=args.control_assumed_reference_bound_ms)
        files.update(ControlSession.artifact_paths(prefix))
    if any(path.exists() for path in files.values()):
        raise FileExistsError(f"output prefix already exists: {prefix}")
    control = ControlSession(prefix, control_config, offline=bool(args.iq_file)) if control_config else None
    counts = Counter()
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
                record, disposition, reason = tracker.observe(payload)
                packet.update(packet_no=counts["fcs_valid_packets"], channel=args.channel,
                              frequency_hz=channel_frequency(args.channel),
                              control_record=record, control_error=reason,
                              run_id=record["run_id"] if record else None,
                              command_id=record["command_id"] if record else None,
                              slot_index=record["slot_index"] if record else None,
                              disposition=disposition,
                              available_sample=counts["samples_processed"],
                              timeline="independent_continuous_iq_nominal_rate")
                output.write(json.dumps(packet, ensure_ascii=False) + "\n")
                if control:
                    control.observe_packet(packet)
                if not args.quiet and disposition != "non_control":
                    detail = (f"run={record['run_id']} cmd={record['command_id']} "
                              f"slot={record['slot_index']} ref={record['ref_tick_ms']}ms "
                              f"target={record['target_id']} opcode={record['opcode']} "
                              f"arg={record['arg']}" if record else f"reason={reason}")
                    print(f"#{packet['packet_no']} FCS=OK {disposition} {detail} "
                          f"sample={packet['sample_start']:.3f} t={packet['sample_time_s']:.9f}s",
                          flush=True)
            if control:
                control.advance(counts["samples_processed"])
            output.flush()
            processing.append(time.monotonic() - before)
            if len(processing) > 10000:
                del processing[:5000]

        print(f"B2Z control RX ch{args.channel} freq={channel_frequency(args.channel)/1e6:g}MHz "
              f"Fs={args.sample_rate/1e6:g}Msps run={args.run_id} cmd={args.command_id} "
              f"output={prefix}", flush=True)
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
                          f"control_unique={tracker.counts['unique']} duplicate={tracker.counts['duplicate']} "
                          f"invalid={tracker.counts['invalid_control']} queue={capture.queue.qsize()}",
                          flush=True)
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
    counts.update(tracker.counts)
    ratio_result = {"numerator": tracker.counts["unique"], "denominator": None,
                    "value": None, "reason": "matching final CONTROL_STATS and full-run coverage required"}
    if board and args.full_run_covered and not error and not interrupted:
        completed = board["tx_completed"]
        if completed >= tracker.counts["unique"] and board["scheduled"] >= completed:
            ratio_result = ratio(tracker.counts["unique"], completed)
    here = Path(__file__).resolve().parent
    sources = [here / name for name in ("control_receive.py", "arguments.py", "zigbee_decoder.py",
                                        "zigbee_protocol.py", "dsp.py", "hackrf_capture.py")]
    sources += [here.parent / "control_match" / name for name in ("protocol.py", "analyze.py")]
    sources += [here.parent / "experiment_tools" / name for name in ("receiver_defaults.py", "reporting.py")]
    if control:
        sources += [here.parent / "control_match" / name for name in
                    ("control_engine.py", "live_control.py", "packet_adapter.py")]
    receiver_status = "error" if error else "interrupted" if interrupted else "complete"
    control_result = control.finish(receiver_status) if control else None
    result = {
        "schema": "zigbee_control_rx_v1", "receiver_version": "control-v1-live1",
        "status": receiver_status, "error": error,
        "start_utc": start_utc, "end_utc": datetime.now(timezone.utc).isoformat(),
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "capture_command": capture.command, "capture_returncode": capture.proc.returncode if capture.proc else None,
        "capture_stats": dict(capture.stats), "stderr_tail": list(capture.stderr_tail),
        "counts": dict(counts), "decoder": dict(decoder.stats), "run_id": args.run_id,
        "control_engine": ({"event_counts": control_result["event_counts"],
                            "tasks": control_result["tasks"],
                            "report": str(files["control_report"])} if control_result else None),
        "command_id": args.command_id,
        "receiver": {"unique": tracker.counts["unique"], "duplicate": tracker.counts["duplicate"],
                     "out_of_order": tracker.counts["out_of_order"],
                     "longest_loss_burst": tracker.longest_loss_burst(),
                     "loss_scope": "explicit planned range" if planned is not None else "min..max valid received slot",
                     "invalid_reasons": dict(tracker.invalid_reasons)},
        "planned_slots": planned, "board": board,
        "ratios": {"control_decode_per_dma": ratio_result},
        "observation": {"sample_duration_s": counts["samples_processed"] / args.sample_rate,
                        "wall_duration_s": time.monotonic() - start,
                        "scope": "all processed capture samples, including experiment margins"},
        "processing_ms_recent": {"samples": len(processing),
                                 "mean": float(np.mean(processing)*1000) if processing else None,
                                 "p99": float(np.percentile(processing, 99)*1000) if processing else None,
                                 "max": max(processing)*1000 if processing else None},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
        "sources_sha256": {str(path.relative_to(here.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sources},
        "files": {key: str(path) for key, path in files.items()},
        "limitations": ["independent SDR PHY and application decode; no physical actuator execution",
                        "FCS-failure candidate counts are not uniquely identified transmitted packets",
                        "sample times are relative to this HackRF IQ and not UTC or another receiver clock",
                        "DMA completion is a proxy for TX; no calibrated RF-start timestamp"],
    }
    text = write_receiver_reports(result, files, args.experiment_dir)
    print(text, end="")
    if error and capture.stderr_tail:
        print("\n".join(capture.stderr_tail), file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
