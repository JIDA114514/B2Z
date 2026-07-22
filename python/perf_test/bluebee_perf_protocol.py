#!/usr/bin/env python3
"""BlueBee Phase-1 payload validation and sequence accounting."""

from dataclasses import dataclass
import re
from typing import Optional


MAGIC = bytes((0xB2, 0x5A))
VERSION = 1
HEADER_LEN = 10
MIN_PAYLOAD_LEN = HEADER_LEN
MAX_PAYLOAD_LEN = 46
FILL_SEED = 0xB25A5A2D


def build_test_payload(payload_len, run_id, sequence):
    """Build exactly the payload emitted by bluebee_perf_build_payload()."""
    if not MIN_PAYLOAD_LEN <= payload_len <= MAX_PAYLOAD_LEN:
        raise ValueError("payload_len must be in [10, 46]")
    if not 0 <= run_id <= 0xFFFF:
        raise ValueError("run_id must be a 16-bit integer")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must be a 32-bit integer")

    payload = bytearray(payload_len)
    payload[0:2] = MAGIC
    payload[2] = VERSION
    payload[3] = HEADER_LEN
    payload[4:6] = run_id.to_bytes(2, "little")
    payload[6:10] = sequence.to_bytes(4, "little")

    state = (FILL_SEED ^ (run_id << 16) ^ sequence) & 0xFFFFFFFF
    for index in range(HEADER_LEN, payload_len):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        payload[index] = state >> 24
    return bytes(payload)


@dataclass(frozen=True)
class ParsedTestPayload:
    valid: bool
    reason: str
    run_id: Optional[int] = None
    sequence: Optional[int] = None
    payload_len: int = 0


def parse_test_payload(payload, expected_run_id=None, expected_payload_len=None):
    """Validate header, Run ID, length, and every deterministic fill byte."""
    payload = bytes(payload)
    if not MIN_PAYLOAD_LEN <= len(payload) <= MAX_PAYLOAD_LEN:
        return ParsedTestPayload(False, "length", payload_len=len(payload))
    if payload[0:2] != MAGIC:
        return ParsedTestPayload(False, "magic", payload_len=len(payload))
    if payload[2] != VERSION:
        return ParsedTestPayload(False, "version", payload_len=len(payload))
    if payload[3] != HEADER_LEN:
        return ParsedTestPayload(False, "header_len", payload_len=len(payload))

    run_id = int.from_bytes(payload[4:6], "little")
    sequence = int.from_bytes(payload[6:10], "little")
    if expected_run_id is not None and run_id != expected_run_id:
        return ParsedTestPayload(False, "run_id", run_id, sequence, len(payload))
    if expected_payload_len is not None and len(payload) != expected_payload_len:
        return ParsedTestPayload(False, "payload_len", run_id, sequence, len(payload))
    if payload != build_test_payload(len(payload), run_id, sequence):
        return ParsedTestPayload(False, "fill", run_id, sequence, len(payload))

    return ParsedTestPayload(True, "valid", run_id, sequence, len(payload))


