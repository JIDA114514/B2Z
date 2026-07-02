#!/usr/bin/env python3
# coding=utf-8

import argparse
import math
import sys

sys.path.append('../')

import ble_analyze


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

PATTERNBEE_ORP_TABLE = {
    2: {2: 4, 3: 12},
    4: {2: 5, 3: 13},
    6: {2: 6, 3: 14},
    8: {2: 7, 3: 15},
    10: {2: 0, 3: 8},
    12: {2: 1, 3: 9},
    14: {2: 2, 3: 10},
    15: {2: 3, 3: 11},
    16: {2: 3, 3: 11},
}


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
    return [
        math.sin(math.pi * (n + 0.5) / samples_per_chip)
        for n in range(samples_per_chip)
    ]


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
    for i_val, q_val in zip(i_chips, q_chips):
        chips.append("1" if i_val else "0")
        chips.append("1" if q_val else "0")
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


def symbols_to_bits_with_unknowns(symbols):
    out = []
    for s in symbols:
        if s is None:
            out.append("????")
        else:
            out.append(f"{s:04b}")
    return "".join(out)


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


def decode_ble(i_list, q_list, meta, args):
    sample_rate = args.ble_sample_rate
    if sample_rate is None and "sample_rate_hz" in meta:
        sample_rate = float(meta["sample_rate_hz"])
    sps = args.ble_sps
    if sps is None and "sps" in meta:
        sps = int(float(meta["sps"]))

    if sample_rate is None or sps is None:
        print("BLE decode: skipped (missing sample_rate or sps)")
        return

    channel = args.ble_channel
    if channel is None and "channel" in meta:
        channel = int(float(meta["channel"]))
    if channel is None:
        channel = 39

    pattern_bits = ble_analyze.build_access_pattern()
    best = None
    best_inverted = None
    best_variant = None
    best_score = (-1, -1)
    variants = []
    for append_last in (True, False):
        base_bits = ble_analyze.gfsk_demod_bits(
            i_list, q_list, sample_rate, sps, append_last=append_last
        )
        variants.append(("append_last", append_last, base_bits))
        if base_bits:
            variants.append(("drop_last", append_last, base_bits[:-1]))

    def score_result(decoded):
        status_order = {
            "ok": 4,
            "crc_mismatch": 3,
            "short_pdu": 2,
            "short_header": 1,
            "no_preamble": 0,
        }
        status = decoded.get("status")
        primary = status_order.get(status, 0)
        secondary = 0
        if status == "short_pdu":
            needed = decoded.get("needed_bytes", 0)
            got = decoded.get("got_bytes", 0)
            secondary = got - needed
        return (primary, secondary)

    for variant_name, append_last, base_bits in variants:
        for inverted in (False, True):
            test_bits = base_bits if not inverted else [1 - b for b in base_bits]
            decoded = ble_analyze.try_decode_with_pad(test_bits, channel, pattern_bits)
            if decoded.get("status") == "no_preamble":
                continue
            score = score_result(decoded)
            if score > best_score:
                best = decoded
                best_inverted = inverted
                best_variant = (variant_name, append_last)
                best_score = score

    if not best:
        print("BLE decode: no valid frame found")
        return

    header = best.get("header")
    payload = best.get("payload")
    print("BLE decode:")
    print(f"  status: {best.get('status')}")
    print(f"  start_bit: {best.get('start_bit')}")
    print(f"  bit_inverted: {best_inverted}")
    if best_variant:
        print(f"  bit_variant: {best_variant[0]} append_last={best_variant[1]}")
    if header is not None:
        print(f"  pdu_header: {bytes(header).hex()}")
        print(f"  pdu_len: {best.get('pdu_len')}")
    if payload is not None:
        payload_wt = best.get("payload_wt")
        if payload_wt is not None:
            print(f"  payload_wt: {bytes(payload_wt).hex()}")
        print(f"  payload: {bytes(payload).hex()}")
        ble_analyze.parse_adv_payload(payload, payload_wt)
    if best.get("status") == "crc_mismatch":
        print("  crc_mismatch")
        print(f"  crc: {bytes(best.get('crc', [])).hex()}")
        print(f"  calc_crc: {bytes(best.get('calc_crc', [])).hex()}")
    if best.get("status") == "ok_crc_lastbit":
        bit_idx = best.get("crc_lastbit_idx")
        print(f"  crc note: matches if CRC last byte bit {bit_idx} flipped")
        print(f"  crc_fixed: {bytes(best.get('fixed_crc', [])).hex()}")


