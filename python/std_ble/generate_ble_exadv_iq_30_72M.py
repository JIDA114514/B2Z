#!/usr/bin/env python3
# coding=utf-8

import argparse
import os
import random
import sys

import numpy as np

from bsp_algorithm import bsp_algorithm
from bsp_string import bsp_string

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STD_ZIGBEE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "ctc_sim", "std_zigbee"))

sys.path.insert(0, STD_ZIGBEE_DIR)

from zigbee_mod import BIT_ORDER, CHIP_MAP, PREAMBLE_BYTES, SFD, bytes_to_bits, crc16_ccitt


BLE_PREAMBLE_AND_AA = [0xAA, 0xD6, 0xBE, 0x89, 0x8E]
BLE_PDU_TYPE_ADV_EXT_IND = 0x07
BLE_AD_TYPE_MANUFACTURER = 0xFF
BLE_AD_TYPE_FLAGS = 0x01
BLE_AD_TYPE_COMPLETE_LOCAL_NAME = 0x09
BLE_EXT_HDR_FLAG_ADVA = 0x01
BLE_EXT_HDR_FLAG_CTE_INFO = 0x04
BLE_EXT_HDR_FLAG_ADI = 0x08
BLE_EXT_HDR_FLAG_AUX_PTR = 0x10
BLE_EXT_ADV_MODE_NONCONN_NONSCAN = 0x00
BLE_EXT_ADV_MODE_CONNECTABLE = 0x01
BLE_AUX_PHY_LE_1M = 0x01
BLE_EXT_ADV_MAX_PDU_PAYLOAD = 255
DEFAULT_AUX_OFFSET_US = 30000
DEFAULT_SECONDARY_PRE_PAD_US = 0.0
BLE_AUX_OFFSET_UNIT_30_US_MAX_US = 245_700
BLE_MIN_AUX_FRAME_SPACE_US = 300
BLE_PRIMARY_MAX_EVENT_SPACING_US = 10000
DEFAULT_MAC = "C1:A2:A3:A4:A5:A6"
DEFAULT_LOCAL_NAME = "SDR_EXADV"
DEFAULT_SID = 0
DEFAULT_DID = None
DEFAULT_PRIMARY_CHANNELS = "39"
DEFAULT_PRIMARY_SPACING_US = 9000
DEFAULT_ZIGBEE_PAYLOAD = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D]
PHASE_POLARITIES = ("normal", "inverted")
DIAGNOSTIC_PROFILES = {
    "baseline-nonconn-nonscan": {
        "adv_mode": BLE_EXT_ADV_MODE_NONCONN_NONSCAN,
        "include_flags": True,
        "description": "current non-connectable/non-scannable baseline with Flags + Complete Local Name",
    },
    "no-flags-name-only": {
        "adv_mode": BLE_EXT_ADV_MODE_NONCONN_NONSCAN,
        "include_flags": False,
        "description": "non-connectable/non-scannable, secondary AdvData contains only Complete Local Name",
    },
    "connectable-advdata": {
        "adv_mode": BLE_EXT_ADV_MODE_CONNECTABLE,
        "include_flags": True,
        "description": "connectable extended advertising display diagnostic with secondary AdvData",
    },
}


def parse_mac(text):
    mac = [int(part, 16) & 0xFF for part in text.split(":")]
    if len(mac) != 6:
        raise ValueError("MAC must contain 6 bytes")
    return mac


def validate_static_random_address(mac):
    if (mac[0] & 0xC0) != 0xC0:
        raise ValueError("static random address must have the two most significant bits set")
    if all(byte == 0x00 for byte in mac) or all(byte == 0xFF for byte in mac):
        raise ValueError("static random address must not be all zeros or all ones")


def parse_channel_list(text):
    channels = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        channel = int(part, 0)
        if channel not in (37, 38, 39):
            raise ValueError(f"primary channel must be one of 37, 38, 39: {channel}")
        if channel in channels:
            raise ValueError(f"duplicate BLE channel: {channel}")
        channels.append(channel)
    if not channels:
        raise ValueError("at least one primary channel is required")
    return channels


def parse_byte_list(text):
    if not text:
        return []
    return [int(item, 0) & 0xFF for item in text.replace(",", " ").split()]


def ble_channel_freq_mhz(channel):
    if channel == 37:
        return 2402
    if channel == 38:
        return 2426
    if channel == 39:
        return 2480
    if 0 <= channel <= 10:
        return 2404 + 2 * channel
    if 11 <= channel <= 36:
        return 2406 + 2 * channel
    raise ValueError(f"unsupported BLE channel: {channel}")


def whiten_ll_pdu(pdu, channel):
    crc = bsp_algorithm.bt_crc(pdu, len(pdu))
    whitened = bsp_algorithm.bt_dewhitening(pdu + crc, channel)
    return BLE_PREAMBLE_AND_AA + whitened, crc


def whitening_mask(byte_len, channel):
    return bsp_algorithm.bt_dewhitening([0] * byte_len, channel)


def build_zigbee_phy_frame(payload_bytes):
    mac_len = len(payload_bytes) + 2
    if mac_len > 127:
        raise ValueError("ZigBee MAC frame too long for 802.15.4 PHR")
    fcs = crc16_ccitt(payload_bytes)
    return [0x00] * PREAMBLE_BYTES + [SFD, mac_len] + list(payload_bytes) + [
        fcs & 0xFF,
        (fcs >> 8) & 0xFF,
    ]


