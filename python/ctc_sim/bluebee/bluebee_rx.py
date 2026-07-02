#!/usr/bin/env python3
# coding=utf-8
"""BlueBee receiver — phase-difference chip detection + BlueBee DSSS decoding.

Consumes packed chip bytes from the GNU Radio phase-difference path
(ZMQ tcp://127.0.0.1:55557).  Applies BlueBee pair-constrained chip maps
(optimized & legacy) for symbol decoding, searches for 802.15.4 preamble
at byte level, and validates CRC-16.

Reference: BlueBee paper (SenSys'17), Sections 4.3–4.5.
"""

import argparse
import os
import sys
import time

import numpy as np

# Allow imports from std_zigbee/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STD_ZIGBEE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "std_zigbee"))
sys.path.insert(0, STD_ZIGBEE_DIR)

from gr_zigbee import gr_zigbee as gr_block                                       # noqa: E402
from zigbee_rx_common import (                                                     # noqa: E402
    ZMQSubscriber,
    unpack_bytes_to_chips,
    chips_to_symbols,
    symbols_to_bits,
    bits_to_bytes_lsb,
    chip_stats,
    validate_frame,
    read_complex64_tail,
    phase_chips_from_iq,
    chips_to_int,
    CHIP_MAP,
    PREAMBLE_BYTES,
    MIN_FRAME_BYTES,
    MIN_FRAME_SYMBOLS,
    SFD,
)

# ── BlueBee constants ────────────────────────────────────────────────────

PREAMBLE_ONLY_SYMBOLS = [0, 0, 0, 0, 0, 0, 0, 0, 14, 5, 0, 0]
PREAMBLE_ONLY_MAX_SYMBOL_DIST = 144
PHASE_TEMPLATE_MAX_DIST = 110
PHASE_DETECT_CONFIRMATIONS = 1

PHASE_SCAN_PERIOD = 0.02
PHASE_SCAN_CHIPS = 4096
PHASE_FAST_SCAN_CHIPS = 50000
PHASE_MAX_CHIPS = 120000
DIAG_SCAN_CHIPS = 4096


# ── BlueBee chip map construction (Section 4.4, Eq.1) ────────────────────

def bluebee_constrain_pair(pair_bits):
    """Majority vote: '01'/'10' → whichever has more '1's."""
    return "11" if pair_bits.count("1") > 1 else "00"


def bluebee_legacy_symbol_chips(symbol):
    """Simple per-pair majority vote (no inter-symbol optimisation)."""
    chips = CHIP_MAP[symbol]
    return "".join(bluebee_constrain_pair(chips[i : i + 2]) for i in range(0, 32, 2))


def bluebee_candidate_chips(chips):
    """Enumerate all 2^k valid pair-constrained emulations for a 32-chip symbol."""
    candidates = [""]
    for i in range(0, 32, 2):
        pair = chips[i : i + 2]
        choices = (pair,) if pair in ("00", "11") else ("00", "11")
        candidates = [prefix + choice for prefix in candidates for choice in choices]
    return candidates


def bluebee_optimized_symbol_chips(symbol):
    """Select the pair-constrained emulation that maximises the minimum inter-symbol
    Hamming distance (Eq.1 in the BlueBee paper)."""
    chips = CHIP_MAP[symbol]
    best = None
    for candidate in bluebee_candidate_chips(chips):
        intra = sum(1 for a, b in zip(candidate, chips) if a != b)
        inter = [
            sum(1 for a, b in zip(candidate, other) if a != b)
            for other_symbol, other in enumerate(CHIP_MAP)
            if other_symbol != symbol
        ]
        score = (-intra, min(inter), sum(inter), candidate)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1]


# Module-level BlueBee chip maps
BB_CHIP_MAP_OPTIMIZED = [bluebee_optimized_symbol_chips(s) for s in range(16)]
BB_CHIP_MAP_LEGACY = [bluebee_legacy_symbol_chips(s) for s in range(16)]


def build_bluebee_chip_maps():
    return [("optimized", BB_CHIP_MAP_OPTIMIZED), ("legacy", BB_CHIP_MAP_LEGACY)]


