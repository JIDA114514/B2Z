#!/usr/bin/env python3
# coding=utf-8
"""Standard ZigBee OQPSK receiver using the known-good 267dd6c hot path."""

import argparse
import time
import zmq

from gr_zigbee import gr_zigbee as gr_block
from zigbee_mod import crc16_ccitt

CHIP_MAP = [
    "11011001110000110101001000101110",
    "11101101100111000011010100100010",
    "00101110110110011100001101010010",
    "00100010111011011001110000110101",
    "01010010001011101101100111000011",
    "00110101001000101110110110011100",
    "11000011010100100010111011011001",
    "10011100001101010010001011101101",
    "10001100100101100000011101111011",
    "10111000110010010110000001110111",
    "01111011100011001001011000000111",
    "01110111101110001100100101100000",
    "00000111011110111000110010010110",
    "01100000011101111011100011001001",
    "10010110000001110111101110001100",
    "11001001011000000111011110111000",
]

PREAMBLE_CHIPS = CHIP_MAP[0]
PREAMBLE_BYTES = 4
SFD = 0xA7
KNOWN_FRAME_LEN = 14
PREAMBLE_SYMBOLS = PREAMBLE_BYTES * 2
FRAME_SYMBOLS = KNOWN_FRAME_LEN * 2
FRAME_CHIPS = FRAME_SYMBOLS * 32
WINDOW_SYMBOLS = FRAME_SYMBOLS + PREAMBLE_SYMBOLS
MAX_CHIPS = 9600
STATS_PERIOD = 2.0
DIAG_SCAN_CHIPS = 4096


class ZMQSubscriber:
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


def unpack_bytes_to_chips(data):
    chips = []
    for byte in data:
        for i in range(8):
            chips.append("1" if (byte >> i) & 1 else "0")
    return "".join(chips)


