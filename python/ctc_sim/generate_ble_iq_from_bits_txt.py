import argparse
import os
import numpy as np
import sys

sys.path.append('../')

from bsp_algorithm import bsp_algorithm
from bsp_string import bsp_string

BLE_CHANS = {37: 0, 0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9,
             9: 10, 10: 11, 38: 12, 11: 13, 12: 14, 13: 15, 14: 16, 15: 17, 16: 18,
             17: 19, 18: 20, 19: 21, 20: 22, 21: 23, 22: 24, 23: 25, 24: 26, 25: 27,
             26: 28, 27: 29, 28: 30, 29: 31, 30: 32, 31: 33, 32: 34, 33: 35, 34: 36,
             35: 37, 36: 38, 39: 39}


def get_gaussian_filter(bt, sps, span=4):
    t = np.arange(-span * sps / 2, span * sps / 2) / sps
    alpha = np.sqrt(np.log(2) / 2) / bt
    h = (np.sqrt(np.pi) / alpha) * np.exp(-((np.pi * t / alpha) ** 2))
    return h / np.sum(h)


def read_bits_from_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    bits = []
    for idx, ch in enumerate(content):
        if ch == "0":
            bits.append(0)
        elif ch == "1":
            bits.append(1)
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"Invalid character at index {idx}: {ch!r}")

    if not bits:
        raise ValueError("No bits found in input file")

    return bits


def whitening_mask(byte_len, channel):
    zeros = [0] * byte_len
    chan_idx = BLE_CHANS.get(channel, channel)
    return bsp_algorithm.bt_dewhitening(zeros, chan_idx)


def build_adv_data_from_bits(payload_bits):
    pad = (-len(payload_bits)) % 8
    if pad:
        payload_bits = payload_bits + [0] * pad

    payload_bytes = list(bsp_string.bits_to_bytes_lsb(payload_bits))
    if len(payload_bytes) > 26:
        raise ValueError("payload too large for ADV device name")

    ad_len = len(payload_bytes) + 1
    adv_data = [ad_len, 0x09]
    adv_data.extend(payload_bytes)
    return adv_data, len(payload_bytes), pad


def create_ll_payload_with_prewhitening(mac, adv_data, channel, payload_len, debug=False):
    ll_payload = [0xAA, 0xD6, 0xBE, 0x89, 0x8E]

    flags = bytes.fromhex("020106")
    pdu_adv = []
    pdu_adv.extend([0x42, (len(adv_data) + 9) & 0xFF])
    pdu_adv.extend(reversed(mac))
    pdu_adv.extend(flags)
    pdu_adv.extend(adv_data)

    adv_data_start = 2 + 6 + 3
    payload_start = adv_data_start + 2

    mask = whitening_mask(len(pdu_adv) + 3, channel)
    for i in range(payload_len):
        idx = payload_start + i
        pdu_adv[idx] ^= mask[idx]

    crc = bsp_algorithm.bt_crc(pdu_adv, len(pdu_adv))
    pdu_adv_crc = pdu_adv + crc
    chan_idx = BLE_CHANS.get(channel, channel)
    pdu_adv_crc_wt = bsp_algorithm.bt_dewhitening(pdu_adv_crc, chan_idx)

    ll_payload.extend(pdu_adv_crc_wt)
    if debug:
        print(f"pdu_adv: {pdu_adv}")
        print(f"crc: {crc}")
    return ll_payload


def bits_to_iq(bits, bt=0.5, sps=1, use_filter=True, freq_dev_hz=250_000.0):
    bits = np.array(bits, dtype=np.float32)
    symbols = np.where(bits > 0.5, 1.0, -1.0).astype(np.float32)
    freq_dev = symbols * float(freq_dev_hz)

    freq_upsampled = np.repeat(freq_dev, sps)
    if use_filter:
        h = get_gaussian_filter(bt=bt, sps=sps, span=4)
        f_sig = np.convolve(freq_upsampled, h, mode="same")
    else:
        f_sig = freq_upsampled

    sample_rate = 1_000_000 * sps
    phase = np.cumsum(2 * np.pi * f_sig / sample_rate)
    i_out = np.cos(phase)
    q_out = np.sin(phase)

    return i_out, q_out