class SequenceTracker:
    """Track valid packets for one Run ID without inferring board transmissions."""

    def __init__(self, expected_run_id=None, expected_payload_len=None):
        self.expected_run_id = expected_run_id
        self.expected_payload_len = expected_payload_len
        self.locked_run_id = expected_run_id
        self.sequences = set()
        self.duplicate = 0
        self.out_of_order = 0
        self.payload_failure = 0
        self.run_id_mismatch = 0
        self.max_arrival_sequence = None
        self.payload_lengths = set()

    @property
    def unique(self):
        return len(self.sequences)

    def observe(self, payload):
        parsed = parse_test_payload(payload, expected_payload_len=self.expected_payload_len)
        if not parsed.valid:
            self.payload_failure += 1
            return parsed, "invalid"

        if self.locked_run_id is None:
            self.locked_run_id = parsed.run_id
        if parsed.run_id != self.locked_run_id:
            self.run_id_mismatch += 1
            return ParsedTestPayload(
                False,
                "run_id",
                parsed.run_id,
                parsed.sequence,
                parsed.payload_len,
            ), "run_id_mismatch"

        self.payload_lengths.add(parsed.payload_len)
        if parsed.sequence in self.sequences:
            self.duplicate += 1
            return parsed, "duplicate"

        if (
            self.max_arrival_sequence is not None
            and parsed.sequence < self.max_arrival_sequence
        ):
            self.out_of_order += 1
            result = "out_of_order"
        else:
            result = "unique"
        self.sequences.add(parsed.sequence)
        if self.max_arrival_sequence is None or parsed.sequence > self.max_arrival_sequence:
            self.max_arrival_sequence = parsed.sequence
        return parsed, result

    def longest_loss_burst(self, scheduled=None):
        if scheduled is not None:
            if scheduled <= 0:
                return 0
            first, last = 0, scheduled - 1
        elif self.sequences:
            first, last = min(self.sequences), max(self.sequences)
        else:
            return 0

        longest = 0
        previous = first - 1
        for sequence in sorted(s for s in self.sequences if first <= s <= last):
            longest = max(longest, sequence - previous - 1)
            previous = sequence
        return max(longest, last - previous)

    def planned_range(self, expected_packets):
        """Summarize received sequences against a bounded planned run.

        Missing ranges are built from the sorted received set, so even a long
        run with a large absent tail does not allocate one entry per planned
        packet. Out-of-range values are retained explicitly because they are
        useful evidence of a stale transmitter run or an overlapping receive
        window.
        """
        if expected_packets is None:
            return None
        if expected_packets < 0:
            raise ValueError("expected_packets must be non-negative")

        in_range = sorted(
            sequence
            for sequence in self.sequences
            if 0 <= sequence < expected_packets
        )
        out_of_range = sorted(
            sequence
            for sequence in self.sequences
            if sequence < 0 or sequence >= expected_packets
        )
        missing_ranges = []
        next_expected = 0
        for sequence in in_range:
            if sequence > next_expected:
                missing_ranges.append(
                    {
                        "start": next_expected,
                        "end": sequence - 1,
                        "count": sequence - next_expected,
                    }
                )
            next_expected = sequence + 1
        if next_expected < expected_packets:
            missing_ranges.append(
                {
                    "start": next_expected,
                    "end": expected_packets - 1,
                    "count": expected_packets - next_expected,
                }
            )

        return {
            "expected_packets": expected_packets,
            "range_start": 0 if expected_packets else None,
            "range_end": expected_packets - 1 if expected_packets else None,
            "in_range_unique": len(in_range),
            "missing": expected_packets - len(in_range),
            "missing_ranges": missing_ranges,
            "out_of_range_count": len(out_of_range),
            "out_of_range_sequences": out_of_range,
        }


_KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
_INTEGER_KEYS = {
    "final",
    "payload_len",
    "interval_us",
    "duration_s",
    "run_id",
    "mode_id",
    "batch_size",
    "expected_packets",
    "elapsed_us",
    "scheduled",
    "generated",
    "tx_started",
    "tx_completed",
    "deadline_miss",
    "dma_timeout",
}


def parse_board_stats_text(text, expected_run_id=None):
    """Return the last matching final PERF_STATS line from a serial log."""
    match_stats = None
    for line in text.splitlines():
        if "PERF_STATS " not in line:
            continue
        values = dict(_KEY_VALUE_RE.findall(line))
        try:
            for key in _INTEGER_KEYS & values.keys():
                values[key] = int(values[key], 10)
        except ValueError:
            continue
        if values.get("final") != 1:
            continue
        if expected_run_id is not None and values.get("run_id") != expected_run_id:
            continue
        match_stats = values
    return match_stats


def ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator in (None, 0) else numerator / denominator,
    }