def decode_zigbee(i_list, q_list, args):
    chips = despread(i_list, q_list, samples_per_chip=args.samples_per_chip)
    symbols = chips_to_symbols(chips) if chips else []
    bits_out = symbols_to_bits(symbols) if symbols else ""

    print("ZigBee decode:")
    print(f"  samples: {len(i_list)}")
    print(f"  chips: {len(chips)}")
    print(f"  symbols: {len(symbols)}")
    print(f"  bits: {len(bits_out)}")
    print(f"  bits_prefix: {bits_out[:128]}")

    frame_info = find_frame_bytes(bits_out)
    if frame_info:
        phy = parse_phy_frame(frame_info["frame"])
        payload_bits = bytes_to_bits(phy["payload"], bit_order=BIT_ORDER)
        print("  phy_frame:")
        print(f"    start_byte: {frame_info['start']}")
        print(f"    length: {phy['length']}")
        print(f"    fcs_ok: {phy['fcs_ok']}")
        print(f"    payload_bits_len: {len(payload_bits)}")
    else:
        print("  phy_frame: not found")
    
    return symbols


def quadrant_index(i_val, q_val):
    if i_val >= 0 and q_val >= 0:
        return 0
    if i_val < 0 and q_val >= 0:
        return 1
    if i_val < 0 and q_val < 0:
        return 2
    return 3


