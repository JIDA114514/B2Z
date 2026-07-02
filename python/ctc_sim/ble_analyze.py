#!/usr/bin/env python3
# coding=utf-8

import argparse
import math


BLE_PREAMBLE = 0xAA
BLE_ACCESS_ADDR = [0xD6, 0xBE, 0x89, 0x8E]

BLE_CHANS = {37: 0, 0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9,
             9: 10, 10: 11, 38: 12, 11: 13, 12: 14, 13: 15, 14: 16, 15: 17, 16: 18,
             17: 19, 18: 20, 19: 21, 20: 22, 21: 23, 22: 24, 23: 25, 24: 26, 25: 27,
             26: 28, 27: 29, 28: 30, 29: 31, 30: 32, 31: 33, 32: 34, 33: 35, 34: 36,
             35: 37, 36: 38, 39: 39}


def bt_swap_bits(value):
    return (value * 0x0202020202 & 0x010884422010) % 1023


def bt_dewhitening(data, channel):
    ret = []
    chan_idx = BLE_CHANS.get(channel, channel)
    lfsr = bt_swap_bits(chan_idx) | 2

    if not data:
        return ret

    processed = [bt_swap_bits(d) for d in data]
    for d in processed:
        for i in [128, 64, 32, 16, 8, 4, 2, 1]:
            if lfsr & 0x80:
                lfsr ^= 0x11
                d ^= i
            lfsr <<= 1
        ret.append(bt_swap_bits(d))
    return ret


def bt_crc(data, length, init=0x555555):
    ret = [(init >> 16) & 0xFF, (init >> 8) & 0xFF, init & 0xFF]
    for d in data[:length]:
        for _ in range(8):
            t = (ret[0] >> 7) & 1
            ret[0] <<= 1
            if ret[1] & 0x80:
                ret[0] |= 1
            ret[1] <<= 1
            if ret[2] & 0x80:
                ret[1] |= 1
            ret[2] <<= 1
            if d & 1 != t:
                ret[2] ^= 0x5B
                ret[1] ^= 0x06
            d >>= 1

    ret[0] = bt_swap_bits(ret[0] & 0xFF)
    ret[1] = bt_swap_bits(ret[1] & 0xFF)
    ret[2] = bt_swap_bits(ret[2] & 0xFF)
    return ret


def bits_to_bytes_lsb(bits, start=0, byte_len=None):
    byte_list = []
    tmp = 0
    idx = 0
    bit_iter = bits[start:]
    for value in bit_iter:
        tmp += (value << idx)
        idx += 1
        if idx % 8 == 0:
            byte_list.append(tmp)
            if byte_len is not None and len(byte_list) >= byte_len:
                break
            idx = 0
            tmp = 0
    return byte_list


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


def gfsk_demod_bits(i_list, q_list, sample_rate, sps, append_last=True):
    phases = [math.atan2(q, i) for i, q in zip(i_list, q_list)]
    dphi = []
    for idx in range(1, len(phases)):
        delta = phases[idx] - phases[idx - 1]
        delta = (delta + math.pi) % (2.0 * math.pi) - math.pi
        dphi.append(delta)
    if append_last and dphi:
        dphi.append(dphi[-1])

    two_pi = 2.0 * math.pi
    freq_inst = [d * sample_rate / two_pi for d in dphi]
    if sps <= 0:
        raise ValueError("sps must be positive")

    bit_count = len(freq_inst) // sps
    bits = []
    for k in range(bit_count):
        s = k * sps
        e = s + sps
        avg = sum(freq_inst[s:e]) / sps
        bits.append(1 if avg >= 0 else 0)
    return bits


def byte_to_bits_lsb(value):
    return [(value >> i) & 1 for i in range(8)]


def build_access_pattern():
    bits = []
    bits.extend(byte_to_bits_lsb(BLE_PREAMBLE))
    for b in BLE_ACCESS_ADDR:
        bits.extend(byte_to_bits_lsb(b))
    return bits