BB_CHIP_MAPS = build_bluebee_chip_maps()


# ── Phase templates for fast preamble pattern matching ───────────────────

def build_phase_templates():
    templates = []
    for name, builder in (
        ("optimized", bluebee_optimized_symbol_chips),
        ("legacy", bluebee_legacy_symbol_chips),
    ):
        chips = "".join(builder(symbol) for symbol in PREAMBLE_ONLY_SYMBOLS)
        templates.append(
            {
                "name": name,
                "chips": chips,
                "int": chips_to_int(chips),
                "len": len(chips),
                "mask": (1 << len(chips)) - 1,
            }
        )
    return templates


PHASE_TEMPLATES = build_phase_templates()


# ── Fast phase-template pre-scan ──────────────────────────────────────────

def fast_phase_template_scan(chips, templates, max_dist=PHASE_TEMPLATE_MAX_DIST):
    """Fast O(N) scan for phase-template preamble candidates.

    Uses an integer sliding window with native ``int.bit_count()`` for
    Hamming distance, checking both normal and inverted polarities against
    pre-computed template and inverted-template integers — no string
    inversion of the full chip buffer is needed.

    Returns
    -------
    list of (chip_pos, dist, template_name)
        Sorted by distance (best matches first).
    """
    candidates = []

    for tmpl in templates:
        tmpl_int = tmpl["int"]
        tmpl_len = tmpl["len"]
        tmpl_mask = tmpl["mask"]
        tmpl_inv_int = (~tmpl_int) & tmpl_mask  # bit-flipped template for "inverted" polarity

        if len(chips) < tmpl_len:
            continue

        # Build initial running integer: chips[pos : pos+tmpl_len] as MSB-first int
        running = chips_to_int(chips[:tmpl_len])

        for pos in range(len(chips) - tmpl_len + 1):
            # Normal polarity Hamming distance
            dist_n = (running ^ tmpl_int).bit_count()
            if dist_n <= max_dist:
                candidates.append((pos, dist_n, tmpl["name"]))

            # Inverted polarity: running vs bit-flipped template
            dist_i = (running ^ tmpl_inv_int).bit_count()
            if dist_i <= max_dist:
                candidates.append((pos, dist_i, tmpl["name"]))

            # Slide window forward by one chip: drop MSB, shift left, add new LSB
            if pos + tmpl_len < len(chips):
                new_bit = 1 if chips[pos + tmpl_len] == "1" else 0
                running = ((running << 1) & tmpl_mask) | new_bit

    candidates.sort(key=lambda x: x[1])
    return candidates


# ── Chip utilities ───────────────────────────────────────────────────────