def patternbee_decode(i_list, q_list, args, zigbee_symbols=None):
    if len(i_list) < 17 or len(q_list) < 17:
        print("PatternBee decode: insufficient samples")
        return

    step = args.patternbee_step
    if step is None:
        chip_period = max(1, args.samples_per_chip // 2)
        chip_count = len(i_list) // chip_period
        symbol_count = chip_count // 32
        if symbol_count > 0:
            step = len(i_list) // (symbol_count * 16)
        else:
            step = chip_period

    print(f"PatternBee params: samples={len(i_list)} step={step} samples_per_chip={args.samples_per_chip}")

    if len(i_list) < step * 16:
        print("PatternBee decode: insufficient samples for one symbol")
        return

    best = None
    best_offset = 0
    best_threshold = args.patternbee_threshold
    best_diag = None
    best_diag_detail = None
    thresholds = [args.patternbee_threshold]
    if args.patternbee_scan_threshold:
        thresholds = [0.5, 1.0, 1.5]

    for threshold in thresholds:
        for offset in range(step):
            usable_symbols = (len(i_list) - offset) // (step * 16)
            if usable_symbols <= 0:
                continue

            symbols = []
            diag = []
            diag_detail = []
            for sym_idx in range(usable_symbols):
                base = offset + sym_idx * step * 16
                if base + 16 * step >= len(i_list):
                    break

                C = [None] * 18
                DF = [0.0] * 17
                for piece_idx in range(1, 18):
                    idx = base + (piece_idx - 1) * step
                    C[piece_idx] = (i_list[idx], q_list[idx])

                for piece_idx in range(1, 17):
                    i_prev, q_prev = C[piece_idx]
                    i_curr, q_curr = C[piece_idx + 1]
                    phase_prev = math.atan2(q_prev, i_prev)
                    phase_curr = math.atan2(q_curr, i_curr)
                    delta = phase_curr - phase_prev
                    delta = (delta + math.pi) % (2.0 * math.pi) - math.pi
                    DF[piece_idx] = delta

                mapped = None
                chosen_k = None
                chosen_q = None
                chosen_dphi = None
                dt_sign = args.patternbee_dt_sign
                if dt_sign is None:
                    dt_sign = 1 if sum(DF) > 0 else -1
                x_idx = 15 if dt_sign > 0 else 16
                candidate_indices = list(range(2, 15, 2)) + [x_idx]
                debug_candidates = []
                for k in candidate_indices:
                    dphi = DF[k]
                    i_val, q_val = C[k]
                    q = quadrant_index(i_val, q_val) + 1
                    in_range = abs(dphi) < threshold
                    in_quad = q in (2, 3)
                    debug_candidates.append(f"k{k}:dphi={dphi:.3f},q={q},ok={in_range and in_quad}")
                    if in_range and in_quad:
                        mapped = PATTERNBEE_ORP_TABLE.get(k, {}).get(q)
                        if mapped is None:
                            continue
                        chosen_k = k
                        chosen_q = q
                        chosen_dphi = dphi
                        break

                symbols.append(mapped)
                diag.append((mapped, chosen_k, chosen_q, chosen_dphi, debug_candidates, [quadrant_index(*C[k]) for k in range(1, 17)]))
                diag_detail.append(DF)

            hit_count = sum(1 for s in symbols if s is not None)
            if zigbee_symbols is not None:
                min_len = min(len(symbols), len(zigbee_symbols))
                match_count = sum(1 for i in range(min_len) if i < len(symbols) and symbols[i] == zigbee_symbols[i])
                score = (match_count, hit_count, len(symbols))
            else:
                score = (hit_count, 0, len(symbols))
            if best is None or score > best[0]:
                best = (score, symbols)
                best_offset = offset
                best_threshold = threshold
                best_diag = diag
                best_diag_detail = diag_detail

    if not best:
        print("PatternBee decode: no symbols mapped")
        return

    symbols = best[1]
    symbols_hex = "".join("?" if s is None else f"{s:X}" for s in symbols)
    symbols_bits = symbols_to_bits_with_unknowns(symbols)
    print("PatternBee decode:")
    print(f"  symbols: {len(symbols)}")
    if zigbee_symbols is not None:
        min_len = min(len(symbols), len(zigbee_symbols))
        match_count = sum(1 for i in range(min_len) if i < len(symbols) and symbols[i] == zigbee_symbols[i])
        print(f"  match_with_zigbee: {match_count}/{min_len}")
        if args.patternbee_debug:
            print("  symbol_comparison:")
            for i in range(min_len):
                p_sym = symbols[i] if i < len(symbols) else None
                z_sym = zigbee_symbols[i]
                p_str = "?" if p_sym is None else f"{p_sym:X}"
                z_str = f"{z_sym:X}"
                match = "✓" if p_sym == z_sym else "✗"
                print(f"    [{i:2d}] pattern={p_str} zigbee={z_str} {match}")
    print(f"  hit_symbols: {best[0][1] if isinstance(best[0], tuple) else best[0]}")
    print(f"  best_offset: {best_offset}")
    print(f"  best_threshold: {best_threshold}")
    print(f"  symbols_hex: {symbols_hex}")
    print(f"  symbols_bits: {symbols_bits}")
    if args.patternbee_debug and best_diag is not None:
        print("  debug_k_q_dphi:")
        for idx, info in enumerate(best_diag):
            mapped, k, q, dphi, candidates, all_quads = info
            mapped_str = "?" if mapped is None else f"{mapped:X}"
            print(f"    sym[{idx}]: {mapped_str} k={k} q={q} dphi={dphi}")
            if idx < 3:
                print(f"      all_quads: {all_quads}")
                print(f"      candidates: {', '.join(candidates)}")
                if best_diag_detail is not None:
                    print(f"      all_DF: {[f'{d:.3f}' for d in best_diag_detail[idx][1:17]]}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze IQ and attempt BLE + ZigBee decode"
    )
    parser.add_argument(
        "input_iq",
        nargs="?",
        default="../std_zigbee/zigbee_iq.txt",
        help="input IQ txt file",
    )
    parser.add_argument(
        "--ble-sample-rate",
        type=float,
        default=None,
        help="BLE sample rate in Hz (overrides file meta)",
    )
    parser.add_argument(
        "--ble-sps",
        type=int,
        default=None,
        help="BLE samples per symbol (overrides file meta)",
    )
    parser.add_argument(
        "--ble-channel",
        type=int,
        default=None,
        help="BLE advertising channel (overrides file meta)",
    )
    parser.add_argument(
        "--samples-per-chip",
        type=int,
        default=8,
        help="ZigBee samples per chip (OQPSK)",
    )
    parser.add_argument(
        "--patternbee",
        action="store_true",
        default=True,
        help="enable PatternBee decode on BLE demodulated IQ",
    )
    parser.add_argument(
        "--patternbee-step",
        type=int,
        default=None,
        help="step between ORP samples (defaults to chunk or samples_per_chip)",
    )
    parser.add_argument(
        "--patternbee-window",
        type=int,
        default=None,
        help="averaging window per ORP sample",
    )
    parser.add_argument(
        "--patternbee-threshold",
        type=float,
        default=1.0,
        help="dphi threshold (radians) for PatternBee mapping",
    )
    parser.add_argument(
        "--patternbee-dt-sign",
        type=int,
        choices=[-1, 1],
        default=None,
        help="Dt sign for PatternBee (1 for >0, -1 for <0)",
    )
    parser.add_argument(
        "--patternbee-scan-threshold",
        action="store_true",
        default=True,
        help="scan dphi thresholds 0.5/1.0/1.5 rad for PatternBee",
    )
    parser.add_argument(
        "--patternbee-debug",
        action="store_true",
        help="print PatternBee k/q/dphi diagnostics",
    )
    args = parser.parse_args()

    i_list, q_list, meta = read_iq(args.input_iq)
    decode_ble(i_list, q_list, meta, args)
    zigbee_symbols = decode_zigbee(i_list, q_list, args)
    if args.patternbee:
        patternbee_decode(i_list, q_list, args, zigbee_symbols)


if __name__ == "__main__":
    main()