def find_access_address_bits(bits, pattern):
    plen = len(pattern)
    for i in range(len(bits) - plen + 1):
        if bits[i : i + plen] == pattern:
            return i
    return -1


def parse_adv_payload(adv_payload, adv_payload_wt=None):
    adva = adv_payload[:6]
    adv_data = adv_payload[6:]
    adv_data_wt = None
    if adv_payload_wt is not None:
        adv_data_wt = adv_payload_wt[6:]
    print("advA:", "".join(f"{b:02X}" for b in reversed(adva)))
    idx = 0
    while idx < len(adv_data):
        if adv_data[idx] == 0:
            break
        length = adv_data[idx]
        if idx + length >= len(adv_data):
            break
        ad_type = adv_data[idx + 1]
        ad_value = adv_data[idx + 2 : idx + 1 + length]
        print(f"AD type 0x{ad_type:02X}: {bytes(ad_value).hex()}")
        if ad_type == 0x09 and adv_data_wt is not None:
            wt_end = idx + 1 + length
            if wt_end <= len(adv_data_wt):
                ad_value_wt = adv_data_wt[idx + 2 : wt_end]
                print(f"  name_wt: {bytes(ad_value_wt).hex()}")
                print(f"  name_clr: {bytes(ad_value).hex()}")
        if ad_type == 0xFF and len(ad_value) >= 2:
            company_id = ad_value[0] | (ad_value[1] << 8)
            mfg_payload = ad_value[2:]
            print(f"  manufacturer: 0x{company_id:04X} payload={bytes(mfg_payload).hex()}")
        idx += length + 1


def try_decode(bits, channel, pattern_bits):
    start_bit = find_access_address_bits(bits, pattern_bits)
    if start_bit < 0:
        return {
            "status": "no_preamble",
            "start_bit": -1,
        }

    head_bit = start_bit + len(pattern_bits)
    header_wt = bits_to_bytes_lsb(bits, start=head_bit, byte_len=2)
    if len(header_wt) < 2:
        return {
            "status": "short_header",
            "start_bit": start_bit,
        }
    header = bt_dewhitening(header_wt, channel)
    pdu_len = header[1] & 0x3F
    pdu_wt = bits_to_bytes_lsb(bits, start=head_bit, byte_len=2 + pdu_len + 3)
    if len(pdu_wt) < 2 + pdu_len + 3:
        return {
            "status": "short_pdu",
            "start_bit": start_bit,
            "header": header,
            "pdu_len": pdu_len,
            "needed_bytes": 2 + pdu_len + 3,
            "got_bytes": len(pdu_wt),
            "total_bits": len(bits),
            "head_bit": head_bit,
        }
    pdu = bt_dewhitening(pdu_wt, channel)
    payload = pdu[2 : 2 + pdu_len]
    payload_wt = pdu_wt[2 : 2 + pdu_len]
    crc = pdu[-3:]
    calc_crc = bt_crc(pdu, 2 + pdu_len)
    crc_ok = crc == calc_crc
    crc_lastbit_ok = False
    crc_lastbit_idx = None
    if not crc_ok and len(crc) == 3:
        for bit_idx in range(8):
            crc_flip = crc[:]
            crc_flip[-1] ^= (1 << bit_idx)
            if crc_flip == calc_crc:
                crc_lastbit_ok = True
                crc_lastbit_idx = bit_idx
                break

    status = "ok" if crc_ok else "crc_mismatch"
    fixed_crc = None
    if crc_lastbit_ok:
        status = "ok_crc_lastbit"
        fixed_crc = crc[:]
        fixed_crc[-1] ^= (1 << crc_lastbit_idx)

    return {
        "status": status,
        "header": header,
        "payload": payload,
        "payload_wt": payload_wt,
        "start_bit": start_bit,
        "pdu_len": pdu_len,
        "crc": crc,
        "calc_crc": calc_crc,
        "crc_lastbit_ok": crc_lastbit_ok,
        "crc_lastbit_idx": crc_lastbit_idx,
        "fixed_crc": fixed_crc,
    }


