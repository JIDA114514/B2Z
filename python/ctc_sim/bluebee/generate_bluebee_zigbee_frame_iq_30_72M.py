#!/usr/bin/env python3
# coding=utf-8
"""
Generate a complete Zigbee PHY frame IQ waveform using BlueBee PHY emulation.

Reference: BlueBee paper (SenSys'17), Sections 4.3–4.5.

Core idea (Section 4.3, Fig.5):
  BLE GFSK has 1 MHz bandwidth (half of ZigBee's 2 MHz). Each BLE symbol
  (1 µs, phase shift ±π/2) is sampled by the ZigBee receiver at 2 MHz
  (every 0.5 µs), producing two consecutive phase shifts of ±π/4 each.
  Sign detection yields two identical chips: "11" (BLE bit 1) or "00" (BLE bit 0).

Optimal DSSS Emulation (Section 4.4):
  Each ZigBee symbol (32 chips) is divided into 16 consecutive 2-chip pairs.
  Pairs "01" or "10" (inconsistent phase) cannot be emulated and produce
  1 chip error regardless of mapping choice. BlueBee selects the mapping
  that maximizes the minimum inter-symbol Hamming distance (Eq.1),
  enabling error correction by ZigBee's DSSS decoder (tolerance ≤12 chips).

Modulation chain:
  Zigbee frame bytes → bits (LSB) → 4-bit symbols → BlueBee pair-constrained
  chips → GFSK bits (1 per pair) → BLE GFSK modulation → 30.72 MSPS IQ
"""

import argparse
import os
import sys

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STD_ZIGBEE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "std_zigbee"))
sys.path.insert(0, STD_ZIGBEE_DIR)

from zigbee_mod import BIT_ORDER, CHIP_MAP, PREAMBLE_BYTES, SFD, bytes_to_bits, crc16_ccitt

OUTPUT_SAMPLE_RATE = 30.72e6

# ── BlueBee chip-map construction (Section 4.4, Eq.1) ──────────────────────────

