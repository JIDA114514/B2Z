#!/usr/bin/env python3
# coding=utf-8
"""Shared utilities for ZigBee and BlueBee receivers.

Constants, ZMQ subscriber, chip-string helpers, symbol decoding,
preamble searching, CRC validation, and IQ file utilities.
"""

import os
import zmq
import numpy as np

# Ensure sibling imports work when this file is run directly.
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in __import__("sys").path:
    __import__("sys").path.insert(0, CUR_DIR)

from zigbee_mod import CHIP_MAP, PREAMBLE_BYTES, SFD, crc16_ccitt  # noqa: E402

# ── Protocol constants ────────────────────────────────────────────────────

PREAMBLE_CHIPS = CHIP_MAP[0]  # "11011001110000110101001000101110"
PREAMBLE_MAX_DIST = 12
MAX_PHR_LEN = 127
MIN_FRAME_BYTES = PREAMBLE_BYTES + 2   # 4 preamble + SFD + PHR = 6
MIN_FRAME_SYMBOLS = MIN_FRAME_BYTES * 2

# Pre-built lookup: byte value → 8-character chip string (LSB-first).
BYTE_TO_CHIPS = tuple(
    "".join("1" if (value >> bit) & 1 else "0" for bit in range(8))
    for value in range(256)
)


# ── ZMQ subscriber ───────────────────────────────────────────────────────

class ZMQSubscriber:
    """High-water-mark ZMQ SUB socket that drains available messages."""

    def __init__(self, addr="tcp://127.0.0.1:55556", hwm=20):
        ctx = zmq.Context()
        self.socket = ctx.socket(zmq.SUB)
        self.socket.setsockopt(zmq.RCVHWM, hwm)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
        self.socket.connect(addr)

    def read_available(self, max_messages=200):
        messages = []
        if self.socket.poll(10) == 0:
            return messages
        while len(messages) < max_messages:
            try:
                messages.append(self.socket.recv(zmq.NOBLOCK))
            except zmq.Again:
                break
        return messages

    def close(self):
        self.socket.close()


# ── Chip / symbol helpers ────────────────────────────────────────────────

def chips_to_int(chips):
    """32-chip string → integer (first char = MSB)."""
    value = 0
    for ch in chips:
        value = (value << 1) | (1 if ch == "1" else 0)
    return value


def unpack_bytes_to_chips(data):
    """Packed bytes (LSB-first) → chip string '0'/'1'."""
    return "".join(BYTE_TO_CHIPS[byte] for byte in data)


def chips_to_symbols(chips):
    """Decode a chip string to (symbol, hamming_distance) pairs using the
    *standard* 802.15.4 CHIP_MAP.  Chips are consumed in 32-chip windows."""
    symbols = []
    usable = (len(chips) // 32) * 32
    for i in range(0, usable, 32):
        chunk = chips[i : i + 32]
        best_s, best_d = 0, 33
        for s, ref in enumerate(CHIP_MAP):
            d = sum(1 for a, b in zip(chunk, ref) if a != b)
            if d < best_d:
                best_d, best_s = d, s
        symbols.append((best_s, best_d))
    return symbols


def symbols_to_bits(symbols):
    """List of (symbol, distance) → bit string (4 bits per symbol)."""
    return "".join(f"{s:04b}" for s, _ in symbols)


def bits_to_bytes_lsb(bit_str):
    """Bit string → list of bytes (LSB-first)."""
    data = []
    for i in range(0, len(bit_str) - len(bit_str) % 8, 8):
        v = 0
        for idx, ch in enumerate(bit_str[i : i + 8]):
            if ch == "1":
                v |= 1 << idx
        data.append(v)
    return data


def chip_stats(chips):
    """Return (fraction_of_ones, fraction_of_transitions)."""
    if not chips:
        return 0.0, 0.0
    ones = chips.count("1") / len(chips)
    transitions = 0.0
    if len(chips) > 1:
        transitions = sum(1 for a, b in zip(chips, chips[1:]) if a != b) / (len(chips) - 1)
    return ones, transitions


# ── Preamble / frame search ──────────────────────────────────────────────

def find_preamble(data):
    """Search *byte* list for 4×0x00 + SFD + valid PHR.  Returns (frame, pos)
    or (None, -1)."""
    preamble = [0x00] * PREAMBLE_BYTES
    for i in range(0, len(data) - MIN_FRAME_BYTES + 1):
        if data[i : i + PREAMBLE_BYTES] != preamble or data[i + PREAMBLE_BYTES] != SFD:
            continue
        phr_len = data[i + PREAMBLE_BYTES + 1]
        total_len = PREAMBLE_BYTES + 2 + phr_len
        if phr_len > MAX_PHR_LEN:
            continue
        if i + total_len <= len(data):
            return data[i : i + total_len], i
    return None, -1


def validate_frame(frame):
    """CRC-16 check on a ZigBee PHY frame.  Returns (fcs_ok, mac_payload_list)."""
    phr_len = frame[PREAMBLE_BYTES + 1]
    if phr_len < 2 or len(frame) < PREAMBLE_BYTES + 2 + phr_len:
        return False, []
    payload_len = phr_len - 2
    payload_start = PREAMBLE_BYTES + 2
    mac_payload = frame[payload_start : payload_start + payload_len]
    fcs_start = payload_start + payload_len
    fcs_rx = frame[fcs_start] | (frame[fcs_start + 1] << 8)
    fcs_calc = crc16_ccitt(mac_payload)
    return fcs_rx == fcs_calc, mac_payload


# ── IQ file helpers (for phase-diff diagnostics) ────────────────────────

def read_complex64_tail(path, max_samples):
    """Read up to *max_samples* complex64 from the tail of a raw file."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return np.array([], dtype=np.complex64)
    sample_size = np.dtype(np.complex64).itemsize
    usable = size - (size % sample_size)
    if usable <= 0:
        return np.array([], dtype=np.complex64)
    read_samples = min(max_samples, usable // sample_size)
    with open(path, "rb") as f:
        f.seek(usable - read_samples * sample_size)
        return np.fromfile(f, dtype=np.complex64, count=read_samples)


def phase_chips_from_iq(iq, sample_rate, chip_rate, phase_offset, polarity, max_chips):
    """Paper-style phase-difference slicing: sign(angle(s[n]·conj(s[n-1]))) → chips."""
    if len(iq) < 2:
        return ""
    phase = np.angle(iq[1:] * np.conj(iq[:-1]))
    samples_per_chip = sample_rate / chip_rate
    chip_count = min(max_chips, int((len(phase) - phase_offset) / samples_per_chip))
    if chip_count <= 0:
        return ""
    sample_idx = np.rint(phase_offset + np.arange(chip_count) * samples_per_chip).astype(np.int64)
    sample_idx = sample_idx[sample_idx < len(phase)]
    signs = phase[sample_idx] >= 0
    if polarity == "inverted":
        signs = np.logical_not(signs)
    return "".join("1" if bit else "0" for bit in signs)
