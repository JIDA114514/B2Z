#!/usr/bin/env python3
# coding=utf-8
"""Standard 802.15.4 OQPSK ZigBee receiver.

Consumes packed chip bytes from the GNU Radio OQPSK demodulation path
(ZMQ tcp://127.0.0.1:55556) and searches for valid ZigBee PHY frames
using the standard 32-chip DSSS symbol map.
"""

import argparse
import time

from gr_zigbee import gr_zigbee as gr_block
from zigbee_rx_common import (
    ZMQSubscriber,
    unpack_bytes_to_chips,
    chips_to_symbols,
    symbols_to_bits,
    bits_to_bytes_lsb,
    chip_stats,
    find_preamble,
    PREAMBLE_CHIPS,
    PREAMBLE_BYTES,
    PREAMBLE_MAX_DIST,
    MIN_FRAME_BYTES,
    MIN_FRAME_SYMBOLS,
    crc16_ccitt,
)

# ── Constants ────────────────────────────────────────────────────────────

MAX_CHIPS = 9600
STATS_PERIOD = 2.0
DIAG_SCAN_CHIPS = 4096


# ── Frame search ─────────────────────────────────────────────────────────

def preamble_candidates(chips, max_dist=PREAMBLE_MAX_DIST):
    """Yield (chip_pos, hamming_dist) for every 32-chip window that matches
    the standard preamble symbol 0 within *max_dist* errors."""
    usable = len(chips) - 32 + 1
    for pos in range(0, usable):
        chunk = chips[pos : pos + 32]
        dist = sum(1 for a, b in zip(chunk, PREAMBLE_CHIPS) if a != b)
        if dist <= max_dist:
            yield pos, dist


def find_frame_window(chips):
    """Locate a full ZigBee PHY frame in the chip buffer using exact
    PREAMBLE_CHIPS string matching, then decode symbols → bytes and
    extract the frame via preamble search."""
    search_pos = 0
    while True:
        candidate = chips.find(PREAMBLE_CHIPS, search_pos)
        if candidate < 0:
            return None, -1, None, 0

        align_offset = candidate % 32
        candidate_symbol = (candidate - align_offset) // 32
        start_symbol = max(candidate_symbol - PREAMBLE_BYTES * 2, 0)
        start_chip = align_offset + start_symbol * 32
        syms = chips_to_symbols(chips[start_chip:])
        if syms:
            bits = symbols_to_bits(syms)
            data = bits_to_bytes_lsb(bits)
            frame, byte_pos = find_preamble(data)
            if frame is not None:
                local_symbol = byte_pos * 2
                preamble_chip = start_chip + local_symbol * 32
                return frame, preamble_chip, syms, local_symbol

        search_pos = candidate + 1


# ── CLI ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Standard 802.15.4 OQPSK ZigBee receiver")
parser.add_argument("--channel", type=int, default=26,
                    help="ZigBee channel (default: 26)")
parser.add_argument("--no-standard-scan", action="store_true", default=True,
                    help="Disable standard OQPSK full-frame search (default: True)")
parser.add_argument("--enable-standard-scan", action="store_true",
                    help="Re-enable standard OQPSK full-frame search")
parser.add_argument("--duration", type=float, default=0.0,
                    help="Run for N seconds then print performance report (0 = forever)")
args = parser.parse_args()

# ── GNU Radio flowgraph ──────────────────────────────────────────────────

gr_block_obj = gr_block()
gr_block_obj.set_zigbee_channel(args.channel)
gr_block_obj.start()
print(f"RX (OQPSK): ch{args.channel}  {gr_block_obj.get_freq()/1e6:.1f} MHz  "
      f"sr={gr_block_obj.get_sample_rate()/1e6:.1f} MHz  "
      f"standard_scan={'on' if args.enable_standard_scan else 'off'}")

zmq_sub = ZMQSubscriber()

# ── State ────────────────────────────────────────────────────────────────

chip_buf = ""
zmq_msgs = 0
crc_ok_packets = 0
preamble_only_packets = 0
start_time = time.time()
last_report = time.time()
last_rx_time = time.time()
last_raw_msgs = []

try:
    while True:
        raw_msgs = zmq_sub.read_available()
        if raw_msgs:
            last_raw_msgs = raw_msgs
            last_rx_time = time.time()
            zmq_msgs += len(raw_msgs)
            chips = "".join(unpack_bytes_to_chips(raw) for raw in raw_msgs if raw)
            chip_buf += chips
            if len(chip_buf) > MAX_CHIPS:
                chip_buf = chip_buf[-MAX_CHIPS:]

        # Clear stale noise buffer after ZMQ stream goes idle.
        if chip_buf and time.time() - last_rx_time > 3.0:
            chip_buf = ""

        use_standard_scan = not args.no_standard_scan or args.enable_standard_scan

        if use_standard_scan and len(chip_buf) >= MIN_FRAME_SYMBOLS * 32:
            frame, chip_pos, syms, sym_pos = find_frame_window(chip_buf)

            if frame is not None:
                last_rx_time = time.time()
                payload_len = frame[PREAMBLE_BYTES + 1] - 2
                if payload_len > 0 and len(frame) >= MIN_FRAME_BYTES + payload_len + 2:
                    mac = frame[MIN_FRAME_BYTES : MIN_FRAME_BYTES + payload_len]
                    fcs_rx = frame[MIN_FRAME_BYTES + payload_len] | (frame[MIN_FRAME_BYTES + payload_len + 1] << 8)
                    fcs_calc = crc16_ccitt(mac)
                    fcs_ok = (fcs_rx == fcs_calc)
                else:
                    fcs_ok = False

                if fcs_ok:
                    crc_ok_packets += 1
                else:
                    preamble_only_packets += 1

                print(f"\n=== FRAME at chip {chip_pos}  FCS={'OK' if fcs_ok else 'FAIL'} "
                      f"crc_ok:{crc_ok_packets} preamble_only:{preamble_only_packets} ===")
                print(f"Frame bytes: {' '.join(f'{b:02X}' for b in frame)}")
                if fcs_ok:
                    print(f"Payload: {[hex(b) for b in mac]}")
                chip_buf = ""

        # Periodic stats
        if time.time() - last_report >= STATS_PERIOD and zmq_msgs > 0:
            ones, transitions = chip_stats(chip_buf[-DIAG_SCAN_CHIPS:])
            preview = chip_buf[:120] if chip_buf else "(empty)"
            print(f"[msgs:{zmq_msgs} chips:{len(chip_buf)} "
                  f"crc_ok:{crc_ok_packets} preamble_only:{preamble_only_packets} "
                  f"ones:{ones:.3f} trans:{transitions:.3f} raw:{preview}]")
            last_report = time.time()

        if args.duration > 0 and time.time() - start_time >= args.duration:
            break

except KeyboardInterrupt:
    pass

finally:
    zmq_sub.close()
    gr_block_obj.stop()
    gr_block_obj.wait()

    elapsed = time.time() - start_time
    total_packets = crc_ok_packets + preamble_only_packets
    print(f"\n{'='*60}")
    print(f"PERFORMANCE REPORT (OQPSK)")
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
    print(f"  ZMQ msgs (OQPSK):      {zmq_msgs}")
    print(f"{'='*60}")
