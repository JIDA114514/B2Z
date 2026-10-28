#!/usr/bin/env python3
"""HackRF exadv receiver: fixed RF capture, optionally several in-band channels."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

import numpy as np

from decoder import ChannelDecoder, IQDCBlocker
from protocol import DiagnosticEventMatcher, EventMatcher, channel_frequency

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_tools.reporting import (add_output_arguments, output_prefix,
                                        validate_output_arguments, write_receiver_reports)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", default="39", help="RF BLE channels, comma separated; default 39")
    parser.add_argument("--whitening-channels", help="optional whitening channels, one per RF channel")
    parser.add_argument("--sample-rate", type=int, default=8000000, choices=[4000000, 8000000, 12000000, 16000000, 20000000])
    parser.add_argument("--center-hz", type=float, help="default: midpoint of selected RF channels")
    parser.add_argument("--iq-file", type=Path, help="offline input; omit to receive from HackRF")
    parser.add_argument("--format", choices=["ci8", "cf32"], default="ci8", help="offline IQ: signed int8 I/Q or complex64 little endian")
    parser.add_argument("--serial", help="HackRF serial number (recommended with two devices)")
    parser.add_argument("--lna", type=int, default=24, choices=range(0, 41, 8))
    parser.add_argument("--vga", type=int, default=20, choices=range(0, 63, 2))
    parser.add_argument("--amp", action="store_true", help="enable RX RF amplifier; default off")
    parser.add_argument("--duration", type=float, default=60, help="capture/sample duration in seconds; 0 until Ctrl-C/EOF")
    parser.add_argument("--block-samples", type=int, default=65536)
    parser.add_argument("--queue-blocks", type=int, default=64)
    parser.add_argument("--stall-timeout", type=float, default=10)
    parser.add_argument("--sync-threshold", type=float, default=.84)
    parser.add_argument("--dc-block-hz", type=float, default=1000,
                        help="continuous IQ high-pass cutoff before demodulation; default 1000 Hz, 0 disables")
    parser.add_argument("--timing-retry", action=argparse.BooleanOptionalAction, default=True,
                        help="bounded narrower symbol-window retry after hard CRC failure; default enabled")
    parser.add_argument("--channel-cutoff-hz", type=float, default=850000,
                        help="channel low-pass cutoff in Hz; default 850000")
    parser.add_argument("--pair-tolerance-us", type=float, default=20)
    parser.add_argument("--diagnostic-pairs", action=argparse.BooleanOptionalAction, default=True,
                        help="separate same-channel debug pairing counter; does not relax strict pairs")
    parser.add_argument("--diagnostic-pair-window-us", type=float, default=2000,
                        help="maximum absolute error from advertised offset for diagnostic pairs, default 2000us")
    parser.add_argument("--save-iq", action="store_true", help="save input bytes and metadata beside output")
    add_output_arguments(parser)
    parser.add_argument("--quiet", action="store_true", help="only periodic status and final summary")
    args = parser.parse_args(argv)
    validate_output_arguments(parser, args)
    try:
        args.channels = [int(value) for value in args.channels.split(",")]
        if not args.channels or len(set(args.channels)) != len(args.channels):
            raise ValueError("channels must be nonempty and distinct")
        freqs = [channel_frequency(channel) for channel in args.channels]
        args.whitening_channels = ([int(value) for value in args.whitening_channels.split(",")]
                                   if args.whitening_channels else args.channels[:])
        if len(args.whitening_channels) != len(args.channels):
            raise ValueError("need one whitening channel per RF channel")
        for channel in args.whitening_channels:
            channel_frequency(channel)
        if args.center_hz is None:
            args.center_hz = (min(freqs) + max(freqs)) / 2
        if not math.isfinite(args.center_hz) or not 1000000 <= args.center_hz <= 6000000000:
            raise ValueError("center-hz outside 1 MHz..6 GHz")
        if any(abs(freq - args.center_hz) + 1200000 >= args.sample_rate / 2 for freq in freqs):
            raise ValueError("RF channels do not fit capture bandwidth with 1.2 MHz edge margin; use a fixed secondary or closer channels")
        if not math.isfinite(args.duration) or args.duration < 0:
            raise ValueError("duration must be finite and nonnegative")
        if args.block_samples < 1024 or args.queue_blocks < 1:
            raise ValueError("block-samples >= 1024 and queue-blocks >= 1 required")
        if not math.isfinite(args.stall_timeout) or args.stall_timeout <= 0:
            raise ValueError("stall-timeout must be positive")
        if not .6 <= args.sync_threshold < 1:
            raise ValueError("sync-threshold must be in [0.6, 1)")
        if not math.isfinite(args.dc_block_hz) or not 0 <= args.dc_block_hz < args.sample_rate / 2:
            raise ValueError("dc-block-hz must be finite and in [0, Fs/2)")
        if not math.isfinite(args.channel_cutoff_hz) or not 400000 <= args.channel_cutoff_hz <= 950000:
            raise ValueError("channel-cutoff-hz must be in [400000, 950000]")
        if not math.isfinite(args.pair_tolerance_us) or args.pair_tolerance_us < 0:
            raise ValueError("pair-tolerance-us must be finite and nonnegative")
        if not math.isfinite(args.diagnostic_pair_window_us) or not 0 < args.diagnostic_pair_window_us <= 10000:
            raise ValueError("diagnostic-pair-window-us must be in (0, 10000]")
        if not args.iq_file and args.format != "ci8":
            raise ValueError("HackRF live capture uses ci8")
        if args.iq_file and not args.iq_file.is_file():
            raise ValueError("iq-file does not exist")
    except ValueError as exc:
        parser.error(str(exc))
    return args


class Capture:
    """Drain stdout independently; abort explicitly on application queue overflow."""
    def __init__(self, args, save_file=None, stderr_file=None):
        self.args = args
        self.save_file = save_file
        self.stderr_file = stderr_file
        self.queue = queue.Queue(maxsize=args.queue_blocks)
        self.done = threading.Event()
        self.stop = threading.Event()
        self.error = None
        self.proc = None
        self.command = None
        self.stats = Counter()
        self.stderr_tail = deque(maxlen=40)
        self.thread = None
        self.stderr_thread = None

    def start(self):
        if self.args.iq_file:
            self.stream = self.args.iq_file.open("rb")
        else:
            executable = shutil.which("hackrf_transfer")
            if not executable:
                raise RuntimeError("hackrf_transfer not found; install HackRF tools or use --iq-file")
            a = self.args
            self.command = [executable, "-r", "-", "-f", str(round(a.center_hz)),
                            "-s", str(a.sample_rate), "-l", str(a.lna), "-g", str(a.vga),
                            "-a", str(int(a.amp)), "-p", "0"]
            if a.serial:
                self.command += ["-d", a.serial]
            if a.duration:
                self.command += ["-n", str(max(1, int(a.duration * a.sample_rate)))]
            self.proc = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.stream = self.proc.stdout
            self.stderr_thread = threading.Thread(target=self._stderr, daemon=True)
            self.stderr_thread.start()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _stderr(self):
        for line in iter(self.proc.stderr.readline, b""):
            value = line.decode(errors="replace")
            self.stderr_tail.append(value.rstrip())
            if self.stderr_file:
                self.stderr_file.write(value)
                self.stderr_file.flush()

    def _read(self):
        width = 2 if self.args.format == "ci8" else 8
        remaining = int(self.args.duration * self.args.sample_rate) * width if self.args.duration else None
        try:
            while not self.stop.is_set() and (remaining is None or remaining > 0):
                size = self.args.block_samples * width
                if remaining is not None:
                    size = min(size, remaining)
                chunk = self.stream.read(size)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                self.stats["bytes_read"] += len(chunk)
                if self.save_file:
                    self.save_file.write(chunk)
                if self.proc:
                    try:
                        self.queue.put_nowait(chunk)
                    except queue.Full:
                        self.stats["queue_overflow"] += 1
                        self.error = "live decode queue overflow; capture incomplete, reduce CPU load or record/replay IQ"
                        break
                else:
                    # A file can be backpressured; do not label offline pacing as loss.
                    while not self.stop.is_set():
                        try:
                            self.queue.put(chunk, timeout=.1)
                            break
                        except queue.Full:
                            pass
                self.stats["queue_high_water"] = max(self.stats["queue_high_water"], self.queue.qsize())
        except Exception as exc:
            self.error = f"capture read failed: {exc}"
        finally:
            self.done.set()

    def close(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        if self.thread:
            self.thread.join(timeout=3)
        if self.stderr_thread:
            self.stderr_thread.join(timeout=3)
        if hasattr(self, "stream"):
            self.stream.close()
        if self.proc:
            self.proc.stderr.close()


def main(argv=None):
    args = parse_args(argv)
    prefix = output_prefix(args, "ble")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {name: Path(str(prefix) + suffix) for name, suffix in
             (("packets", ".packets.jsonl"), ("events", ".events.jsonl"),
              ("summary", ".summary.json"), ("text", ".summary.txt"), ("report", ".report.md"),
              ("stderr", ".hackrf.log"))}
    if args.save_iq:
        paths["iq"] = Path(str(prefix) + "." + args.format)
    for path in paths.values():
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")
    decoders = [ChannelDecoder(args.sample_rate, args.center_hz, channel, white, args.sync_threshold,
                               args.timing_retry, args.channel_cutoff_hz)
                for channel, white in zip(args.channels, args.whitening_channels)]
    matcher = EventMatcher(args.pair_tolerance_us)
    diagnostic_matcher = DiagnosticEventMatcher(args.diagnostic_pair_window_us)
    dc_blocker = IQDCBlocker(args.sample_rate, args.dc_block_hz)
    counts = Counter()
    processing = []
    pending_bytes = b""
    width = 2 if args.format == "ci8" else 8
    interrupted = False
    error = None
    started = time.monotonic()
    start_utc = datetime.now(timezone.utc).isoformat()
    save = paths["iq"].open("xb") if args.save_iq else None
    with paths["packets"].open("x") as packets_file, paths["events"].open("x") as events_file, paths["stderr"].open("x") as stderr_file:
        capture = Capture(args, save, stderr_file)

        def process(iq, final=False):
            before = time.monotonic()
            iq = dc_blocker.feed(iq)
            packets = []
            for decoder in decoders:
                packets.extend(decoder.feed(iq, final=final))
            for packet in sorted(packets, key=lambda value: value["sample_start"]):
                counts["packets"] += 1
                counts[packet["kind"]] += 1
                packet["packet_no"] = counts["packets"]
                packet["timeline"] = "one_continuous_iq_capture_nominal_sample_rate"
                aux = packet["extended"].get("aux_ptr")
                if aux and aux["phy"] != 0:
                    counts["aux_ptr_unsupported_phy"] += 1
                packets_file.write(json.dumps(packet, ensure_ascii=False) + "\n")
                for event in matcher.feed(packet):
                    events_file.write(json.dumps(event) + "\n")
                if args.diagnostic_pairs:
                    for event in diagnostic_matcher.feed(packet):
                        events_file.write(json.dumps(event) + "\n")
                if not args.quiet:
                    ext = packet["extended"]
                    print(f"#{packet['packet_no']} ch{packet['channel']} {packet['kind']} "
                          f"len={packet['pdu_length']} CRC=OK t={packet['sample_time_s']:.9f}s "
                          f"sample={packet['sample_start']:.3f} ref=ble_preamble "
                          f"CFO={packet['cfo_hz']:.0f}Hz ADI={ext.get('adi')} "
                          f"AuxPtr={ext.get('aux_ptr')} "
                          f"AdvData={ext['adv_data_hex']}", flush=True)
            packets_file.flush()
            events_file.flush()
            processing.append(time.monotonic() - before)
            # Bound timing memory for indefinite capture.
            if len(processing) > 10000:
                del processing[:5000]

        print(f"LE 1M exadv RX channels={args.channels} center={args.center_hz / 1e6:.3f}MHz "
              f"Fs={args.sample_rate / 1e6:g}Msps output={prefix}", flush=True)
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
                        raise RuntimeError("capture stalled: no IQ received within stall-timeout")
                    continue
                last_data = time.monotonic()
                raw = pending_bytes + chunk
                size = len(raw) // width * width
                pending_bytes = raw[size:]
                if args.format == "ci8":
                    values = np.frombuffer(raw[:size], dtype=np.int8).astype(np.float32).reshape(-1, 2)
                    iq = (values[:, 0] + 1j * values[:, 1]) / 128
                    counts["clipped_components"] += int(np.count_nonzero(np.abs(values) >= 127))
                else:
                    iq = np.frombuffer(raw[:size], dtype="<c8")
                if not np.all(np.isfinite(iq)):
                    raise RuntimeError("non-finite IQ in input")
                counts["samples_processed"] += len(iq)
                process(iq)
                if time.monotonic() - last_status >= 5:
                    last_status = time.monotonic()
                    print(f"status samples={counts['samples_processed']} packets={counts['packets']} "
                          f"pairs={matcher.matched} diagnostic_pairs={diagnostic_matcher.matched} "
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
            if pending_bytes:
                error = error or "truncated IQ sample at end of capture"
            process(np.empty(0, np.complex64), final=True)
    wall = time.monotonic() - started
    summary = {
        "schema": "exadv_rx_v3", "receiver_version": "2026-10-26-window-retry1", "start_utc": start_utc,
        "end_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error" if error else "interrupted" if interrupted else "complete",
        "error": error, "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "capture_command": capture.command, "capture_returncode": capture.proc.returncode if capture.proc else None,
        "capture_stats": dict(capture.stats), "counts": dict(counts),
        "channels": {str(d.channel): dict(d.stats) for d in decoders},
        "matched_events": matcher.matched, "expired_primary": matcher.expired,
        "diagnostic_pairs": diagnostic_matcher.matched,
        "diagnostic_expired_primary": diagnostic_matcher.expired,
        "diagnostic_pending_overflow": diagnostic_matcher.overflow,
        "pending_primary": len(matcher.pending),
        "wall_duration_s": wall, "processed_sample_duration_s": counts["samples_processed"] / args.sample_rate,
        "processing_ms_recent": {"samples": len(processing), "mean": float(np.mean(processing) * 1000) if processing else None,
                                 "p99": float(np.percentile(processing, 99) * 1000) if processing else None,
                                 "max": max(processing) * 1000 if processing else None},
        "stderr_tail": list(capture.stderr_tail), "files": {key: str(value) for key, value in paths.items()},
        "limitations": ["LE 1M only; fixed RF capture, no host-timed frequency hopping",
                        "DC blocker/filter and demodulation timing require calibration before synchronization claims",
                        "sample timestamps are relative to capture, not hardware/UTC timestamps",
                        "HackRF/USB sample losses may be unobservable in raw IQ; no guaranteed gap-free timeline",
                        "CRC-failure counts refer to sync candidates, not uniquely identified transmitted packets",
                        "no PRR without independently supplied TX counts and matched observation window"],
    }
    text_report = write_receiver_reports(summary, paths, args.experiment_dir)
    print(text_report, end="")
    if error and capture.stderr_tail:
        print("\n".join(capture.stderr_tail), file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
