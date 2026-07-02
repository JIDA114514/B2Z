#!/usr/bin/env python3
# coding=utf-8

import argparse
import os
import sys

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STD_BLE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "std_ble"))
STD_ZIGBEE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "std_zigbee"))

sys.path.insert(0, STD_BLE_DIR)
sys.path.insert(0, STD_ZIGBEE_DIR)

from bsp_algorithm import bsp_algorithm
from bsp_string import bsp_string
from zigbee_mod import BIT_ORDER, CHIP_MAP, PREAMBLE_BYTES, SFD, bytes_to_bits, crc16_ccitt


BLE_CHANS = {
    37: 0, 0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9,
    9: 10, 10: 11, 38: 12, 11: 13, 12: 14, 13: 15, 14: 16, 15: 17,
    16: 18, 17: 19, 18: 20, 19: 21, 20: 22, 21: 23, 22: 24, 23: 25,
    24: 26, 25: 27, 26: 28, 27: 29, 28: 30, 29: 31, 30: 32, 31: 33,
    32: 34, 33: 35, 34: 36, 35: 37, 36: 38, 39: 39,
}

BLE_PREAMBLE_AND_AA = [0xAA, 0xD6, 0xBE, 0x89, 0x8E]
BLE_ADV_MAX_PDU_PAYLOAD = 37
BLE_ADV_MAX_ADV_DATA = 31
BLE_EXT_ADV_MAX_PDU_PAYLOAD = 255
BLE_ADV_ADDR_LEN = 6
BLE_AD_TYPE_MANUFACTURER = 0xFF
BLE_PDU_TYPE_ADV_NONCONN_IND = 0x02
BLE_PDU_TYPE_ADV_EXT_IND = 0x07
BLE_EXT_HDR_FLAG_ADVA = 0x01
BLE_EXT_HDR_FLAG_AUX_PTR = 0x10
BLE_EXT_ADV_MODE_NONCONN_NONSCAN = 0x00
BLE_EXT_ADV_MODE_SCANNABLE_NONCONN = 0x02
BLE_EXT_ADV_MODES = {
    "nonconn-nonscan": BLE_EXT_ADV_MODE_NONCONN_NONSCAN,
    "scannable-nonconn": BLE_EXT_ADV_MODE_SCANNABLE_NONCONN,
}
BLE_AUX_PHY_LE_1M = 0x01
DEFAULT_ZIGBEE_PAYLOAD = [0x11, 0x22, 0x33, 0x44]
PHASE_POLARITIES = ("normal", "inverted")


def parse_byte_list(text):
    if not text:
        return []
    return [int(item, 0) & 0xFF for item in text.replace(",", " ").split()]


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


def map_metrics(ble_chip_map):
    metrics = []
    for symbol, emulated in enumerate(ble_chip_map):
        intra = hamming_distance(emulated, CHIP_MAP[symbol])
        inter = [
            hamming_distance(emulated, ref)
            for other_symbol, ref in enumerate(CHIP_MAP)
            if other_symbol != symbol
        ]
        metrics.append((symbol, intra, min(inter), emulated))
    return metrics


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


def whitening_mask(byte_len, channel):
    zeros = [0] * byte_len
    return bsp_algorithm.bt_dewhitening(zeros, channel)


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


def build_aux_ptr(channel, offset_us, ca=0, phy=BLE_AUX_PHY_LE_1M):
    if not 0 <= channel <= 36:
        raise ValueError("--secondary-channel must be a BLE data channel in 0..36")
    if offset_us <= 0:
        raise ValueError("--aux-offset-us must be positive")
    if offset_us % 300 == 0:
        offset_units = 1
        aux_offset = offset_us // 300
    elif offset_us % 30 == 0:
        offset_units = 0
        aux_offset = offset_us // 30
    else:
        raise ValueError("--aux-offset-us must be a multiple of 30 us or 300 us")
    if not 0 < aux_offset < (1 << 13):
        raise ValueError("encoded AuxOffset must fit in 13 bits and be non-zero")
    return [
        (channel & 0x3F) | ((ca & 0x01) << 6) | ((offset_units & 0x01) << 7),
        aux_offset & 0xFF,
        ((aux_offset >> 8) & 0x1F) | ((phy & 0x07) << 5),
    ]


