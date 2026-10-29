"""Command-line options and validation, separate from the receive loop."""
from __future__ import annotations
import argparse
import math
from pathlib import Path

from experiment_tools.receiver_defaults import apply_defaults, resolve_input_defaults
from experiment_tools.reporting import add_output_arguments, validate_output_arguments
from protocol import channel_frequency


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--channels", help="RF BLE channels, comma separated; default 39")
    parser.add_argument("--whitening-channels", help="optional whitening channels, one per RF channel")
    parser.add_argument("--sample-rate", type=int, choices=[4000000, 8000000, 12000000, 16000000, 20000000], help="input sample rate in Hz")
    parser.add_argument("--center-hz", type=float, help="default: midpoint of selected RF channels")
    parser.add_argument("--iq-file", type=Path, help="offline input; omit to receive from HackRF")
    parser.add_argument("--format", choices=["ci8", "cf32"], help="offline IQ: signed int8 I/Q or complex64 little endian")
    parser.add_argument("--serial", help="live HackRF device; defaults to the BLE bench SDR")
    parser.add_argument("--lna", type=int, choices=range(0, 41, 8), help="LNA gain in dB")
    parser.add_argument("--vga", type=int, choices=range(0, 63, 2), help="VGA gain in dB")
    parser.add_argument("--amp", action="store_true", help="enable RX RF amplifier; default off")
    parser.add_argument("--duration", type=float, help="seconds; auto: 40 live, EOF offline; 0 until Ctrl-C/EOF")
    parser.add_argument("--block-samples", type=int)
    parser.add_argument("--queue-blocks", type=int)
    parser.add_argument("--stall-timeout", type=float)
    parser.add_argument("--sync-threshold", type=float)
    parser.add_argument("--dc-block-hz", type=float,
                        help="continuous IQ high-pass cutoff before demodulation; default 1000 Hz, 0 disables")
    parser.add_argument("--timing-retry", action=argparse.BooleanOptionalAction,
                        help="bounded narrower symbol-window retry after hard CRC failure; default enabled")
    parser.add_argument("--channel-cutoff-hz", type=float,
                        help="channel low-pass cutoff in Hz; default 850000")
    parser.add_argument("--pair-tolerance-us", type=float)
    parser.add_argument("--diagnostic-pairs", action=argparse.BooleanOptionalAction,
                        help="separate same-channel debug pairing counter; does not relax strict pairs")
    parser.add_argument("--diagnostic-pair-window-us", type=float,
                        help="maximum absolute error from advertised offset for diagnostic pairs, default 2000us")
    parser.add_argument("--save-iq", action=argparse.BooleanOptionalAction, help="auto: save live IQ, do not copy offline input")
    add_output_arguments(parser)
    parser.add_argument("--quiet", action=argparse.BooleanOptionalAction, help="only periodic status and final summary")
    parser.add_argument("--run-id", type=int, help="experiment Run ID for archiving only; BLE payload is not filtered")
    apply_defaults(parser, "ble")
    args = parser.parse_args(argv)
    resolve_input_defaults(args)
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

