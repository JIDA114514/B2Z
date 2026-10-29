"""Command-line options and validation, separate from the receive loop."""
from __future__ import annotations
import argparse
import math
from pathlib import Path

from experiment_tools.receiver_defaults import apply_defaults, resolve_input_defaults
from experiment_tools.reporting import add_output_arguments, validate_output_arguments
from zigbee_protocol import channel_frequency
from zigbee_decoder import ZigBeeDecoder


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--channel", type=int, help="802.15.4 channel 11..26, default26=2480MHz")
    p.add_argument("--serial", help="live HackRF device; defaults to the ZigBee bench SDR")
    p.add_argument("--sample-rate", type=int,
                   choices=[4000000, 8000000, 12000000, 16000000, 20000000], help="input sample rate in Hz")
    p.add_argument("--center-hz", type=float, help="actual capture center, default channel frequency")
    p.add_argument("--iq-file", type=Path, help="offline raw IQ; omit to use HackRF")
    p.add_argument("--format", choices=["ci8", "cf32"])
    p.add_argument("--lna", type=int, choices=range(0, 41, 8), help="LNA gain in dB")
    p.add_argument("--vga", type=int, choices=range(0, 63, 2), help="VGA gain in dB")
    p.add_argument("--amp", action="store_true")
    p.add_argument("--duration", type=float, help="seconds; auto: 40 live, EOF offline; 0 until Ctrl-C/EOF")
    p.add_argument("--block-samples", type=int)
    p.add_argument("--queue-blocks", type=int)
    p.add_argument("--stall-timeout", type=float)
    p.add_argument("--dc-block-hz", type=float)
    p.add_argument("--cutoff-hz", type=float, help="project BlueBee channel low-pass cutoff in Hz")
    p.add_argument("--cfo-hz", type=float, help="digital CFO correction, not a timestamp correction")
    p.add_argument("--demod", choices=["auto", "phase", "oqpsk"], help="PHY observation method")
    p.add_argument("--symbol-order", choices=["auto", "project", "ieee"], help="symbol representation")
    p.add_argument("--soft-retry", action=argparse.BooleanOptionalAction)
    p.add_argument("--preamble-max-distance", type=int, help="max errors over 8 preamble symbols")
    p.add_argument("--run-id", type=int, help="test payload Run ID filter, after PHY decoding only")
    p.add_argument("--payload-len", type=int, help="test payload length filter, after FCS only")
    p.add_argument("--expected-packets", type=int, help="explicit planned range 0..N-1, never inferred from RX duration")
    p.add_argument("--board-log", type=Path, help="serial text containing matching final PERF_STATS")
    p.add_argument("--full-run-covered", action="store_true", help="explicit confirmation RX covers the entire board run")
    p.add_argument("--save-iq", action=argparse.BooleanOptionalAction, help="auto: save live IQ, do not copy offline input")
    add_output_arguments(p)
    p.add_argument("--quiet", action=argparse.BooleanOptionalAction, help="only periodic status and final summary; --no-quiet prints packets")
    apply_defaults(p, "zigbee")
    a = p.parse_args(argv)
    resolve_input_defaults(a)
    validate_output_arguments(p, a)
    try:
        frequency = channel_frequency(a.channel)
        if a.center_hz is None:
            a.center_hz = frequency
        if not math.isfinite(a.center_hz) or not 1000000 <= a.center_hz <= 6000000000:
            raise ValueError("invalid center-hz")
        for name in ["duration", "stall_timeout", "dc_block_hz", "cutoff_hz", "cfo_hz"]:
            if not math.isfinite(getattr(a, name)):
                raise ValueError(f"{name} must be finite")
        if a.duration < 0 or a.stall_timeout <= 0 or not 0 <= a.dc_block_hz < a.sample_rate / 2:
            raise ValueError("invalid duration, stall timeout or DC cutoff")
        if a.block_samples < 1024 or a.queue_blocks < 1:
            raise ValueError("block-samples >=1024 and queue-blocks >=1 required")
        if not 0 <= a.preamble_max_distance <= 88:
            raise ValueError("preamble-max-distance must be in 0..88")
        if a.payload_len is not None and not 10 <= a.payload_len <= 46:
            raise ValueError("test payload-len must be 10..46; general PHY frames may be larger")
        if a.expected_packets is not None and a.expected_packets < 0:
            raise ValueError("expected-packets must be nonnegative")
        if a.iq_file:
            if not a.iq_file.is_file():
                raise ValueError("iq-file not found")
        elif not a.serial:
            raise ValueError("live capture requires --serial; use hackrf_info to select the second HackRF")
        elif a.format != "ci8":
            raise ValueError("live HackRF input is ci8")
        if a.board_log and not a.board_log.is_file():
            raise ValueError("board-log not found")
        # Validate all DSP settings before opening files or starting USB capture.
        ZigBeeDecoder(a.sample_rate, a.center_hz, frequency, a.demod, a.symbol_order,
                      a.cutoff_hz, a.cfo_hz, a.soft_retry, a.preamble_max_distance)
    except ValueError as exc:
        p.error(str(exc))
    return a

