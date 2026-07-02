#!/usr/bin/env python3
# coding=utf-8

import argparse
import signal
import sys
import time

import app_frame
import bsp_zmq
from bsp_algorithm import bsp_algorithm


BLE_AA_AND_PREAMBLE = [0xAA, 0xD6, 0xBE, 0x89, 0x8E]
BLE_PDU_TYPES = {
    0x00: "ADV_IND",
    0x01: "ADV_DIRECT_IND",
    0x02: "ADV_NONCONN_IND",
    0x03: "SCAN_REQ/AUX_SCAN_REQ",
    0x04: "SCAN_RSP/AUX_SCAN_RSP",
    0x05: "CONNECT_IND/AUX_CONNECT_REQ",
    0x06: "ADV_SCAN_IND",
    0x07: "ADV_EXT_IND/AUX_ADV_IND",
}


class BlePacketDetector:
    def __init__(
        self,
        channel,
        verbose=False,
        keep_crc_errors=False,
        bit_rate=1000000.0,
        measure_pairs=False,
        pair_window_us=3000.0,
    ):
        self.channel = channel
        self.verbose = verbose
        self.keep_crc_errors = keep_crc_errors
        self.bit_rate = float(bit_rate)
        self.measure_pairs = measure_pairs
        self.pair_window_us = float(pair_window_us)
        self.buffer = bytearray()
        self.stream_offset = 0
        self.detected = 0
        self.crc_errors = 0
        self.short_packets = 0
        self.last_primary = None
        self.pairs = 0
        self.unpaired_secondaries = 0

    def insert_data(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.buffer.extend(data)
        if len(self.buffer) > 8192:
            drop = len(self.buffer) - 1024
            del self.buffer[:drop]
            self.stream_offset += drop

    @staticmethod
    def _hex(data):
        return " ".join(f"{x:02X}" for x in data)

    @staticmethod
    def _mac_from_adv_addr(payload):
        if len(payload) < 6:
            return None
        return ":".join(f"{x:02X}" for x in reversed(payload[:6]))

    @staticmethod
    def _decode_adi(data):
        if len(data) < 2:
            return None
        value = data[0] | (data[1] << 8)
        return (value >> 12) & 0x0F, value & 0x0FFF

    @staticmethod
    def _decode_aux_ptr(data):
        if len(data) < 3:
            return None
        channel = data[0] & 0x3F
        ca = (data[0] >> 6) & 0x01
        offset_units = (data[0] >> 7) & 0x01
        aux_offset = data[1] | ((data[2] & 0x1F) << 8)
        phy = (data[2] >> 5) & 0x07
        offset_us = aux_offset * (300 if offset_units else 30)
        return channel, ca, offset_units, offset_us, phy

    @staticmethod
    def _packet_air_us(total_bytes):
        return total_bytes * 8

    def _byte_delta_us(self, delta_bytes):
        # gr_ble publishes packed demodulated bits; one output byte represents 8 symbols at 1 Mbps.
        return (delta_bytes * 8.0 * 1000000.0) / self.bit_rate

    def _parse_ext_adv_info(self, payload):
        info = {
            "ext_hdr_len": 0,
            "adv_mode": None,
            "flags": 0,
            "adv_data": [],
            "adi": None,
            "aux_ptr": None,
            "adva": None,
        }
        if not payload:
            return info
        ext_hdr_len = payload[0] & 0x3F
        info["ext_hdr_len"] = ext_hdr_len
        info["adv_mode"] = (payload[0] >> 6) & 0x03
        if len(payload) < 1 + ext_hdr_len:
            return info
        ext_hdr = payload[1:1 + ext_hdr_len]
        info["adv_data"] = payload[1 + ext_hdr_len:]
        if not ext_hdr:
            return info
        flags = ext_hdr[0]
        info["flags"] = flags
        pos = 1
        if flags & 0x01 and pos + 6 <= len(ext_hdr):
            info["adva"] = self._mac_from_adv_addr(ext_hdr[pos:pos + 6])
            pos += 6
        if flags & 0x02 and pos + 6 <= len(ext_hdr):
            pos += 6
        if flags & 0x04 and pos + 1 <= len(ext_hdr):
            pos += 1
        if flags & 0x08 and pos + 2 <= len(ext_hdr):
            info["adi"] = self._decode_adi(ext_hdr[pos:pos + 2])
            pos += 2
        if flags & 0x10 and pos + 3 <= len(ext_hdr):
            info["aux_ptr"] = self._decode_aux_ptr(ext_hdr[pos:pos + 3])
            pos += 3
        if flags & 0x20 and pos + 18 <= len(ext_hdr):
            pos += 18
        if flags & 0x40 and pos + 1 <= len(ext_hdr):
            pos += 1
        return info

    def _classify_packet(self, pdu):
        header0, header1 = pdu[0], pdu[1]
        pdu_type = header0 & 0x0F
        length = header1 & 0x3F
        payload = pdu[2:2 + length]
        if pdu_type != 0x07:
            return None, None
        info = self._parse_ext_adv_info(payload)
        flags = info["flags"]
        adv_data = info["adv_data"]
        if (flags & 0x10) and not adv_data:
            return "primary", info
        if (flags & 0x08) and adv_data:
            return "secondary", info
        return "extended", info

    def _format_pair_measurement(self, packet_kind, info, packet_start, packet_total_bytes, packet_no):
        if not self.measure_pairs:
            return None
        if packet_kind == "primary" and info and info.get("aux_ptr"):
            self.last_primary = {
                "packet_no": packet_no,
                "start": packet_start,
                "total_bytes": packet_total_bytes,
                "air_us": self._packet_air_us(packet_total_bytes),
                "aux_offset_us": info["aux_ptr"][3],
                "aux_channel": info["aux_ptr"][0],
            }
            return None
        if packet_kind != "secondary":
            return None
        if self.last_primary is None:
            self.unpaired_secondaries += 1
            return f"unpaired_secondary[{self.unpaired_secondaries}] secondary=#{packet_no} reason=no_recent_primary"

        primary = self.last_primary
        delta_bytes = packet_start - primary["start"]
        delta_us_from_preamble = self._byte_delta_us(delta_bytes)
        delta_us_from_primary_end = delta_us_from_preamble - primary["air_us"]
        error_us = delta_us_from_preamble - primary["aux_offset_us"]
        common = (
            f"primary=#{primary['packet_no']} secondary=#{packet_no} "
            f"delta_bytes={delta_bytes} "
            f"delta_us_from_preamble={delta_us_from_preamble:.1f} "
            f"delta_us_from_primary_end={delta_us_from_primary_end:.1f} "
            f"auxptr_ch={primary['aux_channel']} auxptr_offset_us={primary['aux_offset_us']} "
            f"error_vs_aux_from_preamble_us={error_us:.1f}"
        )

        if abs(error_us) > self.pair_window_us:
            self.unpaired_secondaries += 1
            if delta_us_from_preamble > primary["aux_offset_us"] + self.pair_window_us:
                self.last_primary = None
            return (
                f"unpaired_secondary[{self.unpaired_secondaries}] {common} "
                f"reason=outside_pair_window_us({self.pair_window_us:.1f})"
            )

        self.pairs += 1
        self.last_primary = None
        return f"pair[{self.pairs}] {common}"

    @staticmethod
    def _parse_ad_structures(adv_data):
        items = []
        idx = 0
        while idx < len(adv_data):
            length = adv_data[idx]
            if length == 0:
                break
            end = idx + 1 + length
            if end > len(adv_data):
                items.append(("malformed", adv_data[idx:]))
                break
            ad_type = adv_data[idx + 1]
            value = adv_data[idx + 2:end]
            items.append((ad_type, value))
            idx = end
        return items

    def _describe_adv_data(self, adv_data):
        parts = []
        for ad_type, value in self._parse_ad_structures(adv_data):
            if ad_type == "malformed":
                parts.append(f"malformed={self._hex(value)}")
            elif ad_type == 0x01:
                parts.append(f"Flags=0x{value[0]:02X}" if value else "Flags=<empty>")
            elif ad_type in (0x08, 0x09):
                try:
                    name = bytes(value).decode("ascii", errors="replace")
                except Exception:
                    name = self._hex(value)
                parts.append(f"Name={name}")
            elif ad_type == 0xFF:
                company = value[0] | (value[1] << 8) if len(value) >= 2 else None
                if company is None:
                    parts.append(f"Mfg={self._hex(value)}")
                else:
                    parts.append(f"Mfg=0x{company:04X}:{self._hex(value[2:])}")
            else:
                parts.append(f"AD{ad_type:02X}={self._hex(value)}")
        return ", ".join(parts) if parts else "<none>"

    def _parse_ext_adv_payload(self, payload):
        if not payload:
            return "ExtPayload=<empty>"
        ext_hdr_len = payload[0] & 0x3F
        adv_mode = (payload[0] >> 6) & 0x03
        if len(payload) < 1 + ext_hdr_len:
            return f"ExtHdrLen={ext_hdr_len} AdvMode={adv_mode} short_payload={self._hex(payload)}"
        ext_hdr = payload[1:1 + ext_hdr_len]
        adv_data = payload[1 + ext_hdr_len:]
        fields = []
        pos = 0
        flags = ext_hdr[0] if ext_hdr else 0
        pos += 1 if ext_hdr else 0
        fields.append(f"ExtHdrLen={ext_hdr_len}")
        fields.append(f"AdvMode={adv_mode}")
        fields.append(f"Flags=0x{flags:02X}")
        if flags & 0x01 and pos + 6 <= len(ext_hdr):
            fields.append(f"AdvA={self._mac_from_adv_addr(ext_hdr[pos:pos + 6])}")
            pos += 6
        if flags & 0x02 and pos + 6 <= len(ext_hdr):
            fields.append(f"TargetA={self._mac_from_adv_addr(ext_hdr[pos:pos + 6])}")
            pos += 6
        if flags & 0x04 and pos + 1 <= len(ext_hdr):
            fields.append(f"CTEInfo=0x{ext_hdr[pos]:02X}")
            pos += 1
        if flags & 0x08 and pos + 2 <= len(ext_hdr):
            adi = self._decode_adi(ext_hdr[pos:pos + 2])
            fields.append(f"ADI=SID{adi[0]} DID{adi[1]}")
            pos += 2
        if flags & 0x10 and pos + 3 <= len(ext_hdr):
            aux = self._decode_aux_ptr(ext_hdr[pos:pos + 3])
            fields.append(f"AuxPtr=ch{aux[0]} off{aux[3]}us phy{aux[4]} ca{aux[1]}")
            pos += 3
        if flags & 0x20 and pos + 18 <= len(ext_hdr):
            fields.append(f"SyncInfo={self._hex(ext_hdr[pos:pos + 18])}")
            pos += 18
        if flags & 0x40 and pos + 1 <= len(ext_hdr):
            fields.append(f"TxPower={int.from_bytes(bytes([ext_hdr[pos]]), 'little', signed=True)}dBm")
            pos += 1
        if pos < len(ext_hdr):
            fields.append(f"ExtExtra={self._hex(ext_hdr[pos:])}")
        fields.append(f"AdvData={self._describe_adv_data(adv_data)}")
        return " ".join(fields)

    def _describe_packet(self, pdu, crc_ok, start_pos):
        header0, header1 = pdu[0], pdu[1]
        pdu_type = header0 & 0x0F
        chsel = (header0 >> 5) & 0x01
        txadd = (header0 >> 6) & 0x01
        rxadd = (header0 >> 7) & 0x01
        length = header1 & 0x3F
        payload = pdu[2:2 + length]
        pdu_name = BLE_PDU_TYPES.get(pdu_type, f"UNKNOWN_{pdu_type}")
        base = (
            f"[{self.detected}] ch{self.channel} start={start_pos} "
            f"type={pdu_name} len={length} chsel={chsel} txadd={txadd} rxadd={rxadd} "
            f"crc={'OK' if crc_ok else 'BAD'}"
        )
        if pdu_type == 0x07:
            return base + " " + self._parse_ext_adv_payload(payload)
        if len(payload) >= 6 and pdu_type in (0x00, 0x02, 0x06):
            return base + f" AdvA={self._mac_from_adv_addr(payload)} AdvData={self._describe_adv_data(payload[6:])}"
        return base + f" Payload={self._hex(payload)}"

    def poll(self):
        packets = []
        pattern = bytes(BLE_AA_AND_PREAMBLE)
        while True:
            start = self.buffer.find(pattern)
            if start < 0:
                if len(self.buffer) > len(pattern):
                    drop = len(self.buffer) - len(pattern)
                    del self.buffer[:drop]
                    self.stream_offset += drop
                return packets
            if start > 0:
                del self.buffer[:start]
                self.stream_offset += start
                start = 0
            if len(self.buffer) < 5 + 2:
                return packets
            header_w = list(self.buffer[5:7])
            header = bsp_algorithm.bt_dewhitening(header_w, self.channel)
            length = header[1] & 0x3F
            total = 5 + 2 + length + 3
            if len(self.buffer) < total:
                self.short_packets += 1
                return packets
            pdu_w = list(self.buffer[5:5 + 2 + length + 3])
            pdu = bsp_algorithm.bt_dewhitening(pdu_w, self.channel)
            crc = pdu[-3:]
            calc_crc = bsp_algorithm.bt_crc(pdu, 2 + length)
            crc_ok = crc == calc_crc
            if crc_ok or self.keep_crc_errors:
                self.detected += 1
                packet_start = self.stream_offset + start
                packet_total_bytes = total
                packets.append(self._describe_packet(pdu, crc_ok, packet_start))
                if crc_ok:
                    packet_kind, info = self._classify_packet(pdu)
                    pair_line = self._format_pair_measurement(
                        packet_kind, info, packet_start, packet_total_bytes, self.detected
                    )
                    if pair_line:
                        packets.append(pair_line)
            else:
                self.crc_errors += 1
                if self.verbose:
                    packets.append(
                        f"crc_mismatch start={start} type={BLE_PDU_TYPES.get(pdu[0] & 0x0F, pdu[0] & 0x0F)} "
                        f"len={length} got={self._hex(crc)} calc={self._hex(calc_crc)}"
                    )
            del self.buffer[:total]
            self.stream_offset += total


def ble_channel_to_gr_channel(channel):
    if channel not in app_frame.BLE_CHANS:
        raise ValueError(f"unsupported BLE channel {channel}; valid keys: {sorted(app_frame.BLE_CHANS)}")
    return app_frame.BLE_CHANS[channel]


def run_live(args):
    from gr_ble import gr_ble as gr_block

    tb = gr_block()
    tb.set_ble_channel(ble_channel_to_gr_channel(args.channel))
    tb.set_duration_seconds(args.duration)
    tb.set_num_samples(args.duration * tb.get_sample_rate())
    if args.freq_offset:
        tb.set_freq_offset(args.freq_offset)
    if args.squelch is not None:
        tb.set_squelch_threshold(args.squelch)
    if args.iq_output:
        tb.set_iq_output(args.iq_output)

    zmq_rx = bsp_zmq.bsp_zmq(args.zmq)
    detector = BlePacketDetector(
        args.channel,
        verbose=args.verbose,
        keep_crc_errors=args.keep_crc_errors,
        bit_rate=args.bit_rate,
        measure_pairs=args.measure_pairs,
        pair_window_us=args.pair_window_us,
    )
    stop_at = time.time() + args.duration if args.duration > 0 else None

    def stop_handler(sig=None, frame=None):
        zmq_rx.close()
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(f"BLE detector live: channel={args.channel} gr_channel={ble_channel_to_gr_channel(args.channel)} duration={args.duration}s")
    tb.start()
    try:
        while stop_at is None or time.time() < stop_at:
            if zmq_rx.iswaiting() != 0:
                detector.insert_data(zmq_rx.read())
                for line in detector.poll():
                    print(line)
        print(
            f"summary: detected={detector.detected} crc_errors={detector.crc_errors} short_packets={detector.short_packets}"
        )
    finally:
        zmq_rx.close()
        tb.stop()
        tb.wait()


def run_file(args):
    detector = BlePacketDetector(
        args.channel,
        verbose=args.verbose,
        keep_crc_errors=args.keep_crc_errors,
        bit_rate=args.bit_rate,
        measure_pairs=args.measure_pairs,
        pair_window_us=args.pair_window_us,
    )
    data = open(args.input, "rb").read()
    detector.insert_data(data)
    for line in detector.poll():
        print(line)
    print(f"summary: detected={detector.detected} crc_errors={detector.crc_errors} short_packets={detector.short_packets}")


def main():
    parser = argparse.ArgumentParser(description="Detect BLE packets on a specified channel using std_ble receiver flow")
    parser.add_argument("--channel", type=int, default=37, help="BLE channel number: 37/38/39 or data channel 0..36")
    parser.add_argument("--duration", type=float, default=30.0, help="live capture duration in seconds; <=0 runs until Ctrl-C")
    parser.add_argument("--input", help="optional demodulated byte stream file instead of live GNU Radio/ZMQ")
    parser.add_argument("--zmq", default="tcp://127.0.0.1:55555", help="ZMQ SUB address used by gr_ble")
    parser.add_argument("--freq-offset", type=float, default=0.0, help="receiver frequency offset passed to gr_ble")
    parser.add_argument("--squelch", type=float, default=None, help="override gr_ble squelch threshold")
    parser.add_argument("--iq-output", default=None, help="optional complex64 IQ dump path from gr_ble")
    parser.add_argument("--bit-rate", type=float, default=1000000.0, help="BLE demodulated bit rate used for pair timing estimates")
    parser.add_argument("--measure-pairs", action="store_true", help="measure primary-to-secondary timing when both packets are on one channel")
    parser.add_argument("--pair-window-us", type=float, default=3000.0, help="maximum absolute AuxPtr timing error accepted as a primary/secondary pair")
    parser.add_argument("--keep-crc-errors", action="store_true", help="print packets with CRC mismatch")
    parser.add_argument("--verbose", action="store_true", help="print CRC mismatch diagnostics")
    args = parser.parse_args()

    if args.input:
        run_file(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
