#!/usr/bin/env python3
# coding=utf-8
"""Standard ZigBee OQPSK receiver with BlueBee Phase-1 PRR accounting."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np
import zmq

STD_ZIGBEE_DIR = Path(__file__).resolve().parents[1] / "ctc_sim" / "std_zigbee"
if str(STD_ZIGBEE_DIR) not in sys.path:
    sys.path.insert(0, str(STD_ZIGBEE_DIR))

from bluebee_perf_protocol import (
    MAX_PAYLOAD_LEN,
    MIN_PAYLOAD_LEN,
    SequenceTracker,
    parse_board_stats_text,
    ratio,
)
from zigbee_mod import CHIP_MAP, PREAMBLE_BYTES, SFD, crc16_ccitt


MIN_FRAME_LEN = PREAMBLE_BYTES + 1 + 1 + MIN_PAYLOAD_LEN + 2
MAX_FRAME_LEN = PREAMBLE_BYTES + 1 + 1 + MAX_PAYLOAD_LEN + 2
PREAMBLE_SYMBOLS = PREAMBLE_BYTES * 2
MIN_FRAME_CHIPS = MIN_FRAME_LEN * 2 * 32
MAX_CHIPS = 24000
STATS_PERIOD = 2.0
DIAG_SCAN_CHIPS = 4096
PHASE_MAX_AVG_SYMBOL_DISTANCE = 4
PHASE_FAST_PREFIX_SYMBOLS = 2
PHASE_PREFIX_MAX_DISTANCE = (
    PHASE_FAST_PREFIX_SYMBOLS * PHASE_MAX_AVG_SYMBOL_DISTANCE
)
STANDARD_ENDPOINT = "tcp://127.0.0.1:55556"
PHASE_ENDPOINTS = {
    offset: f"tcp://127.0.0.1:{55557 + offset}" for offset in range(5)
}
POPCOUNT8 = np.asarray([value.bit_count() for value in range(256)], dtype=np.uint8)


# These are the 16 BLE GFSK bit patterns used by the board-side optimized
# BlueBee generator.  Each bit appears as a pair of equal phase chips at the
# ZigBee chip rate.  Keep the phase decoder independent from the waveform
# generator so the performance receiver remains lightweight.
BLUEBEE_OPTIMIZED_GFSK = (
    0x419F, 0x0E77, 0x999E, 0x667A,
    0x9DC3, 0x770E, 0xDC39, 0x70E7,
    0xBCF5, 0xB3D7, 0xCD5F, 0x357F,
    0xD5FC, 0x57F3, 0x5BCF, 0x6F3D,
)


def bluebee_chips_from_gfsk(word):
    return "".join("11" if (word >> bit) & 1 else "00" for bit in range(16))


BLUEBEE_OPTIMIZED_MAP = [
    bluebee_chips_from_gfsk(word) for word in BLUEBEE_OPTIMIZED_GFSK
]
BLUEBEE_LEGACY_MAP = [
    "".join(
        pair if pair in ("00", "11") else "00"
        for pair in (chips[index : index + 2] for index in range(0, 32, 2))
    )
    for chips in CHIP_MAP
]


class ZMQSubscriber:
    def __init__(self, addr="tcp://127.0.0.1:55556", hwm=2000):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.RCVHWM, hwm)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
        self.socket.connect(addr)

    def read_available(self, max_messages=500, poll_timeout_ms=10):
        messages = []
        if self.socket.poll(poll_timeout_ms) == 0:
            return messages
        while len(messages) < max_messages:
            try:
                messages.append(self.socket.recv(zmq.NOBLOCK))
            except zmq.Again:
                break
        return messages

    def close(self):
        self.socket.close()
        self.context.term()


def unpack_bytes_to_chips(data):
    return "".join(
        "1" if (byte >> bit) & 1 else "0"
        for byte in data
        for bit in range(8)
    )


def chips_to_symbols(chips, chip_map=CHIP_MAP):
    usable = (len(chips) // 32) * 32
    if usable == 0:
        return []

    chip_values = (
        np.frombuffer(chips[:usable].encode("ascii"), dtype=np.uint8) - ord("0")
    ).reshape(-1, 32)
    packed = np.packbits(chip_values, axis=1, bitorder="big")
    chunks = (
        (packed[:, 0].astype(np.uint32) << 24)
        | (packed[:, 1].astype(np.uint32) << 16)
        | (packed[:, 2].astype(np.uint32) << 8)
        | packed[:, 3].astype(np.uint32)
    )
    references = np.asarray(
        [int(reference, 2) for reference in chip_map], dtype=np.uint32
    )
    differences = np.bitwise_xor(chunks[:, None], references[None, :])
    byte_differences = differences.view(np.uint8).reshape(
        len(chunks), len(references), 4
    )
    distances = POPCOUNT8[byte_differences].sum(axis=2)
    best_symbols = np.argmin(distances, axis=1)
    best_distances = distances[np.arange(len(chunks)), best_symbols]
    return list(zip(best_symbols.tolist(), best_distances.tolist()))


def symbols_to_bits(symbols):
    return "".join(f"{symbol:04b}" for symbol, _ in symbols)


def bits_to_bytes_lsb(bit_string):
    data = []
    usable = len(bit_string) - len(bit_string) % 8
    for index in range(0, usable, 8):
        value = 0
        for bit, character in enumerate(bit_string[index : index + 8]):
            if character == "1":
                value |= 1 << bit
        data.append(value)
    return data


def chip_stats(chips):
    if not chips:
        return 0.0, 0.0
    ones = chips.count("1") / len(chips)
    transitions = 0.0
    if len(chips) > 1:
        transitions = sum(a != b for a, b in zip(chips, chips[1:])) / (
            len(chips) - 1
        )
    return ones, transitions


def find_preamble(data, search_start=0):
    preamble = [0x00] * PREAMBLE_BYTES
    for index in range(search_start, len(data) - (PREAMBLE_BYTES + 2) + 1):
        if data[index : index + PREAMBLE_BYTES] != preamble:
            continue
        if data[index + PREAMBLE_BYTES] != SFD:
            continue
        phr_len = data[index + PREAMBLE_BYTES + 1]
        frame_len = PREAMBLE_BYTES + 2 + phr_len
        if not MIN_FRAME_LEN <= frame_len <= MAX_FRAME_LEN:
            continue
        if index + frame_len <= len(data):
            return data[index : index + frame_len], index
    return None, -1


def find_phase_preamble(
    data, expected_payload_len, search_start=0, max_symbol_errors=1
):
    """Find a diagnostic frame with limited preamble/SFD symbol errors.

    The payload length is supplied by the performance command, so PHR remains
    exact and determines a fixed frame boundary.  Only the ten symbols in the
    four-byte preamble and SFD may differ; payload acceptance still requires a
    valid FCS later.  The standard receiver continues to use find_preamble().
    """
    phr_len = expected_payload_len + 2
    frame_len = PREAMBLE_BYTES + 2 + phr_len
    prefix = [0x00] * PREAMBLE_BYTES + [SFD]

    for index in range(search_start, len(data) - frame_len + 1):
        if data[index + PREAMBLE_BYTES + 1] != phr_len:
            continue
        symbol_errors = 0
        for actual, expected in zip(
            data[index : index + PREAMBLE_BYTES + 1], prefix
        ):
            difference = actual ^ expected
            symbol_errors += int((difference & 0x0F) != 0)
            symbol_errors += int((difference & 0xF0) != 0)
            if symbol_errors > max_symbol_errors:
                break
        if symbol_errors <= max_symbol_errors:
            return data[index : index + frame_len], index, symbol_errors
    return None, -1, 0


def invert_chips(chips):
    return chips.translate(str.maketrans("01", "10"))


def phase_prefix_chips(expected_payload_len):
    prefix = bytes(
        [0x00] * PREAMBLE_BYTES + [SFD, expected_payload_len + 2]
    )
    bit_string = "".join(
        "1" if (byte >> bit) & 1 else "0"
        for byte in prefix
        for bit in range(8)
    )
    return "".join(
        BLUEBEE_OPTIMIZED_MAP[int(bit_string[index : index + 4], 2)]
        for index in range(0, len(bit_string), 4)
    )


def find_phase_frame_candidate_fast(
    chips,
    expected_payload_len,
    phase_offset=None,
    polarities=("normal", "inverted"),
):
    """Vectorized optimized-map detector for the live five-phase path."""
    frame_len = PREAMBLE_BYTES + 2 + expected_payload_len + 2
    frame_chip_count = frame_len * 2 * 32
    prefix = phase_prefix_chips(expected_payload_len)[
        : PHASE_FAST_PREFIX_SYMBOLS * 32
    ]
    prefix_values = (
        np.frombuffer(prefix.encode("ascii"), dtype=np.uint8) - ord("0")
    ).astype(np.int16)
    chip_values = (
        np.frombuffer(chips.encode("ascii"), dtype=np.uint8) - ord("0")
    ).astype(np.int16)
    if len(chip_values) < frame_chip_count:
        return None

    best = None
    ones = np.ones(len(prefix_values), dtype=np.int16)
    prefix_ones = int(prefix_values.sum())
    for polarity in polarities:
        work_values = chip_values if polarity == "normal" else 1 - chip_values
        correlations = np.correlate(work_values, prefix_values, mode="valid")
        window_ones = np.correlate(work_values, ones, mode="valid")
        distances = window_ones + prefix_ones - 2 * correlations
        positions = np.flatnonzero(distances <= PHASE_PREFIX_MAX_DISTANCE)
        if not len(positions):
            continue

        ordered = positions[np.argsort(distances[positions])]
        selected_positions = []
        for position in ordered:
            position = int(position)
            if position + frame_chip_count > len(work_values):
                continue
            if any(abs(position - previous) < 32 for previous in selected_positions):
                continue
            selected_positions.append(position)
            if len(selected_positions) >= 16:
                break

        for position in selected_positions:
            frame_values = work_values[
                position : position + frame_chip_count
            ]
            frame_chips = (frame_values + ord("0")).astype(
                np.uint8
            ).tobytes().decode("ascii")
            symbols = chips_to_symbols(frame_chips, BLUEBEE_OPTIMIZED_MAP)
            frame = bits_to_bytes_lsb(symbols_to_bits(symbols))
            if len(frame) != frame_len:
                continue
            fcs_ok, _ = validate_frame(frame)
            prefix_symbol_errors = 0
            expected_prefix = [0x00] * PREAMBLE_BYTES + [SFD]
            for actual, expected in zip(frame[: PREAMBLE_BYTES + 1], expected_prefix):
                difference = actual ^ expected
                prefix_symbol_errors += int((difference & 0x0F) != 0)
                prefix_symbol_errors += int((difference & 0xF0) != 0)
            preamble_distance = sum(
                distance
                for _, distance in symbols[: PREAMBLE_SYMBOLS + 4]
            )
            frame_distance = sum(distance for _, distance in symbols)
            rank = (
                0 if fcs_ok else 1,
                prefix_symbol_errors,
                preamble_distance,
                frame_distance,
                position,
                "optimized",
                polarity,
            ) + (() if phase_offset is None else (phase_offset,))
            candidate = {
                "rank": rank,
                "frame": frame,
                "chip_pos": position,
                "symbols": symbols,
                "symbol_pos": 0,
                "prefix_symbol_errors": prefix_symbol_errors,
                "preamble_distance": preamble_distance,
                "frame_distance": frame_distance,
                "phase_offset": phase_offset,
                "polarity": polarity,
            }
            if best is None or rank < best["rank"]:
                best = candidate
    return best


def decoder_variants(chip_source):
    if chip_source == "phase":
        return (
            ("optimized", "normal", BLUEBEE_OPTIMIZED_MAP),
            ("optimized", "inverted", BLUEBEE_OPTIMIZED_MAP),
            ("legacy", "normal", BLUEBEE_LEGACY_MAP),
            ("legacy", "inverted", BLUEBEE_LEGACY_MAP),
        )
    return (("standard", "normal", CHIP_MAP),)


def find_frame_candidate(
    chips,
    chip_source="standard",
    phase_offset=None,
    expected_payload_len=None,
):
    if len(chips) < MIN_FRAME_CHIPS:
        return None, -1, None, 0

    best = None
    for mode, polarity, chip_map in decoder_variants(chip_source):
        work_chips = invert_chips(chips) if polarity == "inverted" else chips
        for align_offset in range(32):
            symbols = chips_to_symbols(work_chips[align_offset:], chip_map)
            if not symbols:
                continue
            data = bits_to_bytes_lsb(symbols_to_bits(symbols))
            search_start = 0
            while True:
                if chip_source == "phase" and expected_payload_len is not None:
                    frame, byte_pos, prefix_symbol_errors = (
                        find_phase_preamble(
                            data, expected_payload_len, search_start
                        )
                    )
                else:
                    frame, byte_pos = find_preamble(data, search_start)
                    prefix_symbol_errors = 0
                if frame is None:
                    break
                search_start = byte_pos + 1

                local_symbol = byte_pos * 2
                frame_symbol_count = len(frame) * 2
                frame_symbols = symbols[
                    local_symbol : local_symbol + frame_symbol_count
                ]
                if len(frame_symbols) != frame_symbol_count:
                    continue
                fcs_ok, _ = validate_frame(frame)
                preamble_distance = sum(
                    distance
                    for _, distance in frame_symbols[
                        : PREAMBLE_SYMBOLS + 4
                    ]
                )
                frame_distance = sum(distance for _, distance in frame_symbols)
                if chip_source == "phase" and (
                    preamble_distance
                    > (PREAMBLE_SYMBOLS + 4)
                    * PHASE_MAX_AVG_SYMBOL_DISTANCE
                    or frame_distance
                    > frame_symbol_count * PHASE_MAX_AVG_SYMBOL_DISTANCE
                ):
                    continue
                preamble_chip = align_offset + local_symbol * 32
                rank = (
                    0 if fcs_ok else 1,
                    prefix_symbol_errors,
                    preamble_distance,
                    frame_distance,
                    preamble_chip,
                    mode,
                    polarity,
                )
                if best is None or rank < best[0]:
                    best = (
                        rank,
                        frame,
                        preamble_chip,
                        symbols,
                        local_symbol,
                        prefix_symbol_errors,
                        preamble_distance,
                        frame_distance,
                    )

    if best is None:
        return None
    return {
        "rank": best[0] + (() if phase_offset is None else (phase_offset,)),
        "frame": best[1],
        "chip_pos": best[2],
        "symbols": best[3],
        "symbol_pos": best[4],
        "prefix_symbol_errors": best[5],
        "preamble_distance": best[6],
        "frame_distance": best[7],
        "phase_offset": phase_offset,
    }


def find_frame_window(chips, chip_source="standard"):
    candidate = find_frame_candidate(chips, chip_source)
    if candidate is None:
        return None, -1, None, 0
    return (
        candidate["frame"],
        candidate["chip_pos"],
        candidate["symbols"],
        candidate["symbol_pos"],
    )


def choose_phase_candidate(candidates):
    """Return one best frame for a receive iteration across phase offsets.

    CRC validity is the first rank component, followed by preamble and whole
    frame distances.  Collapsing here makes simultaneous detections of one RF
    burst a single protocol observation; a later retransmission still reaches
    SequenceTracker in a separate iteration and is counted as a duplicate.
    """
    usable = [candidate for candidate in candidates if candidate is not None]
    return min(usable, key=lambda candidate: candidate["rank"]) if usable else None


def validate_frame(frame):
    phr_len = frame[PREAMBLE_BYTES + 1]
    if phr_len < 2 or len(frame) != PREAMBLE_BYTES + 2 + phr_len:
        return False, []
    payload_len = phr_len - 2
    payload_start = PREAMBLE_BYTES + 2
    payload = frame[payload_start : payload_start + payload_len]
    fcs_start = payload_start + payload_len
    fcs_rx = frame[fcs_start] | (frame[fcs_start + 1] << 8)
    return fcs_rx == crc16_ccitt(payload), payload


def utc_iso(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


def format_ratio(label, item):
    numerator = item["numerator"]
    denominator = item["denominator"]
    if item["value"] is None:
        return f"  {label:<25} N/A ({numerator}/{denominator})"
    return (
        f"  {label:<25} {item['value'] * 100:.3f}% "
        f"({numerator}/{denominator})"
    )


def output_paths(args):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = Path(args.output_prefix or f"bluebee_perf_rx_{stamp}")
    csv_path = Path(args.csv_out) if args.csv_out else prefix.with_suffix(".csv")
    json_path = Path(args.json_out) if args.json_out else prefix.with_suffix(".json")
    return csv_path, json_path


def build_summary(
    args,
    tracker,
    board_stats,
    start_epoch,
    end_epoch,
    crc_ok_packets,
    crc_failure,
    non_test_packets,
    zmq_msgs,
    csv_path,
):
    elapsed = max(0.0, end_epoch - start_epoch)
    scheduled = board_stats.get("scheduled") if board_stats else None
    tx_completed = board_stats.get("tx_completed") if board_stats else None
    completion = ratio(
        tx_completed if tx_completed is not None else 0,
        scheduled,
    )
    wireless_prr = ratio(tracker.unique, tx_completed)
    end_to_end = ratio(tracker.unique, scheduled)

    payload_len = None
    if len(tracker.payload_lengths) == 1:
        payload_len = next(iter(tracker.payload_lengths))
    elif args.payload_len is not None:
        payload_len = args.payload_len

    throughput = {
        "payload_len": payload_len,
        "gross_bit_s": None,
        "gross_byte_s": None,
        "application_bit_s": None,
        "application_byte_s": None,
    }
    if elapsed > 0 and payload_len is not None:
        gross_bytes = tracker.unique * payload_len / elapsed
        app_bytes = tracker.unique * (payload_len - 10) / elapsed
        throughput.update(
            gross_bit_s=gross_bytes * 8,
            gross_byte_s=gross_bytes,
            application_bit_s=app_bytes * 8,
            application_byte_s=app_bytes,
        )

    return {
        "schema": "bluebee-perf-rx-v1",
        "run_id": tracker.locked_run_id,
        "expected_run_id": args.run_id,
        "expected_payload_len": args.payload_len,
        "observation": {
            "start_utc": utc_iso(start_epoch),
            "end_utc": utc_iso(end_epoch),
            "start_epoch_s": start_epoch,
            "end_epoch_s": end_epoch,
            "duration_s": elapsed,
            "scope": "receiver process start through receiver stop",
        },
        "receiver": {
            "chip_source": args.chip_source,
            "chip_zmq": args.chip_zmq,
            "phase_keep_offset": args.phase_keep_offset,
            "phase_endpoints": getattr(args, "phase_endpoints", None),
            "freq_offset_hz": args.freq_offset,
            "unique": tracker.unique,
            "duplicate": tracker.duplicate,
            "out_of_order": tracker.out_of_order,
            "crc_failure": crc_failure,
            "longest_loss_burst": tracker.longest_loss_burst(scheduled),
            "loss_scope": (
                f"sequence 0..{scheduled - 1} from board scheduled"
                if scheduled is not None and scheduled > 0
                else "minimum through maximum valid received sequence"
            ),
            "payload_failure": tracker.payload_failure,
            "run_id_mismatch": tracker.run_id_mismatch,
            "crc_ok_packets": crc_ok_packets,
            "non_test_packets": non_test_packets,
            "zmq_messages": zmq_msgs,
            "phase_zmq_messages": getattr(args, "phase_zmq_messages", None),
            "phase_candidate_stats": getattr(
                args, "phase_candidate_stats", None
            ),
            "phase_scan_timing": getattr(args, "phase_scan_timing", None),
        },
        "board": board_stats,
        "ratios": {
            "scheduling_completion": completion,
            "wireless_prr": wireless_prr,
            "end_to_end_receive": end_to_end,
        },
        "throughput": throughput,
        "raw_csv": str(csv_path),
    }


def print_summary(summary, json_path):
    observation = summary["observation"]
    receiver = summary["receiver"]
    throughput = summary["throughput"]

    print("\n" + "=" * 72)
    print(
        "BLUEBEE PHASE-1 PERFORMANCE REPORT "
        f"(chip source: {receiver['chip_source']})"
    )
    print("=" * 72)
    print(f"  Run ID:                  {summary['run_id']}")
    print(f"  Observation start:       {observation['start_utc']}")
    print(f"  Observation end:         {observation['end_utc']}")
    print(f"  Observation duration:    {observation['duration_s']:.3f} s")
    print(f"  Unique:                  {receiver['unique']}")
    print(f"  Duplicate:               {receiver['duplicate']}")
    print(f"  Out of order:            {receiver['out_of_order']}")
    print(f"  CRC/FCS failures:        {receiver['crc_failure']}")
    print(f"  Payload failures:        {receiver['payload_failure']}")
    print(f"  Run-ID mismatches:       {receiver['run_id_mismatch']}")
    print(f"  Longest loss burst:      {receiver['longest_loss_burst']}")
    print(format_ratio("Scheduling completion:", summary["ratios"]["scheduling_completion"]))
    print(format_ratio("Wireless PRR:", summary["ratios"]["wireless_prr"]))
    print(format_ratio("End-to-end receive:", summary["ratios"]["end_to_end_receive"]))
    if throughput["gross_bit_s"] is not None:
        print(
            f"  Gross throughput:        {throughput['gross_bit_s']:.3f} bit/s "
            f"({throughput['gross_byte_s']:.3f} byte/s)"
        )
        print(
            f"  Application goodput:     {throughput['application_bit_s']:.3f} bit/s "
            f"({throughput['application_byte_s']:.3f} byte/s)"
        )
    else:
        print("  Gross throughput:        N/A")
        print("  Application goodput:     N/A")
    if summary["board"] is None:
        print("  Board merge:             N/A (provide --board-stats serial.log)")
    print(f"  Raw CSV:                 {summary['raw_csv']}")
    print(f"  Summary JSON:            {json_path}")
    print("=" * 72)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Known-good standard ZigBee OQPSK receiver with BlueBee PRR statistics"
    )
    parser.add_argument("--channel", type=int, default=26, help="ZigBee channel (default: 26)")
    parser.add_argument(
        "--chip-source",
        choices=("standard", "phase"),
        default="standard",
        help=(
            "Chip stream: standard OQPSK on ZMQ 55556 (default) or "
            "five-phase diagnostic on ZMQ 55557..55561"
        ),
    )
    parser.add_argument(
        "--chip-zmq",
        help=(
            "Override the standard or fixed-phase ZMQ endpoint; unavailable "
            "with phase auto"
        ),
    )
    parser.add_argument(
        "--phase-keep-offset",
        choices=("auto", "0", "1", "2", "3", "4"),
        default="auto",
        help=(
            "Phase sampler endpoint: auto (default for phase source) or fixed "
            "offset 0..4"
        ),
    )
    parser.add_argument(
        "--freq-offset",
        type=float,
        default=0.0,
        help="Optional receiver frequency correction in Hz",
    )
    parser.add_argument("--duration", type=float, default=0.0, help="Run for N seconds (0 = forever)")
    parser.add_argument("--run-id", type=int, help="Expected decimal 16-bit Run ID")
    parser.add_argument("--payload-len", type=int, help="Expected payload length, 10-46 bytes")
    parser.add_argument("--board-stats", help="Serial log containing a matching final PERF_STATS line")
    parser.add_argument("--output-prefix", help="Default prefix for CSV and JSON output")
    parser.add_argument("--csv-out", help="Raw per-detection CSV path")
    parser.add_argument("--json-out", help="Final summary JSON path")
    parser.add_argument("--verbose-packets", action="store_true", help="Print every decoded packet")
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("--duration must be non-negative")
    if args.run_id is not None and not 0 <= args.run_id <= 0xFFFF:
        parser.error("--run-id must be in [0, 65535]")
    if args.payload_len is not None and not MIN_PAYLOAD_LEN <= args.payload_len <= MAX_PAYLOAD_LEN:
        parser.error("--payload-len must be in [10, 46]")
    if args.chip_source == "standard":
        args.chip_zmq = args.chip_zmq or STANDARD_ENDPOINT
        args.phase_endpoints = None
    elif args.phase_keep_offset == "auto":
        if args.chip_zmq is not None:
            parser.error(
                "--chip-zmq cannot override the five fixed endpoints in "
                "--phase-keep-offset auto"
            )
        args.phase_endpoints = dict(PHASE_ENDPOINTS)
    else:
        offset = int(args.phase_keep_offset)
        args.phase_keep_offset = offset
        args.chip_zmq = args.chip_zmq or PHASE_ENDPOINTS[offset]
        args.phase_endpoints = {offset: args.chip_zmq}
    return args


def main():
    from gr_zigbee import gr_zigbee as gr_block

    args = parse_args()
    csv_path, json_path = output_paths(args)
    tracker = SequenceTracker(args.run_id, args.payload_len)
    csv_file = csv_path.open("w", newline="", encoding="utf-8")
    fieldnames = [
        "time_utc",
        "elapsed_s",
        "fcs_ok",
        "result",
        "run_id",
        "sequence",
        "payload_len",
        "phase_offset",
        "phase_polarity",
        "prefix_symbol_errors",
        "preamble_distance",
        "frame_distance",
        "phase_candidate_offsets",
        "frame_hex",
    ]
    csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    csv_writer.writeheader()
    csv_file.flush()

    gr_block_obj = gr_block()
    gr_block_obj.set_zigbee_channel(args.channel)
    if args.freq_offset:
        gr_block_obj.set_freq_offset(args.freq_offset)
    gr_block_obj.start()
    endpoint_label = (
        args.chip_zmq
        if args.chip_source == "standard"
        else ",".join(
            f"{offset}:{endpoint}"
            for offset, endpoint in args.phase_endpoints.items()
        )
    )
    print(
        f"RX (OQPSK): ch{args.channel} {gr_block_obj.get_freq()/1e6:.1f} MHz "
        f"sr={gr_block_obj.get_sample_rate()/1e6:.1f} MHz "
        f"chip_source={args.chip_source} zmq={endpoint_label} "
        f"phase_offset={args.phase_keep_offset} "
        f"freq_offset={args.freq_offset:g}"
    )
    print(f"Raw CSV: {csv_path}")

    endpoint_map = (
        args.phase_endpoints
        if args.chip_source == "phase"
        else {None: args.chip_zmq}
    )
    subscribers = {
        offset: ZMQSubscriber(addr=endpoint)
        for offset, endpoint in endpoint_map.items()
    }
    chip_buffers = {offset: "" for offset in subscribers}
    zmq_msgs_by_offset = {offset: 0 for offset in subscribers}
    phase_candidate_stats = {
        offset: {"candidates": 0, "fcs_ok": 0, "fcs_failure": 0}
        for offset in subscribers
        if offset is not None
    }
    zmq_msgs = 0
    crc_ok_packets = 0
    crc_failure = 0
    non_test_packets = 0
    start_epoch = time.time()
    last_report = start_epoch
    pending_scan = False
    phase_polarity_hint = None
    phase_scan_polarity = "normal"
    phase_scan_count = 0
    phase_scan_sum_s = 0.0
    phase_scan_max_s = 0.0

    try:
        while True:
            received_any = False
            poll_ms = 10 if len(subscribers) == 1 else 2
            for offset, subscriber in subscribers.items():
                raw_messages = subscriber.read_available(
                    poll_timeout_ms=poll_ms
                )
                if not raw_messages:
                    continue
                received_any = True
                message_count = len(raw_messages)
                zmq_msgs += message_count
                zmq_msgs_by_offset[offset] += message_count
                chip_buffers[offset] += "".join(
                    unpack_bytes_to_chips(raw) for raw in raw_messages if raw
                )
                if len(chip_buffers[offset]) > MAX_CHIPS:
                    chip_buffers[offset] = chip_buffers[offset][-MAX_CHIPS:]

            if received_any or pending_scan:
                scan_start = time.perf_counter()
                candidates = {}
                for offset, chip_buffer in chip_buffers.items():
                    if len(chip_buffer) < MIN_FRAME_CHIPS:
                        continue
                    if (
                        args.chip_source == "phase"
                        and args.payload_len is not None
                    ):
                        candidate = find_phase_frame_candidate_fast(
                            chip_buffer,
                            args.payload_len,
                            phase_offset=offset,
                            polarities=(
                                phase_polarity_hint or phase_scan_polarity,
                            ),
                        )
                    else:
                        candidate = find_frame_candidate(
                            chip_buffer,
                            args.chip_source,
                            phase_offset=(
                                offset
                                if args.chip_source == "phase"
                                else None
                            ),
                        )
                    if candidate is not None:
                        candidates[offset] = candidate
                        if offset is not None:
                            phase_candidate_stats[offset]["candidates"] += 1
                            if validate_frame(candidate["frame"])[0]:
                                phase_candidate_stats[offset]["fcs_ok"] += 1
                            else:
                                phase_candidate_stats[offset][
                                    "fcs_failure"
                                ] += 1

                if args.chip_source == "phase":
                    scan_elapsed = time.perf_counter() - scan_start
                    phase_scan_count += 1
                    phase_scan_sum_s += scan_elapsed
                    phase_scan_max_s = max(phase_scan_max_s, scan_elapsed)

                selected = (
                    choose_phase_candidate(candidates.values())
                    if args.chip_source == "phase"
                    else next(iter(candidates.values()), None)
                )
                if selected is not None:
                    frame = selected["frame"]
                    chip_pos = selected["chip_pos"]
                    symbols = selected["symbols"]
                    symbol_pos = selected["symbol_pos"]
                    phase_offset = selected["phase_offset"]
                    now = time.time()
                    fcs_ok, payload = validate_frame(frame)
                    parsed = None
                    result = "crc_failure"
                    if fcs_ok:
                        crc_ok_packets += 1
                        if args.chip_source == "phase":
                            phase_polarity_hint = selected.get(
                                "polarity", phase_scan_polarity
                            )
                        parsed, result = tracker.observe(payload)
                        if parsed.reason == "magic":
                            non_test_packets += 1
                    else:
                        crc_failure += 1

                    record = {
                        "time_utc": utc_iso(now),
                        "elapsed_s": f"{now - start_epoch:.6f}",
                        "fcs_ok": int(fcs_ok),
                        "result": result,
                        "run_id": "" if parsed is None or parsed.run_id is None else parsed.run_id,
                        "sequence": "" if parsed is None or parsed.sequence is None else parsed.sequence,
                        "payload_len": len(payload),
                        "phase_offset": "" if phase_offset is None else phase_offset,
                        "phase_polarity": selected.get("polarity", ""),
                        "prefix_symbol_errors": selected[
                            "prefix_symbol_errors"
                        ],
                        "preamble_distance": selected["preamble_distance"],
                        "frame_distance": selected["frame_distance"],
                        "phase_candidate_offsets": " ".join(
                            str(offset) for offset in sorted(
                                candidate_offset
                                for candidate_offset in candidates
                                if candidate_offset is not None
                            )
                        ),
                        "frame_hex": " ".join(f"{byte:02X}" for byte in frame),
                    }
                    csv_writer.writerow(record)
                    csv_file.flush()

                    if args.verbose_packets or not fcs_ok or result not in ("unique",):
                        print(
                            f"packet chip={chip_pos} phase={record['phase_offset']} "
                            f"FCS={'OK' if fcs_ok else 'FAIL'} "
                            f"result={result} run_id={record['run_id']} "
                            f"sequence={record['sequence']} payload_len={len(payload)}"
                        )
                        if args.verbose_packets:
                            distances = [
                                distance
                                for _, distance in symbols[
                                    symbol_pos : symbol_pos + PREAMBLE_SYMBOLS
                                ]
                            ]
                            print(f"  Symbol distances: {distances}")
                            print(f"  Frame bytes: {record['frame_hex']}")
                    # Consume every same-iteration phase candidate.  Even when
                    # several offsets decoded the burst, it was observed once
                    # above and therefore cannot inflate duplicate accounting.
                    for offset, candidate in candidates.items():
                        frame_end_chip = (
                            candidate["chip_pos"]
                            + len(candidate["frame"]) * 2 * 32
                        )
                        chip_buffers[offset] = chip_buffers[offset][
                            frame_end_chip:
                        ]
                    pending_scan = any(
                        len(buffer) >= MIN_FRAME_CHIPS
                        for buffer in chip_buffers.values()
                    )
                else:
                    pending_scan = False

            if args.chip_source == "phase" and phase_polarity_hint is None:
                phase_scan_polarity = (
                    "inverted"
                    if phase_scan_polarity == "normal"
                    else "normal"
                )

            now = time.time()
            if now - last_report >= STATS_PERIOD:
                diag_buffer = max(chip_buffers.values(), key=len, default="")
                ones, transitions = chip_stats(diag_buffer[-DIAG_SCAN_CHIPS:])
                print(
                    f"[elapsed:{now-start_epoch:.1f}s unique:{tracker.unique} "
                    f"duplicate:{tracker.duplicate} out_of_order:{tracker.out_of_order} "
                    f"crc_failure:{crc_failure} payload_failure:{tracker.payload_failure} "
                    f"zmq:{zmq_msgs} chips:{sum(map(len, chip_buffers.values()))} "
                    f"ones:{ones:.3f} transitions:{transitions:.3f}]"
                )
                last_report = now

            if args.duration > 0 and now - start_epoch >= args.duration:
                break

    except KeyboardInterrupt:
        pass
    finally:
        end_epoch = time.time()
        for subscriber in subscribers.values():
            subscriber.close()
        gr_block_obj.stop()
        gr_block_obj.wait()
        csv_file.close()

        board_stats = None
        args.phase_zmq_messages = (
            {
                str(offset): count
                for offset, count in zmq_msgs_by_offset.items()
            }
            if args.chip_source == "phase"
            else None
        )
        args.phase_candidate_stats = (
            {
                str(offset): stats
                for offset, stats in phase_candidate_stats.items()
            }
            if args.chip_source == "phase"
            else None
        )
        args.phase_scan_timing = (
            {
                "samples": phase_scan_count,
                "avg_ms": (
                    phase_scan_sum_s * 1000.0 / phase_scan_count
                    if phase_scan_count
                    else 0.0
                ),
                "max_ms": phase_scan_max_s * 1000.0,
                "buffer_span_ms": MAX_CHIPS / 2000.0,
            }
            if args.chip_source == "phase"
            else None
        )
        if args.board_stats:
            expected_board_run_id = (
                tracker.locked_run_id
                if tracker.locked_run_id is not None
                else args.run_id
            )
            try:
                board_text = Path(args.board_stats).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError as error:
                print(f"Warning: cannot read board stats: {error}")
            else:
                board_stats = parse_board_stats_text(
                    board_text,
                    expected_run_id=expected_board_run_id,
                )
                if board_stats is None:
                    print("Warning: no matching final PERF_STATS line found in board log")

        summary = build_summary(
            args,
            tracker,
            board_stats,
            start_epoch,
            end_epoch,
            crc_ok_packets,
            crc_failure,
            non_test_packets,
            zmq_msgs,
            csv_path,
        )
        json_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print_summary(summary, json_path)


if __name__ == "__main__":
    main()
