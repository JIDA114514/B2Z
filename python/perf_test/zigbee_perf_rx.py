#!/usr/bin/env python3
# coding=utf-8
"""BlueBee differential receiver with standard ZigBee DSSS PRR accounting."""

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
MAX_CHIPS = 48000
SOFT_MAX_CHIPS = 96000
STATS_PERIOD = 2.0
DIAG_SCAN_CHIPS = 4096
PHASE_MAX_AVG_SYMBOL_DISTANCE = 4
PHASE_FAST_PREFIX_SYMBOLS = 2
PHASE_PREFIX_MAX_DISTANCE = (
    PHASE_FAST_PREFIX_SYMBOLS * PHASE_MAX_AVG_SYMBOL_DISTANCE
)
STANDARD_FAST_PREFIX_SYMBOLS = PREAMBLE_SYMBOLS
STANDARD_MAX_AVG_PREFIX_DISTANCE = 10
STANDARD_PREFIX_MAX_DISTANCE = (
    STANDARD_FAST_PREFIX_SYMBOLS * STANDARD_MAX_AVG_PREFIX_DISTANCE
)
STANDARD_MAX_PREFIX_CANDIDATES = 16
STANDARD_PHASE_COUNT = 5
STANDARD_AMBIGUITIES = (
    "normal",
    "inverted",
    "even_inverted",
    "odd_inverted",
    "swapped",
    "swapped_inverted",
    "swapped_even_inverted",
    "swapped_odd_inverted",
)
STANDARD_ENDPOINT = "tcp://127.0.0.1:55556"
STANDARD_SOFT_ENDPOINT = "tcp://127.0.0.1:55562"
STANDARD_SOFT_SCALE = 40.0
STANDARD_SOFT_ALIGNMENT_CHIPS = 64
PHASE_ENDPOINTS = {
    offset: f"tcp://127.0.0.1:{55557 + offset}" for offset in range(5)
}
POPCOUNT8 = np.asarray([value.bit_count() for value in range(256)], dtype=np.uint8)
STANDARD_SOFT_REFERENCES = np.asarray(
    [
        [1 if chip == "1" else -1 for chip in reference]
        for reference in CHIP_MAP
    ],
    dtype=np.float32,
)


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


def unpack_messages_to_chips(messages):
    """Vectorized LSB-first unpack for one batch of ZMQ messages."""
    bits = unpack_messages_to_chip_values(messages)
    if not len(bits):
        return ""
    return (bits + ord("0")).tobytes().decode("ascii")


def unpack_messages_to_chip_values(messages):
    """Return one batch as a uint8 array of LSB-first unpacked bits."""
    packed = b"".join(message for message in messages if message)
    if not packed:
        return np.empty(0, dtype=np.uint8)
    values = np.frombuffer(packed, dtype=np.uint8)
    return np.unpackbits(values, bitorder="little")


def deinterleave_standard_phase_values(
    chip_values,
    stream_phase,
    offsets=range(STANDARD_PHASE_COUNT),
):
    """Split the full-rate standard stream while preserving modulo-5 phase."""
    streams = {}
    for offset in offsets:
        start = (int(offset) - stream_phase) % STANDARD_PHASE_COUNT
        selected = chip_values[start::STANDARD_PHASE_COUNT]
        streams[int(offset)] = (
            (selected + ord("0")).astype(np.uint8).tobytes().decode("ascii")
        )
    next_phase = (stream_phase + len(chip_values)) % STANDARD_PHASE_COUNT
    return streams, next_phase


def deinterleave_standard_soft_values(
    soft_values,
    stream_phase,
    offsets=range(STANDARD_PHASE_COUNT),
):
    """Split the quantized full-rate phase-difference stream by timing phase."""
    streams = {}
    for offset in offsets:
        start = (int(offset) - stream_phase) % STANDARD_PHASE_COUNT
        streams[int(offset)] = soft_values[start::STANDARD_PHASE_COUNT].tobytes()
    next_phase = (stream_phase + len(soft_values)) % STANDARD_PHASE_COUNT
    return streams, next_phase


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


def standard_prefix_chips():
    """Return the four-byte preamble in the standard 802.15.4 chip map."""
    bit_string = "0" * (PREAMBLE_BYTES * 8)
    return "".join(
        CHIP_MAP[int(bit_string[index : index + 4], 2)]
        for index in range(0, len(bit_string), 4)
    )


def prefix_distances(chip_values, prefix_values):
    """Compute Hamming distance at every possible chip position."""
    correlations = np.correlate(chip_values, prefix_values, mode="valid")
    cumulative_ones = np.empty(len(chip_values) + 1, dtype=np.int64)
    cumulative_ones[0] = 0
    np.cumsum(chip_values, dtype=np.int64, out=cumulative_ones[1:])
    window_ones = (
        cumulative_ones[len(prefix_values) :]
        - cumulative_ones[: -len(prefix_values)]
    )
    return window_ones + int(prefix_values.sum()) - 2 * correlations


def repeated_symbol_prefix_distances(chip_values, symbol_values, repetitions):
    """Correlate a repeated 32-chip symbol without a long convolution."""
    symbol_distances = prefix_distances(chip_values, symbol_values)
    prefix_len = len(symbol_values) * repetitions
    output_len = len(chip_values) - prefix_len + 1
    distances = np.zeros(output_len, dtype=symbol_distances.dtype)
    for repetition in range(repetitions):
        start = repetition * len(symbol_values)
        distances += symbol_distances[start : start + output_len]
    return distances


def score_standard_offset(
    chips,
    expected_payload_len,
    ambiguity="normal",
    sample_offset=None,
):
    """Score one modulo-5 stream using only the repeated preamble symbol.

    The returned work array and candidate positions let the selected offset be
    decoded without repeating correlation. Full CHIP_MAP symbol decoding is
    deliberately deferred until offsets have been ranked.
    """
    frame_len = PREAMBLE_BYTES + 2 + expected_payload_len + 2
    frame_chip_count = frame_len * 2 * 32
    if len(chips) < frame_chip_count:
        return None

    preamble_symbol = standard_prefix_chips()[:32]
    symbol_values = (
        np.frombuffer(preamble_symbol.encode("ascii"), dtype=np.uint8)
        - ord("0")
    ).astype(np.int16)
    chip_values = (
        np.frombuffer(chips.encode("ascii"), dtype=np.uint8) - ord("0")
    ).astype(np.int16)
    work_values = transform_standard_chip_values(chip_values, ambiguity)
    distances = repeated_symbol_prefix_distances(
        work_values,
        symbol_values,
        STANDARD_FAST_PREFIX_SYMBOLS,
    )
    if not len(distances):
        return None
    positions = select_prefix_positions(
        distances,
        STANDARD_PREFIX_MAX_DISTANCE,
        frame_chip_count,
        len(work_values),
        STANDARD_MAX_PREFIX_CANDIDATES,
    )
    minimum_distance = int(distances.min())
    return {
        "sample_offset": sample_offset,
        "ambiguity": ambiguity,
        "frame_chip_count": frame_chip_count,
        "work_values": work_values,
        "positions": positions,
        "minimum_distance": minimum_distance,
        "best_distance": (
            min(int(distances[position]) for position in positions)
            if positions
            else None
        ),
        "best_position": (
            min(
                positions,
                key=lambda position: (int(distances[position]), position),
            )
            if positions
            else None
        ),
    }


