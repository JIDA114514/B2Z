#!/usr/bin/env python3
# coding=utf-8

import argparse
import math
import matplotlib.pyplot as plt


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


def parse_meta_line(line):
    if not line.startswith("#"):
        return None, None
    content = line[1:].strip()
    if ":" not in content:
        return None, None
    key, value = content.split(":", 1)
    return key.strip(), value.strip()


def read_iq(path):
    i_list = []
    q_list = []
    meta = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                key, value = parse_meta_line(line)
                if key:
                    meta[key] = value
                continue
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            i_list.append(float(parts[0]))
            q_list.append(float(parts[1]))
    if not i_list:
        raise ValueError(f"no samples in {path}")
    return i_list, q_list, meta


def half_sine_pulse(samples_per_chip):
    return [math.sin(math.pi * (n + 0.5) / samples_per_chip) for n in range(samples_per_chip)]


def despread(i_list, q_list, samples_per_chip=8):
    pulse = half_sine_pulse(samples_per_chip)
    delay = samples_per_chip // 2
    if len(q_list) > delay:
        q_aligned = q_list[delay:]
    else:
        q_aligned = []
    if len(q_aligned) < len(i_list):
        q_aligned.extend([0.0] * (len(i_list) - len(q_aligned)))

    chip_count = len(i_list) // samples_per_chip
    i_chips = []
    q_chips = []
    for k in range(chip_count):
        s = k * samples_per_chip
        e = s + samples_per_chip
        i_val = sum(i_list[s:e][n] * pulse[n] for n in range(samples_per_chip))
        q_val = sum(q_aligned[s:e][n] * pulse[n] for n in range(samples_per_chip))
        i_chips.append(1 if i_val >= 0 else 0)
        q_chips.append(1 if q_val >= 0 else 0)

    chips = []
    for i, q in zip(i_chips, q_chips):
        chips.append(str(i))
        chips.append(str(q))
    return "".join(chips)


def ble_gfsk_to_bits(i_list, q_list, sample_rate, sps):
    phases = []
    for i_val, q_val in zip(i_list, q_list):
        phases.append(math.atan2(q_val, i_val))

    two_pi = 2.0 * math.pi
    dphi = []
    for idx in range(1, len(phases)):
        delta = phases[idx] - phases[idx - 1]
        delta = (delta + math.pi) % (2.0 * math.pi) - math.pi
        dphi.append(delta)
    if dphi:
        dphi.append(dphi[-1])

    freq_inst = [d * sample_rate / two_pi for d in dphi]
    if sps <= 0:
        raise ValueError("ble sps must be positive")

    bit_count = len(freq_inst) // sps
    bits = []
    for k in range(bit_count):
        s = k * sps
        e = s + sps
        avg = sum(freq_inst[s:e]) / sps
        bits.append(1 if avg >= 0 else 0)
    return bits


def ble_bits_to_chips(bits):
    chips = []
    for b in bits:
        if b == 1:
            chips.append("11")
        else:
            chips.append("00")
    return "".join(chips)


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


def plot_iq(i_list, q_list, samples=2000):
    n = min(samples, len(i_list))
    t = list(range(n))
    plt.figure(figsize=(10, 5))
    plt.plot(t, i_list[:n], label="I")
    plt.plot(t, q_list[:n], label="Q")
    plt.title("ZigBee IQ (time domain)")
    plt.xlabel("Sample")
    plt.ylabel("Amplitude")
    plt.legend()


def plot_constellation(i_list, q_list, samples_per_chip=8, samples=2000):
    delay = samples_per_chip // 2
    if len(q_list) > delay:
        q_aligned = q_list[delay:]
    else:
        q_aligned = []
    if len(q_aligned) < len(i_list):
        q_aligned.extend([0.0] * (len(i_list) - len(q_aligned)))
    n = min(samples, len(i_list))
    plt.figure(figsize=(5, 5))
    plt.scatter(i_list[:n], q_aligned[:n], s=4, alpha=0.6)
    plt.title("ZigBee IQ (constellation)")
    plt.xlabel("I")
    plt.ylabel("Q")
    plt.axis("equal")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze ZigBee IQ and attempt DSSS decode"
    )
    parser.add_argument(
        "input_iq",
        nargs="?",
        default="zigbee_iq.txt",
        help="input IQ txt file",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "oqpsk", "ble"],
        default="auto",
        help="analysis mode",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=None,
        help="IQ sample rate in Hz (overrides file meta)",
    )
    parser.add_argument(
        "--samples-per-chip",
        type=int,
        default=8,
        help="samples per ZigBee chip (OQPSK mode)",
    )
    parser.add_argument(
        "--ble-sps",
        type=int,
        default=None,
        help="BLE samples per bit (overrides file meta)",
    )
    parser.add_argument(
        "--chips-out",
        default="zigbee_chips_out.txt",
        help="output file for recovered chip sequence",
    )
    args = parser.parse_args()

    i_list, q_list, meta = read_iq(args.input_iq)
    plot_iq(i_list, q_list)

    mode = args.mode
    if mode == "auto":
        modulation = meta.get("modulation", "").lower()
        if modulation == "gfsk":
            mode = "ble"
        else:
            mode = "oqpsk"

    if mode == "ble":
        sample_rate = args.sample_rate
        if sample_rate is None and "sample_rate_hz" in meta:
            sample_rate = float(meta["sample_rate_hz"])
        if sample_rate is None:
            raise ValueError("sample_rate is required for BLE mode")

        ble_sps = args.ble_sps
        if ble_sps is None and "sps" in meta:
            ble_sps = int(float(meta["sps"]))
        if ble_sps is None:
            raise ValueError("ble_sps is required for BLE mode")

        bits = ble_gfsk_to_bits(i_list, q_list, sample_rate, ble_sps)
        chips = ble_bits_to_chips(bits)
        plot_constellation(i_list, q_list, samples_per_chip=max(1, args.samples_per_chip))
    else:
        plot_constellation(i_list, q_list, samples_per_chip=args.samples_per_chip)
        chips = despread(i_list, q_list, samples_per_chip=args.samples_per_chip)

    symbols = chips_to_symbols(chips) if chips else []
    bits_out = symbols_to_bits(symbols) if symbols else ""
    with open(args.chips_out, "w", encoding="utf-8") as f:
        f.write(chips)

    print(f"samples: {len(i_list)}")
    print(f"chips: {len(chips)}")
    print("chip sequence:")
    print(chips)
    print(f"symbols: {len(symbols)}")
    print(f"bits: {len(bits_out)}")
    print("decoded bits (first 128):")
    print(bits_out[:128])

    frame_info = find_frame_bytes(bits_out)
    if frame_info:
        phy = parse_phy_frame(frame_info["frame"])
        payload_bits = bytes_to_bits(phy["payload"], bit_order=BIT_ORDER)
        print("zigbee phy frame:")
        print(f"  start_byte: {frame_info['start']}")
        print(f"  length: {phy['length']}")
        print(f"  fcs_ok: {phy['fcs_ok']}")
        print(f"  payload_bits_len: {len(payload_bits)}")
    else:
        print("zigbee phy frame: not found")

    plt.show()


if __name__ == "__main__":
    main()