def build_adv_data(bluebee_bytes, ad_mode, company_id, include_flags):
    adv_data = []
    bluebee_start = 0

    if include_flags:
        adv_data.extend([0x02, 0x01, 0x06])

    if ad_mode == "raw":
        bluebee_start = len(adv_data)
        adv_data.extend(bluebee_bytes)
        return adv_data, bluebee_start

    if ad_mode == "manufacturer":
        bluebee_start = len(adv_data) + 4
        ad_len = len(bluebee_bytes) + 3
        if ad_len > 0xFF:
            raise ValueError("manufacturer AD structure is too long for a one-octet AD length field")
        adv_data.extend([
            ad_len,
            BLE_AD_TYPE_MANUFACTURER,
            company_id & 0xFF,
            (company_id >> 8) & 0xFF,
        ])
        adv_data.extend(bluebee_bytes)
        return adv_data, bluebee_start

    raise ValueError(f"unsupported AD mode: {ad_mode}")


def apply_profile_defaults(args):
    if args.profile == "ble-visible":
        if args.ad_mode is None:
            args.ad_mode = "manufacturer"
        if args.embed_mode is None:
            args.embed_mode = "preamble"
        args.include_flags = True if args.include_flags is None else args.include_flags
    elif args.profile == "zigbee-frame":
        if args.ad_mode is None:
            args.ad_mode = "raw"
        if args.embed_mode is None:
            args.embed_mode = "phy-frame"
        args.include_flags = False if args.include_flags is None else args.include_flags
    elif args.profile == "extended":
        if args.ad_mode is None:
            args.ad_mode = "manufacturer"
        if args.embed_mode is None:
            args.embed_mode = "phy-frame"
        args.include_flags = False if args.include_flags is None else args.include_flags
    else:
        raise ValueError(f"unsupported profile: {args.profile}")


def build_zigbee_source_bytes(embed_mode, payload_bytes):
    if embed_mode == "payload":
        return list(payload_bytes), None

    if embed_mode == "preamble":
        return [0x00] * PREAMBLE_BYTES + [SFD, 0x00], None

    if embed_mode == "phy-frame":
        frame = build_zigbee_phy_frame(payload_bytes)
        return frame, frame

    raise ValueError(f"unsupported embed mode: {embed_mode}")


def repeat_zigbee_source(zigbee_source, embed_mode, repeats):
    if repeats < 1:
        raise ValueError("--preamble-repeats must be at least 1")
    if repeats == 1:
        return zigbee_source
    if embed_mode != "preamble":
        raise ValueError("--preamble-repeats is only valid with --embed-mode preamble")
    return list(zigbee_source) * repeats


def create_bluebee_ll_payload(mac, adv_data, channel, bluebee_start, bluebee_len):
    pdu_payload_len = BLE_ADV_ADDR_LEN + len(adv_data)
    if pdu_payload_len > BLE_ADV_MAX_PDU_PAYLOAD:
        raise ValueError(
            f"BLE advertising PDU payload is {pdu_payload_len} bytes, "
            f"but legacy BLE advertising supports at most {BLE_ADV_MAX_PDU_PAYLOAD}. "
            "Shorten --zigbee-payload, use --embed-mode payload, or move to extended advertising."
        )
    if len(adv_data) > BLE_ADV_MAX_ADV_DATA:
        raise ValueError(
            f"BLE AdvData is {len(adv_data)} bytes, but legacy advertising supports at most "
            f"{BLE_ADV_MAX_ADV_DATA}. Shorten --zigbee-payload or disable optional AD fields."
        )

    pdu_adv = [0x40 | BLE_PDU_TYPE_ADV_NONCONN_IND, pdu_payload_len & 0x3F]
    pdu_adv.extend(reversed(mac))
    pdu_adv.extend(adv_data)

    adv_data_start = 2 + BLE_ADV_ADDR_LEN
    bluebee_pdu_start = adv_data_start + bluebee_start
    mask = whitening_mask(len(pdu_adv) + 3, channel)
    for i in range(bluebee_len):
        pdu_adv[bluebee_pdu_start + i] ^= mask[bluebee_pdu_start + i]

    ll_payload, crc = whiten_ll_pdu(pdu_adv, channel)
    return ll_payload, pdu_adv, crc, bluebee_pdu_start


