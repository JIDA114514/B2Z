#!/usr/bin/env python3
# coding=utf-8

import math
import sys

sys.path.append('../')

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


def read_bits(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    bits = [ch for ch in raw if ch in ("0", "1")]
    if not bits:
        raise ValueError("no bits found in data_bit.txt")
    return "".join(bits)


def bits_to_chips(bit_str):
    if len(bit_str) % 4 != 0:
        pad = 4 - (len(bit_str) % 4)
        bit_str = bit_str + ("0" * pad)
    chips = []
    for i in range(0, len(bit_str), 4):
        nibble = bit_str[i : i + 4]
        symbol = int(nibble, 2)
        chips.append(CHIP_MAP[symbol])
    return "".join(chips)


def bits_to_bytes(bit_str, bit_order=BIT_ORDER):
    if len(bit_str) % 8 != 0:
        pad = 8 - (len(bit_str) % 8)
        bit_str = bit_str + ("0" * pad)
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


def bytes_to_bits(data, bit_order=BIT_ORDER):
    bits = []
    for value in data:
        if bit_order == "lsb":
            for idx in range(8):
                bits.append("1" if (value >> idx) & 1 else "0")
        else:
            for idx in range(7, -1, -1):
                bits.append("1" if (value >> idx) & 1 else "0")
    return "".join(bits)


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


def build_phy_frame(payload_bits):
    payload_bytes = bits_to_bytes(payload_bits, bit_order=BIT_ORDER)
    mac_len = len(payload_bytes) + 2
    if mac_len > 127:
        raise ValueError("MAC frame too long for 802.15.4 length")
    fcs = crc16_ccitt(payload_bytes)
    fcs_bytes = [fcs & 0xFF, (fcs >> 8) & 0xFF]
    frame = [0x00] * PREAMBLE_BYTES + [SFD, mac_len] + payload_bytes + fcs_bytes
    return bytes_to_bits(frame, bit_order=BIT_ORDER)


def half_sine_pulse(samples_per_chip):
    return [math.sin(math.pi * (n + 0.5) / samples_per_chip) for n in range(samples_per_chip)]


def oqpsk_modulate(chip_bits, samples_per_chip=8):
    chips = [1.0 if b == "1" else -1.0 for b in chip_bits]
    i_chips = chips[0::2]
    q_chips = chips[1::2]

    pulse = half_sine_pulse(samples_per_chip)
    i_wave = []
    q_wave = []
    for c in i_chips:
        i_wave.extend([c * p for p in pulse])
    for c in q_chips:
        q_wave.extend([c * p for p in pulse])

    delay = samples_per_chip // 2
    q_wave = ([0.0] * delay) + q_wave

    length = max(len(i_wave), len(q_wave))
    if len(i_wave) < length:
        i_wave.extend([0.0] * (length - len(i_wave)))
    if len(q_wave) < length:
        q_wave.extend([0.0] * (length - len(q_wave)))

    return i_wave, q_wave


def write_iq(path, i_wave, q_wave):
    with open(path, "w", encoding="utf-8") as f:
        for i, q in zip(i_wave, q_wave):
            f.write(f"{i:.6f} {q:.6f}\n")


def main():
    bit_str = read_bits("../data_bits.txt")
    frame_bits = build_phy_frame(bit_str)
    chip_bits = bits_to_chips(frame_bits)
    i_wave, q_wave = oqpsk_modulate(chip_bits, samples_per_chip=8)
    write_iq("zigbee_iq.txt", i_wave, q_wave)
    print(f"input bits: {len(bit_str)}")
    print(f"frame bits: {len(frame_bits)}")
    print(f"chips: {len(chip_bits)}")
    print(f"samples: {len(i_wave)}")


if __name__ == "__main__":
    main()
