#!/usr/bin/env python3

import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "app_FreeRTOS" / "app"


HARNESS_SOURCE = r"""
#include <stdint.h>

#define BLUEBEE_GEN_HOST_TEST 1
#include "bluebee_gen.c"

uint32_t bluebee_gen_legacy_reference(uint32_t *iq, uint32_t capacity)
{
	uint32_t bit_count = g_meta.gfsk_bit_count;
	uint32_t high_count = bit_count * BLUEBEE_GEN_SPS_HIGH;
	uint32_t out_samples = ((high_count - 1u) / BLUEBEE_GEN_DECIM) + 1u;
	uint32_t out_words = BLUEBEE_GEN_PRE_PAD_WORDS + (out_samples * 2u) +
		BLUEBEE_GEN_POST_PAD_WORDS;
	float phase_step =
		(float)M_PI / (2.0f * (float)BLUEBEE_GEN_SPS_HIGH);
	float phase_step_decim = phase_step * (float)BLUEBEE_GEN_DECIM;
	float phase = 0.0f;
	uint32_t w = 0u;

	if (!iq || capacity < out_words)
		return 0u;
	for (uint32_t pad = 0u; pad < BLUEBEE_GEN_PRE_PAD_WORDS; pad++)
		iq[w++] = 0u;
	for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
		uint32_t n = n_out * BLUEBEE_GEN_DECIM;
		int32_t start = (int32_t)n - (int32_t)(BLUEBEE_GEN_TAPS / 2u);
		float acc = 0.0f;
		int32_t ii;
		int32_t qq;

		for (uint32_t k = 0u; k < BLUEBEE_GEN_TAPS; k++) {
			int32_t idx = start + (int32_t)k;

			if (idx >= 0 && idx < (int32_t)high_count) {
				uint32_t bit_idx =
					(uint32_t)idx / BLUEBEE_GEN_SPS_HIGH;
				float sym = g_gfsk_bits[bit_idx] ? 1.0f : -1.0f;

				acc += g_gfsk_taps[k] * sym;
			}
		}
		phase += acc * phase_step_decim;
		phase = wrap_pi(phase);
		ii = round_float_to_int(cosf(phase) * BLUEBEE_GEN_IQ_AMPLITUDE);
		qq = round_float_to_int(sinf(phase) * BLUEBEE_GEN_IQ_AMPLITUDE);
		iq[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
		iq[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
	}
	for (uint32_t pad = 0u; pad < BLUEBEE_GEN_POST_PAD_WORDS; pad++)
		iq[w++] = 0u;
	return w;
}
"""


class BluebeeGenMeta(ctypes.Structure):
    _fields_ = [
        ("payload", ctypes.POINTER(ctypes.c_uint8)),
        ("payload_len", ctypes.c_uint32),
        ("frame", ctypes.POINTER(ctypes.c_uint8)),
        ("frame_len", ctypes.c_uint32),
        ("gfsk_bytes", ctypes.POINTER(ctypes.c_uint8)),
        ("gfsk_bit_count", ctypes.c_uint32),
        ("gfsk_byte_count", ctypes.c_uint32),
        ("iq_words", ctypes.POINTER(ctypes.c_uint32)),
        ("iq_word_count", ctypes.c_uint32),
        ("iq_byte_count", ctypes.c_uint32),
        ("pre_pad_us", ctypes.c_uint32),
        ("air_us", ctypes.c_uint32),
        ("post_pad_us", ctypes.c_uint32),
        ("frame_time_us", ctypes.c_uint32),
        ("mapping_time_us", ctypes.c_uint32),
        ("gfsk_time_us", ctypes.c_uint32),
        ("total_time_us", ctypes.c_uint32),
    ]


def iq_complex(words):
    words = np.asarray(words, dtype=np.uint32)
    i_values = (words & 0xFFFF).astype(np.uint16).view(np.int16)
    q_values = (words >> 16).astype(np.uint16).view(np.int16)
    return i_values.astype(np.float64) + 1j * q_values.astype(np.float64)


