#!/usr/bin/env python3
# coding=utf-8

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zigbee_mod import (
    CHIP_MAP, PREAMBLE_BYTES, SFD, BIT_ORDER,
    bits_to_chips, bytes_to_bits, crc16_ccitt,
    oqpsk_modulate,
)


def build_phy_frame_from_bytes(payload_bytes):
    mac_len = len(payload_bytes) + 2
    if mac_len > 127:
        raise ValueError("MAC frame too long for 802.15.4 length")
    fcs = crc16_ccitt(payload_bytes)
    fcs_bytes = [fcs & 0xFF, (fcs >> 8) & 0xFF]
    frame = [0x00] * PREAMBLE_BYTES + [SFD, mac_len] + list(payload_bytes) + fcs_bytes
    return bytes_to_bits(frame, bit_order=BIT_ORDER)


def fft_resample(x, n_out):
    """FFT-based resampling. Preserves signal shape with zero-padding/truncation in frequency domain."""
    from numpy.fft import rfft, irfft
    n_in = len(x)
    X = rfft(x)
    if n_out > n_in:
        X_pad = np.zeros(n_out // 2 + 1, dtype=complex)
        k = min(len(X), len(X_pad))
        X_pad[:k] = X[:k]
        return irfft(X_pad, n=n_out) * (n_out / n_in)
    else:
        k = n_out // 2 + 1
        X_trim = X[:k]
        return irfft(X_trim, n=n_out) * (n_out / n_in)


def generate_zigbee_iq_30_72M(payload_bytes, pad_us=500):
    """Generate Zigbee OQPSK IQ at 30.72 MSPS, compatible with 10 MHz HackRF reception.

    Strategy: generate at 10 MHz (sps=5, integer chip alignment) using the proven
    oqpsk_modulate, add padding, then FFT-resample to 30.72 MHz.
    """
    # 1. Build PHY frame bits
    frame_bits = build_phy_frame_from_bytes(payload_bytes)

    # 2. Bits → chips (4 bits per symbol → 32 chips per symbol)
    chip_bits = bits_to_chips(frame_bits)

    # 3. OQPSK modulate at 10 MHz (sps=5) — integer chip boundaries
    sps_rx = 5
    i_wave, q_wave = oqpsk_modulate(chip_bits, samples_per_chip=sps_rx)
    i_wave = np.array(i_wave, dtype=np.float64)
    q_wave = np.array(q_wave, dtype=np.float64)

    # 4. FFT resample from 10 MHz to 30.72 MHz (ratio = 30.72/10 = 384/125)
    #    MUST be done BEFORE adding padding — FFT assumes periodic signal
    n_10m = len(i_wave)
    n_30m = int(n_10m * 384 / 125)
    i_out = fft_resample(i_wave, n_30m)
    q_out = fft_resample(q_wave, n_30m)

    # 5. Add silence padding at 30.72 MHz (after resampling to avoid artifacts)
    sample_rate_30m = 30.72e6
    pad_samples = int(pad_us * 1e-6 * sample_rate_30m)
    i_out = np.concatenate([np.zeros(pad_samples, dtype=np.float64),
                             i_out,
                             np.zeros(pad_samples, dtype=np.float64)])
    q_out = np.concatenate([np.zeros(pad_samples, dtype=np.float64),
                             q_out,
                             np.zeros(pad_samples, dtype=np.float64)])

    # 6. Scale to 16-bit integer range
    peak = max(np.max(np.abs(i_out)), np.max(np.abs(q_out)))
    if peak > 0:
        scale = 32000.0 / peak
    else:
        scale = 1.0

    i_int = np.round(i_out * scale).astype(np.int32)
    q_int = np.round(q_out * scale).astype(np.int32)
    i_int = np.clip(i_int, -32768, 32767)
    q_int = np.clip(q_int, -32768, 32767)

    # 7. Pack as uint32: Q<<16 | I
    i_uint16 = i_int.astype(np.uint16)
    q_uint16 = q_int.astype(np.uint16)
    iq_uint32 = (q_uint16.astype(np.uint32) << 16) | i_uint16.astype(np.uint32)

    # 8. Repeat each sample twice for dual-channel DMA
    iq_uint32_repeated = np.repeat(iq_uint32, 2)

    return iq_uint32_repeated


if __name__ == '__main__':
    payload = [0x11, 0x22, 0x33, 0x44, 0x55]

    pad_us = 500
    iq_data = generate_zigbee_iq_30_72M(payload, pad_us=pad_us)

    unique_samples = len(iq_data) // 2

    # Output zigbee_tx.c for the SDK
    sdk_src = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "hdl", "projects", "antsdre310",
        "antsdre310.sdk", "app", "src", "zigbee_tx.c"
    )
    sdk_src = os.path.normpath(sdk_src)

    with open(sdk_src, "w") as f:
        f.write('#include <stdlib.h>\n')
        f.write('#include <stdio.h>\n')
        f.write('#include <inttypes.h>\n')
        f.write('\n')
        f.write(f'const uint32_t zigbee_iq[{len(iq_data)}] __attribute__((aligned(64))) = {{\n')

        for i in range(0, len(iq_data), 8):
            chunk = iq_data[i:i + 8]
            hex_strs = [f"0x{val:08X}" for val in chunk]
            f.write("    " + ", ".join(hex_strs))
            if i + 8 < len(iq_data):
                f.write(",\n")
            else:
                f.write("\n")

        f.write("};\n")

    # Update zigbee_tx.h
    sdk_hdr = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "hdl", "projects", "antsdre310",
        "antsdre310.sdk", "app", "src", "zigbee_tx.h"
    )
    sdk_hdr = os.path.normpath(sdk_hdr)

    with open(sdk_hdr, "w") as f:
        f.write('#ifndef ZIGBEE_TX\n')
        f.write('\n')
        f.write('#define ZIGBEE_TX\n')
        f.write('\n')
        f.write(f'extern const uint32_t zigbee_iq[{len(iq_data)}] __attribute__((aligned(64)));\n')
        f.write('\n')
        f.write('#endif\n')

    frame_bits = build_phy_frame_from_bytes(payload)
    print(f"Generated {len(iq_data)} samples -> {sdk_src}")
    print(f"Padding: {pad_us} us before + {pad_us} us after")
    print(f"Unique samples: {unique_samples}, duration: {unique_samples/30.72:.0f} μs")
    print(f"Chip count: {len(frame_bits) // 4}")
    print(f"Frame bits: {len(frame_bits)}")
    print(f"Total chips: {len(bits_to_chips(frame_bits))}")