def hamming_distance(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def constrain_chip_pair(pair_bits):
    return "11" if pair_bits.count("1") > 1 else "00"


def legacy_emulated_chips(chips):
    return "".join(constrain_chip_pair(chips[i:i + 2]) for i in range(0, 32, 2))


def emulation_candidates(chips):
    candidates = [""]
    for i in range(0, 32, 2):
        pair = chips[i:i + 2]
        choices = (pair,) if pair in ("00", "11") else ("00", "11")
        candidates = [prefix + choice for prefix in candidates for choice in choices]
    return candidates


def build_bluebee_chip_map(map_mode):
    if map_mode == "legacy":
        return [legacy_emulated_chips(chips) for chips in CHIP_MAP]
    if map_mode != "optimized":
        raise ValueError(f"unsupported map mode: {map_mode}")

    optimized = []
    for symbol, chips in enumerate(CHIP_MAP):
        best = None
        for candidate in emulation_candidates(chips):
            intra = hamming_distance(candidate, chips)
            inter_distances = [
                hamming_distance(candidate, other)
                for other_symbol, other in enumerate(CHIP_MAP)
                if other_symbol != symbol
            ]
            min_inter = min(inter_distances)
            sum_inter = sum(inter_distances)
            score = (-intra, min_inter, sum_inter, candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
        optimized.append(best[1])
    return optimized


def zigbee_bytes_to_bluebee_bits(zigbee_bytes, ble_chip_map, phase_polarity):
    frame_bits = bytes_to_bits(zigbee_bytes, bit_order=BIT_ORDER)
    if len(frame_bits) % 4:
        frame_bits += "0" * (4 - len(frame_bits) % 4)

    ble_bits = []
    approx_chips = []
    for i in range(0, len(frame_bits), 4):
        symbol = int(frame_bits[i:i + 4], 2)
        chips = ble_chip_map[symbol]
        for j in range(0, 32, 2):
            bit = 1 if chips[j:j + 2] == "11" else 0
            if phase_polarity == "inverted":
                bit ^= 1
            ble_bits.append(bit)
            approx_chips.extend(("1", "1") if bit else ("0", "0"))
    return ble_bits, "".join(approx_chips)


def bits_to_bytes_lsb(bits):
    padded = list(bits)
    pad = (-len(padded)) % 8
    if pad:
        padded.extend([0] * pad)
    return list(bsp_string.bits_to_bytes_lsb(padded)), pad


def build_zigbee_source_bytes(embed_mode, payload_bytes):
    if embed_mode == "payload":
        return list(payload_bytes), None
    if embed_mode == "preamble":
        return [0x00] * PREAMBLE_BYTES + [SFD, 0x00], None
    if embed_mode == "phy-frame":
        frame = build_zigbee_phy_frame(payload_bytes)
        return frame, frame
    raise ValueError(f"unsupported BlueBee embed mode: {embed_mode}")


def chips_to_symbols(chips):
    symbols = []
    for i in range(0, len(chips) - len(chips) % 32, 32):
        chunk = chips[i:i + 32]
        best_symbol = 0
        best_dist = 33
        for symbol, ref in enumerate(CHIP_MAP):
            dist = hamming_distance(chunk, ref)
            if dist < best_dist:
                best_symbol = symbol
                best_dist = dist
        symbols.append((best_symbol, best_dist))
    return symbols


def verify_zigbee_projection(frame_bytes, approx_chips):
    symbols = chips_to_symbols(approx_chips)
    bits = "".join(f"{symbol:04b}" for symbol, _ in symbols)
    decoded = []
    for i in range(0, len(bits) - len(bits) % 8, 8):
        value = 0
        for bit_idx, bit in enumerate(bits[i:i + 8]):
            if bit == "1":
                value |= 1 << bit_idx
        decoded.append(value)
    return decoded[:len(frame_bytes)] == frame_bytes, decoded, [dist for _, dist in symbols]


def build_aux_ptr(channel, offset_us, ca=0, phy=BLE_AUX_PHY_LE_1M):
    if not 0 <= channel <= 36:
        raise ValueError("secondary channel must be a BLE data channel in 0..36")
    if offset_us <= 0:
        raise ValueError("aux offset must be positive")
    if offset_us < BLE_AUX_OFFSET_UNIT_30_US_MAX_US:
        if offset_us % 30 != 0:
            raise ValueError("aux offset below 245700 us must be a multiple of 30 us")
        offset_units = 0
        aux_offset = offset_us // 30
    else:
        if offset_us % 300 != 0:
            raise ValueError("aux offset at or above 245700 us must be a multiple of 300 us")
        offset_units = 1
        aux_offset = offset_us // 300
    if not 0 < aux_offset < (1 << 13):
        raise ValueError("encoded AuxOffset must fit in 13 bits and be non-zero")

    return [
        (channel & 0x3F) | ((ca & 0x01) << 6) | ((offset_units & 0x01) << 7),
        aux_offset & 0xFF,
        ((aux_offset >> 8) & 0x1F) | ((phy & 0x07) << 5),
    ]


def decode_aux_ptr(aux_ptr):
    channel = aux_ptr[0] & 0x3F
    ca = (aux_ptr[0] >> 6) & 0x01
    offset_units = (aux_ptr[0] >> 7) & 0x01
    aux_offset = aux_ptr[1] | ((aux_ptr[2] & 0x1F) << 8)
    phy = (aux_ptr[2] >> 5) & 0x07
    offset_us = aux_offset * (300 if offset_units else 30)
    return channel, ca, offset_units, aux_offset, offset_us, phy


def build_complete_local_name_adv_data(name):
    encoded = name.encode("ascii")
    ad_len = len(encoded) + 1
    if ad_len > 0xFF:
        raise ValueError("Complete Local Name AD structure is too long")
    return [ad_len, BLE_AD_TYPE_COMPLETE_LOCAL_NAME] + list(encoded)


def build_adv_data(
    name,
    include_flags=True,
    include_name=True,
    bluebee_bytes=None,
    bluebee_ad_mode="manufacturer",
    company_id=0xFFFF,
):
    adv_data = []
    if include_flags:
        adv_data.extend([0x02, BLE_AD_TYPE_FLAGS, 0x06])
    if include_name:
        adv_data.extend(build_complete_local_name_adv_data(name))
    if bluebee_bytes is None:
        return adv_data, None, 0

    bluebee_bytes = list(bluebee_bytes)
    if bluebee_ad_mode == "raw":
        bluebee_start = len(adv_data)
        adv_data.extend(bluebee_bytes)
        return adv_data, bluebee_start, len(bluebee_bytes)

    if bluebee_ad_mode == "manufacturer":
        bluebee_start = len(adv_data) + 4
        ad_len = len(bluebee_bytes) + 3
        if ad_len > 0xFF:
            raise ValueError("BlueBee manufacturer AD structure is too long for a one-octet AD length field")
        adv_data.extend(
            [
                ad_len,
                BLE_AD_TYPE_MANUFACTURER,
                company_id & 0xFF,
                (company_id >> 8) & 0xFF,
            ]
        )
        adv_data.extend(bluebee_bytes)
        return adv_data, bluebee_start, len(bluebee_bytes)

    raise ValueError(f"unsupported BlueBee AD mode: {bluebee_ad_mode}")


def adv_mode_name(adv_mode):
    if adv_mode == BLE_EXT_ADV_MODE_NONCONN_NONSCAN:
        return "nonconn-nonscan"
    if adv_mode == BLE_EXT_ADV_MODE_CONNECTABLE:
        return "connectable"
    return f"reserved-{adv_mode}"


def build_adi(sid, did):
    if not 0 <= sid <= 0x0F:
        raise ValueError("SID must fit in 4 bits")
    if not 0 <= did <= 0x0FFF:
        raise ValueError("DID must fit in 12 bits")
    value = ((sid & 0x0F) << 12) | (did & 0x0FFF)
    return [value & 0xFF, (value >> 8) & 0xFF]


def decode_adi(adi):
    value = adi[0] | (adi[1] << 8)
    return (value >> 12) & 0x0F, value & 0x0FFF


def packet_air_us(ll_payload):
    return len(ll_payload) * 8


def ext_header_flags(pdu):
    length = pdu[1] & 0x3F
    if length < 2:
        return 0
    return pdu[3]


def validate_ext_adv_event(primary_infos, secondary_pdu, secondary_adi, mac, adv_mode):
    validate_static_random_address(mac)
    if len(primary_infos) > 1:
        for left, right in zip(primary_infos, primary_infos[1:]):
            spacing_us = right["event_offset_us"] - left["event_offset_us"]
            if spacing_us > BLE_PRIMARY_MAX_EVENT_SPACING_US:
                raise ValueError("primary ADV_EXT_IND start spacing must be <= 10000 us")
    aux_times = set()
    for primary in primary_infos:
        flags = ext_header_flags(primary["pdu"])
        primary_adv_mode = (primary["pdu"][2] >> 6) & 0x03
        if primary_adv_mode != adv_mode:
            raise ValueError("primary AdvMode does not match selected diagnostic profile")
        if flags & BLE_EXT_HDR_FLAG_ADVA:
            raise ValueError("primary ADV_EXT_IND must not include AdvA")
        if (flags & (BLE_EXT_HDR_FLAG_ADI | BLE_EXT_HDR_FLAG_AUX_PTR)) != (
            BLE_EXT_HDR_FLAG_ADI | BLE_EXT_HDR_FLAG_AUX_PTR
        ):
            raise ValueError("primary ADV_EXT_IND must include ADI and AuxPtr")
        if primary["adi"] != secondary_adi:
            raise ValueError("primary and secondary ADI must be identical within one generated waveform")
        if primary["aux_offset_us"] % 30 != 0:
            raise ValueError("AuxPtr offset must be encodable in 30 us units")
        min_aux_offset_us = packet_air_us(primary["ll_payload"]) + BLE_MIN_AUX_FRAME_SPACE_US
        if primary["aux_offset_us"] < min_aux_offset_us:
            raise ValueError(
                f"primary ch{primary['channel']} AuxOffset must be at least packet length + T_MAFS "
                f"({min_aux_offset_us} us)"
            )
        decoded_aux = decode_aux_ptr(primary["aux_ptr"])
        if decoded_aux[4] != primary["aux_offset_us"]:
            raise ValueError("encoded AuxPtr offset does not match requested offset")
        aux_times.add(primary["event_offset_us"] + primary["aux_offset_us"])
    if len(aux_times) != 1:
        raise ValueError("all primary AuxPtr values must point to the same absolute AUX start")

    secondary_flags = ext_header_flags(secondary_pdu)
    secondary_adv_mode = (secondary_pdu[2] >> 6) & 0x03
    if secondary_adv_mode != adv_mode:
        raise ValueError("secondary AdvMode does not match selected diagnostic profile")
    if not (secondary_flags & BLE_EXT_HDR_FLAG_ADVA):
        raise ValueError("secondary AUX_ADV_IND must include AdvA")
    if not (secondary_flags & BLE_EXT_HDR_FLAG_ADI):
        raise ValueError("secondary AUX_ADV_IND must include ADI")
    if ((secondary_pdu[0] >> 6) & 0x01) != 1:
        raise ValueError("secondary AUX_ADV_IND must set TxAdd=1 for a random AdvA")


def create_ext_primary_ll_payload(mac, primary_channel, secondary_channel, aux_offset_us, sid, did, adv_mode):
    aux_ptr = build_aux_ptr(secondary_channel, aux_offset_us)
    adi = build_adi(sid, did)
    ext_header = [BLE_EXT_HDR_FLAG_ADI | BLE_EXT_HDR_FLAG_AUX_PTR]
    ext_header.extend(adi)
    ext_header.extend(aux_ptr)
    ext_payload = [len(ext_header) | ((adv_mode & 0x03) << 6)] + ext_header
    if len(ext_payload) > BLE_EXT_ADV_MAX_PDU_PAYLOAD:
        raise ValueError("primary extended advertising PDU payload is too long")

    pdu = [BLE_PDU_TYPE_ADV_EXT_IND, len(ext_payload) & 0xFF] + ext_payload
    ll_payload, crc = whiten_ll_pdu(pdu, primary_channel)
    return ll_payload, pdu, crc, aux_ptr, adi


def create_ext_secondary_ll_payload(
    mac,
    adv_data,
    channel,
    sid,
    did,
    adv_mode,
    bluebee_start=None,
    bluebee_len=0,
):
    adi = build_adi(sid, did)
    ext_header = [BLE_EXT_HDR_FLAG_ADVA | BLE_EXT_HDR_FLAG_ADI]
    ext_header.extend(reversed(mac))
    ext_header.extend(adi)
    ext_payload = [len(ext_header) | ((adv_mode & 0x03) << 6)] + ext_header + list(adv_data)
    if len(ext_payload) > BLE_EXT_ADV_MAX_PDU_PAYLOAD:
        raise ValueError("secondary extended advertising PDU payload is too long")

    pdu = [0x40 | BLE_PDU_TYPE_ADV_EXT_IND, len(ext_payload) & 0xFF] + ext_payload
    bluebee_pdu_start = None
    if bluebee_start is not None and bluebee_len:
        adv_data_start = 2 + 1 + len(ext_header)
        bluebee_pdu_start = adv_data_start + bluebee_start
        mask = whitening_mask(len(pdu) + 3, channel)
        for i in range(bluebee_len):
            pdu[bluebee_pdu_start + i] ^= mask[bluebee_pdu_start + i]
    ll_payload, crc = whiten_ll_pdu(pdu, channel)
    return ll_payload, pdu, crc, adi, bluebee_pdu_start


def get_gaussian_filter(bt, sps, span=4):
    t = np.arange(-span * sps / 2, span * sps / 2) / sps
    alpha = np.sqrt(np.log(2) / 2) / bt
    h = (np.sqrt(np.pi) / alpha) * np.exp(-((np.pi * t / alpha) ** 2))
    return h / np.sum(h)


def ble_bits_to_iq_30_72m(bits, bt=0.5, pre_pad_us=0.0, post_pad_us=10.0):
    symbols = np.array(list(bits), dtype=np.float32) * 2 - 1
    sps_high = 768
    nrz_high = np.repeat(symbols, sps_high)
    h = get_gaussian_filter(bt=bt, sps=sps_high, span=4)
    f_sig = np.convolve(nrz_high, h, mode="same")
    phase_step = np.pi / (2 * sps_high)
    phase = np.cumsum(f_sig * phase_step)
    i_high = np.cos(phase)
    q_high = np.sin(phase)
    i_out = i_high[::25]
    q_out = q_high[::25]
    i_int = np.round(i_out * 10000).astype(int)
    q_int = np.round(q_out * 10000).astype(int)
    iq_uint32 = ((q_int & 0xFFFF) << 16) | (i_int & 0xFFFF)
    iq_uint32 = np.repeat(iq_uint32, 2)
    pre_pad_words = int(round(pre_pad_us * 1e-6 * 30_720_000)) * 2
    post_pad_words = int(round(post_pad_us * 1e-6 * 30_720_000)) * 2
    if pre_pad_words > 0:
        iq_uint32 = np.concatenate([np.zeros(pre_pad_words, dtype=iq_uint32.dtype), iq_uint32])
    if post_pad_words > 0:
        iq_uint32 = np.concatenate([iq_uint32, np.zeros(post_pad_words, dtype=iq_uint32.dtype)])
    return iq_uint32


def write_one_c_array(f, symbol_name, iq_data):
    f.write(f"const uint32_t {symbol_name}[{len(iq_data)}] __attribute__((aligned(64))) = {{\n")
    for i in range(0, len(iq_data), 8):
        chunk = iq_data[i:i + 8]
        f.write("    " + ", ".join(f"0x{int(val):08X}" for val in chunk))
        f.write(",\n" if i + 8 < len(iq_data) else "\n")
    f.write("};\n")


def write_iq_c_arrays(path, arrays, meta_lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated standard BLE extended advertising waveform\n")
        f.write("// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)\n")
        for item in arrays:
            f.write(f"// Array {item['symbol']}: BLE ch{item['channel']} {item['freq_mhz']} MHz\n")
        for line in meta_lines:
            f.write(f"// {line}\n")
        f.write("\n#include <stdint.h>\n\n")
        for idx, item in enumerate(arrays):
            if idx:
                f.write("\n")
            macro_name = item["symbol"].upper() + "_WORDS"
            f.write(f"#define {macro_name} ({len(item['iq'])}u)\n")
        f.write("\n")
        f.write("#ifdef BLE_EXADV_WAVEFORM_DEFINE_ARRAYS\n")
        for item in arrays:
            f.write("\n")
            write_one_c_array(f, item["symbol"], item["iq"])
        f.write("#else\n")
        for item in arrays:
            macro_name = item["symbol"].upper() + "_WORDS"
            f.write(f"extern const uint32_t {item['symbol']}[{macro_name}] __attribute__((aligned(64)));\n")
        f.write("#endif\n")


def bytes_hex(data):
    return " ".join(f"{x:02X}" for x in data)


def distance_range_text(distances):
    if not distances:
        return "none"
    return f"{min(distances)}..{max(distances)}"


def main():
    parser = argparse.ArgumentParser(description="Generate standard BLE extended advertising IQ waveforms")
    parser.add_argument("--mac", default=DEFAULT_MAC, help="BLE advertiser MAC")
    parser.add_argument("--name", default=DEFAULT_LOCAL_NAME, help="Complete Local Name in AUX_ADV_IND")
    parser.add_argument("--channel", type=int, default=37, help="legacy single primary BLE advertising channel")
    parser.add_argument("--primary-channels", default=DEFAULT_PRIMARY_CHANNELS, help="comma-separated primary BLE advertising channels")
    parser.add_argument("--primary-spacing-us", type=int, default=DEFAULT_PRIMARY_SPACING_US, help="start-to-start spacing between primary PDUs in one advertising event")
    parser.add_argument("--secondary-channel", type=int, default=3, help="BLE data channel encoded in AuxPtr")
    parser.add_argument("--aux-offset-us", type=int, default=DEFAULT_AUX_OFFSET_US, help="AuxPtr offset encoded in the primary ADV_EXT_IND, in us")
    parser.add_argument(
        "--timing-debug-same-channel",
        action="store_true",
        help="diagnostic mode: transmit/whiten secondary on the primary channel while keeping AuxPtr on --secondary-channel",
    )
    parser.add_argument("--sid", type=int, default=DEFAULT_SID, help="advertising SID encoded in ADI")
    parser.add_argument("--did", type=int, default=DEFAULT_DID, help="advertising DID encoded in ADI; default is random per generated waveform")
    parser.add_argument(
        "--diagnostic-profile",
        choices=sorted(DIAGNOSTIC_PROFILES.keys()),
        default="connectable-advdata",
        help="extended advertising phone-display diagnostic profile",
    )
    parser.add_argument(
        "--include-flags",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="override whether to include BLE Flags AD structure before Complete Local Name",
    )
    parser.add_argument(
        "--no-name",
        action="store_true",
        help="omit Complete Local Name AD structure to maximise BlueBee payload space",
    )
    parser.add_argument(
        "--append-bluebee-zigbee",
        action="store_true",
        help="append a BlueBee-emulated ZigBee frame to secondary AdvData",
    )
    parser.add_argument(
        "--zigbee-payload",
        default=" ".join(f"0x{x:02X}" for x in DEFAULT_ZIGBEE_PAYLOAD),
        help="ZigBee content bytes for BlueBee mode, e.g. '0x11 0x22 0x33 0x44'",
    )
    parser.add_argument(
        "--bluebee-embed-mode",
        choices=("payload", "preamble", "phy-frame"),
        default="phy-frame",
        help="payload maps only --zigbee-payload; preamble maps 00 00 00 00 A7 00; phy-frame maps the full ZigBee PHY frame",
    )
    parser.add_argument(
        "--bluebee-ad-mode",
        choices=("manufacturer", "raw"),
        default="manufacturer",
        help="secondary AdvData wrapping for BlueBee bytes",
    )
    parser.add_argument(
        "--company-id",
        type=lambda value: int(value, 0),
        default=0xFFFF,
        help="manufacturer company ID used by --bluebee-ad-mode manufacturer",
    )
    parser.add_argument(
        "--map-mode",
        choices=("legacy", "optimized"),
        default="optimized",
        help="BlueBee chip-map mode; optimized follows the margin-based selection used by the BlueBee helper",
    )
    parser.add_argument(
        "--phase-polarity",
        choices=PHASE_POLARITIES,
        default="normal",
        help="invert flips the BlueBee RF chip projection for phase-sign A/B tests",
    )
    parser.add_argument("--bt", type=float, default=0.5, help="BLE Gaussian BT")
    parser.add_argument("--post-pad-us", type=float, default=10.0, help="zero-IQ silence appended after each packet")
    parser.add_argument("--secondary-pre-pad-us", type=float, default=DEFAULT_SECONDARY_PRE_PAD_US, help="zero-IQ silence prepended before AUX_ADV_IND for RF settle")
    parser.add_argument(
        "--output",
        default=os.path.join(SCRIPT_DIR, "ble_exadv_waveform_30_72M.h"),
        help="output C header path",
    )
    parser.add_argument("--primary-symbol-name", default=None, help="C array name for primary waveform")
    parser.add_argument("--secondary-symbol-name", default=None, help="C array name for secondary waveform")
    args = parser.parse_args()

    primary_channels = parse_channel_list(args.primary_channels) if args.primary_channels else parse_channel_list(str(args.channel))
    if args.timing_debug_same_channel and len(primary_channels) != 1:
        raise ValueError("--timing-debug-same-channel requires exactly one primary channel")
    if args.primary_spacing_us < 0:
        raise ValueError("--primary-spacing-us must be non-negative")
    if args.primary_spacing_us > BLE_PRIMARY_MAX_EVENT_SPACING_US:
        raise ValueError("--primary-spacing-us must be <= 10000 us within one advertising event")
    if args.primary_spacing_us % 30 != 0:
        raise ValueError("--primary-spacing-us must be a multiple of 30 us so all AuxPtr offsets remain encodable")
    if args.secondary_symbol_name is None:
        args.secondary_symbol_name = f"ble_exadv_secondary_iq_ch{args.secondary_channel}"

    mac = parse_mac(args.mac)
    validate_static_random_address(mac)
    did = args.did if args.did is not None else random.SystemRandom().randrange(0x1000)
    profile = DIAGNOSTIC_PROFILES[args.diagnostic_profile]
    adv_mode = profile["adv_mode"]
    include_flags = profile["include_flags"] if args.include_flags is None else args.include_flags
    secondary_wave_channel = primary_channels[0] if args.timing_debug_same_channel else args.secondary_channel

    zigbee_payload = []
    zigbee_source = []
    zigbee_frame = None
    bluebee_bits = []
    bluebee_bytes = None
    bluebee_bit_pad = 0
    zigbee_projection_ok = None
    zigbee_projection_distances = []
    on_air_projection_ok = None
    on_air_projection_distances = []
    if args.append_bluebee_zigbee:
        zigbee_payload = parse_byte_list(args.zigbee_payload)
        zigbee_source, zigbee_frame = build_zigbee_source_bytes(args.bluebee_embed_mode, zigbee_payload)
        ble_chip_map = build_bluebee_chip_map(args.map_mode)
        bluebee_bits, approx_chips = zigbee_bytes_to_bluebee_bits(
            zigbee_source,
            ble_chip_map=ble_chip_map,
            phase_polarity=args.phase_polarity,
        )
        bluebee_bytes, bluebee_bit_pad = bits_to_bytes_lsb(bluebee_bits)
        zigbee_projection_ok, _, zigbee_projection_distances = verify_zigbee_projection(
            zigbee_source,
            approx_chips,
        )

    adv_data, bluebee_start, bluebee_len = build_adv_data(
        args.name,
        include_flags=include_flags,
        include_name=not args.no_name,
        bluebee_bytes=bluebee_bytes,
        bluebee_ad_mode=args.bluebee_ad_mode,
        company_id=args.company_id,
    )
    primary_infos = []
    for primary_index, primary_channel in enumerate(primary_channels):
        primary_aux_offset_us = args.aux_offset_us - primary_index * args.primary_spacing_us
        if primary_aux_offset_us <= 0:
            raise ValueError("primary spacing pushes a later primary AuxPtr offset below zero")
        symbol_name = (
            args.primary_symbol_name
            if args.primary_symbol_name is not None and len(primary_channels) == 1
            else f"ble_exadv_primary_iq_ch{primary_channel}"
        )
        primary_ll_payload, primary_pdu, primary_crc, aux_ptr, primary_adi = create_ext_primary_ll_payload(
            mac,
            primary_channel=primary_channel,
            secondary_channel=args.secondary_channel,
            aux_offset_us=primary_aux_offset_us,
            sid=args.sid,
            did=did,
            adv_mode=adv_mode,
        )
        primary_iq = ble_bits_to_iq_30_72m(
            list(bsp_string.bytes_to_bits_lsb(primary_ll_payload)),
            bt=args.bt,
            post_pad_us=args.post_pad_us,
        )
        primary_infos.append(
            {
                "channel": primary_channel,
                "symbol": symbol_name,
                "event_offset_us": primary_index * args.primary_spacing_us,
                "aux_offset_us": primary_aux_offset_us,
                "ll_payload": primary_ll_payload,
                "pdu": primary_pdu,
                "crc": primary_crc,
                "aux_ptr": aux_ptr,
                "adi": primary_adi,
                "iq": primary_iq,
            }
        )
    secondary_ll_payload, secondary_pdu, secondary_crc, secondary_adi, bluebee_pdu_start = create_ext_secondary_ll_payload(
        mac,
        adv_data,
        channel=secondary_wave_channel,
        sid=args.sid,
        did=did,
        adv_mode=adv_mode,
        bluebee_start=bluebee_start,
        bluebee_len=bluebee_len,
    )
    if args.append_bluebee_zigbee and bluebee_pdu_start is not None:
        on_air_bluebee = secondary_ll_payload[5 + bluebee_pdu_start:5 + bluebee_pdu_start + bluebee_len]
        on_air_bits = list(bsp_string.bytes_to_bits_lsb(on_air_bluebee))
        on_air_chips = "".join("11" if bit else "00" for bit in on_air_bits[:len(bluebee_bits)])
        on_air_projection_ok, _, on_air_projection_distances = verify_zigbee_projection(
            zigbee_source,
            on_air_chips,
        )
    validate_ext_adv_event(primary_infos, secondary_pdu, secondary_adi, mac, adv_mode)
    secondary_iq = ble_bits_to_iq_30_72m(
        list(bsp_string.bytes_to_bits_lsb(secondary_ll_payload)),
        bt=args.bt,
        pre_pad_us=args.secondary_pre_pad_us,
        post_pad_us=args.post_pad_us,
    )
    decoded_aux = decode_aux_ptr(primary_infos[0]["aux_ptr"])
    decoded_secondary_sid, decoded_secondary_did = decode_adi(secondary_adi)

    meta = [
        f"primary_channels: {','.join(str(x) for x in primary_channels)}",
        f"primary_frequencies_mhz: {','.join(str(ble_channel_freq_mhz(x)) for x in primary_channels)}",
        f"primary_spacing_us: {args.primary_spacing_us}",
        f"secondary_aux_ptr_channel: {args.secondary_channel}",
        f"secondary_wave_channel: {secondary_wave_channel}",
        f"secondary_wave_frequency_mhz: {ble_channel_freq_mhz(secondary_wave_channel)}",
        f"timing_debug_same_channel: {int(args.timing_debug_same_channel)}",
        f"same_channel_diagnostic: {int(args.timing_debug_same_channel)}",
        f"secondary_rf_whitening_channel: {secondary_wave_channel}",
        f"aux_offset_us: {args.aux_offset_us}",
        f"aux_ptr_first_primary: {bytes_hex(primary_infos[0]['aux_ptr'])}",
        f"aux_ptr_decoded: ch={decoded_aux[0]} ca={decoded_aux[1]} units={'300us' if decoded_aux[2] else '30us'} offset={decoded_aux[4]}us phy={decoded_aux[5]}",
        f"diagnostic_profile: {args.diagnostic_profile}",
        f"diagnostic_profile_description: {profile['description']}",
        f"adv_mode: {adv_mode_name(adv_mode)}",
        f"adv_mode_value: {adv_mode}",
        f"adv_data_include_flags: {int(include_flags)}",
        "primary_ext_header_flags: ADI|AuxPtr",
        "secondary_ext_header_flags: AdvA|ADI",
        f"sid: {args.sid}",
        f"did: {did}",
        f"did_source: {'cli' if args.did is not None else 'random'}",
        f"adv_address: {args.mac.upper()}",
        "adv_address_type: static_random",
        f"secondary_adi: {bytes_hex(secondary_adi)}",
        f"secondary_adi_decoded: sid={decoded_secondary_sid} did={decoded_secondary_did}",
        f"adv_data: {bytes_hex(adv_data)}",
        f"local_name: {args.name}",
        f"bluebee_enabled: {int(args.append_bluebee_zigbee)}",
        f"bluebee_ad_mode: {args.bluebee_ad_mode if args.append_bluebee_zigbee else 'none'}",
        f"bluebee_embed_mode: {args.bluebee_embed_mode if args.append_bluebee_zigbee else 'none'}",
        f"bluebee_company_id: 0x{args.company_id:04X}",
        f"zigbee_payload: {bytes_hex(zigbee_payload)}",
        f"zigbee_source: {bytes_hex(zigbee_source)}",
        f"zigbee_frame: {bytes_hex(zigbee_frame) if zigbee_frame else ''}",
        f"zigbee_payload_bytes: {len(zigbee_payload)}",
        f"zigbee_source_bytes: {len(zigbee_source)}",
        f"zigbee_frame_bytes: {len(zigbee_frame) if zigbee_frame else 0}",
        f"bluebee_payload_bytes: {bluebee_len}",
        f"bluebee_bit_pad: {bluebee_bit_pad}",
        f"bluebee_adv_data_start: {'none' if bluebee_start is None else bluebee_start}",
        f"bluebee_pdu_start: {'none' if bluebee_pdu_start is None else bluebee_pdu_start}",
        f"map_mode: {args.map_mode}",
        f"phase_polarity: {args.phase_polarity}",
        f"zigbee_projection_ok: {zigbee_projection_ok if zigbee_projection_ok is not None else 'not_run'}",
        f"zigbee_symbol_distance_range: {distance_range_text(zigbee_projection_distances)}",
        f"on_air_projection_ok: {on_air_projection_ok if on_air_projection_ok is not None else 'not_run'}",
        f"on_air_symbol_distance_range: {distance_range_text(on_air_projection_distances)}",
        f"secondary_pdu: {bytes_hex(secondary_pdu)}",
        f"secondary_pdu_payload_bytes: {len(secondary_pdu) - 2}",
        f"secondary_crc: {bytes_hex(secondary_crc)}",
        f"primary_air_us: {packet_air_us(primary_infos[0]['ll_payload'])}",
        f"secondary_air_us: {packet_air_us(secondary_ll_payload)}",
        f"min_aux_offset_us: {packet_air_us(primary_infos[0]['ll_payload']) + BLE_MIN_AUX_FRAME_SPACE_US}",
        f"secondary_pre_pad_us: {args.secondary_pre_pad_us:g}",
        f"primary_words: {len(primary_infos[0]['iq'])}",
        f"secondary_words: {len(secondary_iq)}",
        f"post_pad_us: {args.post_pad_us:g}",
    ]
    for primary in primary_infos:
        decoded_primary_sid, decoded_primary_did = decode_adi(primary["adi"])
        meta.extend(
            [
                f"primary_ch{primary['channel']}_adi: {bytes_hex(primary['adi'])}",
                f"primary_ch{primary['channel']}_adi_decoded: sid={decoded_primary_sid} did={decoded_primary_did}",
                f"primary_ch{primary['channel']}_event_offset_us: {primary['event_offset_us']}",
                f"primary_ch{primary['channel']}_aux_offset_us: {primary['aux_offset_us']}",
                f"primary_ch{primary['channel']}_absolute_aux_start_us: {primary['event_offset_us'] + primary['aux_offset_us']}",
                f"primary_ch{primary['channel']}_aux_ptr: {bytes_hex(primary['aux_ptr'])}",
                f"primary_ch{primary['channel']}_pdu: {bytes_hex(primary['pdu'])}",
                f"primary_ch{primary['channel']}_pdu_payload_bytes: {len(primary['pdu']) - 2}",
                f"primary_ch{primary['channel']}_crc: {bytes_hex(primary['crc'])}",
            ]
        )
    if args.timing_debug_same_channel:
        meta.extend(
            [
                "aux_ptr_channel_diagnostic_only: 1",
                f"diagnostic_note: same_channel_diagnostic=1; secondary RF/whitening is ch{secondary_wave_channel}; AuxPtr channel is diagnostic only",
            ]
        )
    output_arrays = [
        {
            "symbol": primary["symbol"],
            "iq": primary["iq"],
            "channel": primary["channel"],
            "freq_mhz": ble_channel_freq_mhz(primary["channel"]),
        }
        for primary in primary_infos
    ]
    output_arrays.append(
        {
            "symbol": args.secondary_symbol_name,
            "iq": secondary_iq,
            "channel": secondary_wave_channel,
            "freq_mhz": ble_channel_freq_mhz(secondary_wave_channel),
        }
    )
    write_iq_c_arrays(
        args.output,
        output_arrays,
        meta,
    )

    for primary in primary_infos:
        decoded_primary_sid, decoded_primary_did = decode_adi(primary["adi"])
        print(f"Primary ADV_EXT_IND: ch{primary['channel']} {ble_channel_freq_mhz(primary['channel'])} MHz")
        print(f"Primary ADI ch{primary['channel']}: {bytes_hex(primary['adi'])} SID={decoded_primary_sid} DID={decoded_primary_did}")
        print(f"Primary timing ch{primary['channel']}: event_offset={primary['event_offset_us']} us AuxPtr offset={primary['aux_offset_us']} us")
        print(f"Primary PDU ch{primary['channel']}: {bytes_hex(primary['pdu'])}")
        print(f"Primary BLE CRC ch{primary['channel']}: {bytes_hex(primary['crc'])}")
    print(f"Diagnostic profile: {args.diagnostic_profile} ({profile['description']})")
    print(f"AdvMode: {adv_mode_name(adv_mode)} value={adv_mode}")
    print(f"AdvData include Flags: {int(include_flags)}")
    print(f"Secondary AUX_ADV_IND waveform: ch{secondary_wave_channel} {ble_channel_freq_mhz(secondary_wave_channel)} MHz")
    print(f"Secondary AuxPtr channel: ch{args.secondary_channel}")
    if args.timing_debug_same_channel:
        print("Same-channel diagnostic: same_channel_diagnostic=1")
        print(f"Same-channel diagnostic: secondary RF/whitening is ch{secondary_wave_channel}")
        print(f"Same-channel diagnostic: AuxPtr channel ch{args.secondary_channel} is diagnostic only")
    print(f"AuxPtr: {bytes_hex(primary_infos[0]['aux_ptr'])} offset={args.aux_offset_us} us")
    print(f"Secondary ADI: {bytes_hex(secondary_adi)} SID={decoded_secondary_sid} DID={decoded_secondary_did}")
    print(f"AdvA: {args.mac.upper()} static_random")
    print(f"AdvData: {bytes_hex(adv_data)}")
    if args.append_bluebee_zigbee:
        print(f"BlueBee AD mode: {args.bluebee_ad_mode}, embed mode: {args.bluebee_embed_mode}")
        print(f"ZigBee payload: {bytes_hex(zigbee_payload)}")
        print(f"ZigBee source: {bytes_hex(zigbee_source)}")
        if zigbee_frame:
            print(f"ZigBee frame: {bytes_hex(zigbee_frame)}")
        print(f"BlueBee bytes: {bluebee_len}")
        print(f"BlueBee AdvData start: {bluebee_start}")
        print(f"BlueBee PDU start: {bluebee_pdu_start}")
        print(f"Map mode: {args.map_mode}, phase polarity: {args.phase_polarity}")
        print(f"ZigBee projection: {'OK' if zigbee_projection_ok else 'FAIL'}")
        print(f"On-air projection: {'OK' if on_air_projection_ok else 'FAIL'}")
        print(f"Symbol distance range: {distance_range_text(zigbee_projection_distances)}")
        print(f"On-air symbol distance range: {distance_range_text(on_air_projection_distances)}")
    print(f"Secondary PDU: {bytes_hex(secondary_pdu)}")
    print(f"Secondary BLE CRC: {bytes_hex(secondary_crc)}")
    print(f"Primary air time: {packet_air_us(primary_infos[0]['ll_payload'])} us")
    print(f"Secondary air time: {packet_air_us(secondary_ll_payload)} us")
    print(f"Secondary pre-pad: {args.secondary_pre_pad_us:g} us")
    print(f"Generated {len(primary_infos)} primary arrays x {len(primary_infos[0]['iq'])} words and {len(secondary_iq)} secondary words -> {args.output}")


if __name__ == "__main__":
    main()