def create_ext_primary_ll_payload(mac, primary_channel, secondary_channel, aux_offset_us,
                                  ext_adv_mode):
    aux_ptr = build_aux_ptr(secondary_channel, aux_offset_us)
    ext_header = [BLE_EXT_HDR_FLAG_ADVA | BLE_EXT_HDR_FLAG_AUX_PTR]
    ext_header.extend(reversed(mac))
    ext_header.extend(aux_ptr)
    if len(ext_header) > 0x3F:
        raise ValueError("extended advertising header is too long")
    ext_payload = [len(ext_header) | (ext_adv_mode << 6)] + ext_header
    if len(ext_payload) > BLE_EXT_ADV_MAX_PDU_PAYLOAD:
        raise ValueError("primary extended advertising PDU payload is too long")
    pdu = [0x40 | BLE_PDU_TYPE_ADV_EXT_IND, len(ext_payload) & 0xFF] + ext_payload
    ll_payload, crc = whiten_ll_pdu(pdu, primary_channel)
    return ll_payload, pdu, crc, aux_ptr


def create_ext_secondary_bluebee_ll_payload(adv_data, channel, bluebee_start, bluebee_len,
                                            ext_adv_mode):
    ext_payload = [ext_adv_mode << 6] + list(adv_data)
    if len(ext_payload) > BLE_EXT_ADV_MAX_PDU_PAYLOAD:
        raise ValueError(
            f"secondary extended advertising PDU payload is {len(ext_payload)} bytes, "
            f"but this single-PDU generator supports at most {BLE_EXT_ADV_MAX_PDU_PAYLOAD}"
        )
    pdu = [BLE_PDU_TYPE_ADV_EXT_IND, len(ext_payload) & 0xFF] + ext_payload
    adv_data_start = 2 + 1
    bluebee_pdu_start = adv_data_start + bluebee_start
    mask = whitening_mask(len(pdu) + 3, channel)
    for i in range(bluebee_len):
        pdu[bluebee_pdu_start + i] ^= mask[bluebee_pdu_start + i]
    ll_payload, crc = whiten_ll_pdu(pdu, channel)
    return ll_payload, pdu, crc, bluebee_pdu_start


def get_gaussian_filter(bt, sps, span=4):
    t = np.arange(-span * sps / 2, span * sps / 2) / sps
    alpha = np.sqrt(np.log(2) / 2) / bt
    h = (np.sqrt(np.pi) / alpha) * np.exp(-((np.pi * t / alpha) ** 2))
    return h / np.sum(h)


def ble_bits_to_iq_30_72m(bits, bt=0.5, post_pad_us=1000.0):
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
    pad_words = int(round(post_pad_us * 1e-6 * 30_720_000)) * 2
    if pad_words > 0:
        iq_uint32 = np.concatenate([iq_uint32, np.zeros(pad_words, dtype=iq_uint32.dtype)])
    return iq_uint32


def write_one_c_array(f, symbol_name, iq_data):
    f.write(
        f"const uint32_t {symbol_name}[{len(iq_data)}] __attribute__((aligned(64))) = {{\n"
    )
    for i in range(0, len(iq_data), 8):
        chunk = iq_data[i:i + 8]
        f.write("    " + ", ".join(f"0x{int(val):08X}" for val in chunk))
        f.write(",\n" if i + 8 < len(iq_data) else "\n")
    f.write("};\n")