def decode_standard_offset_score(score, expected_payload_len):
    """Run full CHIP_MAP decoding for one previously scored offset."""
    if score is None or not score["positions"]:
        return None

    frame_len = PREAMBLE_BYTES + 2 + expected_payload_len + 2
    expected_prefix = [0x00] * PREAMBLE_BYTES + [SFD]
    expected_phr = expected_payload_len + 2
    best = None
    for position in score["positions"]:
        frame_values = score["work_values"][
            position : position + score["frame_chip_count"]
        ]
        frame_chips = (frame_values + ord("0")).astype(
            np.uint8
        ).tobytes().decode("ascii")
        symbols = chips_to_symbols(frame_chips, CHIP_MAP)
        frame = bits_to_bytes_lsb(symbols_to_bits(symbols))
        if len(frame) != frame_len:
            continue
        if frame[PREAMBLE_BYTES + 1] != expected_phr:
            continue

        prefix_symbol_errors = 0
        for actual, expected in zip(
            frame[: PREAMBLE_BYTES + 1], expected_prefix
        ):
            difference = actual ^ expected
            prefix_symbol_errors += int((difference & 0x0F) != 0)
            prefix_symbol_errors += int((difference & 0xF0) != 0)
        fcs_ok, _ = validate_frame(frame)
        preamble_distance = sum(
            distance for _, distance in symbols[: PREAMBLE_SYMBOLS + 4]
        )
        frame_distance = sum(distance for _, distance in symbols)
        rank = (
            position,
            0 if fcs_ok else 1,
            prefix_symbol_errors,
            preamble_distance,
            frame_distance,
            "standard-fast",
            score["ambiguity"],
        )
        candidate = {
            "rank": rank,
            "frame": frame,
            "hard_frame_values": frame_values.astype(np.uint8, copy=True),
            "chip_pos": position,
            "symbols": symbols,
            "symbol_pos": 0,
            "prefix_symbol_errors": prefix_symbol_errors,
            "preamble_distance": preamble_distance,
            "frame_distance": frame_distance,
            "phase_offset": score["sample_offset"],
            "polarity": "normal",
            "standard_ambiguity": score["ambiguity"],
            "offset_prefix_distance": score["best_distance"],
            "decode_method": "hard",
        }
        if best is None or rank < best["rank"]:
            best = candidate
    return best


def rank_standard_offset_scores(scores):
    """Return offsets with viable preambles, best score first."""
    return sorted(
        (score for score in scores if score and score["positions"]),
        key=lambda score: (
            score["best_distance"],
            score["best_position"],
            -1 if score["sample_offset"] is None else score["sample_offset"],
        ),
    )


def decode_ranked_standard_offsets(
    scores,
    expected_payload_len,
    max_offsets=None,
):
    """Decode ranked offsets until FCS succeeds or the policy limit is hit.

    ``max_offsets=None`` is the reception-first policy: it normally decodes
    only the best offset, but keeps trying lower-ranked offsets after an FCS
    failure.  A finite limit retains the earlier bounded-work policy for A/B
    measurements.
    """
    if max_offsets is not None and max_offsets <= 0:
        raise ValueError("max_offsets must be positive or None")
    ranked = rank_standard_offset_scores(scores)
    decoded = []
    attempted = 0
    decode_scores = ranked if max_offsets is None else ranked[:max_offsets]
    for offset_rank, score in enumerate(decode_scores, start=1):
        attempted += 1
        candidate = decode_standard_offset_score(score, expected_payload_len)
        if candidate is not None:
            candidate["offset_rank"] = offset_rank
            decoded.append(candidate)
            if validate_frame(candidate["frame"])[0]:
                break
    return choose_standard_candidate(decoded), decoded, ranked, attempted