def write_iq_txt(path, i_out, q_out, sample_rate, meta):
    with open(path, "w", encoding="utf-8") as f:
        for line in meta:
            f.write(f"# {line}\n")
        f.write(f"# sample_rate_hz: {sample_rate}\n")
        f.write("# columns: I Q\n")
        for i_val, q_val in zip(i_out, q_out):
            f.write(f"{i_val:.8f} {q_val:.8f}\n")


def generate_ble_iq_30_72m(bits, bt=0.5):
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
    i_uint16 = i_int & 0xFFFF
    q_uint16 = q_int & 0xFFFF
    iq_uint32 = (q_uint16 << 16) | i_uint16
    iq_uint32_repeated = np.repeat(iq_uint32, 2)
    return iq_uint32_repeated


def write_iq_c_array(path, iq_data, channel):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated BLE Waveforms\n")
        f.write("// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)\n")
        f.write(f"// Channel: {channel}\n\n")
        f.write("#include <stdint.h>\n\n")
        f.write(
            f"const uint32_t ble_iq_ch{channel}[{len(iq_data)}] __attribute__((aligned(64))) = {{\n"
        )
        for i in range(0, len(iq_data), 8):
            chunk = iq_data[i : i + 8]
            hex_strs = [f"0x{val:08X}" for val in chunk]
            f.write("    " + ", ".join(hex_strs))
            if i + 8 < len(iq_data):
                f.write(",\n")
            else:
                f.write("\n")
        f.write("};\n")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(script_dir, "data_bits.txt")
    default_output = os.path.join(script_dir, "iq_data.txt")

    parser = argparse.ArgumentParser(
        description="Generate BLE IQ waveform from payload bitstream"
    )
    parser.add_argument(
        "input_bits",
        nargs="?",
        default=default_input,
        help="txt file containing 0/1 bitstream",
    )
    parser.add_argument(
        "output_iq",
        nargs="?",
        default=default_output,
        help="output txt file for IQ samples",
    )
    parser.add_argument("--bt", type=float, default=0.5, help="Gaussian BT")
    parser.add_argument(
        "--sps",
        type=int,
        default=1,
        help="samples per symbol (no resampling)",
    )
    parser.add_argument(
        "--freq-dev",
        type=float,
        default=250000.0,
        help="GFSK frequency deviation in Hz",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="disable Gaussian filtering",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=39,
        help="BLE advertising channel (37/38/39)",
    )
    parser.add_argument(
        "--company-id",
        type=lambda x: int(x, 0),
        default=0xFFFF,
        help="manufacturer company ID (hex)",
    )
    parser.add_argument(
        "--mac",
        default="FF:22:33:44:55:FF",
        help="advertiser MAC address",
    )
    parser.add_argument(
        "--out-30m",
        nargs="?",
        const="ble_waveform_30_72M.h",
        default=None,
        help="output C header for 30.72 MSPS IQ",
    )
    args = parser.parse_args()

    payload_bits = read_bits_from_txt(args.input_bits)
    adv_data, payload_len, pad = build_adv_data_from_bits(payload_bits)

    mac = [int(x, 16) for x in args.mac.split(":")]
    if len(mac) != 6:
        raise ValueError("MAC must have 6 bytes")

    ll_payload = create_ll_payload_with_prewhitening(
        mac, adv_data, args.channel, payload_len, debug=False
    )
    bits = list(bsp_string.bytes_to_bits_lsb(ll_payload))

    i_out, q_out = bits_to_iq(
        bits,
        bt=args.bt,
        sps=args.sps,
        use_filter=not args.no_filter,
        freq_dev_hz=args.freq_dev,
    )

    symbol_rate = 1_000_000
    sample_rate = symbol_rate * args.sps
    meta = [
        "modulation: GFSK",
        f"input_bits: {len(payload_bits)}",
        f"payload_pad_bits: {pad}",
        f"bt: {args.bt}",
        f"sps: {args.sps}",
        f"gaussian_filter: {not args.no_filter}",
        f"freq_dev_hz: {args.freq_dev}",
        f"channel: {args.channel}",
        f"company_id: 0x{args.company_id:04X}",
        f"mac: {args.mac}",
    ]
    write_iq_txt(args.output_iq, i_out, q_out, sample_rate, meta)

    if args.out_30m:
        iq_30m = generate_ble_iq_30_72m(bits, bt=args.bt)
        write_iq_c_array(args.out_30m, iq_30m, args.channel)


if __name__ == "__main__":
    main()