def write_iq_c_arrays(path, arrays, meta_lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated BlueBee BLE GFSK waveform\n")
        f.write("// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)\n")
        for item in arrays:
            f.write(f"// Array {item['symbol']}: BLE ch{item['channel']} {item['freq_mhz']} MHz\n")
        for line in meta_lines:
            f.write(f"// {line}\n")
        f.write("\n#include <stdint.h>\n\n")
        for idx, item in enumerate(arrays):
            if idx:
                f.write("\n")
            write_one_c_array(f, item["symbol"], item["iq"])


def write_iq_c_array(path, symbol_name, iq_data, channel, meta_lines):
    write_iq_c_arrays(
        path,
        [{"symbol": symbol_name, "iq": iq_data, "channel": channel, "freq_mhz": ble_channel_freq_mhz(channel)}],
        meta_lines,
    )


def chips_to_symbols(chips):
    symbols = []
    for i in range(0, len(chips) - len(chips) % 32, 32):
        chunk = chips[i:i + 32]
        best_symbol = 0
        best_dist = 33
        for symbol, ref in enumerate(CHIP_MAP):
            dist = sum(1 for a, b in zip(chunk, ref) if a != b)
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


def main():
    parser = argparse.ArgumentParser(
        description="Generate BLE GFSK waveform(s) whose payload emulates a ZigBee PHY frame"
    )
    parser.add_argument(
        "--profile",
        choices=("extended", "ble-visible", "zigbee-frame"),
        default="extended",
        help="extended emits ADV_EXT_IND on --channel and AUX_ADV_IND on --secondary-channel",
    )
    parser.add_argument(
        "--embed-mode",
        choices=("payload", "preamble", "phy-frame"),
        default=None,
        help="payload maps only --zigbee-payload; preamble maps 00 00 00 00 A7 00; phy-frame maps the full ZigBee PHY frame",
    )
    parser.add_argument(
        "--zigbee-payload",
        default=" ".join(f"0x{x:02X}" for x in DEFAULT_ZIGBEE_PAYLOAD),
        help="ZigBee content bytes, e.g. '0x11 0x22 0x33 0x44'",
    )
    parser.add_argument("--channel", type=int, default=39, help="primary BLE advertising channel")
    parser.add_argument("--secondary-channel", type=int, default=3, help="BLE data channel used by AUX_ADV_IND")
    parser.add_argument(
        "--aux-offset-us",
        type=int,
        default=6990,
        help="AuxPtr offset encoded in the primary ADV_EXT_IND; must be a multiple of 30 us or 300 us",
    )
    parser.add_argument("--bt", type=float, default=0.5, help="BLE Gaussian BT")
    parser.add_argument(
        "--ext-adv-mode",
        choices=tuple(BLE_EXT_ADV_MODES),
        default="nonconn-nonscan",
        help="extended advertising AdvMode bits; AdvData in AUX_ADV_IND should use nonconn-nonscan",
    )
    parser.add_argument(
        "--post-pad-us",
        type=float,
        default=10.0,
        help="zero-IQ silence appended after each packet before cyclic DMA repeats",
    )
    parser.add_argument(
        "--map-mode",
        choices=("legacy", "optimized"),
        default="optimized",
        help="legacy uses per-pair majority; optimized follows BlueBee Sec. 4.4 inter-symbol margin selection",
    )
    parser.add_argument(
        "--phase-polarity",
        choices=PHASE_POLARITIES,
        default="normal",
        help="invert flips the BlueBee RF chip projection for phase-sign A/B tests",
    )
    parser.add_argument(
        "--preamble-repeats",
        type=int,
        default=1,
        help="repeat the emulated 00 00 00 00 A7 00 sequence; only valid with --embed-mode preamble",
    )
    parser.add_argument("--mac", default="FF:22:33:44:55:FF", help="BLE advertiser MAC")
    parser.add_argument(
        "--ad-mode",
        choices=("raw", "manufacturer"),
        default=None,
        help="raw emits the BlueBee bytes directly in AdvData; manufacturer wraps them in AD type 0xFF",
    )
    parser.add_argument(
        "--include-flags",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include BLE Flags AD structure before BlueBee data; normally disabled for extended advertising",
    )
    parser.add_argument(
        "--company-id",
        type=lambda value: int(value, 0),
        default=0xFFFF,
        help="manufacturer company ID used with --ad-mode manufacturer",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(SCRIPT_DIR, "bluebee_waveform_30_72M.h"),
        help="output C header path",
    )
    parser.add_argument("--primary-symbol-name", default=None, help="C array name for the primary ADV_EXT_IND waveform")
    parser.add_argument("--secondary-symbol-name", default=None, help="C array name for the secondary AUX_ADV_IND waveform")
    parser.add_argument("--symbol-name", default=None, help="legacy single-array symbol name; also aliases the secondary array in extended mode")
    args = parser.parse_args()
    apply_profile_defaults(args)

    if args.primary_symbol_name is None:
        args.primary_symbol_name = f"bluebee_ext_primary_iq_ch{args.channel}"
    if args.secondary_symbol_name is None:
        args.secondary_symbol_name = args.symbol_name or f"bluebee_ext_secondary_iq_ch{args.secondary_channel}"

    mac = [int(part, 16) for part in args.mac.split(":")]
    if len(mac) != 6:
        raise ValueError("MAC must contain 6 bytes")

    zigbee_payload = parse_byte_list(args.zigbee_payload)
    zigbee_source, zigbee_frame = build_zigbee_source_bytes(args.embed_mode, zigbee_payload)
    zigbee_source = repeat_zigbee_source(zigbee_source, args.embed_mode, args.preamble_repeats)
    ble_chip_map = build_bluebee_chip_map(args.map_mode)
    bluebee_bits, approx_chips = zigbee_bytes_to_bluebee_bits(
        zigbee_source,
        ble_chip_map=ble_chip_map,
        phase_polarity=args.phase_polarity,
    )
    bluebee_bytes, bit_pad = bits_to_bytes_lsb(bluebee_bits)
    adv_data, bluebee_start = build_adv_data(
        bluebee_bytes,
        ad_mode=args.ad_mode,
        company_id=args.company_id,
        include_flags=args.include_flags,
    )
    ok, decoded_frame, distances = verify_zigbee_projection(zigbee_source, approx_chips)
    ext_adv_mode = BLE_EXT_ADV_MODES.get(getattr(args, "ext_adv_mode", "nonconn-nonscan"))

    if args.profile == "extended":
        primary_ll_payload, primary_pdu, primary_crc, aux_ptr = create_ext_primary_ll_payload(
            mac,
            primary_channel=args.channel,
            secondary_channel=args.secondary_channel,
            aux_offset_us=args.aux_offset_us,
            ext_adv_mode=ext_adv_mode,
        )
        secondary_ll_payload, secondary_pdu, secondary_crc, bluebee_pdu_start = create_ext_secondary_bluebee_ll_payload(
            adv_data,
            channel=args.secondary_channel,
            bluebee_start=bluebee_start,
            bluebee_len=len(bluebee_bytes),
            ext_adv_mode=ext_adv_mode,
        )
        primary_iq = ble_bits_to_iq_30_72m(
            list(bsp_string.bytes_to_bits_lsb(primary_ll_payload)),
            bt=args.bt,
            post_pad_us=args.post_pad_us,
        )
        secondary_iq = ble_bits_to_iq_30_72m(
            list(bsp_string.bytes_to_bits_lsb(secondary_ll_payload)),
            bt=args.bt,
            post_pad_us=args.post_pad_us,
        )
        on_air_bluebee = secondary_ll_payload[5 + bluebee_pdu_start:5 + bluebee_pdu_start + len(bluebee_bytes)]
        on_air_bits = list(bsp_string.bytes_to_bits_lsb(on_air_bluebee))
        on_air_chips = "".join("11" if bit else "00" for bit in on_air_bits[:len(bluebee_bits)])
        on_air_ok, _, on_air_distances = verify_zigbee_projection(zigbee_source, on_air_chips)

        meta = [
            f"profile: {args.profile}",
            f"primary_channel: {args.channel}",
            f"primary_frequency_mhz: {ble_channel_freq_mhz(args.channel)}",
            f"secondary_channel: {args.secondary_channel}",
            f"secondary_frequency_mhz: {ble_channel_freq_mhz(args.secondary_channel)}",
            f"aux_offset_us: {args.aux_offset_us}",
            f"aux_ptr: {' '.join(f'{x:02X}' for x in aux_ptr)}",
            f"adv_mode: {args.ext_adv_mode}",
            f"ad_mode: {args.ad_mode}",
            f"embed_mode: {args.embed_mode}",
            f"zigbee_payload_bytes: {len(zigbee_payload)}",
            f"zigbee_source_bytes: {len(zigbee_source)}",
            f"zigbee_frame_bytes: {len(zigbee_frame) if zigbee_frame else 0}",
            f"bluebee_payload_bytes: {len(bluebee_bytes)}",
            f"bluebee_bit_pad: {bit_pad}",
            f"ble_adv_data_bytes: {len(adv_data)}",
            f"primary_pdu_payload_bytes: {len(primary_pdu) - 2}",
            f"secondary_pdu_payload_bytes: {len(secondary_pdu) - 2}",
            f"post_pad_us: {args.post_pad_us:g}",
            f"map_mode: {args.map_mode}",
            f"phase_polarity: {args.phase_polarity}",
            f"preamble_repeats: {args.preamble_repeats}",
            f"zigbee_projection_ok: {ok}",
            f"on_air_projection_ok: {on_air_ok}",
        ]
        write_iq_c_arrays(
            args.output,
            [
                {
                    "symbol": args.primary_symbol_name,
                    "iq": primary_iq,
                    "channel": args.channel,
                    "freq_mhz": ble_channel_freq_mhz(args.channel),
                },
                {
                    "symbol": args.secondary_symbol_name,
                    "iq": secondary_iq,
                    "channel": args.secondary_channel,
                    "freq_mhz": ble_channel_freq_mhz(args.secondary_channel),
                },
            ],
            meta,
        )

        print(f"Profile: {args.profile}")
        print(f"Primary ADV_EXT_IND: ch{args.channel} {ble_channel_freq_mhz(args.channel)} MHz")
        print(f"Secondary AUX_ADV_IND: ch{args.secondary_channel} {ble_channel_freq_mhz(args.secondary_channel)} MHz")
        print(f"AuxPtr: {' '.join(f'{x:02X}' for x in aux_ptr)} offset={args.aux_offset_us} us")
        print(f"AD mode: {args.ad_mode}, embed mode: {args.embed_mode}, include flags: {args.include_flags}")
        print(f"ZigBee source: {' '.join(f'{x:02X}' for x in zigbee_source)}")
        if zigbee_frame:
            print(f"ZigBee frame: {' '.join(f'{x:02X}' for x in zigbee_frame)}")
        print(f"BlueBee bytes: {len(bluebee_bytes)}")
        print(f"BLE AdvData length: {len(adv_data)}")
        print(f"Primary PDU payload length: {len(primary_pdu) - 2}")
        print(f"Secondary PDU payload length: {len(secondary_pdu) - 2}")
        print(f"Primary BLE CRC: {' '.join(f'{x:02X}' for x in primary_crc)}")
        print(f"Secondary BLE CRC: {' '.join(f'{x:02X}' for x in secondary_crc)}")
        print(f"Map mode: {args.map_mode}, phase polarity: {args.phase_polarity}")
        print(f"ZigBee projection: {'OK' if ok else 'FAIL'}")
        print(f"On-air projection: {'OK' if on_air_ok else 'FAIL'}")
        print(f"Symbol distance range: {min(distances)}..{max(distances)}")
        print(f"On-air symbol distance range: {min(on_air_distances)}..{max(on_air_distances)}")
        print(f"Generated {len(primary_iq)} primary samples and {len(secondary_iq)} secondary samples -> {args.output}")
        return

    ll_payload, pdu_adv, crc, bluebee_pdu_start = create_bluebee_ll_payload(
        mac,
        adv_data,
        args.channel,
        bluebee_start=bluebee_start,
        bluebee_len=len(bluebee_bytes),
    )
    ble_bits = list(bsp_string.bytes_to_bits_lsb(ll_payload))
    iq_data = ble_bits_to_iq_30_72m(ble_bits, bt=args.bt, post_pad_us=args.post_pad_us)
    on_air_bluebee = ll_payload[5 + bluebee_pdu_start:5 + bluebee_pdu_start + len(bluebee_bytes)]
    on_air_bits = list(bsp_string.bytes_to_bits_lsb(on_air_bluebee))
    on_air_chips = "".join("11" if bit else "00" for bit in on_air_bits[:len(bluebee_bits)])
    on_air_ok, _, on_air_distances = verify_zigbee_projection(zigbee_source, on_air_chips)

    meta = [
        f"profile: {args.profile}",
        f"ad_mode: {args.ad_mode}",
        f"embed_mode: {args.embed_mode}",
        f"zigbee_payload_bytes: {len(zigbee_payload)}",
        f"zigbee_source_bytes: {len(zigbee_source)}",
        f"zigbee_frame_bytes: {len(zigbee_frame) if zigbee_frame else 0}",
        f"bluebee_payload_bytes: {len(bluebee_bytes)}",
        f"bluebee_bit_pad: {bit_pad}",
        f"ble_adv_data_bytes: {len(adv_data)}",
        f"ble_pdu_payload_bytes: {len(pdu_adv) - 2}",
        f"post_pad_us: {args.post_pad_us:g}",
        f"map_mode: {args.map_mode}",
        f"phase_polarity: {args.phase_polarity}",
        f"preamble_repeats: {args.preamble_repeats}",
        f"zigbee_projection_ok: {ok}",
        f"on_air_projection_ok: {on_air_ok}",
    ]
    legacy_symbol_name = args.symbol_name or f"bluebee_iq_ch{args.channel}"
    write_iq_c_array(args.output, legacy_symbol_name, iq_data, args.channel, meta)

    print(f"Profile: {args.profile}")
    print(f"AD mode: {args.ad_mode}, embed mode: {args.embed_mode}, include flags: {args.include_flags}")
    print(f"ZigBee source: {' '.join(f'{x:02X}' for x in zigbee_source)}")
    if zigbee_frame:
        print(f"ZigBee frame: {' '.join(f'{x:02X}' for x in zigbee_frame)}")
    print(f"BlueBee bytes: {len(bluebee_bytes)}")
    print(f"BLE AdvData length: {len(adv_data)}")
    print(f"BLE PDU payload length: {len(pdu_adv) - 2}")
    print(f"Post-pad silence: {args.post_pad_us:g} us")
    print(f"Map mode: {args.map_mode}, phase polarity: {args.phase_polarity}")
    print(f"BLE CRC: {' '.join(f'{x:02X}' for x in crc)}")
    print("BlueBee DSSS map:")
    for symbol, intra, min_inter, chips in map_metrics(ble_chip_map):
        marker = "*" if args.map_mode == "optimized" and chips != legacy_emulated_chips(CHIP_MAP[symbol]) else " "
        print(f"  {symbol:X}: intra={intra:2d} min_inter={min_inter:2d} {marker} {chips}")
    print(f"ZigBee projection: {'OK' if ok else 'FAIL'}")
    print(f"On-air projection: {'OK' if on_air_ok else 'FAIL'}")
    print(f"Symbol distance range: {min(distances)}..{max(distances)}")
    print(f"On-air symbol distance range: {min(on_air_distances)}..{max(on_air_distances)}")
    print(f"Generated {len(iq_data)} samples -> {args.output}")


if __name__ == "__main__":
    main()