def try_decode_with_pad(bits, channel, pattern_bits):
    result = try_decode(bits, channel, pattern_bits)
    if result.get("status") != "short_pdu":
        return result

    needed = result.get("needed_bytes", 0)
    got = result.get("got_bytes", 0)
    if needed - got != 1:
        return result

    if not bits:
        return result

    last_bit = bits[-1]
    pad_bits = [last_bit] * 8
    padded = bits + pad_bits
    retry = try_decode(padded, channel, pattern_bits)
    if retry.get("status") == "ok":
        retry["status"] = "ok_padded"
    return retry


def main():
    parser = argparse.ArgumentParser(
        description="Analyze BLE IQ and print decoded payload"
    )
    parser.add_argument(
        "input_iq",
        nargs="?",
        default="iq_data.txt",
        help="input IQ txt file",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=None,
        help="IQ sample rate in Hz (overrides file meta)",
    )
    parser.add_argument(
        "--sps",
        type=int,
        default=None,
        help="samples per BLE symbol (overrides file meta)",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=None,
        help="BLE advertising channel (37/38/39)",
    )
    args = parser.parse_args()

    i_list, q_list, meta = read_iq(args.input_iq)

    sample_rate = args.sample_rate
    if sample_rate is None and "sample_rate_hz" in meta:
        sample_rate = float(meta["sample_rate_hz"])
    if sample_rate is None:
        raise ValueError("sample_rate is required")

    sps = args.sps
    if sps is None and "sps" in meta:
        sps = int(float(meta["sps"]))
    if sps is None:
        raise ValueError("sps is required")

    channel = args.channel
    if channel is None and "channel" in meta:
        channel = int(float(meta["channel"]))
    if channel is None:
        channel = 39

    pattern_bits = build_access_pattern()
    best = None
    best_inverted = None
    best_variant = None
    best_score = (-1, -1)
    variants = []
    for append_last in (True, False):
        base_bits = gfsk_demod_bits(i_list, q_list, sample_rate, sps, append_last=append_last)
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
            decoded = try_decode_with_pad(test_bits, channel, pattern_bits)
            if decoded.get("status") == "no_preamble":
                continue
            score = score_result(decoded)
            if score > best_score:
                best = decoded
                best_inverted = inverted
                best_variant = (variant_name, append_last)
                best_score = score

    if not best:
        print("no valid BLE frame found")
        return

    header = best.get("header")
    payload = best.get("payload")
    print(f"status: {best.get('status')}")
    print(f"start_bit: {best.get('start_bit')}")
    print(f"bit_inverted: {best_inverted}")
    if best_variant:
        print(f"bit_variant: {best_variant[0]} append_last={best_variant[1]}")
    if header is not None:
        print("PDU header:", bytes(header).hex())
        print(f"pdu_len: {best.get('pdu_len')}")
        if best.get("status") == "short_pdu":
            print(f"needed_bytes: {best.get('needed_bytes')}")
            print(f"got_bytes: {best.get('got_bytes')}")
            print(f"total_bits: {best.get('total_bits')}")
            print(f"head_bit: {best.get('head_bit')}")
    if payload is not None:
        payload_wt = best.get("payload_wt")
        if payload_wt is not None:
            print("payload_wt:", bytes(payload_wt).hex())
        print("payload:", bytes(payload).hex())
        parse_adv_payload(payload, payload_wt)
    if best.get("status") == "crc_mismatch":
        print("CRC mismatch")
        print("crc:", bytes(best.get("crc", [])).hex())
        print("calc:", bytes(best.get("calc_crc", [])).hex())
    if best.get("status") == "ok_crc_lastbit":
        bit_idx = best.get("crc_lastbit_idx")
        print(f"crc note: matches if CRC last byte bit {bit_idx} flipped")
        print("crc fixed:", bytes(best.get("fixed_crc", [])).hex())


if __name__ == "__main__":
    main()