def chips_to_symbols_bluebee(chips, bb_map):
    """Decode chips → (symbol, hamming_distance) using a BlueBee chip map."""
    symbols = []
    usable = (len(chips) // 32) * 32
    for i in range(0, usable, 32):
        chunk = chips[i : i + 32]
        best_s, best_d = 0, 33
        for s, ref in enumerate(bb_map):
            d = sum(1 for a, b in zip(chunk, ref) if a != b)
            if d < best_d:
                best_d, best_s = d, s
        symbols.append((best_s, best_d))
    return symbols


def invert_chips(chips):
    return chips.translate(str.maketrans("01", "10"))


def symbol_window_distance(syms, start, target):
    """Return (symbol_mismatch_count, total_hamming_dist) or None."""
    if start + len(target) > len(syms):
        return None
    mismatch = sum(1 for i in range(len(target)) if syms[start + i][0] != target[i])
    dist = sum(syms[start + i][1] for i in range(len(target)))
    return mismatch, dist


# ── BlueBee-aware frame detection ────────────────────────────────────────

def find_bluebee_detection(chips, bb_chip_maps, max_preamble_dist=PHASE_TEMPLATE_MAX_DIST):
    """BlueBee-aware preamble detection with full frame extraction and CRC.

    Iterates over chip maps, polarities, and alignments.  For each combination:
    decode symbols using a BlueBee chip map, convert to bytes, search for
    preamble + SFD at byte level, optionally validate CRC.
    Returns a detection dict or None.
    """
    MIN_DETECT_BYTES = PREAMBLE_BYTES + 2

    best = None
    for mode_name, bb_map in bb_chip_maps:
        for polarity in ("normal", "inverted"):
            work_chips = invert_chips(chips) if polarity == "inverted" else chips
            for chip_align in range(32):
                syms = chips_to_symbols_bluebee(work_chips[chip_align:], bb_map)
                if len(syms) < MIN_DETECT_BYTES * 2:
                    continue

                bits = symbols_to_bits(syms)
                data = bits_to_bytes_lsb(bits)

                preamble_seq = [0x00] * PREAMBLE_BYTES
                limit = len(data) - MIN_DETECT_BYTES + 1
                for byte_pos in range(0, max(0, limit)):
                    if (
                        data[byte_pos : byte_pos + PREAMBLE_BYTES] != preamble_seq
                        or data[byte_pos + PREAMBLE_BYTES] != SFD
                    ):
                        continue

                    sym_pos = byte_pos * 2
                    preamble_syms = syms[sym_pos : sym_pos + MIN_DETECT_BYTES * 2]
                    if len(preamble_syms) < MIN_DETECT_BYTES * 2:
                        continue
                    preamble_dist = sum(dist for _, dist in preamble_syms)
                    if preamble_dist > max_preamble_dist:
                        continue

                    phr_len = data[byte_pos + PREAMBLE_BYTES + 1]
                    local_chip_pos = chip_align + sym_pos * 32

                    detection = {
                        "chip_pos": local_chip_pos,
                        "chip_align": chip_align,
                        "sym_pos": sym_pos,
                        "byte_pos": byte_pos,
                        "mode": mode_name,
                        "polarity": polarity,
                        "preamble_dist": preamble_dist,
                        "phr_len": phr_len,
                        "frame": data[byte_pos : byte_pos + MIN_DETECT_BYTES],
                        "payload": [],
                        "fcs_ok": False,
                        "consume_chips": local_chip_pos + MIN_DETECT_BYTES * 64,
                        "symbol_distances": [dist for _, dist in syms[sym_pos : sym_pos + 12]],
                        "symbols": [symbol for symbol, _ in syms[sym_pos : sym_pos + 12]],
                        "_syms": syms,  # keep ref for full-frame distance diag
                    }

                    if 0 < phr_len <= 127:
                        total_len = PREAMBLE_BYTES + 2 + phr_len
                        if byte_pos + total_len > len(data):
                            continue
                        frame = data[byte_pos : byte_pos + total_len]
                        fcs_ok, payload = validate_frame(frame)
                        detection.update(
                            {
                                "frame": frame,
                                "payload": payload,
                                "fcs_ok": fcs_ok,
                                "consume_chips": local_chip_pos + total_len * 64,
                            }
                        )

                    # Prefer CRC-OK, then earliest chip position (robust ranking)
                    if best is None:
                        best = detection
                    elif detection["fcs_ok"] and not best["fcs_ok"]:
                        best = detection
                    elif not detection["fcs_ok"] and best["fcs_ok"]:
                        pass
                    elif detection["chip_pos"] < best["chip_pos"]:
                        best = detection

    if best is not None:
        best_syms = best.pop("_syms")
        total_sym_count = len(best["frame"]) * 2
        best["all_symbol_distances"] = [
            dist for _, dist in best_syms[best["sym_pos"] : best["sym_pos"] + total_sym_count]
        ]

    return best


# ── Phase-diff IQ diagnostics ────────────────────────────────────────────

def best_phase_preamble_diagnostic(iq, sample_rate, chip_rate, max_chips):
    """Paper-style phase-difference slicing + preamble template search over IQ."""
    if len(iq) < 2:
        return None
    samples_per_chip = sample_rate / chip_rate
    phase_offsets = np.linspace(
        0, samples_per_chip, max(2, int(np.ceil(samples_per_chip)) * 4), endpoint=False
    )
    best = None
    for polarity in ("normal", "inverted"):
        for phase_offset in phase_offsets:
            chips = phase_chips_from_iq(iq, sample_rate, chip_rate, phase_offset, polarity, max_chips)
            for chip_align in range(32):
                syms = chips_to_symbols(chips[chip_align:])
                if len(syms) < len(PREAMBLE_ONLY_SYMBOLS):
                    continue
                for sym_pos in range(0, len(syms) - len(PREAMBLE_ONLY_SYMBOLS) + 1):
                    result = symbol_window_distance(syms, sym_pos, PREAMBLE_ONLY_SYMBOLS)
                    if result is None:
                        continue
                    mismatch, dist = result
                    score = mismatch * 1000 + dist
                    if best is None or score < best["score"]:
                        chip_pos = chip_align + sym_pos * 32
                        window = syms[sym_pos : sym_pos + len(PREAMBLE_ONLY_SYMBOLS)]
                        best = {
                            "score": score,
                            "polarity": polarity,
                            "phase_offset": phase_offset,
                            "chip_align": chip_align,
                            "chip_pos": chip_pos,
                            "mismatch": mismatch,
                            "dist": dist,
                            "symbols": [v for v, _ in window],
                            "distances": [d for _, d in window],
                            "chips": chips[chip_pos : chip_pos + 96],
                        }
    return best


def print_phase_diag_report(path, sample_rate, chip_rate, max_samples, max_chips):
    iq = read_complex64_tail(path, max_samples)
    if len(iq) == 0:
        print(f"[phase_diag] iq_samples=0 path={path}")
        return None
    power = float(np.mean(np.abs(iq) ** 2))
    peak = float(np.max(np.abs(iq)))
    best = best_phase_preamble_diagnostic(iq, sample_rate, chip_rate, max_chips)
    if best is None:
        print(f"[phase_diag] iq_samples={len(iq)} power={power:.4g} peak={peak:.4g} preamble_window=none")
        return None
    best["power"] = power
    best["peak"] = peak
    best["iq_samples"] = len(iq)
    print(
        f"[phase_diag] iq_samples={len(iq)} power={power:.4g} peak={peak:.4g} "
        f"polarity={best['polarity']} phase_offset={best['phase_offset']:.3f} "
        f"align={best['chip_align']} chip={best['chip_pos']} "
        f"mismatch={best['mismatch']} dist={best['dist']} score={best['score']}"
    )
    print(f"[phase_diag] symbols={best['symbols']} distances={best['distances']}")
    print(f"[phase_diag] chips={best['chips']}")
    return best


# ── CLI ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="BlueBee receiver — phase-difference chip detection + BlueBee DSSS decoding"
)
parser.add_argument("--channel", type=int, default=26,
                    help="ZigBee channel (default: 26, = BLE ch39 / 2480 MHz)")
