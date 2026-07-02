#!/usr/bin/env python3
# coding=utf-8

import argparse
import queue
import signal
import sys
import threading
import time

from bsp_algorithm import bsp_algorithm


BLE_AA_AND_PREAMBLE = bytes([0xAA, 0xD6, 0xBE, 0x89, 0x8E])
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


def ble_channel_freq_hz(channel):
    if channel == 37:
        return 2402000000
    if channel == 38:
        return 2426000000
    if channel == 39:
        return 2480000000
    if 0 <= channel <= 10:
        return int((2404 + 2 * channel) * 1e6)
    if 11 <= channel <= 36:
        return int((2406 + 2 * channel) * 1e6)
    raise ValueError(f"unsupported BLE channel {channel}")


def fmt_hex(data):
    return " ".join(f"{x:02X}" for x in data)


def mac_from_adv_addr(payload):
    if len(payload) < 6:
        return None
    return ":".join(f"{x:02X}" for x in reversed(payload[:6]))


def decode_adi(data):
    if len(data) < 2:
        return None
    value = data[0] | (data[1] << 8)
    return (value >> 12) & 0x0F, value & 0x0FFF


def decode_aux_ptr(data):
    if len(data) < 3:
        return None
    channel = data[0] & 0x3F
    ca = (data[0] >> 6) & 0x01
    offset_units = (data[0] >> 7) & 0x01
    aux_offset = data[1] | ((data[2] & 0x1F) << 8)
    phy = (data[2] >> 5) & 0x07
    offset_us = aux_offset * (300 if offset_units else 30)
    return {
        "channel": channel,
        "ca": ca,
        "offset_units": offset_units,
        "offset_us": offset_us,
        "phy": phy,
    }


def parse_ad_structures(adv_data):
    items = []
    pos = 0
    while pos < len(adv_data):
        length = adv_data[pos]
        if length == 0:
            break
        end = pos + 1 + length
        if end > len(adv_data):
            items.append(("malformed", adv_data[pos:]))
            break
        items.append((adv_data[pos + 1], adv_data[pos + 2:end]))
        pos = end
    return items


def describe_adv_data(adv_data):
    parts = []
    name = None
    flags = None
    for ad_type, value in parse_ad_structures(adv_data):
        if ad_type == "malformed":
            parts.append(f"malformed={fmt_hex(value)}")
        elif ad_type == 0x01:
            flags = value[0] if value else None
            parts.append(f"Flags=0x{flags:02X}" if flags is not None else "Flags=<empty>")
        elif ad_type in (0x08, 0x09):
            name = bytes(value).decode("ascii", errors="replace")
            parts.append(f"Name={name}")
        elif ad_type == 0xFF:
            company = value[0] | (value[1] << 8) if len(value) >= 2 else None
            if company is None:
                parts.append(f"Mfg={fmt_hex(value)}")
            else:
                parts.append(f"Mfg=0x{company:04X}:{fmt_hex(value[2:])}")
        else:
            parts.append(f"AD{ad_type:02X}={fmt_hex(value)}")
    return {
        "text": ", ".join(parts) if parts else "<none>",
        "name": name,
        "flags": flags,
    }


def parse_ext_adv_payload(payload):
    info = {
        "ext_hdr_len": 0,
        "adv_mode": None,
        "flags": 0,
        "adva": None,
        "adi": None,
        "aux_ptr": None,
        "adv_data": [],
        "adv_data_text": "<none>",
        "name": None,
    }
    if not payload:
        return info
    ext_hdr_len = payload[0] & 0x3F
    info["ext_hdr_len"] = ext_hdr_len
    info["adv_mode"] = (payload[0] >> 6) & 0x03
    if len(payload) < 1 + ext_hdr_len:
        info["short"] = True
        return info

    ext_hdr = payload[1:1 + ext_hdr_len]
    adv_data = payload[1 + ext_hdr_len:]
    info["adv_data"] = adv_data
    if not ext_hdr:
        parsed_ad = describe_adv_data(adv_data)
        info["adv_data_text"] = parsed_ad["text"]
        info["name"] = parsed_ad["name"]
        return info

    flags = ext_hdr[0]
    info["flags"] = flags
    pos = 1
    if flags & 0x01 and pos + 6 <= len(ext_hdr):
        info["adva"] = mac_from_adv_addr(ext_hdr[pos:pos + 6])
        pos += 6
    if flags & 0x02 and pos + 6 <= len(ext_hdr):
        pos += 6
    if flags & 0x04 and pos + 1 <= len(ext_hdr):
        pos += 1
    if flags & 0x08 and pos + 2 <= len(ext_hdr):
        info["adi"] = decode_adi(ext_hdr[pos:pos + 2])
        pos += 2
    if flags & 0x10 and pos + 3 <= len(ext_hdr):
        info["aux_ptr"] = decode_aux_ptr(ext_hdr[pos:pos + 3])
        pos += 3
    if flags & 0x20 and pos + 18 <= len(ext_hdr):
        pos += 18
    if flags & 0x40 and pos + 1 <= len(ext_hdr):
        pos += 1
    parsed_ad = describe_adv_data(adv_data)
    info["adv_data_text"] = parsed_ad["text"]
    info["name"] = parsed_ad["name"]
    return info