def transform_standard_chip_values(chip_values, ambiguity):
    """Undo one Costas quadrant or I/Q polarity ambiguity."""
    if ambiguity not in STANDARD_AMBIGUITIES:
        raise ValueError(f"unsupported standard ambiguity: {ambiguity}")

    work_values = chip_values.copy()
    if ambiguity.startswith("swapped"):
        paired = (len(work_values) // 2) * 2
        work_values[:paired] = (
            work_values[:paired].reshape(-1, 2)[:, ::-1].reshape(-1)
        )

    if ambiguity in ("inverted", "swapped_inverted"):
        work_values = 1 - work_values
    elif ambiguity in ("even_inverted", "swapped_even_inverted"):
        work_values[0::2] = 1 - work_values[0::2]
    elif ambiguity in ("odd_inverted", "swapped_odd_inverted"):
        work_values[1::2] = 1 - work_values[1::2]
    return work_values


def transform_standard_chips(chips, ambiguity):
    """String wrapper used by tests and offline diagnostics."""
    chip_values = (
        np.frombuffer(chips.encode("ascii"), dtype=np.uint8) - ord("0")
    ).astype(np.uint8)
    transformed = transform_standard_chip_values(chip_values, ambiguity)
    return (transformed + ord("0")).astype(np.uint8).tobytes().decode("ascii")


def transform_standard_soft_values(soft_values, ambiguity):
    """Apply the hard decoder's ambiguity transform to signed soft chips."""
    if ambiguity not in STANDARD_AMBIGUITIES:
        raise ValueError(f"unsupported standard ambiguity: {ambiguity}")

    work_values = np.asarray(soft_values, dtype=np.int16).copy()
    if ambiguity.startswith("swapped"):
        paired = (len(work_values) // 2) * 2
        work_values[:paired] = (
            work_values[:paired].reshape(-1, 2)[:, ::-1].reshape(-1)
        )

    if ambiguity in ("inverted", "swapped_inverted"):
        work_values = -work_values
    elif ambiguity in ("even_inverted", "swapped_even_inverted"):
        work_values[0::2] = -work_values[0::2]
    elif ambiguity in ("odd_inverted", "swapped_odd_inverted"):
        work_values[1::2] = -work_values[1::2]
    return work_values


def soft_chips_to_symbols(soft_values):
    """Decode 32-chip symbols using phase magnitude as confidence."""
    usable = (len(soft_values) // 32) * 32
    if usable == 0:
        return [], np.empty(0, dtype=np.float32)

    chunks = np.asarray(soft_values[:usable], dtype=np.float32).reshape(-1, 32)
    correlations = chunks @ STANDARD_SOFT_REFERENCES.T
    best_symbols = np.argmax(correlations, axis=1)
    best_correlations = correlations[np.arange(len(chunks)), best_symbols]
    second_correlations = np.partition(correlations, -2, axis=1)[:, -2]
    margins = best_correlations - second_correlations

    hard_values = (chunks > 0).astype(np.uint8)
    chosen_references = (STANDARD_SOFT_REFERENCES[best_symbols] > 0).astype(
        np.uint8
    )
    hard_distances = np.count_nonzero(
        hard_values != chosen_references,
        axis=1,
    )
    symbols = list(zip(best_symbols.tolist(), hard_distances.tolist()))
    return symbols, margins


def decode_standard_soft_frame(
    soft_frame_values,
    expected_payload_len,
    hard_candidate,
    soft_phase_offset,
    alignment_mismatches,
):
    """Soft-decode one frame window already acquired by the hard path."""
    frame_len = PREAMBLE_BYTES + 2 + expected_payload_len + 2
    frame_chip_count = frame_len * 2 * 32
    if len(soft_frame_values) != frame_chip_count:
        return None

    centered = np.asarray(soft_frame_values, dtype=np.float32).copy()
    phase_bias = float(centered[: PREAMBLE_SYMBOLS * 32].mean())
    centered -= phase_bias
    symbols, margins = soft_chips_to_symbols(centered)
    frame = bits_to_bytes_lsb(symbols_to_bits(symbols))
    expected_prefix = bytes([0x00] * PREAMBLE_BYTES + [SFD])
    if len(frame) != frame_len:
        return None
    if bytes(frame[: PREAMBLE_BYTES + 1]) != expected_prefix:
        return None
    if frame[PREAMBLE_BYTES + 1] != expected_payload_len + 2:
        return None
    if not validate_frame(frame)[0]:
        return None

    recovered = dict(hard_candidate)
    recovered.update(
        frame=frame,
        symbols=symbols,
        symbol_pos=0,
        prefix_symbol_errors=0,
        preamble_distance=sum(
            distance for _, distance in symbols[: PREAMBLE_SYMBOLS + 4]
        ),
        frame_distance=sum(distance for _, distance in symbols),
        decode_method="soft_retry",
        hard_frame=hard_candidate["frame"],
        soft_phase_offset=soft_phase_offset,
        soft_phase_bias=phase_bias,
        soft_min_symbol_margin=(float(margins.min()) if len(margins) else None),
        soft_alignment_mismatches=int(alignment_mismatches),
    )
    return recovered


def align_soft_frame(
    hard_candidate,
    soft_buffers,
    expected_payload_len,
    preferred_soft_offset=None,
):
    """Locate a hard candidate in independently buffered soft timing streams.

    Hard and soft ZMQ message boundaries need not match.  Their decisions come
    from the same ``phase_arg`` samples, so short exact sign runs identify the
    corresponding soft window without changing the established hard path.
    """
    hard_values = hard_candidate.get("hard_frame_values")
    if hard_values is None:
        return None
    frame_len = PREAMBLE_BYTES + 2 + expected_payload_len + 2
    frame_chip_count = frame_len * 2 * 32
    if len(hard_values) != frame_chip_count:
        return None

    hard_values = np.asarray(hard_values, dtype=np.uint8)
    ambiguity = hard_candidate.get("standard_ambiguity", "normal")
    # Avoid the repeated preamble when selecting alignment signatures.
    starts = [
        PREAMBLE_SYMBOLS * 32,
        min(PREAMBLE_SYMBOLS * 32 + 128, frame_chip_count - 64),
        max(PREAMBLE_SYMBOLS * 32, frame_chip_count - 128),
    ]
    ordered_offsets = list(soft_buffers)
    if preferred_soft_offset in soft_buffers:
        ordered_offsets.remove(preferred_soft_offset)
        ordered_offsets.insert(0, preferred_soft_offset)
    for soft_phase_offset in ordered_offsets:
        raw_buffer = soft_buffers[soft_phase_offset]
        raw_values = np.frombuffer(raw_buffer, dtype=np.int8)
        if len(raw_values) < frame_chip_count:
            continue
        work_values = transform_standard_soft_values(raw_values, ambiguity)
        signs = (work_values > 0).astype(np.uint8)
        signs_bytes = signs.tobytes()
        possible_starts = set()
        for signature_start in starts:
            signature = hard_values[
                signature_start : signature_start + STANDARD_SOFT_ALIGNMENT_CHIPS
            ].tobytes()
            found = signs_bytes.rfind(signature)
            if found >= signature_start:
                possible_starts.add(found - signature_start)

        best_for_offset = None
        for frame_start in possible_starts:
            frame_end = frame_start + frame_chip_count
            if frame_end > len(work_values):
                continue
            mismatches = int(
                np.count_nonzero(signs[frame_start:frame_end] != hard_values)
            )
            rank = (mismatches, -frame_start, soft_phase_offset)
            if best_for_offset is None or rank < best_for_offset[0]:
                best_for_offset = (
                    rank,
                    work_values[frame_start:frame_end].copy(),
                    soft_phase_offset,
                    mismatches,
                )
        # A matching 64-chip signature is effectively unique in the retained
        # window.  Returning here avoids scanning four unnecessary phases.
        if best_for_offset is not None:
            return best_for_offset[1], best_for_offset[2], best_for_offset[3]
    return None


def retry_standard_candidates_with_soft(
    candidates,
    soft_buffers,
    expected_payload_len,
    preferred_phase_delta=None,
):
    """Try soft decoding only after every hard candidate failed FCS."""
    attempts = 0
    aligned = 0
    observed_phase_delta = preferred_phase_delta
    ordered = sorted(
        (candidate for candidate in candidates if candidate is not None),
        key=lambda candidate: candidate.get("offset_rank", 999),
    )
    for candidate in ordered:
        if validate_frame(candidate["frame"])[0]:
            continue
        attempts += 1
        hard_phase_offset = candidate.get("phase_offset")
        preferred_soft_offset = (
            (hard_phase_offset + observed_phase_delta) % STANDARD_PHASE_COUNT
            if hard_phase_offset is not None
            and observed_phase_delta is not None
            else None
        )
        alignment = align_soft_frame(
            candidate,
            soft_buffers,
            expected_payload_len,
            preferred_soft_offset=preferred_soft_offset,
        )
        if alignment is None:
            continue
        aligned += 1
        soft_values, soft_phase_offset, mismatches = alignment
        if hard_phase_offset is not None:
            observed_phase_delta = (
                soft_phase_offset - hard_phase_offset
            ) % STANDARD_PHASE_COUNT
        recovered = decode_standard_soft_frame(
            soft_values,
            expected_payload_len,
            candidate,
            soft_phase_offset,
            mismatches,
        )
        if recovered is not None:
            return recovered, attempts, aligned, observed_phase_delta
    return None, attempts, aligned, observed_phase_delta


def select_prefix_positions(
    distances,
    max_distance,
    frame_chip_count,
    available_chips,
    max_candidates,
):
    """Select the strongest non-overlapping symbol-aligned candidates."""
    positions = np.flatnonzero(distances <= max_distance)
    if not len(positions):
        return []

    ordered = positions[np.argsort(distances[positions])]
    selected = []
    for position in ordered:
        position = int(position)
        if position + frame_chip_count > available_chips:
            continue
        if any(abs(position - previous) < 32 for previous in selected):
            continue
        selected.append(position)
        if len(selected) >= max_candidates:
            break
    return selected


def find_standard_frame_candidate_fast(
    chips,
    expected_payload_len,
    ambiguities=("normal",),
    sample_offset=None,
):
    """Find a known-length standard frame using preamble-first scoring."""
    best = None
    for ambiguity in ambiguities:
        score = score_standard_offset(
            chips,
            expected_payload_len,
            ambiguity=ambiguity,
            sample_offset=sample_offset,
        )
        candidate = decode_standard_offset_score(score, expected_payload_len)
        if candidate is not None and (
            best is None or candidate["rank"] < best["rank"]
        ):
            best = candidate
    return best


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
    for polarity in polarities:
        work_values = chip_values if polarity == "normal" else 1 - chip_values
        distances = prefix_distances(work_values, prefix_values)
        selected_positions = select_prefix_positions(
            distances,
            PHASE_PREFIX_MAX_DISTANCE,
            frame_chip_count,
            len(work_values),
            16,
        )

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


def choose_standard_candidate(candidates):
    """Choose one physical burst across differential timing phases."""
    usable = [candidate for candidate in candidates if candidate is not None]
    if not usable:
        return None

    def quality(candidate):
        fcs_ok, _ = validate_frame(candidate["frame"])
        return (
            0 if fcs_ok else 1,
            candidate["prefix_symbol_errors"],
            candidate["preamble_distance"],
            candidate["frame_distance"],
            candidate["chip_pos"],
            candidate["phase_offset"],
        )

    return min(usable, key=quality)


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


def summarize_numeric_samples(samples, scale=1.0):
    """Return compact distribution statistics for JSON diagnostics."""
    if not samples:
        return {
            "samples": 0,
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
            "avg": None,
        }
    values = np.asarray(samples, dtype=np.float64) * scale
    return {
        "samples": len(values),
        "min": float(values.min()),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "max": float(values.max()),
        "avg": float(values.mean()),
    }


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
    planned = tracker.planned_range(args.expected_packets)
    scheduled = board_stats.get("scheduled") if board_stats else None
    tx_completed = board_stats.get("tx_completed") if board_stats else None
    completion = ratio(
        tx_completed if tx_completed is not None else 0,
        scheduled,
    )
    wireless_numerator = (
        planned["in_range_unique"] if planned is not None else tracker.unique
    )
    wireless_prr = ratio(wireless_numerator, tx_completed)
    if tx_completed is None:
        wireless_prr["reason"] = "board tx_completed was not provided"
    end_to_end = ratio(tracker.unique, scheduled)
    planned_end_to_end = ratio(
        planned["in_range_unique"] if planned is not None else 0,
        planned["expected_packets"] if planned is not None else None,
    )
    if planned is None:
        planned_end_to_end["reason"] = (
            "provide --tx-duration-s and --tx-interval-us together"
        )

    payload_len = None
    if len(tracker.payload_lengths) == 1:
        payload_len = next(iter(tracker.payload_lengths))
    elif args.payload_len is not None:
        payload_len = args.payload_len

    throughput = {
        "payload_len": payload_len,
        "time_basis": None,
        "time_s": None,
        "unique_basis": None,
        "gross_bit_s": None,
        "gross_byte_s": None,
        "application_bit_s": None,
        "application_byte_s": None,
    }
    throughput_time = args.tx_duration_s if args.tx_duration_s else elapsed
    throughput_unique = (
        planned["in_range_unique"] if planned is not None else tracker.unique
    )
    if throughput_time > 0 and payload_len is not None:
        gross_bytes = throughput_unique * payload_len / throughput_time
        app_bytes = throughput_unique * (payload_len - 10) / throughput_time
        throughput.update(
            time_basis=(
                "planned_tx_duration" if planned is not None
                else "receiver_observation_duration"
            ),
            time_s=throughput_time,
            unique_basis=throughput_unique,
            gross_bit_s=gross_bytes * 8,
            gross_byte_s=gross_bytes,
            application_bit_s=app_bytes * 8,
            application_byte_s=app_bytes,
        )

    return {
        "schema": "bluebee-perf-rx-v2",
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
        "tx_plan": {
            "duration_s": args.tx_duration_s,
            "interval_us": args.tx_interval_us,
            "expected_packets": args.expected_packets,
            "sequence_scope": (
                f"0..{args.expected_packets - 1}"
                if args.expected_packets else None
            ),
        },
        "planned_sequences": planned,
        "receiver": {
            "chip_source": args.chip_source,
            "chip_zmq": args.chip_zmq,
            "standard_keep_offset": args.standard_keep_offset,
            "standard_offset_policy": args.standard_offset_policy,
            "standard_ambiguity": args.standard_ambiguity,
            "standard_ambiguity_stats": getattr(
                args, "standard_ambiguity_stats", None
            ),
            "standard_offset_stats": getattr(
                args, "standard_offset_stats", None
            ),
            "standard_stream": (
                "full-rate differential phase bits; modulo-5 deinterleaved"
                if args.chip_source == "standard"
                else None
            ),
            "phase_keep_offset": args.phase_keep_offset,
            "phase_endpoints": getattr(args, "phase_endpoints", None),
            "freq_offset_hz": args.freq_offset,
            "cfo_correction_hz": args.cfo_correction_hz,
            "rf_gain": args.rf_gain,
            "if_gain": args.if_gain,
            "bb_gain": args.bb_gain,
            "unique": tracker.unique,
            "duplicate": tracker.duplicate,
            "out_of_order": tracker.out_of_order,
            "crc_failure": crc_failure,
            "hard_crc_failure_before_soft_retry": getattr(
                args, "hard_crc_failure", crc_failure
            ),
            "standard_soft_retry": getattr(
                args, "standard_soft_retry_stats", None
            ),
            "longest_loss_burst": tracker.longest_loss_burst(
                args.expected_packets
                if args.expected_packets is not None
                else scheduled
            ),
            "loss_scope": (
                f"sequence 0..{scheduled - 1} from board scheduled"
                if scheduled is not None and scheduled > 0
                else (
                    f"planned sequence 0..{args.expected_packets - 1}"
                    if args.expected_packets is not None
                    and args.expected_packets > 0
                    else "minimum through maximum valid received sequence"
                )
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
            "processing_timing": getattr(
                args, "receiver_processing_timing", None
            ),
            "phase_scan_timing": getattr(args, "phase_scan_timing", None),
            "standard_offset_ranking": getattr(
                args, "standard_offset_ranking", None
            ),
            "buffer_critical": getattr(args, "buffer_critical", None),
        },
        "board": board_stats,
        "ratios": {
            "scheduling_completion": completion,
            "wireless_prr": wireless_prr,
            "end_to_end_receive": end_to_end,
            "planned_end_to_end_receive": planned_end_to_end,
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
    tx_plan = summary["tx_plan"]
    if tx_plan["expected_packets"] is not None:
        planned = summary["planned_sequences"]
        print(
            f"  Planned TX duration:     {tx_plan['duration_s']} s "
            f"at {tx_plan['interval_us']} us"
        )
        print(f"  Expected packets:        {tx_plan['expected_packets']}")
        print(f"  In-range unique:         {planned['in_range_unique']}")
        print(f"  Missing in range:        {planned['missing']}")
        print(f"  Out-of-range sequences:  {planned['out_of_range_count']}")
    print(f"  Unique:                  {receiver['unique']}")
    print(f"  Duplicate:               {receiver['duplicate']}")
    print(f"  Out of order:            {receiver['out_of_order']}")
    print(f"  CRC/FCS failures:        {receiver['crc_failure']}")
    soft_retry = receiver.get("standard_soft_retry")
    if soft_retry and soft_retry["enabled"]:
        print(
            f"  Hard CRC failures:       "
            f"{receiver['hard_crc_failure_before_soft_retry']}"
        )
        print(f"  Soft-retry recovered:    {soft_retry['recovered']}")
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
        print(
            f"  Throughput time basis:   {throughput['time_basis']} "
            f"({throughput['time_s']:.3f} s)"
        )
    else:
        print("  Gross throughput:        N/A")
        print("  Application goodput:     N/A")
    print(
        format_ratio(
            "Planned end-to-end:",
            summary["ratios"]["planned_end_to_end_receive"],
        )
    )
    if summary["board"] is None:
        print("  Board merge:             N/A (provide --board-stats serial.log)")
    print(f"  Raw CSV:                 {summary['raw_csv']}")
    print(f"  Summary JSON:            {json_path}")
    print("=" * 72)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "BlueBee differential receiver with standard ZigBee DSSS "
            "validation and PRR statistics"
        )
    )
    parser.add_argument("--channel", type=int, default=26, help="ZigBee channel (default: 26)")
    parser.add_argument(
        "--chip-source",
        choices=("standard", "phase"),
        default="standard",
        help=(
            "Chip stream: full-rate differential standard stream on ZMQ "
            "55556 (default) or "
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
        "--standard-keep-offset",
        choices=("auto", "0", "1", "2", "3", "4"),
        default="auto",
        help=(
            "Differential standard sampler: auto (default) or fixed "
            "modulo-5 offset 0..4"
        ),
    )
    parser.add_argument(
        "--standard-ambiguity",
        choices=("auto",) + STANDARD_AMBIGUITIES,
        default="auto",
        help=(
            "Differential-chip polarity for standard; auto alternates normal "
            "and inverted until FCS lock (default: auto)"
        ),
    )
    parser.add_argument(
        "--standard-offset-policy",
        choices=("adaptive", "ranked2"),
        default="adaptive",
        help=(
            "Full-decode ranked standard offsets until FCS succeeds "
            "(adaptive, default), or stop after the best two (ranked2)"
        ),
    )
    parser.add_argument(
        "--standard-soft-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Retry hard CRC failures with the parallel quantized soft-phase "
            "stream (default: enabled; disable with --no-standard-soft-retry)"
        ),
    )
    parser.add_argument(
        "--soft-zmq",
        default=STANDARD_SOFT_ENDPOINT,
        help=(
            "Parallel int8 phase-difference endpoint used only for standard "
            f"CRC retry (default: {STANDARD_SOFT_ENDPOINT})"
        ),
    )
    parser.add_argument(
        "--freq-offset",
        type=float,
        default=0.0,
        help=(
            "Hardware LO offset in Hz for DC-spur avoidance; this is "
            "digitally translated back and is not residual-CFO correction"
        ),
    )
    parser.add_argument(
        "--cfo-correction-hz",
        type=float,
        default=0.0,
        help=(
            "Digital residual CFO correction in Hz; positive means the "
            "received carrier is above the nominal channel center"
        ),
    )
    parser.add_argument(
        "--rf-gain",
        type=float,
        default=0.0,
        help="HackRF RF gain (default: 0)",
    )
    parser.add_argument(
        "--if-gain",
        type=float,
        default=32.0,
        help="HackRF IF gain (default: 32)",
    )
    parser.add_argument(
        "--bb-gain",
        type=float,
        default=40.0,
        help="HackRF baseband gain (default: 40)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        help=(
            "Receiver run time in seconds; defaults to TX duration + 10 s "
            "for a bounded TX plan, otherwise runs forever"
        ),
    )
    parser.add_argument(
        "--tx-duration-s",
        type=int,
        help="Bounded board command duration used only for planned accounting",
    )
    parser.add_argument(
        "--tx-interval-us",
        type=int,
        help="Bounded board command interval used only for planned accounting",
    )
    parser.add_argument("--run-id", type=int, help="Expected decimal 16-bit Run ID")
    parser.add_argument("--payload-len", type=int, help="Expected payload length, 10-46 bytes")
    parser.add_argument("--board-stats", help="Serial log containing a matching final PERF_STATS line")
    parser.add_argument("--output-prefix", help="Default prefix for CSV and JSON output")
    parser.add_argument("--csv-out", help="Raw per-detection CSV path")
    parser.add_argument("--json-out", help="Final summary JSON path")
    parser.add_argument("--verbose-packets", action="store_true", help="Print every decoded packet")
    args = parser.parse_args()
    if (args.tx_duration_s is None) != (args.tx_interval_us is None):
        parser.error("--tx-duration-s and --tx-interval-us must be provided together")
    if args.tx_duration_s is not None:
        if not 1 <= args.tx_duration_s <= 600:
            parser.error("--tx-duration-s must be in [1, 600]")
        if args.tx_interval_us <= 0:
            parser.error("--tx-interval-us must be positive")
        args.expected_packets = (
            args.tx_duration_s * 1_000_000 // args.tx_interval_us
        )
    else:
        args.expected_packets = None
    if args.duration is None:
        args.duration = (
            args.tx_duration_s + 10.0 if args.tx_duration_s is not None else 0.0
        )
    if args.duration < 0:
        parser.error("--duration must be non-negative")
    if args.run_id is not None and not 0 <= args.run_id <= 0xFFFF:
        parser.error("--run-id must be in [0, 65535]")
    if args.payload_len is not None and not MIN_PAYLOAD_LEN <= args.payload_len <= MAX_PAYLOAD_LEN:
        parser.error("--payload-len must be in [10, 46]")
    if args.chip_source == "standard":
        args.chip_zmq = args.chip_zmq or STANDARD_ENDPOINT
        args.phase_endpoints = None
        if args.standard_keep_offset != "auto":
            args.standard_keep_offset = int(args.standard_keep_offset)
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
    if args.chip_source != "standard" or args.payload_len is None:
        args.standard_soft_retry = False
    if not args.standard_soft_retry:
        args.soft_zmq = None
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
        "standard_ambiguity",
        "standard_offset_rank",
        "decode_method",
        "soft_phase_offset",
        "soft_phase_bias",
        "soft_min_symbol_margin",
        "soft_alignment_mismatches",
        "prefix_symbol_errors",
        "preamble_distance",
        "frame_distance",
        "phase_candidate_offsets",
        "hard_frame_hex",
        "frame_hex",
    ]
    csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    csv_writer.writeheader()
    csv_file.flush()

    gr_block_obj = gr_block(enable_standard_soft=args.standard_soft_retry)
    gr_block_obj.set_zigbee_channel(args.channel)
    if args.freq_offset:
        gr_block_obj.set_freq_offset(args.freq_offset)
    if args.cfo_correction_hz:
        gr_block_obj.set_cfo_correction(args.cfo_correction_hz)
    if args.rf_gain is not None:
        gr_block_obj.set_rf_gain(args.rf_gain)
    else:
        args.rf_gain = gr_block_obj.get_rf_gain()
    if args.if_gain is not None:
        gr_block_obj.set_if_gain(args.if_gain)
    else:
        args.if_gain = gr_block_obj.get_if_gain()
    if args.bb_gain is not None:
        gr_block_obj.set_bb_gain(args.bb_gain)
    else:
        args.bb_gain = gr_block_obj.get_bb_gain()
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
        f"RX (BlueBee differential/standard DSSS): ch{args.channel} "
        f"{gr_block_obj.get_freq()/1e6:.1f} MHz "
        f"sr={gr_block_obj.get_sample_rate()/1e6:.1f} MHz "
        f"chip_source={args.chip_source} zmq={endpoint_label} "
        f"phase_offset={args.phase_keep_offset} "
        f"standard_offset={args.standard_keep_offset} "
        f"standard_policy={args.standard_offset_policy} "
        f"standard_ambiguity={args.standard_ambiguity} "
        f"soft_retry={'on' if args.standard_soft_retry else 'off'} "
        f"soft_zmq={args.soft_zmq or 'N/A'} "
        f"lo_offset={args.freq_offset:g} "
        f"cfo_correction={args.cfo_correction_hz:g} "
        f"rf_gain={args.rf_gain:g} if_gain={args.if_gain:g} "
        f"bb_gain={args.bb_gain:g}"
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
    soft_subscriber = (
        ZMQSubscriber(addr=args.soft_zmq)
        if args.standard_soft_retry
        else None
    )
    standard_offsets = (
        tuple(range(STANDARD_PHASE_COUNT))
        if args.chip_source == "standard"
        and args.standard_keep_offset == "auto"
        else (
            (args.standard_keep_offset,)
            if args.chip_source == "standard"
            else ()
        )
    )
    chip_buffers = (
        {offset: "" for offset in standard_offsets}
        if args.chip_source == "standard"
        else {offset: "" for offset in subscribers}
    )
    soft_buffers = {
        offset: bytearray() for offset in range(STANDARD_PHASE_COUNT)
    }
    zmq_msgs_by_offset = {offset: 0 for offset in subscribers}
    phase_candidate_stats = {
        offset: {"candidates": 0, "fcs_ok": 0, "fcs_failure": 0}
        for offset in subscribers
        if offset is not None
    }
    standard_ambiguity_stats = {
        ambiguity: {"candidates": 0, "fcs_ok": 0, "fcs_failure": 0}
        for ambiguity in STANDARD_AMBIGUITIES
    }
    standard_offset_stats = {
        offset: {"candidates": 0, "fcs_ok": 0, "fcs_failure": 0}
        for offset in standard_offsets
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
    standard_polarity_hint = None
    standard_scan_polarity = "normal"
    standard_stream_phase = 0
    soft_stream_phase = 0
    soft_zmq_messages = 0
    soft_samples = 0
    soft_buffer_truncations = 0
    hard_crc_failure = 0
    soft_retry_bursts = 0
    soft_candidate_attempts = 0
    soft_aligned_candidates = 0
    soft_alignment_misses = 0
    soft_decode_failures = 0
    soft_recovered = 0
    soft_retry_times_s = []
    soft_phase_delta = None
    processing_count = 0
    processing_sum_s = 0.0
    processing_max_s = 0.0
    processing_samples_s = []
    standard_best_offset_distances = []
    standard_second_offset_distances = []
    standard_no_candidate_min_distances = []
    standard_full_decode_attempts = 0
    standard_fcs_success_ranks = []
    standard_no_fcs_scans = 0
    buffer_critical_events = {offset: 0 for offset in chip_buffers}
    buffer_truncations = {offset: 0 for offset in chip_buffers}
    buffer_critical_threshold = int(MAX_CHIPS * 0.9)

    try:
        while True:
            processing_start = time.perf_counter()
            received_any = False
            # A decoded frame may leave more complete frames in the retained
            # buffer.  Drain those without adding one blocking poll per frame.
            poll_ms = 0 if pending_scan else (
                10 if len(subscribers) == 1 else 2
            )
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
                if args.chip_source == "standard":
                    chip_values = unpack_messages_to_chip_values(raw_messages)
                    streams, standard_stream_phase = (
                        deinterleave_standard_phase_values(
                            chip_values,
                            standard_stream_phase,
                            standard_offsets,
                        )
                    )
                    for sample_offset, chips in streams.items():
                        chip_buffers[sample_offset] += chips
                        if len(chip_buffers[sample_offset]) >= buffer_critical_threshold:
                            buffer_critical_events[sample_offset] += 1
                        if len(chip_buffers[sample_offset]) > MAX_CHIPS:
                            buffer_truncations[sample_offset] += 1
                            chip_buffers[sample_offset] = chip_buffers[
                                sample_offset
                            ][-MAX_CHIPS:]
                else:
                    chip_buffers[offset] += unpack_messages_to_chips(
                        raw_messages
                    )
                    if len(chip_buffers[offset]) >= buffer_critical_threshold:
                        buffer_critical_events[offset] += 1
                    if len(chip_buffers[offset]) > MAX_CHIPS:
                        buffer_truncations[offset] += 1
                        chip_buffers[offset] = chip_buffers[offset][-MAX_CHIPS:]

            if soft_subscriber is not None:
                soft_messages = soft_subscriber.read_available(
                    poll_timeout_ms=0
                )
                if soft_messages:
                    soft_zmq_messages += len(soft_messages)
                    packed_soft = b"".join(
                        message for message in soft_messages if message
                    )
                    soft_values = np.frombuffer(packed_soft, dtype=np.int8)
                    soft_samples += len(soft_values)
                    soft_streams, soft_stream_phase = (
                        deinterleave_standard_soft_values(
                            soft_values,
                            soft_stream_phase,
                        )
                    )
                    for sample_offset, values in soft_streams.items():
                        soft_buffers[sample_offset].extend(values)
                        excess = (
                            len(soft_buffers[sample_offset]) - SOFT_MAX_CHIPS
                        )
                        if excess > 0:
                            del soft_buffers[sample_offset][:excess]
                            soft_buffer_truncations += 1

            if received_any or pending_scan:
                candidates = {}
                predecoded_standard = {}
                if (
                    args.chip_source == "standard"
                    and args.payload_len is not None
                ):
                    ambiguity = (
                        standard_polarity_hint or standard_scan_polarity
                        if args.standard_ambiguity == "auto"
                        else args.standard_ambiguity
                    )
                    standard_scores = [
                        score_standard_offset(
                            chip_buffer,
                            args.payload_len,
                            ambiguity=ambiguity,
                            sample_offset=offset,
                        )
                        for offset, chip_buffer in chip_buffers.items()
                    ]
                    (
                        _,
                        decoded,
                        ranked_scores,
                        decode_attempts,
                    ) = decode_ranked_standard_offsets(
                        standard_scores,
                        args.payload_len,
                        max_offsets=(
                            2
                            if args.standard_offset_policy == "ranked2"
                            else None
                        ),
                    )
                    standard_full_decode_attempts += decode_attempts
                    successful = next(
                        (
                            candidate
                            for candidate in decoded
                            if validate_frame(candidate["frame"])[0]
                        ),
                        None,
                    )
                    if successful is not None:
                        standard_fcs_success_ranks.append(
                            successful["offset_rank"]
                        )
                    elif decoded:
                        standard_no_fcs_scans += 1
                    predecoded_standard = {
                        candidate["phase_offset"]: candidate
                        for candidate in decoded
                    }
                    if ranked_scores:
                        standard_best_offset_distances.append(
                            ranked_scores[0]["best_distance"]
                        )
                        if len(ranked_scores) > 1:
                            standard_second_offset_distances.append(
                                ranked_scores[1]["best_distance"]
                            )
                    else:
                        minimums = [
                            score["minimum_distance"]
                            for score in standard_scores
                            if score is not None
                        ]
                        if minimums:
                            standard_no_candidate_min_distances.append(
                                min(minimums)
                            )
                for offset, chip_buffer in chip_buffers.items():
                    if len(chip_buffer) < MIN_FRAME_CHIPS:
                        continue
                    if (
                        args.chip_source == "standard"
                        and args.payload_len is not None
                    ):
                        candidate = predecoded_standard.get(offset)
                    elif (
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
                    elif args.chip_source == "standard":
                        ambiguity = (
                            standard_polarity_hint or standard_scan_polarity
                            if args.standard_ambiguity == "auto"
                            else args.standard_ambiguity
                        )
                        candidate = find_frame_candidate(
                            transform_standard_chips(
                                chip_buffer,
                                ambiguity,
                            ),
                            "standard",
                            phase_offset=offset,
                        )
                        if candidate is not None:
                            candidate["standard_ambiguity"] = ambiguity
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
                        if args.chip_source == "standard":
                            ambiguity = candidate["standard_ambiguity"]
                            standard_ambiguity_stats[ambiguity][
                                "candidates"
                            ] += 1
                            if validate_frame(candidate["frame"])[0]:
                                standard_ambiguity_stats[ambiguity][
                                    "fcs_ok"
                                ] += 1
                            else:
                                standard_ambiguity_stats[ambiguity][
                                    "fcs_failure"
                                ] += 1
                            standard_offset_stats[offset]["candidates"] += 1
                            if validate_frame(candidate["frame"])[0]:
                                standard_offset_stats[offset]["fcs_ok"] += 1
                            else:
                                standard_offset_stats[offset][
                                    "fcs_failure"
                                ] += 1
                        if args.chip_source == "phase" and offset is not None:
                            phase_candidate_stats[offset]["candidates"] += 1
                            if validate_frame(candidate["frame"])[0]:
                                phase_candidate_stats[offset]["fcs_ok"] += 1
                            else:
                                phase_candidate_stats[offset][
                                    "fcs_failure"
                                ] += 1

                # Include ZMQ receive and packed-bit expansion so the timing
                # reflects the whole receiver iteration, not only correlation.
                scan_elapsed = time.perf_counter() - processing_start
                processing_count += 1
                processing_sum_s += scan_elapsed
                processing_max_s = max(processing_max_s, scan_elapsed)
                processing_samples_s.append(scan_elapsed)

                selected = (
                    choose_phase_candidate(candidates.values())
                    if args.chip_source == "phase"
                    else choose_standard_candidate(candidates.values())
                )
                if selected is not None:
                    hard_fcs_ok = validate_frame(selected["frame"])[0]
                    if args.chip_source == "standard" and not hard_fcs_ok:
                        hard_crc_failure += 1
                        if args.standard_soft_retry:
                            soft_retry_bursts += 1
                            soft_retry_start = time.perf_counter()
                            recovered, attempted, aligned, observed_delta = (
                                retry_standard_candidates_with_soft(
                                    candidates.values(),
                                    soft_buffers,
                                    args.payload_len,
                                    preferred_phase_delta=soft_phase_delta,
                                )
                            )
                            if observed_delta is not None:
                                soft_phase_delta = observed_delta
                            soft_retry_times_s.append(
                                time.perf_counter() - soft_retry_start
                            )
                            soft_candidate_attempts += attempted
                            soft_aligned_candidates += aligned
                            if aligned == 0:
                                soft_alignment_misses += 1
                            elif recovered is None:
                                soft_decode_failures += 1
                            if recovered is not None:
                                selected = recovered
                                soft_recovered += 1
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
                        elif args.chip_source == "standard":
                            standard_polarity_hint = selected.get(
                                "standard_ambiguity",
                                standard_scan_polarity,
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
                        "standard_ambiguity": selected.get(
                            "standard_ambiguity", ""
                        ),
                        "standard_offset_rank": selected.get(
                            "offset_rank", ""
                        ),
                        "decode_method": selected.get(
                            "decode_method", "hard"
                        ),
                        "soft_phase_offset": selected.get(
                            "soft_phase_offset", ""
                        ),
                        "soft_phase_bias": selected.get(
                            "soft_phase_bias", ""
                        ),
                        "soft_min_symbol_margin": selected.get(
                            "soft_min_symbol_margin", ""
                        ),
                        "soft_alignment_mismatches": selected.get(
                            "soft_alignment_mismatches", ""
                        ),
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
                        "hard_frame_hex": " ".join(
                            f"{byte:02X}"
                            for byte in selected.get("hard_frame", ())
                        ),
                        "frame_hex": " ".join(f"{byte:02X}" for byte in frame),
                    }
                    csv_writer.writerow(record)
                    csv_file.flush()

                    if args.verbose_packets or not fcs_ok or result not in ("unique",):
                        print(
                            f"packet chip={chip_pos} phase={record['phase_offset']} "
                            f"ambiguity={record['standard_ambiguity']} "
                            f"decode={record['decode_method']} "
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
                    consume_offsets = (
                        chip_buffers.keys()
                        if args.chip_source == "standard"
                        else candidates.keys()
                    )
                    for offset in consume_offsets:
                        candidate = candidates.get(offset)
                        frame_end_chip = (
                            candidate["chip_pos"]
                            + len(candidate["frame"]) * 2 * 32
                            if candidate is not None
                            else chip_pos + len(frame) * 2 * 32
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
            if (
                args.chip_source == "standard"
                and args.standard_ambiguity == "auto"
                and standard_polarity_hint is None
            ):
                standard_scan_polarity = (
                    "inverted"
                    if standard_scan_polarity == "normal"
                    else "normal"
                )

            now = time.time()
            if now - last_report >= STATS_PERIOD:
                diag_buffer = max(chip_buffers.values(), key=len, default="")
                ones, transitions = chip_stats(diag_buffer[-DIAG_SCAN_CHIPS:])
                print(
                    f"[elapsed:{now-start_epoch:.1f}s unique:{tracker.unique} "
                    f"duplicate:{tracker.duplicate} out_of_order:{tracker.out_of_order} "
                    f"crc_failure:{crc_failure} soft_recovered:{soft_recovered} "
                    f"payload_failure:{tracker.payload_failure} "
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
        if soft_subscriber is not None:
            soft_subscriber.close()
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
        args.standard_ambiguity_stats = (
            standard_ambiguity_stats
            if args.chip_source == "standard"
            else None
        )
        args.standard_offset_stats = (
            {
                str(offset): stats
                for offset, stats in standard_offset_stats.items()
            }
            if args.chip_source == "standard"
            else None
        )
        args.hard_crc_failure = hard_crc_failure
        soft_retry_timing = summarize_numeric_samples(
            soft_retry_times_s,
            1000.0,
        )
        args.standard_soft_retry_stats = (
            {
                "enabled": args.standard_soft_retry,
                "scope": "hard CRC failures only",
                "endpoint": args.soft_zmq,
                "format": "signed int8 quantized phase difference",
                "quantization_scale": STANDARD_SOFT_SCALE,
                "buffer_chips_per_offset": SOFT_MAX_CHIPS,
                "zmq_messages": soft_zmq_messages,
                "samples": soft_samples,
                "buffer_truncations": soft_buffer_truncations,
                "hard_failure_bursts_attempted": soft_retry_bursts,
                "candidate_attempts": soft_candidate_attempts,
                "aligned_candidates": soft_aligned_candidates,
                "alignment_miss_bursts": soft_alignment_misses,
                "aligned_but_not_recovered": soft_decode_failures,
                "recovered": soft_recovered,
                "phase_offset_delta": soft_phase_delta,
                "retry_timing_ms": soft_retry_timing,
            }
            if args.chip_source == "standard"
            else None
        )
        processing_distribution = summarize_numeric_samples(processing_samples_s, 1000.0)
        args.receiver_processing_timing = {
            "samples": processing_count,
            "avg_ms": (
                processing_sum_s * 1000.0 / processing_count
                if processing_count
                else 0.0
            ),
            "p50_ms": processing_distribution["p50"],
            "p95_ms": processing_distribution["p95"],
            "p99_ms": processing_distribution["p99"],
            "max_ms": processing_max_s * 1000.0,
            "buffer_chips": MAX_CHIPS,
            "includes_zmq_receive": True,
            "includes_soft_retry": False,
        }
        args.standard_offset_ranking = (
            {
                "strategy": (
                    "score all offsets; decode in rank order until FCS "
                    + (
                        "success"
                        if args.standard_offset_policy == "adaptive"
                        else "success or two offsets have been tried"
                    )
                ),
                "policy": args.standard_offset_policy,
                "scans": (
                    len(standard_best_offset_distances)
                    + len(standard_no_candidate_min_distances)
                ),
                "full_decode_attempts": standard_full_decode_attempts,
                "fcs_success_by_rank": {
                    str(rank): standard_fcs_success_ranks.count(rank)
                    for rank in sorted(set(standard_fcs_success_ranks))
                },
                "no_fcs_after_decode_scans": standard_no_fcs_scans,
                "best_offset_distance": summarize_numeric_samples(
                    standard_best_offset_distances
                ),
                "second_offset_distance": summarize_numeric_samples(
                    standard_second_offset_distances
                ),
                "no_candidate_min_preamble_distance": summarize_numeric_samples(
                    standard_no_candidate_min_distances
                ),
            }
            if args.chip_source == "standard"
            else None
        )
        args.buffer_critical = {
            "capacity_chips_per_offset": MAX_CHIPS,
            "critical_threshold_chips": buffer_critical_threshold,
            "critical_events": sum(buffer_critical_events.values()),
            "truncations": sum(buffer_truncations.values()),
            "by_offset": {
                str(offset): {
                    "critical_events": buffer_critical_events[offset],
                    "truncations": buffer_truncations[offset],
                }
                for offset in chip_buffers
            },
        }
        args.phase_scan_timing = (
            {
                **args.receiver_processing_timing,
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
