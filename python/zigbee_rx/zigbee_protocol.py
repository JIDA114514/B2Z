"""IEEE 802.15.4 2.4 GHz PHY framing, standard DSSS and project compatibility.

The canonical chip strings are identical to ctc_sim/std_zigbee/zigbee_mod.py.
No emulated BlueBee chip map is used by this receiver.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import numpy as np

CHIP_MAP = (
    "11011001110000110101001000101110", "11101101100111000011010100100010",
    "00101110110110011100001101010010", "00100010111011011001110000110101",
    "01010010001011101101100111000011", "00110101001000101110110110011100",
    "11000011010100100010111011011001", "10011100001101010010001011101101",
    "10001100100101100000011101111011", "10111000110010010110000001110111",
    "01111011100011001001011000000111", "01110111101110001100100101100000",
    "00000111011110111000110010010110", "01100000011101111011100011001001",
    "10010110000001110111101110001100", "11001001011000000111011110111000",
)
REFERENCES = np.array([[1 if bit == "1" else -1 for bit in word] for word in CHIP_MAP], np.float32)
# O-QPSK half-sine is MSK-equivalent: p[n]=(-1)^(n+1)*c[n]*c[n-1].
# Ignore first differential chip, which depends on the preceding symbol.
MSK_REFERENCES = REFERENCES.copy()
MSK_REFERENCES[:, 0] = 0
for index in range(1, 32):
    MSK_REFERENCES[:, index] = ((-1) ** (index + 1)) * REFERENCES[:, index] * REFERENCES[:, index - 1]
REFERENCE_PROFILES = {"phase": REFERENCES, "oqpsk": MSK_REFERENCES}
REVERSE4 = np.array([int(f"{i:04b}"[::-1], 2) for i in range(16)], np.uint8)


def channel_frequency(channel: int) -> int:
    if not 11 <= channel <= 26:
        raise ValueError("IEEE 802.15.4 channel must be in 11..26")
    return (2405 + 5 * (channel - 11)) * 1000000


def fcs16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc


def symbols_to_bytes(symbols, order: str) -> bytes:
    symbols = np.asarray(symbols, dtype=np.uint8)
    if len(symbols) % 2:
        raise ValueError("whole bytes require an even symbol count")
    if order == "project":
        symbols = REVERSE4[symbols]
    elif order != "ieee":
        raise ValueError("unknown symbol order")
    return (symbols[::2] | (symbols[1::2] << 4)).tobytes()


def frame_payload(frame: bytes) -> bytes:
    if len(frame) < 8 or frame[:5] != bytes.fromhex("00000000a7"):
        raise ValueError("invalid preamble/SFD")
    length = frame[5]
    if not 2 <= length <= 127 or len(frame) != 6 + length:
        raise ValueError("invalid PHR or frame length")
    payload = frame[6:-2]
    if int.from_bytes(frame[-2:], "little") != fcs16(payload):
        raise ValueError("FCS mismatch")
    return payload


# The shared measurement helper has no radio/DSP/BLE dependencies. Use a unique
# module name to avoid collision with historical receiver modules on sys.path.
_path = Path(__file__).resolve().parents[1] / "perf_test" / "bluebee_perf_protocol.py"
_key = "_b2z_measurement_protocol_v1"
if _key not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_key, _path)
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_key] = _module
    _spec.loader.exec_module(_module)
_measurement = sys.modules[_key]
SequenceTracker = _measurement.SequenceTracker
parse_test_payload = _measurement.parse_test_payload
parse_board_stats_text = _measurement.parse_board_stats_text
ratio = _measurement.ratio