def chips_to_symbols(chips):
    symbols = []
    usable = (len(chips) // 32) * 32
    for i in range(0, usable, 32):
        chunk = chips[i:i + 32]
        best_s, best_d = 0, 33
        for s, ref in enumerate(CHIP_MAP):
            d = sum(1 for a, b in zip(chunk, ref) if a != b)
            if d < best_d:
                best_d, best_s = d, s
        symbols.append((best_s, best_d))
    return symbols


def symbols_to_bits(symbols):
    return "".join(f"{s:04b}" for s, _ in symbols)


def bits_to_bytes_lsb(bit_str):
    data = []
    for i in range(0, len(bit_str) - len(bit_str) % 8, 8):
        v = 0
        for idx, ch in enumerate(bit_str[i:i + 8]):
            if ch == "1":
                v |= 1 << idx
        data.append(v)
    return data


def chip_stats(chips):
    if not chips:
        return 0.0, 0.0
    ones = chips.count("1") / len(chips)
    if len(chips) <= 1:
        return ones, 0.0
    transitions = sum(1 for a, b in zip(chips, chips[1:]) if a != b) / (len(chips) - 1)
    return ones, transitions


def find_preamble(data):
    preamble = [0x00] * PREAMBLE_BYTES
    for i in range(0, len(data) - KNOWN_FRAME_LEN + 1):
        if data[i:i + PREAMBLE_BYTES] == preamble and data[i + PREAMBLE_BYTES] == SFD:
            return data[i:i + KNOWN_FRAME_LEN], i
    return None, -1


def find_frame_window(chips):
    search_pos = 0
    while True:
        candidate = chips.find(PREAMBLE_CHIPS, search_pos)
        if candidate < 0:
            return None, -1, None, 0
        if len(chips) - candidate < FRAME_CHIPS:
            return None, -1, None, 0

        align_offset = candidate % 32
        candidate_symbol = (candidate - align_offset) // 32
        start_symbol = max(candidate_symbol - PREAMBLE_SYMBOLS, 0)
        start_chip = align_offset + start_symbol * 32
        end_chip = min(len(chips), start_chip + WINDOW_SYMBOLS * 32)

        syms = chips_to_symbols(chips[start_chip:end_chip])
        if syms:
            bits = symbols_to_bits(syms)
            data = bits_to_bytes_lsb(bits)
            frame, byte_pos = find_preamble(data)
            if frame is not None:
                local_symbol = byte_pos * 2
                preamble_chip = start_chip + local_symbol * 32
                return frame, preamble_chip, syms, local_symbol

        search_pos = candidate + 1


parser = argparse.ArgumentParser(description="Known-good standard ZigBee OQPSK receiver")
parser.add_argument("--channel", type=int, default=26, help="ZigBee channel (default: 26)")
parser.add_argument("--duration", type=float, default=0.0, help="Run for N seconds (0 = forever)")
args = parser.parse_args()

gr_block_obj = gr_block()
gr_block_obj.start()
gr_block_obj.set_zigbee_channel(args.channel)
print(f"RX (OQPSK): ch{args.channel}  {gr_block_obj.get_freq()/1e6:.1f} MHz  "
      f"sr={gr_block_obj.get_sample_rate()/1e6:.1f} MHz")

zmq_sub = ZMQSubscriber()
zmq_msgs = 0
crc_ok_packets = 0
preamble_only_packets = 0
payload_bytes = 0
start_time = time.time()
last_report = time.time()
last_clear = time.time()
chip_buf = ""

try:
    while True:
        raw_msgs = zmq_sub.read_available()
        if raw_msgs:
            zmq_msgs += len(raw_msgs)
            chips = "".join(unpack_bytes_to_chips(raw) for raw in raw_msgs if raw)
            chip_buf += chips
            if len(chip_buf) > MAX_CHIPS:
                chip_buf = chip_buf[-MAX_CHIPS:]

        if zmq_msgs > 0 and time.time() - last_clear > 3.0:
            chip_buf = ""
            last_clear = time.time()

        if len(chip_buf) >= 32 * (PREAMBLE_BYTES + 2):
            frame, chip_pos, syms, sym_pos = find_frame_window(chip_buf)
            if frame is not None:
                last_clear = time.time()
                payload_len = frame[5] - 2
                if payload_len > 0 and len(frame) >= 6 + payload_len + 2:
                    mac = frame[6:6 + payload_len]
                    fcs_rx = frame[6 + payload_len] | (frame[6 + payload_len + 1] << 8)
                    fcs_calc = crc16_ccitt(mac)
                    fcs_ok = (fcs_rx == fcs_calc)
                else:
                    fcs_ok = False

                if fcs_ok:
                    crc_ok_packets += 1
                    payload_bytes += len(mac)
                else:
                    preamble_only_packets += 1

                total_packets = crc_ok_packets + preamble_only_packets
                print(f"\n=== OQPSK PREAMBLE at chip {chip_pos} "
                      f"hit:{total_packets} crc_ok:{crc_ok_packets} "
                      f"preamble_only:{preamble_only_packets} FCS:{'OK' if fcs_ok else 'FAIL'} ===")
                print(f"Chips around preamble: {chip_buf[chip_pos:chip_pos + 64]}")
                print(f"Symbol distances: {[d for _, d in syms[sym_pos:sym_pos + 8]]}")
                if fcs_ok:
                    print(f"Payload: {' '.join(f'{b:02X}' for b in mac)}")
                print(f"Frame bytes: {' '.join(f'{b:02X}' for b in frame)}")
                chip_buf = ""

        if time.time() - last_report >= STATS_PERIOD and zmq_msgs > 0:
            now = time.time()
            elapsed = now - start_time
            total_packets = crc_ok_packets + preamble_only_packets
            ones, transitions = chip_stats(chip_buf[-DIAG_SCAN_CHIPS:])
            preview = chip_buf[:120] if chip_buf else "(empty)"
            throughput = payload_bytes * 8 / elapsed if elapsed > 0 else 0.0

            if ones > 0.55:
                tune_hint = "ones_high"
            elif ones < 0.45:
                tune_hint = "ones_low"
            else:
                tune_hint = "ones_ok"

            print(f"[oqpsk_msgs:{zmq_msgs} oqpsk_chips:{len(chip_buf)} "
                  f"crc_ok:{crc_ok_packets} preamble_only:{preamble_only_packets} "
                  f"oqpsk_preamble:{total_packets} "
                  f"oqpsk_ones:{ones:.3f}({tune_hint}) oqpsk_trans:{transitions:.3f} "
                  f"throughput:{throughput:.0f}bps "
                  f"raw:{preview}]")
            last_report = now

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
    print("PERFORMANCE REPORT (OQPSK)")
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
    print(f"  CRC-OK payload bytes:  {payload_bytes}")
    if elapsed > 0:
        print(f"  Throughput:            {payload_bytes*8/elapsed:.0f} bps")
    print(f"  ZMQ msgs (OQPSK):      {zmq_msgs}")
    print(f"{'='*60}")