class BleStreamParser:
    def __init__(self, channel, keep_crc_errors=False):
        self.channel = channel
        self.keep_crc_errors = keep_crc_errors
        self.buffer = bytearray()
        self.stream_offset = 0
        self.detected = 0
        self.crc_errors = 0

    def reset(self, channel=None, reset_counts=False):
        if channel is not None:
            self.channel = channel
        self.buffer = bytearray()
        self.stream_offset = 0
        if reset_counts:
            self.detected = 0
            self.crc_errors = 0

    def insert_data(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.buffer.extend(data)
        if len(self.buffer) > 65536:
            drop = len(self.buffer) - 4096
            del self.buffer[:drop]
            self.stream_offset += drop

    def poll(self):
        packets = []
        while True:
            start = self.buffer.find(BLE_AA_AND_PREAMBLE)
            if start < 0:
                if len(self.buffer) > len(BLE_AA_AND_PREAMBLE):
                    drop = len(self.buffer) - len(BLE_AA_AND_PREAMBLE)
                    del self.buffer[:drop]
                    self.stream_offset += drop
                return packets
            if start > 0:
                del self.buffer[:start]
                self.stream_offset += start
                start = 0
            if len(self.buffer) < 7:
                return packets

            header = bsp_algorithm.bt_dewhitening(list(self.buffer[5:7]), self.channel)
            length = header[1] & 0x3F
            total = 5 + 2 + length + 3
            if len(self.buffer) < total:
                return packets

            pdu = bsp_algorithm.bt_dewhitening(list(self.buffer[5:5 + 2 + length + 3]), self.channel)
            crc = pdu[-3:]
            calc_crc = bsp_algorithm.bt_crc(pdu, 2 + length)
            crc_ok = crc == calc_crc
            if crc_ok or self.keep_crc_errors:
                self.detected += 1
                packet = self._build_packet(pdu, crc_ok, self.stream_offset + start, total)
                packets.append(packet)
            else:
                self.crc_errors += 1
            del self.buffer[:total]
            self.stream_offset += total

    def _build_packet(self, pdu, crc_ok, start, total):
        header0, header1 = pdu[0], pdu[1]
        pdu_type = header0 & 0x0F
        length = header1 & 0x3F
        payload = pdu[2:2 + length]
        ext = parse_ext_adv_payload(payload) if pdu_type == 0x07 else None
        kind = "other"
        if ext:
            flags = ext["flags"]
            if (flags & 0x10) and not ext["adv_data"]:
                kind = "primary"
            elif (flags & 0x08) and ext["adv_data"]:
                kind = "secondary"
            else:
                kind = "extended"
        return {
            "packet_no": self.detected,
            "channel": self.channel,
            "start": start,
            "total_bytes": total,
            "pdu": pdu,
            "pdu_type": pdu_type,
            "pdu_name": BLE_PDU_TYPES.get(pdu_type, f"UNKNOWN_{pdu_type}"),
            "length": length,
            "chsel": (header0 >> 5) & 0x01,
            "txadd": (header0 >> 6) & 0x01,
            "rxadd": (header0 >> 7) & 0x01,
            "crc_ok": crc_ok,
            "kind": kind,
            "ext": ext,
            "monotonic": time.monotonic(),
        }


class ExtendedAdvMatcher:
    def __init__(
        self,
        secondary_channel,
        match_window_s=1.0,
        timing_window_us=1000.0,
        expected_name=None,
        event_interval_us=0.0,
    ):
        self.secondary_channel = secondary_channel
        self.match_window_s = match_window_s
        self.timing_window_us = timing_window_us
        self.expected_name = expected_name
        self.event_interval_us = event_interval_us
        self.primaries = []
        self.secondaries = []
        self.events = 0
        self.expired_primaries = 0
        self.expired_secondaries = 0

    @staticmethod
    def _adi_text(adi):
        return f"SID{adi[0]} DID{adi[1]}" if adi else "<none>"

    @staticmethod
    def _packet_start(packet):
        return packet.get("abs_start", packet["start"])

    @classmethod
    def _start_delta_us(cls, primary, secondary):
        return (cls._packet_start(secondary) - cls._packet_start(primary)) * 8.0

    def _fold_timing(self, delta_us, aux_offset_us):
        if self.event_interval_us <= 0:
            return None
        event_skip = int(round((delta_us - aux_offset_us) / self.event_interval_us))
        folded_delta_us = delta_us - event_skip * self.event_interval_us
        folded_error_us = folded_delta_us - aux_offset_us
        return {
            "event_skip": event_skip,
            "folded_delta_us": folded_delta_us,
            "folded_error_us": folded_error_us,
        }

    def _timing_metrics(self, primary, secondary):
        aux = primary["ext"]["aux_ptr"]
        start_delta_us = self._start_delta_us(primary, secondary)
        error_vs_aux_us = start_delta_us - aux["offset_us"]
        wall_delta_us = (secondary["monotonic"] - primary["monotonic"]) * 1000000.0
        metrics = {
            "start_delta_us": start_delta_us,
            "error_vs_aux_us": error_vs_aux_us,
            "wall_delta_us": wall_delta_us,
            "wall_delta_ms": wall_delta_us / 1000.0,
            "match_error_us": error_vs_aux_us,
            "timing_source": "stream",
        }
        stream_fold = self._fold_timing(start_delta_us, aux["offset_us"])
        wall_fold = self._fold_timing(wall_delta_us, aux["offset_us"])
        if stream_fold:
            metrics.update(stream_fold)
            metrics["match_error_us"] = stream_fold["folded_error_us"]
            metrics["timing_source"] = "stream_folded"
        if wall_fold:
            metrics["wall_event_skip"] = wall_fold["event_skip"]
            metrics["wall_folded_delta_us"] = wall_fold["folded_delta_us"]
            metrics["wall_folded_error_us"] = wall_fold["folded_error_us"]
            if abs(wall_fold["folded_error_us"]) < abs(metrics["match_error_us"]):
                metrics["match_error_us"] = wall_fold["folded_error_us"]
                metrics["timing_source"] = "wall_folded"
        return metrics

    def _format_timing_metrics(self, metrics):
        text = (
            f"start_delta_us={metrics['start_delta_us']:.1f} "
            f"error_vs_aux_us={metrics['error_vs_aux_us']:.1f}"
        )
        if self.event_interval_us > 0:
            text += (
                f" event_skip={metrics['event_skip']} "
                f"folded_delta_us={metrics['folded_delta_us']:.1f} "
                f"folded_error_vs_aux_us={metrics['folded_error_us']:.1f} "
                f"wall_event_skip={metrics['wall_event_skip']} "
                f"wall_folded_delta_us={metrics['wall_folded_delta_us']:.1f} "
                f"wall_folded_error_vs_aux_us={metrics['wall_folded_error_us']:.1f} "
                f"timing_source={metrics['timing_source']} "
                f"match_error_us={metrics['match_error_us']:.1f}"
            )
        return text

    @staticmethod
    def _same_identity(primary, secondary):
        pri_ext = primary["ext"]
        sec_ext = secondary["ext"]
        aux = pri_ext["aux_ptr"]
        if not aux or aux["channel"] != secondary["channel"]:
            return False
        if pri_ext["adi"] and sec_ext["adi"] and pri_ext["adi"] != sec_ext["adi"]:
            return False
        if pri_ext["adva"] and sec_ext["adva"] and pri_ext["adva"] != sec_ext["adva"]:
            return False
        return True

    def _timing_error_us(self, primary, secondary):
        return self._timing_metrics(primary, secondary)["match_error_us"]

    def _same_event(self, primary, secondary):
        if not self._same_identity(primary, secondary):
            return False
        return abs(self._timing_error_us(primary, secondary)) <= self.timing_window_us

    def _best_event_score(self, primary, secondary):
        if not self._same_identity(primary, secondary):
            return None
        return abs(self._timing_error_us(primary, secondary))

    def _nearest_candidate(self, packet, candidates):
        best = None
        best_key = None
        packet_is_primary = packet["kind"] == "primary"
        for candidate in candidates:
            primary = packet if packet_is_primary else candidate
            secondary = candidate if packet_is_primary else packet
            identity_ok = self._same_identity(primary, secondary)
            if identity_ok:
                score = abs(self._timing_error_us(primary, secondary))
                key = (0, score)
            else:
                key = (1, abs((secondary["monotonic"] - primary["monotonic"]) * 1000000.0))
            if best_key is None or key < best_key:
                best = candidate
                best_key = key
        return best

    def _format_nearest_candidate(self, packet, candidate):
        if candidate is None:
            opposite = "secondary" if packet["kind"] == "primary" else "primary"
            return f"nearest_{opposite}=<none> reason=no_candidate"

        if packet["kind"] == "primary":
            primary = packet
            secondary = candidate
            opposite = "secondary"
        else:
            primary = candidate
            secondary = packet
            opposite = "primary"

        pri_ext = primary["ext"]
        sec_ext = secondary["ext"]
        identity_ok = self._same_identity(primary, secondary)
        aux = pri_ext["aux_ptr"]
        metrics = self._timing_metrics(primary, secondary) if aux else None
        wall_delta_ms = (secondary["monotonic"] - primary["monotonic"]) * 1000.0
        if not identity_ok:
            reason = "identity_mismatch"
        elif abs(metrics["match_error_us"]) > self.timing_window_us:
            reason = "timing_error"
        else:
            reason = "unmatched"
        timing_text = self._format_timing_metrics(metrics) if metrics else "start_delta_us=nan error_vs_aux_us=nan"

        return (
            f"nearest_{opposite}=ch{candidate['channel']}#{candidate['packet_no']} "
            f"reason={reason} "
            f"primary_ADI={self._adi_text(pri_ext['adi'])} secondary_ADI={self._adi_text(sec_ext['adi'])} "
            f"primary_AdvA={pri_ext['adva']} secondary_AdvA={sec_ext['adva']} "
            f"{timing_text} wall_delta_ms={wall_delta_ms:.3f}"
        )

    def _cleanup(self, now):
        lines = []
        old_primaries = list(self.primaries)
        old_secondaries = list(self.secondaries)
        keep = []
        for primary in self.primaries:
            if now - primary["monotonic"] <= self.match_window_s:
                keep.append(primary)
            else:
                self.expired_primaries += 1
                ext = primary["ext"]
                aux = ext["aux_ptr"]
                lines.append(
                    f"primary-only[{self.expired_primaries}] ch{primary['channel']} #{primary['packet_no']} "
                    f"ADI={self._adi_text(ext['adi'])} AdvA={ext['adva']} "
                    f"AuxPtr=ch{aux['channel']}+{aux['offset_us']}us "
                    f"aux_window=[{aux['offset_us'] - self.timing_window_us:.0f},"
                    f"{aux['offset_us'] + self.timing_window_us:.0f}]us "
                    f"{self._format_nearest_candidate(primary, self._nearest_candidate(primary, old_secondaries))}"
                )
        self.primaries = keep

        keep = []
        for secondary in self.secondaries:
            if now - secondary["monotonic"] <= self.match_window_s:
                keep.append(secondary)
            else:
                self.expired_secondaries += 1
                ext = secondary["ext"]
                lines.append(
                    f"secondary-only[{self.expired_secondaries}] ch{secondary['channel']} #{secondary['packet_no']} "
                    f"ADI={self._adi_text(ext['adi'])} AdvA={ext['adva']} AdvData={ext['adv_data_text']} "
                    f"{self._format_nearest_candidate(secondary, self._nearest_candidate(secondary, old_primaries))}"
                )
        self.secondaries = keep
        return lines

    def flush(self):
        return self._cleanup(float("inf"))

    def _format_event(self, primary, secondary):
        self.events += 1
        pri_ext = primary["ext"]
        sec_ext = secondary["ext"]
        aux = pri_ext["aux_ptr"]
        wall_delta_ms = (secondary["monotonic"] - primary["monotonic"]) * 1000.0
        timing_text = self._format_timing_metrics(self._timing_metrics(primary, secondary))
        name_ok = ""
        if self.expected_name:
            name_ok = " name_ok=1" if sec_ext["name"] == self.expected_name else " name_ok=0"
        return (
            f"EXT_ADV_EVENT[{self.events}] primary_ch={primary['channel']} secondary_ch={secondary['channel']} "
            f"AuxPtr=ch{aux['channel']}+{aux['offset_us']}us phy{aux['phy']} "
            f"ADI={self._adi_text(sec_ext['adi'])} AdvA={sec_ext['adva']} "
            f"Name={sec_ext['name']} {timing_text} wall_delta_ms={wall_delta_ms:.3f}{name_ok}"
        )

    def _try_match_primary(self, primary):
        best_idx = None
        best_score = None
        for idx in range(len(self.secondaries) - 1, -1, -1):
            secondary = self.secondaries[idx]
            score = self._best_event_score(primary, secondary)
            if score is None:
                continue
            if best_score is None or score < best_score:
                best_idx = idx
                best_score = score
        if best_idx is not None and best_score is not None and best_score <= self.timing_window_us:
            secondary = self.secondaries.pop(best_idx)
            return self._format_event(primary, secondary)
        return None

    def _try_match_secondary(self, secondary):
        best_idx = None
        best_score = None
        for idx in range(len(self.primaries) - 1, -1, -1):
            primary = self.primaries[idx]
            score = self._best_event_score(primary, secondary)
            if score is None:
                continue
            if best_score is None or score < best_score:
                best_idx = idx
                best_score = score
        if best_idx is not None and best_score is not None and best_score <= self.timing_window_us:
            primary = self.primaries.pop(best_idx)
            return self._format_event(primary, secondary)
        return None

    def feed(self, packet):
        lines = self._cleanup(packet["monotonic"])
        if packet["kind"] == "primary":
            line = self._try_match_primary(packet)
            if line:
                lines.append(line)
            else:
                self.primaries.append(packet)
        elif packet["kind"] == "secondary":
            line = self._try_match_secondary(packet)
            if line:
                lines.append(line)
            else:
                self.secondaries.append(packet)
        return lines

def describe_packet(packet):
    ext = packet["ext"]
    abs_start_text = f" abs_start={packet['abs_start']}" if "abs_start" in packet else ""
    base = (
        f"[ch{packet['channel']} #{packet['packet_no']}] start={packet['start']}{abs_start_text} "
        f"type={packet['pdu_name']} len={packet['length']} "
        f"chsel={packet['chsel']} txadd={packet['txadd']} rxadd={packet['rxadd']} "
        f"crc={'OK' if packet['crc_ok'] else 'BAD'}"
    )
    if not ext:
        return base
    parts = [
        base,
        f"kind={packet['kind']}",
        f"ExtHdrLen={ext['ext_hdr_len']}",
        f"Flags=0x{ext['flags']:02X}",
    ]
    if ext["adva"]:
        parts.append(f"AdvA={ext['adva']}")
    if ext["adi"]:
        parts.append(f"ADI=SID{ext['adi'][0]} DID{ext['adi'][1]}")
    if ext["aux_ptr"]:
        aux = ext["aux_ptr"]
        parts.append(f"AuxPtr=ch{aux['channel']} off{aux['offset_us']}us phy{aux['phy']}")
    parts.append(f"AdvData={ext['adv_data_text']}")
    return " ".join(parts)


def adi_text(adi):
    return f"SID{adi[0]} DID{adi[1]}" if adi else "<none>"


def aux_expectation_text(aux, args):
    expected_offset = args.expected_aux_offset_us if args.expected_aux_offset_us > 0 else None
    channel_ok = aux["channel"] == args.secondary_channel
    offset_ok = expected_offset is None or aux["offset_us"] == expected_offset
    expected = f"ch{args.secondary_channel}"
    if expected_offset is not None:
        expected += f"+{expected_offset}us"
    return f"aux_expected={'OK' if channel_ok and offset_ok else 'MISMATCH'} expected={expected}"


def build_top_block(args, packet_queue):
    from gnuradio import blocks
    from gnuradio import digital
    from gnuradio import filter
    from gnuradio import gr
    from gnuradio.filter import firdes
    import numpy
    import osmosdr

    class BlePacketSink(gr.sync_block):
        def __init__(self, channel, name):
            gr.sync_block.__init__(
                self,
                name=name,
                in_sig=[numpy.uint8],
                out_sig=None,
            )
            self.parser = BleStreamParser(channel, keep_crc_errors=args.keep_crc_errors)
            self.channel = channel
            self.abs_stream_offset = 0
            self.parser_base_offset = 0

        def work(self, input_items, output_items):
            del output_items
            data = bytes(input_items[0])
            if data:
                self.parser.insert_data(data)
                packets = self.parser.poll()
                for packet in packets:
                    packet["abs_start"] = self.parser_base_offset + packet["start"]
                self.abs_stream_offset += len(data)
                for packet in packets:
                    packet_queue.put(packet)
            return len(input_items[0])

    class DualBleTopBlock(gr.top_block):
        def __init__(self):
            gr.top_block.__init__(self, "BLE Extended Advertising Single-Timeline Sniffer", catch_exceptions=True)

            sample_rate = float(args.sample_rate)
            data_rate = 1e6
            sps = int(sample_rate / data_rate)
            taps = firdes.low_pass(1, sample_rate, args.cutoff, args.transition)

            self.source = osmosdr.source(args=f"numchan=1 {args.osmosdr_args}")
            self.source.set_sample_rate(sample_rate)
            self.source.set_center_freq(args.center_freq, 0)
            self.source.set_freq_corr(0, 0)
            self.source.set_dc_offset_mode(0, 0)
            self.source.set_iq_balance_mode(0, 0)
            self.source.set_gain_mode(False, 0)
            self.source.set_gain(args.gain, 0)
            self.source.set_if_gain(args.if_gain, 0)
            self.source.set_bb_gain(args.bb_gain, 0)
            self.source.set_bandwidth(0, 0)
            self.head = blocks.head(gr.sizeof_gr_complex, int(args.duration * sample_rate)) if args.duration > 0 else None

            src = self.source
            if self.head:
                self.connect((self.source, 0), (self.head, 0))
                src = self.head

            self.blocks = []
            self.packet_sinks = {}
            for channel, role in (
                (args.primary_channel, "primary"),
                (args.secondary_channel, "secondary"),
            ):
                offset = ble_channel_freq_hz(channel) - args.center_freq
                xlate = filter.freq_xlating_fir_filter_ccc(1, taps, offset, sample_rate)
                demod = digital.gfsk_demod(
                    samples_per_symbol=sps,
                    sensitivity=((numpy.pi * 0.5) / sps),
                    gain_mu=0.175,
                    mu=0.5,
                    omega_relative_limit=0.005,
                    freq_error=0.0,
                    verbose=False,
                    log=False,
                )
                pack = blocks.unpacked_to_packed_bb(1, gr.GR_LSB_FIRST)
                sink = BlePacketSink(channel, f"BLE packet sink ch{channel}")
                self.connect((src, 0), (xlate, 0))
                self.connect((xlate, 0), (demod, 0))
                self.connect((demod, 0), (pack, 0))
                self.connect((pack, 0), (sink, 0))
                self.blocks.extend([xlate, demod, pack, sink])
                self.packet_sinks[role] = sink

    return DualBleTopBlock()


def build_hop_top_block(args, packet_queue):
    from gnuradio import blocks
    from gnuradio import digital
    from gnuradio import gr
    import numpy
    import osmosdr

    class HopBlePacketSink(gr.sync_block):
        def __init__(self, channel):
            gr.sync_block.__init__(
                self,
                name="BLE hop packet sink",
                in_sig=[numpy.uint8],
                out_sig=None,
            )
            self.lock = threading.RLock()
            self.parser = BleStreamParser(channel, keep_crc_errors=args.keep_crc_errors)
            self.abs_stream_offset = 0
            self.parser_base_offset = 0

        def set_channel(self, channel):
            with self.lock:
                self.parser_base_offset = self.abs_stream_offset
                self.parser.reset(channel=channel)

        def work(self, input_items, output_items):
            del output_items
            data = bytes(input_items[0])
            if data:
                with self.lock:
                    self.parser.insert_data(data)
                    packets = self.parser.poll()
                    for packet in packets:
                        packet["abs_start"] = self.parser_base_offset + packet["start"]
                    self.abs_stream_offset += len(data)
                for packet in packets:
                    packet_queue.put(packet)
            return len(input_items[0])

    class HopBleTopBlock(gr.top_block):
        def __init__(self):
            gr.top_block.__init__(self, "BLE Extended Advertising Hop Sniffer", catch_exceptions=True)

            sample_rate = float(args.sample_rate)
            data_rate = 1e6
            sps = int(sample_rate / data_rate)

            self.source = osmosdr.source(args=f"numchan=1 {args.osmosdr_args}")
            self.source.set_sample_rate(sample_rate)
            self.source.set_center_freq(args.center_freq, 0)
            self.source.set_freq_corr(0, 0)
            self.source.set_dc_offset_mode(0, 0)
            self.source.set_iq_balance_mode(0, 0)
            self.source.set_gain_mode(False, 0)
            self.source.set_gain(args.gain, 0)
            self.source.set_if_gain(args.if_gain, 0)
            self.source.set_bb_gain(args.bb_gain, 0)
            self.source.set_bandwidth(0, 0)
            self.head = blocks.head(gr.sizeof_gr_complex, int(args.duration * sample_rate)) if args.duration > 0 else None

            src = self.source
            if self.head:
                self.connect((self.source, 0), (self.head, 0))
                src = self.head

            self.demod = digital.gfsk_demod(
                samples_per_symbol=sps,
                sensitivity=((numpy.pi * 0.5) / sps),
                gain_mu=0.175,
                mu=0.5,
                omega_relative_limit=0.005,
                freq_error=0.0,
                verbose=False,
                log=False,
            )
            self.pack = blocks.unpacked_to_packed_bb(1, gr.GR_LSB_FIRST)
            self.packet_sink = HopBlePacketSink(args.primary_channel)

            self.connect((src, 0), (self.demod, 0))
            self.connect((self.demod, 0), (self.pack, 0))
            self.connect((self.pack, 0), (self.packet_sink, 0))

        def tune_channel(self, channel, settle_us):
            self.source.set_center_freq(ble_channel_freq_hz(channel), 0)
            if settle_us > 0:
                time.sleep(settle_us / 1e6)
            self.packet_sink.set_channel(channel)

    return HopBleTopBlock()


def validate_args(args):
    primary_freq = ble_channel_freq_hz(args.primary_channel)
    secondary_freq = ble_channel_freq_hz(args.secondary_channel)
    if args.event_interval_us < 0:
        raise ValueError("event-interval-us must be non-negative")
    if args.mode == "fixed":
        if args.fixed_channel is None:
            args.fixed_channel = args.secondary_channel
        fixed_freq = ble_channel_freq_hz(args.fixed_channel)
        if args.center_freq is None:
            args.center_freq = fixed_freq
        if args.primary_settle_us < 0:
            raise ValueError("primary-settle-us must be non-negative")
        return
    if args.mode == "hop":
        if args.center_freq is None:
            args.center_freq = primary_freq
        if args.aux_window_us <= 0:
            raise ValueError("aux-window-us must be positive")
        if args.expected_aux_offset_us < 0:
            raise ValueError("expected-aux-offset-us must be non-negative")
        if args.retune_guard_us < 0 or args.primary_settle_us < 0 or args.secondary_settle_us < 0:
            raise ValueError("retune/settle timing values must be non-negative")
        return
    if args.center_freq is None:
        args.center_freq = (primary_freq + secondary_freq) / 2.0
    max_offset = max(abs(primary_freq - args.center_freq), abs(secondary_freq - args.center_freq))
    if max_offset + args.cutoff + args.transition > args.sample_rate / 2.0:
        raise ValueError(
            "sample rate is too low for the requested channel spacing; "
            f"need > {2 * (max_offset + args.cutoff + args.transition):.0f} sps"
        )


def run_wide(args):
    validate_args(args)
    packet_queue = queue.Queue()
    tb = build_top_block(args, packet_queue)
    matcher = ExtendedAdvMatcher(
        secondary_channel=args.secondary_channel,
        match_window_s=args.match_window_ms / 1000.0,
        timing_window_us=args.timing_window_us,
        expected_name=args.expected_name,
        event_interval_us=args.event_interval_us,
    )
    stop_at = time.monotonic() + args.duration if args.duration > 0 else None

    def stop_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(
        "BLE exadv HackRF sniffer: "
        f"center={args.center_freq / 1e6:.3f}MHz sample_rate={args.sample_rate / 1e6:.1f}Msps "
        f"primary_ch={args.primary_channel} secondary_ch={args.secondary_channel} "
        f"event_interval_us={args.event_interval_us:.0f} timeline=inproc"
    )
    tb.start()
    try:
        while stop_at is None or time.monotonic() < stop_at:
            try:
                packet = packet_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if args.print_packets:
                print(describe_packet(packet))
            for line in matcher.feed(packet):
                print(line)
        for line in matcher.flush():
            print(line)
        primary_parser = tb.packet_sinks["primary"].parser
        secondary_parser = tb.packet_sinks["secondary"].parser
        print(
            "summary: "
            f"primary_packets={primary_parser.detected} "
            f"secondary_packets={secondary_parser.detected} "
            f"matched_events={matcher.events} "
            f"primary_crc_errors={primary_parser.crc_errors} "
            f"secondary_crc_errors={secondary_parser.crc_errors}"
        )
    finally:
        tb.stop()
        tb.wait()


def packet_identity_matches(primary, secondary):
    pri_ext = primary["ext"]
    sec_ext = secondary["ext"]
    if pri_ext["adi"] and sec_ext["adi"] and pri_ext["adi"] != sec_ext["adi"]:
        return False
    if pri_ext["adva"] and sec_ext["adva"] and pri_ext["adva"] != sec_ext["adva"]:
        return False
    return True


def format_hop_event(event_no, primary, secondary, retuned_at, window_end, expected_name):
    pri_ext = primary["ext"]
    sec_ext = secondary["ext"]
    aux = pri_ext["aux_ptr"]
    wall_delta_ms = (secondary["monotonic"] - primary["monotonic"]) * 1000.0
    primary_start = primary.get("abs_start", primary["start"])
    secondary_start = secondary.get("abs_start", secondary["start"])
    start_delta_us = (secondary_start - primary_start) * 8.0
    aux_error_us = start_delta_us - aux["offset_us"]
    retune_after_primary_ms = (retuned_at - primary["monotonic"]) * 1000.0
    window_left_ms = max(0.0, (window_end - secondary["monotonic"]) * 1000.0)
    name_ok = ""
    if expected_name:
        name_ok = " name_ok=1" if sec_ext["name"] == expected_name else " name_ok=0"
    return (
        f"EXT_ADV_EVENT[{event_no}] mode=hop primary_ch={primary['channel']} secondary_ch={secondary['channel']} "
        f"AuxPtr=ch{aux['channel']}+{aux['offset_us']}us phy{aux['phy']} "
        f"ADI={adi_text(sec_ext['adi'])} AdvA={sec_ext['adva']} "
        f"Name={sec_ext['name']} start_delta_us={start_delta_us:.1f} "
        f"error_vs_aux_us={aux_error_us:.1f} wall_delta_ms={wall_delta_ms:.3f} "
        f"retune_after_primary_ms={retune_after_primary_ms:.3f} window_left_ms={window_left_ms:.3f}{name_ok}"
    )


def drain_packet_queue(packet_queue):
    while True:
        try:
            packet_queue.get_nowait()
        except queue.Empty:
            return


def run_hop(args):
    validate_args(args)
    packet_queue = queue.Queue()
    tb = build_hop_top_block(args, packet_queue)
    stop_at = time.monotonic() + args.duration if args.duration > 0 else None
    active_primary = None
    primary_packets = 0
    secondary_packets = 0
    matched_events = 0
    aux_misses = 0
    identity_mismatches = 0
    aux_scan_crc_errors = 0
    aux_scan_bad_crc_packets = 0
    aux_scan_non_secondary_packets = 0
    aux_window_crc_errors_start = 0
    aux_window_bad_crc_packets = 0
    aux_window_non_secondary_packets = 0
    state = "SCAN_PRIMARY"
    aux_deadline = 0.0
    aux_window_end = 0.0
    retuned_at = 0.0

    def stop_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(
        "BLE exadv HackRF sniffer: "
        f"mode=hop primary_ch={args.primary_channel} secondary_ch={args.secondary_channel} "
        f"sample_rate={args.sample_rate / 1e6:.1f}Msps "
        f"retune_guard_us={args.retune_guard_us:.0f} secondary_settle_us={args.secondary_settle_us:.0f} "
        f"aux_window_us={args.aux_window_us:.0f} "
        f"expected_aux=ch{args.secondary_channel}"
        f"{'+' + str(args.expected_aux_offset_us) + 'us' if args.expected_aux_offset_us > 0 else ''}"
    )

    tb.start()
    try:
        tb.tune_channel(args.primary_channel, args.primary_settle_us)
        print(f"HOP state=SCAN_PRIMARY ch{args.primary_channel}")
        while stop_at is None or time.monotonic() < stop_at:
            now = time.monotonic()
            if state == "SCAN_AUX" and now >= aux_window_end:
                aux_misses += 1
                ext = active_primary["ext"]
                aux = ext["aux_ptr"]
                window_crc_errors = tb.packet_sink.parser.crc_errors - aux_window_crc_errors_start
                aux_scan_crc_errors += window_crc_errors
                aux_scan_bad_crc_packets += aux_window_bad_crc_packets
                aux_scan_non_secondary_packets += aux_window_non_secondary_packets
                print(
                    f"aux-window-miss[{aux_misses}] reason=no_secondary "
                    f"primary_ch={active_primary['channel']} AuxPtr=ch{aux['channel']}+{aux['offset_us']}us "
                    f"{aux_expectation_text(aux, args)} "
                    f"window_us={args.aux_window_us:.0f} "
                    f"crc_errors_in_window={window_crc_errors} "
                    f"bad_crc_packets_in_window={aux_window_bad_crc_packets} "
                    f"non_secondary_packets_in_window={aux_window_non_secondary_packets}"
                )
                tb.tune_channel(args.primary_channel, args.primary_settle_us)
                drain_packet_queue(packet_queue)
                active_primary = None
                state = "SCAN_PRIMARY"
                print(f"HOP state=SCAN_PRIMARY ch{args.primary_channel}")
                continue

            try:
                packet = packet_queue.get(timeout=0.01)
            except queue.Empty:
                continue

            if args.print_packets:
                print(describe_packet(packet))

            if state == "SCAN_PRIMARY":
                if packet["kind"] != "primary":
                    continue
                ext = packet["ext"]
                aux = ext["aux_ptr"]
                if not aux:
                    continue
                primary_packets += 1
                active_primary = packet
                aux_delay_s = aux["offset_us"] / 1e6
                retune_delay_s = max(0.0, aux_delay_s - args.retune_guard_us / 1e6)
                aux_deadline = packet["monotonic"] + aux_delay_s
                if retune_delay_s > 0:
                    time.sleep(retune_delay_s)
                tb.tune_channel(aux["channel"], args.secondary_settle_us)
                drain_packet_queue(packet_queue)
                retuned_at = time.monotonic()
                aux_window_crc_errors_start = tb.packet_sink.parser.crc_errors
                aux_window_bad_crc_packets = 0
                aux_window_non_secondary_packets = 0
                aux_window_end = max(aux_deadline, retuned_at) + args.aux_window_us / 1e6
                state = "SCAN_AUX"
                print(
                    f"PRIMARY ch{packet['channel']} #{packet['packet_no']} "
                    f"ADI={adi_text(ext['adi'])} AdvA={ext['adva']} "
                    f"AuxPtr=ch{aux['channel']}+{aux['offset_us']}us "
                    f"{aux_expectation_text(aux, args)}"
                )
                print(
                    f"HOP state=SCAN_AUX ch{aux['channel']} "
                    f"retune_delay_ms={retune_delay_s * 1000.0:.3f} "
                    f"settle_ms={args.secondary_settle_us / 1000.0:.3f} "
                    f"aux_deadline_relative_ms={aux_delay_s * 1000.0:.3f} "
                    f"ready_after_primary_ms={(retuned_at - packet['monotonic']) * 1000.0:.3f} "
                    f"deadline_after_ready_ms={(aux_deadline - retuned_at) * 1000.0:.3f} "
                    f"window_ms={args.aux_window_us / 1000.0:.3f}"
                )
                continue

            if state == "SCAN_AUX":
                if not packet["crc_ok"]:
                    aux_window_bad_crc_packets += 1
                if packet["kind"] != "secondary":
                    aux_window_non_secondary_packets += 1
                    continue
                secondary_packets += 1
                if not packet_identity_matches(active_primary, packet):
                    identity_mismatches += 1
                    print(
                        f"aux-identity-mismatch[{identity_mismatches}] "
                        f"secondary_ch={packet['channel']} AdvData={packet['ext']['adv_data_text']}"
                    )
                    continue
                matched_events += 1
                print(format_hop_event(matched_events, active_primary, packet, retuned_at, aux_window_end, args.expected_name))
                window_crc_errors = tb.packet_sink.parser.crc_errors - aux_window_crc_errors_start
                aux_scan_crc_errors += window_crc_errors
                aux_scan_bad_crc_packets += aux_window_bad_crc_packets
                aux_scan_non_secondary_packets += aux_window_non_secondary_packets
                tb.tune_channel(args.primary_channel, args.primary_settle_us)
                drain_packet_queue(packet_queue)
                active_primary = None
                state = "SCAN_PRIMARY"
                print(f"HOP state=SCAN_PRIMARY ch{args.primary_channel}")

        if state == "SCAN_AUX":
            window_crc_errors = tb.packet_sink.parser.crc_errors - aux_window_crc_errors_start
            aux_scan_crc_errors += window_crc_errors
            aux_scan_bad_crc_packets += aux_window_bad_crc_packets
            aux_scan_non_secondary_packets += aux_window_non_secondary_packets
        parser = tb.packet_sink.parser
        print(
            "summary: "
            f"mode=hop primary_packets={primary_packets} "
            f"secondary_packets={secondary_packets} "
            f"matched_events={matched_events} "
            f"aux_misses={aux_misses} "
            f"identity_mismatches={identity_mismatches} "
            f"aux_scan_crc_errors={aux_scan_crc_errors} "
            f"aux_scan_bad_crc_packets={aux_scan_bad_crc_packets} "
            f"aux_scan_non_secondary_packets={aux_scan_non_secondary_packets} "
            f"crc_errors={parser.crc_errors}"
        )
    finally:
        tb.stop()
        tb.wait()


def run_fixed(args):
    validate_args(args)
    packet_queue = queue.Queue()
    tb = build_hop_top_block(args, packet_queue)
    stop_at = time.monotonic() + args.duration if args.duration > 0 else None
    counts = {
        "primary": 0,
        "secondary": 0,
        "extended": 0,
        "other": 0,
    }

    def stop_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(
        "BLE exadv HackRF sniffer: "
        f"mode=fixed ch{args.fixed_channel} center={args.center_freq / 1e6:.3f}MHz "
        f"sample_rate={args.sample_rate / 1e6:.1f}Msps"
    )
    tb.start()
    try:
        tb.tune_channel(args.fixed_channel, args.primary_settle_us)
        while stop_at is None or time.monotonic() < stop_at:
            try:
                packet = packet_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            counts[packet["kind"]] = counts.get(packet["kind"], 0) + 1
            if args.print_packets or packet["kind"] in ("primary", "secondary"):
                print(describe_packet(packet))

        parser = tb.packet_sink.parser
        print(
            "summary: "
            f"mode=fixed channel={args.fixed_channel} "
            f"primary_packets={counts.get('primary', 0)} "
            f"secondary_packets={counts.get('secondary', 0)} "
            f"extended_packets={counts.get('extended', 0)} "
            f"other_packets={counts.get('other', 0)} "
            f"crc_errors={parser.crc_errors}"
        )
    finally:
        tb.stop()
        tb.wait()


def run(args):
    if args.mode == "hop":
        run_hop(args)
    elif args.mode == "fixed":
        run_fixed(args)
    else:
        run_wide(args)


def main():
    parser = argparse.ArgumentParser(description="HackRF BLE extended advertising sniffer")
    parser.add_argument("--mode", choices=("hop", "wide", "fixed"), default="hop", help="hop retunes after primary; wide processes primary/secondary together; fixed listens on one channel")
    parser.add_argument("--primary-channel", type=int, default=37, help="primary BLE advertising channel")
    parser.add_argument("--secondary-channel", type=int, default=3, help="secondary BLE data channel from AuxPtr")
    parser.add_argument("--fixed-channel", type=int, default=None, help="fixed mode BLE channel; default is --secondary-channel")
    parser.add_argument("--center-freq", type=float, default=None, help="HackRF center frequency in Hz; hop default is primary channel, wide default is midpoint, fixed default is fixed channel")
    parser.add_argument("--sample-rate", type=float, default=4e6, help="HackRF sample rate; use >=20e6 for --mode wide with ch37/ch3")
    parser.add_argument("--duration", type=float, default=30.0, help="capture duration in seconds; <=0 runs until Ctrl-C")
    parser.add_argument("--cutoff", type=float, default=850e3, help="per-channel low-pass cutoff")
    parser.add_argument("--transition", type=float, default=300e3, help="per-channel low-pass transition width")
    parser.add_argument("--gain", type=float, default=40, help="HackRF RF gain")
    parser.add_argument("--if-gain", type=float, default=32, help="HackRF IF gain")
    parser.add_argument("--bb-gain", type=float, default=16, help="HackRF baseband gain")
    parser.add_argument("--osmosdr-args", default="hackrf=0", help="osmosdr source args")
    parser.add_argument("--match-window-ms", type=float, default=1000.0, help="wall-clock window for primary/secondary association")
    parser.add_argument("--timing-window-us", type=float, default=1000.0, help="maximum absolute primary-to-secondary AuxPtr timing error accepted as one event")
    parser.add_argument("--event-interval-us", type=float, default=0.0, help="wide mode: expected advertising event period; >0 folds candidate timing by this period before matching")
    parser.add_argument("--retune-guard-us", type=float, default=5000.0, help="hop mode: retune this many us before AuxPtr offset")
    parser.add_argument("--aux-window-us", type=float, default=8000.0, help="hop mode: time spent listening on the secondary channel after retune")
    parser.add_argument("--primary-settle-us", type=float, default=1000.0, help="hop mode: delay after tuning back to primary")
    parser.add_argument("--secondary-settle-us", type=float, default=500.0, help="hop mode: delay after tuning to secondary")
    parser.add_argument("--expected-aux-offset-us", type=int, default=0, help="expected AuxPtr offset for hop diagnostics; 0 disables offset check")
    parser.add_argument("--expected-name", default="SDR_EXADV", help="expected Complete Local Name for event OK marker")
    parser.add_argument("--print-packets", action="store_true", help="print every decoded packet as well as matched events")
    parser.add_argument("--keep-crc-errors", action="store_true", help="keep packets with CRC mismatch")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