def demodulate_center_bits(samples, bit_count):
    decoded = []
    for bit_index in range(bit_count):
        high_rate_center = bit_index * 768 + 384
        sample_index = int(round(high_rate_center / 25))
        delta = np.angle(samples[sample_index] * np.conj(samples[sample_index - 1]))
        decoded.append(1 if delta >= 0 else 0)
    return decoded


class WaveformEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(cls.temp_dir.name)
        harness = temp_path / "bluebee_gen_harness.c"
        library = temp_path / "libbluebee_gen_test.so"
        harness.write_text(HARNESS_SOURCE, encoding="utf-8")
        subprocess.run(
            [
                "cc",
                "-std=c99",
                "-O0",
                "-shared",
                "-fPIC",
                f"-I{APP_DIR}",
                str(harness),
                "-lm",
                "-o",
                str(library),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.bluebee_gen_build_payload.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint32,
        ]
        cls.lib.bluebee_gen_build_payload.restype = ctypes.c_int32
        cls.lib.bluebee_gen_get_last_meta.restype = ctypes.POINTER(
            BluebeeGenMeta
        )
        cls.lib.bluebee_gen_legacy_reference.argtypes = [
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint32,
        ]
        cls.lib.bluebee_gen_legacy_reference.restype = ctypes.c_uint32

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_prefix_sum_matches_legacy_waveform_and_bits(self):
        payload = bytes(range(10))
        payload_array = (ctypes.c_uint8 * len(payload))(*payload)
        self.assertEqual(
            self.lib.bluebee_gen_build_payload(payload_array, len(payload)),
            0,
        )
        meta = self.lib.bluebee_gen_get_last_meta().contents
        optimized = np.ctypeslib.as_array(
            meta.iq_words, shape=(meta.iq_word_count,)
        ).copy()
        reference_buffer = (ctypes.c_uint32 * meta.iq_word_count)()
        reference_count = self.lib.bluebee_gen_legacy_reference(
            reference_buffer, meta.iq_word_count
        )
        reference = np.ctypeslib.as_array(reference_buffer).copy()

        pre_pad_words = 30720 * 2
        post_pad_words = 30720 * 2
        self.assertEqual(reference_count, meta.iq_word_count)
        self.assertEqual(meta.pre_pad_us, 1000)
        self.assertEqual(meta.post_pad_us, 1000)
        self.assertTrue(np.all(optimized[:pre_pad_words] == 0))
        self.assertTrue(np.all(optimized[-post_pad_words:] == 0))
        self.assertTrue(np.all(reference[:pre_pad_words] == 0))
        self.assertTrue(np.all(reference[-post_pad_words:] == 0))

        optimized_samples = iq_complex(
            optimized[pre_pad_words:-post_pad_words:2]
        )
        reference_samples = iq_complex(
            reference[pre_pad_words:-post_pad_words:2]
        )
        correlation = abs(
            np.vdot(reference_samples, optimized_samples)
        ) / np.sqrt(
            np.vdot(reference_samples, reference_samples).real
            * np.vdot(optimized_samples, optimized_samples).real
        )
        self.assertGreaterEqual(correlation, 0.999)

        gfsk_bytes = bytes(
            np.ctypeslib.as_array(
                meta.gfsk_bytes, shape=(meta.gfsk_byte_count,)
            )
        )
        expected_bits = [
            (gfsk_bytes[index >> 3] >> (index & 7)) & 1
            for index in range(meta.gfsk_bit_count)
        ]
        self.assertEqual(
            demodulate_center_bits(optimized_samples, meta.gfsk_bit_count),
            expected_bits,
        )
        self.assertEqual(
            demodulate_center_bits(reference_samples, meta.gfsk_bit_count),
            expected_bits,
        )


if __name__ == "__main__":
    unittest.main()