parser.add_argument("--no-phase-rx", action="store_true",
                    help="Disable BlueBee phase-difference ZMQ detector")
parser.add_argument("--phase-zmq", default="tcp://127.0.0.1:55557",
                    help="ZMQ endpoint for phase-difference BlueBee chips")
parser.add_argument("--phase-keep-offset", type=int, default=0,
                    help="Sample offset 0..4 used by the GNU Radio phase chip sampler")
parser.add_argument("--phase-scan-period", type=float, default=PHASE_SCAN_PERIOD,
                    help="Seconds between fast phase-domain BlueBee scans")
parser.add_argument("--phase-fast-scan-chips", type=int, default=PHASE_FAST_SCAN_CHIPS,
                    help="Max chips for fast phase-template pre-scan (0 = fall back to old PHASE_SCAN_CHIPS window)")
parser.add_argument("--phase-hit-print-every", type=int, default=1,
                    help="Print every N phase preamble hits")
parser.add_argument("--phase-detect-confirmations", type=int, default=PHASE_DETECT_CONFIRMATIONS,
                    help="Consecutive phase-template matches required before counting a hit")
parser.add_argument("--phase-detect-max-mismatch", type=int, default=0,
                    help="Maximum symbol mismatch for phase-domain preamble hit")
parser.add_argument("--phase-detect-max-dist", type=int, default=PHASE_TEMPLATE_MAX_DIST,
                    help="Maximum template Hamming distance for phase-domain preamble hit")