def hamming_distance(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def constrain_chip_pair(pair_bits):
    """Majority vote: map '01'/'10'→either '00' or '11' (Section 4.3, Fig.6)."""
    return "11" if pair_bits.count("1") > 1 else "00"


def legacy_emulated_chips(chips):
    """Simple per-pair majority vote (no inter-symbol optimization)."""
    return "".join(constrain_chip_pair(chips[i:i + 2]) for i in range(0, 32, 2))


def emulation_candidates(chips):
    """Enumerate all 2^k valid emulations for a symbol with k inconsistent pairs."""
    candidates = [""]
    for i in range(0, 32, 2):
        pair = chips[i:i + 2]
        choices = (pair,) if pair in ("00", "11") else ("00", "11")
        candidates = [prefix + choice for prefix in candidates for choice in choices]
    return candidates


def build_bluebee_chip_map(map_mode):
    """Build the 16-entry BlueBee chip map.

    'optimized' mode (Section 4.4, Eq.1): for each ZigBee symbol, select the
    emulation with the maximum minimum inter-symbol Hamming distance.
    """
    if map_mode == "legacy":
        return [legacy_emulated_chips(chips) for chips in CHIP_MAP]
    if map_mode != "optimized":
        raise ValueError(f"unsupported map mode: {map_mode}")

    optimized = []
    for symbol, chips in enumerate(CHIP_MAP):
        best = None
        for candidate in emulation_candidates(chips):
            intra = hamming_distance(candidate, chips)  # Dist(E_i, S_i)
            inter_distances = [                          # Dist(E_i, S_j), j≠i
                hamming_distance(candidate, other)
                for other_symbol, other in enumerate(CHIP_MAP)
                if other_symbol != symbol
            ]
            min_inter = min(inter_distances)
            sum_inter = sum(inter_distances)
            # Eq.1: maximize min inter-symbol distance, break ties with sum
            score = (-intra, min_inter, sum_inter, candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
        optimized.append(best[1])
    return optimized


# ── Zigbee frame → BlueBee GFSK bits (Section 4.3) ─────────────────────────────

def zigbee_frame_to_gfsk_bits(frame_bytes, bluebee_chip_map, phase_polarity):
    """Convert Zigbee PHY frame bytes to BLE GFSK bits via BlueBee chip mapping.

    Section 4.3: each 32-chip symbol → 16 chip pairs → 16 BLE GFSK bits.
    "11" pair → BLE bit 1 (phase shift +π/2 → two +π/4 → chips "11")
    "00" pair → BLE bit 0 (phase shift -π/2 → two -π/4 → chips "00")
    """
    frame_bits = bytes_to_bits(frame_bytes, bit_order=BIT_ORDER)
    if len(frame_bits) % 4:
        frame_bits += "0" * (4 - len(frame_bits) % 4)

    gfsk_bits = []
    approx_chips = []  # the chip stream seen by ZigBee receiver after emulation
    for i in range(0, len(frame_bits), 4):
        symbol = int(frame_bits[i:i + 4], 2)
        chips = bluebee_chip_map[symbol]
        for j in range(0, 32, 2):
            bit = 1 if chips[j:j + 2] == "11" else 0
            if phase_polarity == "inverted":
                bit ^= 1
            gfsk_bits.append(bit)
            # Each GFSK bit → two identical chips at ZigBee's 2 MHz sampling
            approx_chips.extend(("1", "1") if bit else ("0", "0"))
    return gfsk_bits, "".join(approx_chips)


# ── BLE GFSK modulator (identical to the standard BlueBee generator) ───────────

def get_gaussian_filter(bt, sps, span=4):
    """BLE Gaussian pulse-shaping filter (BT=0.5, Section 4.1)."""
    t = np.arange(-span * sps / 2, span * sps / 2) / sps
    alpha = np.sqrt(np.log(2) / 2) / bt
    h = (np.sqrt(np.pi) / alpha) * np.exp(-((np.pi * t / alpha) ** 2))
    return h / np.sum(h)


def gfsk_modulate_30_72m(bits, bt=0.5, post_pad_us=1000.0):
    """BLE 1M GFSK IQ at 30.72 MSPS, uint32 interleaved for dual-channel DMA.

    Steps (i)→(iv) in Fig.2: NRZ → Gaussian filter → phase integral → I/Q.
    30.72 MSPS is achieved by oversampling at 768× and decimating by 25×.
    """
    symbols = np.array([int(b) for b in bits], dtype=np.float32) * 2 - 1
    sps_high = 768  # intermediate oversampling rate
    nrz_high = np.repeat(symbols, sps_high)
    h = get_gaussian_filter(bt=bt, sps=sps_high, span=4)
    f_sig = np.convolve(nrz_high, h, mode="same")       # step (ii): Gaussian shaping
    phase_step = np.pi / (2 * sps_high)                   # ±π/2 per bit / sps_high
    phase = np.cumsum(f_sig * phase_step)                 # step (iii): phase integral
    i_high = np.cos(phase)                                 # step (iv): I/Q
    q_high = np.sin(phase)
    # Decimate: 768 / 25 = 30.72 samples/bit → 30.72 MSPS
    i_out = i_high[::25]
    q_out = q_high[::25]
    # Scale to 16-bit integer range
    peak = max(np.max(np.abs(i_out)), np.max(np.abs(q_out)))
    scale = 10000.0 / peak if peak > 0 else 1.0
    i_int = np.round(i_out * scale).astype(int)
    q_int = np.round(q_out * scale).astype(int)
    iq_uint32 = ((q_int & 0xFFFF) << 16) | (i_int & 0xFFFF)
    # Repeat each sample ×2 for dual-channel DMA
    iq_uint32 = np.repeat(iq_uint32, 2)
    # Post-packet zero padding
    pad_words = int(round(post_pad_us * 1e-6 * OUTPUT_SAMPLE_RATE)) * 2
    if pad_words > 0:
        iq_uint32 = np.concatenate(
            [iq_uint32, np.zeros(pad_words, dtype=iq_uint32.dtype)]
        )
    return iq_uint32


# ── Zigbee PHY frame ────────────────────────────────────────────────────────────

def build_zigbee_phy_frame(payload_bytes):
    """Build an 802.15.4 PHY frame: 4B preamble | SFD | PHR | payload | CRC-16."""
    mac_len = len(payload_bytes) + 2
    if mac_len > 127:
        raise ValueError("ZigBee MAC frame too long for 802.15.4 PHR (max 127 bytes)")
    fcs = crc16_ccitt(payload_bytes)
    return (
        [0x00] * PREAMBLE_BYTES
        + [SFD, mac_len]
        + list(payload_bytes)
        + [fcs & 0xFF, (fcs >> 8) & 0xFF]
    )


# ── Verification ────────────────────────────────────────────────────────────────

def verify_bluebee_roundtrip(frame_bytes, approx_chips):
    """Verify BlueBee chips decode back to original frame bytes via standard DSSS.

    Section 4.4: the emulated chips are decoded by finding the closest standard
    CHIP_MAP symbol (minimum Hamming distance). Due to pair constraints, each
    symbol has intra-distance ≤8 (Fig.9), well within DSSS tolerance of 12.
    """
    symbols = []
    for i in range(0, len(approx_chips) - len(approx_chips) % 32, 32):
        chunk = approx_chips[i:i + 32]
        best_sym, best_dist = 0, 33
        for sym, ref in enumerate(CHIP_MAP):
            d = hamming_distance(chunk, ref)
            if d < best_dist:
                best_sym, best_dist = sym, d
        symbols.append((best_sym, best_dist))

    bits = "".join(f"{sym:04b}" for sym, _ in symbols)
    decoded = []
    for i in range(0, len(bits) - len(bits) % 8, 8):
        value = 0
        for bit_idx, bit in enumerate(bits[i:i + 8]):
            if bit == "1":
                value |= 1 << bit_idx
        decoded.append(value)
    ok = decoded[:len(frame_bytes)] == list(frame_bytes)
    return ok, decoded, [d for _, d in symbols]


# ── Output writers ──────────────────────────────────────────────────────────────

def write_c_header(path, symbol_name, iq_data, defines, meta_lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated BlueBee Zigbee PHY frame waveform\n")
        f.write("// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)\n")
        f.write(f"// Array {symbol_name}: Zigbee 802.15.4 PHY frame via BlueBee PHY emulation\n")
        f.write("// Reference: BlueBee paper (SenSys'17), Sections 4.3-4.4\n")
        for line in meta_lines:
            f.write(f"// {line}\n")
        f.write("\n#include <stdint.h>\n\n")
        for name, value in defines:
            f.write(f"#define {name} {value}\n")
        if defines:
            f.write("\n")
        f.write(
            f"const uint32_t {symbol_name}[{len(iq_data)}] "
            f"__attribute__((aligned(64))) = {{\n"
        )
        for i in range(0, len(iq_data), 8):
            chunk = iq_data[i:i + 8]
            f.write("    " + ", ".join(f"0x{int(val):08X}" for val in chunk))
            f.write(",\n" if i + 8 < len(iq_data) else "\n")
        f.write("};\n")


def write_complex64(path, iq_data):
    """Write IQ as complex64 (de-duplicated, for HackRF offline analysis)."""
    i = (iq_data.astype(np.uint32) & 0xFFFF).astype(np.int32)
    q = ((iq_data.astype(np.uint32) >> 16) & 0xFFFF).astype(np.int32)
    i[i >= 0x8000] -= 0x10000
    q[q >= 0x8000] -= 0x10000
    iq = (i.astype(np.float32) + 1j * q.astype(np.float32)) / 10000.0
    iq = iq[0::2]
    iq.astype(np.complex64).tofile(path)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate Zigbee PHY frame IQ via BlueBee PHY emulation "
                    "(BLE GFSK modulating BlueBee pair-constrained chips). "
                    "Reference: BlueBee paper, SenSys'17."
    )
    parser.add_argument(
        "--zigbee-payload", default="0x11 0x22 0x33 0x44",
        help="ZigBee payload bytes (default: 0x11 0x22 0x33 0x44)",
    )
    parser.add_argument(
        "--bt", type=float, default=0.5,
        help="Gaussian filter BT product (default: 0.5, BLE standard)",
    )
    parser.add_argument(
        "--post-pad-us", type=float, default=1000.0,
        help="Silence after the frame in µs (default: 1000)",
    )
    parser.add_argument(
        "--map-mode", choices=("legacy", "optimized"), default="optimized",
        help="BlueBee chip-map mode (Section 4.4). "
             "optimized = max-min inter-symbol Hamming distance (Eq.1). "
             "legacy = simple per-pair majority vote. (default: optimized)",
    )
    parser.add_argument(
        "--phase-polarity", choices=("normal", "inverted"), default="normal",
        help="Invert GFSK bit sense (default: normal)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(SCRIPT_DIR, "bluebee_zigbee_frame_30_72M.h"),
        help="Output C header path",
    )
    parser.add_argument(
        "--output-iq", default=None,
        help="Optional complex64 IQ file for HackRF offline analysis",
    )
    parser.add_argument(
        "--symbol-name", default="bluebee_zigbee_frame_iq",
        help="C array symbol name",
    )
    parser.add_argument(
        "--sdk-output", action="store_true",
        help="Also write zigbee_tx.c/.h to the SDK source directory",
    )
    args = parser.parse_args()

    # 1. Parse payload
    payload_bytes = [int(item, 0) & 0xFF
                     for item in args.zigbee_payload.replace(",", " ").split()]

    # 2. Build Zigbee PHY frame
    frame = build_zigbee_phy_frame(payload_bytes)

    # 3. Build BlueBee chip map (Section 4.4)
    bb_map = build_bluebee_chip_map(args.map_mode)

    # 4. Zigbee frame → BlueBee GFSK bits (Section 4.3)
    gfsk_bits, approx_chips = zigbee_frame_to_gfsk_bits(
        frame, bluebee_chip_map=bb_map, phase_polarity=args.phase_polarity,
    )

    # 5. GFSK modulate (Sections 4.1-4.2, Fig.2)
    iq_data = gfsk_modulate_30_72m(gfsk_bits, bt=args.bt, post_pad_us=args.post_pad_us)

    # 6. Verify self-consistency
    ok, decoded_frame, distances = verify_bluebee_roundtrip(frame, approx_chips)

    # 7. Write output
    unique_samples = len(iq_data) // 2
    pad_samples_30m = int(args.post_pad_us * 1e-6 * OUTPUT_SAMPLE_RATE)
    nonzero_samples = unique_samples - pad_samples_30m
    air_us = int(nonzero_samples / (OUTPUT_SAMPLE_RATE / 1e6))
    effective_chip_rate = len(gfsk_bits) * 2 / (air_us * 1e-6) if air_us > 0 else 0

    defines = [
        ("BLUEBEE_ZIGBEE_FRAME_IQ", args.symbol_name),
        ("BLUEBEE_ZIGBEE_FRAME_WORDS", f"({len(iq_data)}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_UNIQUE_WORDS", f"({unique_samples}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_AIR_US", f"({air_us}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_POST_PAD_US", f"({int(args.post_pad_us)}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_PAYLOAD_BYTES", f"({len(payload_bytes)}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_BYTES", f"({len(frame)}u)"),
        ("BLUEBEE_ZIGBEE_FRAME_GFSK_BITS", f"({len(gfsk_bits)}u)"),
    ]

    meta = [
        f"zigbee_frame_bytes: {len(frame)}",
        f"zigbee_payload_bytes: {len(payload_bytes)}",
        f"gfsk_bits: {len(gfsk_bits)} (each = 2 chips)",
        f"bt: {args.bt}",
        f"map_mode: {args.map_mode}",
        f"phase_polarity: {args.phase_polarity}",
        f"post_pad_us: {args.post_pad_us:g}",
        f"air_us: {air_us}",
        f"zigbee_projection_ok: {ok}",
        f"frame: {' '.join(f'{b:02X}' for b in frame)}",
    ]

    write_c_header(args.output, args.symbol_name, iq_data, defines, meta)

    if args.output_iq:
        write_complex64(args.output_iq, iq_data)

    # SDK output
    if args.sdk_output:
        sdk_src = os.path.normpath(os.path.join(
            SCRIPT_DIR, "..", "..", "..", "hdl", "projects", "antsdre310",
            "antsdre310.sdk", "app", "src", "zigbee_tx.c"
        ))
        sdk_hdr = os.path.normpath(os.path.join(
            SCRIPT_DIR, "..", "..", "..", "hdl", "projects", "antsdre310",
            "antsdre310.sdk", "app", "src", "zigbee_tx.h"
        ))
        with open(sdk_src, "w") as f:
            f.write('#include <stdlib.h>\n#include <stdio.h>\n#include <inttypes.h>\n\n')
            f.write(f'const uint32_t zigbee_iq[{len(iq_data)}] __attribute__((aligned(64))) = {{\n')
            for i in range(0, len(iq_data), 8):
                chunk = iq_data[i:i+8]
                f.write("    " + ", ".join(f"0x{int(val):08X}" for val in chunk))
                f.write(",\n" if i + 8 < len(iq_data) else "\n")
            f.write("};\n")
        with open(sdk_hdr, "w") as f:
            f.write('#ifndef ZIGBEE_TX\n#define ZIGBEE_TX\n\n')
            f.write(f'extern const uint32_t zigbee_iq[{len(iq_data)}] __attribute__((aligned(64)));\n')
            f.write('\n#endif\n')
        print(f"SDK source: {sdk_src}")

    # 8. Summary
    duration_us = unique_samples / (OUTPUT_SAMPLE_RATE / 1e6)
    nonzero_duration_us = nonzero_samples / (OUTPUT_SAMPLE_RATE / 1e6)

    def _map_metrics(chip_map):
        for sym, emulated in enumerate(chip_map):
            intra = hamming_distance(emulated, CHIP_MAP[sym])
            inter = [hamming_distance(emulated, ref)
                     for o, ref in enumerate(CHIP_MAP) if o != sym]
            yield sym, intra, min(inter), emulated

    print(f"ZigBee PHY frame ({len(frame)} bytes):")
    print(f"  {' '.join(f'{b:02X}' for b in frame)}")
    print(f"  Preamble+SFD: {' '.join(f'{b:02X}' for b in frame[:6])}")
    print(f"  Payload:      {' '.join(f'{b:02X}' for b in payload_bytes)}")
    print(f"  CRC:          {' '.join(f'{b:02X}' for b in frame[-2:])}")
    print()
    print(f"BlueBee emulation (Section 4.3-4.4):")
    print(f"  GFSK bits: {len(gfsk_bits)} (each → 2 chips → {len(gfsk_bits)*2} chips)")
    print(f"  Map mode: {args.map_mode}")
    print(f"  DSSS map (symbol: intra  min_inter  chips):")
    for sym, intra, min_inter, chips in _map_metrics(bb_map):
        marker = ""
        if args.map_mode == "optimized" and chips != legacy_emulated_chips(CHIP_MAP[sym]):
            marker = " *"
        print(f"    0x{sym:X}: {intra:2d}     {min_inter:2d}{marker}        {chips}")
    print()
    print(f"IQ output:")
    print(f"  DMA words: {len(iq_data)} ({unique_samples} unique)")
    print(f"  Duration: {duration_us:.0f} µs (nonzero {nonzero_duration_us:.0f} µs + {args.post_pad_us:g} µs pad)")
    print(f"  Effective chip rate: {effective_chip_rate:.1f} Mchip/s (target: 2.0)")
    print(f"  Zigbee projection: {'OK' if ok else 'FAIL'}")
    if distances:
        print(f"  Symbol distance range: {min(distances)}-{max(distances)} (DSSS tolerance: ≤12)")
    print(f"  Output: {args.output}")
    if args.output_iq:
        print(f"  IQ recording: {args.output_iq}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
