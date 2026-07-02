#!/usr/bin/env python3
# coding=utf-8

import sys

CHIP_MAP = [
    "11011001110000110101001000101110",  # 0x0
    "11101101100111000011010100100010",  # 0x1
    "00101110110110011100001101010010",  # 0x2
    "00100010111011011001110000110101",  # 0x3
    "01010010001011101101100111000011",  # 0x4
    "00110101001000101110110110011100",  # 0x5
    "11000011010100100010111011011001",  # 0x6
    "10011100001101010010001011101101",  # 0x7
    "10001100100101100000011101111011",  # 0x8
    "10111000110010010110000001110111",  # 0x9
    "01111011100011001001011000000111",  # 0xA
    "01110111101110001100100101100000",  # 0xB
    "00000111011110111000110010010110",  # 0xC
    "01100000011101111011100011001001",  # 0xD
    "10010110000001110111101110001100",  # 0xE
    "11001001011000000111011110111000",  # 0xF
]

PREAMBLE_BYTES = 4
SFD = 0xA7
BIT_ORDER = "lsb"


def crc16_ccitt(data, init=0x0000):
    crc = init
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


def chips_to_symbols(chips):
    symbols = []
    usable = (len(chips) // 32) * 32
    for i in range(0, usable, 32):
        chunk = chips[i : i + 32]
        best_symbol = 0
        best_dist = 33
        for s, ref in enumerate(CHIP_MAP):
            dist = sum(1 for a, b in zip(chunk, ref) if a != b)
            if dist < best_dist:
                best_dist = dist
                best_symbol = s
        symbols.append(best_symbol)
    return symbols


def symbols_to_bits(symbols):
    return "".join(f"{s:04b}" for s in symbols)


def bits_to_bytes(bit_str, bit_order=BIT_ORDER):
    if len(bit_str) % 8 != 0:
        bit_str = bit_str[: len(bit_str) - (len(bit_str) % 8)]
    data = []
    for i in range(0, len(bit_str), 8):
        chunk = bit_str[i : i + 8]
        value = 0
        if bit_order == "lsb":
            for idx, ch in enumerate(chunk):
                if ch == "1":
                    value |= 1 << idx
        else:
            for ch in chunk:
                value = (value << 1) | (1 if ch == "1" else 0)
        data.append(value)
    return data


def find_frame_bytes(bit_str):
    data = bits_to_bytes(bit_str, bit_order=BIT_ORDER)
    if len(data) < PREAMBLE_BYTES + 2:
        return None
    preamble = [0x00] * PREAMBLE_BYTES
    for i in range(0, len(data) - (PREAMBLE_BYTES + 2) + 1):
        if data[i : i + PREAMBLE_BYTES] != preamble:
            continue
        if data[i + PREAMBLE_BYTES] != SFD:
            continue
        length = data[i + PREAMBLE_BYTES + 1]
        total = PREAMBLE_BYTES + 2 + length
        end = i + total
        if end <= len(data):
            frame = data[i:end]
            return {
                "start": i,
                "length": length,
                "frame": frame,
            }
    return None


def parse_phy_frame(frame_bytes):
    if len(frame_bytes) < PREAMBLE_BYTES + 2:
        raise ValueError("frame too short for PHY header")
    length = frame_bytes[PREAMBLE_BYTES + 1]
    expected = PREAMBLE_BYTES + 2 + length
    if len(frame_bytes) < expected:
        raise ValueError("incomplete frame")
    payload = frame_bytes[PREAMBLE_BYTES + 2 : PREAMBLE_BYTES + 2 + length]
    if len(payload) < 2:
        raise ValueError("MAC payload too short for FCS")
    mac_payload = payload[:-2]
    fcs_rx = payload[-2] | (payload[-1] << 8)
    fcs_calc = crc16_ccitt(mac_payload)
    return {
        "length": length,
        "payload": mac_payload,
        "fcs_rx": fcs_rx,
        "fcs_calc": fcs_calc,
        "fcs_ok": fcs_rx == fcs_calc,
    }


class FRAME:

    MAX_DATA_BUF_CHIPS = 300 * 32

    def __init__(self, fun_analysis):
        self.chip_buf = ""
        self.fun_analysis = fun_analysis

    def insert_chips(self, chips):
        self.chip_buf += chips
        if len(self.chip_buf) > self.MAX_DATA_BUF_CHIPS:
            self.chip_buf = self.chip_buf[-self.MAX_DATA_BUF_CHIPS:]

    def run(self):
        if len(self.chip_buf) < 32 * (PREAMBLE_BYTES + 2):
            return

        # Try 32 alignments to find correct DSSS symbol boundary
        for align in range(32):
            if align > 0:
                aligned = self.chip_buf[align:]
            else:
                aligned = self.chip_buf

            if len(aligned) < 32 * (PREAMBLE_BYTES + 2):
                return

            symbols = chips_to_symbols(aligned)
            if not symbols:
                continue

            bits_out = symbols_to_bits(symbols)
            frame_info = find_frame_bytes(bits_out)

            if frame_info:
                try:
                    phy = parse_phy_frame(frame_info["frame"])
                    if phy["fcs_ok"]:
                        self.fun_analysis(phy, frame_info["frame"])
                except ValueError:
                    pass

                end_byte = frame_info["start"] + PREAMBLE_BYTES + 2 + frame_info["length"]
                end_chip = end_byte * 32 + align
                self.chip_buf = self.chip_buf[end_chip:]
                return

        # No frame found: shift by 1 chip to slide alignment
        if len(self.chip_buf) > 1:
            self.chip_buf = self.chip_buf[1:]