parser.add_argument("--iq-output", default=None,
                    help="Optional complex64 filtered-IQ recording path")
parser.add_argument("--phase-diag", action="store_true",
                    help="Periodically search the filtered IQ tail using phase-difference slicing")
parser.add_argument("--phase-diag-period", type=float, default=1.0,
                    help="Seconds between --phase-diag reports")
parser.add_argument("--phase-diag-samples", type=int, default=50000,
                    help="Complex64 IQ tail samples per --phase-diag report")
parser.add_argument("--phase-diag-chips", type=int, default=4096,
                    help="Maximum sliced chips per --phase-diag report")
parser.add_argument("--freq-offset", type=float, default=0.0,
                    help="Optional RX frequency offset in Hz")
parser.add_argument("--duration", type=float, default=0.0,
                    help="Run for N seconds then print performance report (0 = forever)")
args = parser.parse_args()

if args.phase_diag and not args.iq_output:
    args.iq_output = "/tmp/zigbee_rx_phase_diag.c64"
if args.iq_output:
    open(args.iq_output, "wb").close()

# ── GNU Radio flowgraph ──────────────────────────────────────────────────

gr_block_obj = gr_block()
gr_block_obj.set_zigbee_channel(args.channel)
if hasattr(gr_block_obj, "set_phase_keep_offset"):
    gr_block_obj.set_phase_keep_offset(args.phase_keep_offset)
if args.freq_offset:
    gr_block_obj.set_freq_offset(args.freq_offset)
if args.iq_output:
    gr_block_obj.set_iq_output(args.iq_output)
gr_block_obj.start()

print(
    f"RX (BlueBee): ch{args.channel}  {gr_block_obj.get_freq()/1e6:.1f} MHz  "
    f"sr={gr_block_obj.get_sample_rate()/1e6:.1f} MHz  "
    f"phase_diag={'on' if args.phase_diag else 'off'}  "
    f"iq={args.iq_output or 'off'}  freq_offset={args.freq_offset:g}"
)

# ── ZMQ subscriber (phase-diff only) ─────────────────────────────────────

phase_zmq_sub = None if args.no_phase_rx else ZMQSubscriber(addr=args.phase_zmq)

# ── State ────────────────────────────────────────────────────────────────

phase_zmq_msgs = 0
crc_ok_packets = 0
preamble_only_packets = 0
phase_preamble_hits = 0
phase_payload_bytes = 0
phase_candidate_streak = 0
phase_best_dist = None
phase_fast_scan_candidates = 0

start_time = time.time()
last_report = time.time()
last_phase_scan = 0.0
last_phase_diag = 0.0
last_rx_time = time.time()

phase_chip_buf = ""

try:
    while True:
        phase_raw_msgs = phase_zmq_sub.read_available() if phase_zmq_sub is not None else []

        if phase_raw_msgs:
            last_rx_time = time.time()
            phase_zmq_msgs += len(phase_raw_msgs)
            phase_chips = "".join(unpack_bytes_to_chips(raw) for raw in phase_raw_msgs if raw)
            phase_chip_buf += phase_chips
            if len(phase_chip_buf) > PHASE_MAX_CHIPS:
                phase_chip_buf = phase_chip_buf[-PHASE_MAX_CHIPS:]

        # Clear stale noise buffer after ZMQ stream goes idle.
        if phase_chip_buf and time.time() - last_rx_time > 3.0:
            phase_chip_buf = ""

        # ── Phase-diff BlueBee scan (fast template pre-scan + targeted decode) ──

        if (
            not args.no_phase_rx
            and len(phase_chip_buf) >= MIN_FRAME_SYMBOLS * 32
            and time.time() - last_phase_scan >= args.phase_scan_period
        ):
            last_phase_scan = time.time()

            # ── Step 1: Fast phase-template scan on a large buffer window ──
            if args.phase_fast_scan_chips > 0:
                scan_chips = min(args.phase_fast_scan_chips, len(phase_chip_buf))
                phase_scan_buf = phase_chip_buf[-scan_chips:]

                candidates = fast_phase_template_scan(
                    phase_scan_buf, PHASE_TEMPLATES,
                    max_dist=args.phase_detect_max_dist,
                )
                phase_fast_scan_candidates = len(candidates)

                # ── Step 2: Targeted full decode around each candidate ─────
                WINDOW_BEFORE = 64     # chips before candidate for chip-alignment search
                WINDOW_AFTER = 9000    # enough for max-length ZigBee frame (~8640 chips)

                detection = None
                tried_positions = set()

                for cand_pos, cand_dist, cand_name in candidates:
                    # Skip candidates too close to one we already tried
                    if any(abs(cand_pos - seen) < 64 for seen in tried_positions):
                        continue
                    tried_positions.add(cand_pos)

                    window_start = max(0, cand_pos - WINDOW_BEFORE)
                    window_end = min(len(phase_scan_buf), cand_pos + WINDOW_AFTER)
                    window = phase_scan_buf[window_start:window_end]

                    detection = find_bluebee_detection(
                        window, BB_CHIP_MAPS,
                        max_preamble_dist=args.phase_detect_max_dist,
                    )
                    if detection is not None:
                        # Adjust positions from window-relative to scan_buf-relative
                        detection["chip_pos"] += window_start
                        detection["consume_chips"] += window_start
                        break
            else:
                # ── Legacy path: brute-force on last PHASE_SCAN_CHIPS ─────
                phase_scan_buf = phase_chip_buf[-PHASE_SCAN_CHIPS:]
                detection = find_bluebee_detection(
                    phase_scan_buf, BB_CHIP_MAPS,
                    max_preamble_dist=args.phase_detect_max_dist,
                )

            # ── Step 3: Process detection (same confirmation logic) ────────
            if detection is None:
                phase_candidate_streak = 0
                phase_best_dist = None
            else:
                phase_candidate_streak += 1
                phase_chip_pos = len(phase_chip_buf) - len(phase_scan_buf) + detection["chip_pos"]
                phase_best_dist = detection["preamble_dist"]
                if phase_candidate_streak >= args.phase_detect_confirmations:
                    phase_preamble_hits += 1
                    phase_candidate_streak = 0
                    if detection["fcs_ok"]:
                        crc_ok_packets += 1
                        phase_payload_bytes += len(detection["payload"])
                    else:
                        preamble_only_packets += 1

                    if (
                        args.phase_hit_print_every > 0
                        and phase_preamble_hits % args.phase_hit_print_every == 0
                    ):
                        fcs_str = "OK" if detection["fcs_ok"] else "FAIL"
                        print(
                            f"\n=== PHASE PREAMBLE at chip {phase_chip_pos} "
                            f"hit:{phase_preamble_hits} crc_ok:{crc_ok_packets} "
                            f"preamble_only:{preamble_only_packets} FCS:{fcs_str} "
                            f"dist:{detection['preamble_dist']} "
                            f"mode:{detection['mode']} polarity:{detection['polarity']} "
                            f"align:{detection['chip_align']} ==="
                        )
                        print(f"Phase symbols: {detection['symbols']}")
                        print(f"Preamble distances: {detection['symbol_distances']}")
                        if not detection["fcs_ok"] and "all_symbol_distances" in detection:
                            # Show tail-end symbol distances for CRC-FAIL diagnostics
                            all_d = detection["all_symbol_distances"]
                            tail_n = min(16, len(all_d))
                            print(f"All symbol distances (N={len(all_d)}): {all_d}")
                            print(f"Tail {tail_n} distances: {all_d[-tail_n:]}")
                        print(f"Frame bytes: {' '.join(f'{b:02X}' for b in detection['frame'])}")
                        if detection["fcs_ok"]:
                            print(f"Payload: {' '.join(f'{b:02X}' for b in detection['payload'])}")
                        print(f"Phase chips: {phase_chip_buf[phase_chip_pos:phase_chip_pos+96]}")

                    consume = phase_chip_pos + detection["consume_chips"] - detection["chip_pos"]
                    phase_chip_buf = phase_chip_buf[min(consume, len(phase_chip_buf)):]

        # ── Phase-diag from IQ file ─────────────────────────────────────

        if args.phase_diag and time.time() - last_phase_diag >= args.phase_diag_period:
            last_phase_diag = time.time()
            phase_best = print_phase_diag_report(
                args.iq_output,
                gr_block_obj.get_sample_rate(),
                2e6,
                args.phase_diag_samples,
                args.phase_diag_chips,
            )
            if (
                phase_best is not None
                and phase_best["mismatch"] <= args.phase_detect_max_mismatch
                and phase_best["dist"] <= args.phase_detect_max_dist
            ):
                phase_preamble_hits += 1
                print(
                    f"=== PHASE PREAMBLE hit:{phase_preamble_hits} "
                    f"mismatch:{phase_best['mismatch']} dist:{phase_best['dist']} "
                    f"polarity:{phase_best['polarity']} offset:{phase_best['phase_offset']:.3f} "
                    f"align:{phase_best['chip_align']} ==="
                )

        # ── Periodic stats ──────────────────────────────────────────────

        if time.time() - last_report >= 2.0 and phase_zmq_msgs > 0:
            phase_ones, phase_transitions = chip_stats(phase_chip_buf[-DIAG_SCAN_CHIPS:])
            preview = phase_chip_buf[:120] if phase_chip_buf else "(empty)"
            best_text = "none" if phase_best_dist is None else str(phase_best_dist)

            if phase_ones > 0.55:
                tune_hint = f"freq↑ try --freq-offset {-int((phase_ones - 0.5) * 200)}k"
            elif phase_ones < 0.45:
                tune_hint = f"freq↓ try --freq-offset +{int((0.5 - phase_ones) * 200)}k"
            else:
                tune_hint = "freq≈OK"

            print(
                f"[phase_msgs:{phase_zmq_msgs} phase_chips:{len(phase_chip_buf)} "
                f"crc_ok:{crc_ok_packets} preamble_only:{preamble_only_packets} "
                f"phase_preamble:{phase_preamble_hits} phase_best_dist:{best_text} "
                f"phase_streak:{phase_candidate_streak} phase_cands:{phase_fast_scan_candidates} "
                f"phase_ones:{phase_ones:.3f}({tune_hint}) phase_trans:{phase_transitions:.3f} "
                f"raw:{preview}]"
            )
            last_report = time.time()

        if args.duration > 0 and time.time() - start_time >= args.duration:
            break

except KeyboardInterrupt:
    pass

finally:
    if phase_zmq_sub is not None:
        phase_zmq_sub.close()
    gr_block_obj.stop()
    gr_block_obj.wait()

    elapsed = time.time() - start_time
    total_packets = crc_ok_packets + preamble_only_packets
    print(f"\n{'='*60}")
    print(f"PERFORMANCE REPORT (BlueBee)")
    print(f"{'='*60}")
    print(f"  Duration:              {elapsed:.1f} s")
    print(f"  CRC-OK packets:        {crc_ok_packets}")
    print(f"  Preamble-only packets: {preamble_only_packets}")
    print(f"  Total detections:      {total_packets}")
    if elapsed > 0:
        print(f"  Packet rate:           {total_packets/elapsed:.1f} pkts/s")
        print(f"  CRC-OK rate:           {crc_ok_packets/elapsed:.1f} pkts/s")
    if total_packets > 0:
        print(f"  Success rate:          {crc_ok_packets/total_packets*100:.1f}%")
    print(f"  CRC-OK payload bytes:  {phase_payload_bytes}")
    if elapsed > 0:
        print(f"  Throughput:            {phase_payload_bytes*8/elapsed:.0f} bps")
    print(f"  ZMQ msgs (phase):      {phase_zmq_msgs}")
    print(f"{'='*60}")
