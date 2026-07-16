#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "bluebee_gen.h"

#define BLUEBEE_GEN_PREAMBLE_BYTES       4u
#define BLUEBEE_GEN_SFD                  0xA7u
#define BLUEBEE_GEN_FCS_BYTES            2u
#define BLUEBEE_GEN_PHR_BYTES            1u
#define BLUEBEE_GEN_FRAME_OVERHEAD_BYTES \
	(BLUEBEE_GEN_PREAMBLE_BYTES + 1u + BLUEBEE_GEN_PHR_BYTES + \
	 BLUEBEE_GEN_FCS_BYTES)
#define BLUEBEE_GEN_MAX_FRAME_BYTES \
	(BLUEBEE_GEN_FRAME_OVERHEAD_BYTES + BLUEBEE_GEN_MAX_PAYLOAD_BYTES)
#define BLUEBEE_GEN_GFSK_BITS_PER_FRAME_BYTE 32u
#define BLUEBEE_GEN_MAX_GFSK_BITS \
	(BLUEBEE_GEN_MAX_FRAME_BYTES * BLUEBEE_GEN_GFSK_BITS_PER_FRAME_BYTE)
#define BLUEBEE_GEN_MAX_GFSK_BYTES \
	((BLUEBEE_GEN_MAX_GFSK_BITS + 7u) / 8u)
#define BLUEBEE_GEN_SPS_HIGH             768u
#define BLUEBEE_GEN_DECIM                25u
#define BLUEBEE_GEN_SPAN                 4u
#define BLUEBEE_GEN_TAPS                 \
	(BLUEBEE_GEN_SPAN * BLUEBEE_GEN_SPS_HIGH)
#define BLUEBEE_GEN_BT                   0.5f
#define BLUEBEE_GEN_IQ_AMPLITUDE         10000
#define BLUEBEE_GEN_OUTPUT_SAMPLE_RATE   30720000u
#define BLUEBEE_GEN_POST_PAD_US          1000u
#define BLUEBEE_GEN_POST_PAD_WORDS \
	((uint32_t)((((uint64_t)BLUEBEE_GEN_OUTPUT_SAMPLE_RATE * \
		      BLUEBEE_GEN_POST_PAD_US) + 500000ULL) / 1000000ULL) * \
	 2u)
#define BLUEBEE_GEN_MAX_IQ_UNIQUE_WORDS \
	((((BLUEBEE_GEN_MAX_GFSK_BITS * BLUEBEE_GEN_SPS_HIGH) - 1u) / \
	  BLUEBEE_GEN_DECIM) + 1u)
#define BLUEBEE_GEN_MAX_IQ_WORDS \
	((BLUEBEE_GEN_MAX_IQ_UNIQUE_WORDS * 2u) + BLUEBEE_GEN_POST_PAD_WORDS)

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const uint8_t g_default_payload[] = { 0x11u, 0x22u, 0x33u, 0x44u };

static const char *const g_zigbee_chip_map[16] = {
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
};

/*
 * Python optimized BlueBee map collapsed from 32 pair-constrained chips to
 * 16 BLE GFSK bits. Bit 0 is the first chip pair emitted on air.
 */
static const uint16_t g_bluebee_gfsk_symbol_map[16] = {
	0x419Fu, 0x0E77u, 0x999Eu, 0x667Au,
	0x9DC3u, 0x770Eu, 0xDC39u, 0x70E7u,
	0xBCF5u, 0xB3D7u, 0xCD5Fu, 0x357Fu,
	0xD5FCu, 0x57F3u, 0x5BCFu, 0x6F3Du,
};

static uint8_t g_payload[BLUEBEE_GEN_MAX_PAYLOAD_BYTES];
static uint8_t g_frame[BLUEBEE_GEN_MAX_FRAME_BYTES];
static uint8_t g_gfsk_bits[BLUEBEE_GEN_MAX_GFSK_BITS];
static uint8_t g_gfsk_bytes[BLUEBEE_GEN_MAX_GFSK_BYTES];
static uint32_t g_iq_words[BLUEBEE_GEN_MAX_IQ_WORDS]
	__attribute__((aligned(64)));
static float g_gfsk_taps[BLUEBEE_GEN_TAPS];
static uint8_t g_gfsk_taps_ready;
static struct bluebee_gen_meta g_meta;

static uint32_t pack_iq_word(int16_t i, int16_t q)
{
	return (uint32_t)(uint16_t)i | ((uint32_t)(uint16_t)q << 16);
}

static int32_t round_float_to_int(float x)
{
	return (int32_t)(x >= 0.0f ? (x + 0.5f) : (x - 0.5f));
}

static float wrap_pi(float x)
{
	const float two_pi = 2.0f * (float)M_PI;

	while (x > (float)M_PI)
		x -= two_pi;
	while (x < -(float)M_PI)
		x += two_pi;

	return x;
}

static void init_gfsk_taps(void)
{
	const float alpha = sqrtf(logf(2.0f) / 2.0f) / BLUEBEE_GEN_BT;
	const float inv_sps = 1.0f / (float)BLUEBEE_GEN_SPS_HIGH;
	const float half = (float)BLUEBEE_GEN_TAPS / 2.0f;
	float sum = 0.0f;

	if (g_gfsk_taps_ready)
		return;

	for (uint32_t n = 0u; n < BLUEBEE_GEN_TAPS; n++) {
		float t = ((float)n - half) * inv_sps;
		float x = (float)M_PI * t / alpha;
		float h = (sqrtf((float)M_PI) / alpha) * expf(-(x * x));

		g_gfsk_taps[n] = h;
		sum += h;
	}

	if (sum != 0.0f) {
		float inv_sum = 1.0f / sum;

		for (uint32_t n = 0u; n < BLUEBEE_GEN_TAPS; n++)
			g_gfsk_taps[n] *= inv_sum;
	}

	g_gfsk_taps_ready = 1u;
}

static uint16_t crc16_ccitt_reflected(const uint8_t *data, uint32_t len)
{
	uint16_t crc = 0x0000u;

	for (uint32_t i = 0u; i < len; i++) {
		crc ^= data[i];
		for (uint32_t bit = 0u; bit < 8u; bit++) {
			if (crc & 1u)
				crc = (uint16_t)((crc >> 1) ^ 0x8408u);
			else
				crc >>= 1;
		}
	}

	return crc;
}

static int32_t build_zigbee_phy_frame(const uint8_t *payload,
				      uint32_t payload_len,
				      uint8_t *frame,
				      uint32_t *frame_len)
{
	uint16_t fcs;
	uint32_t off = 0u;
	uint32_t mac_len = payload_len + BLUEBEE_GEN_FCS_BYTES;

	if (payload_len > BLUEBEE_GEN_MAX_PAYLOAD_BYTES || mac_len > 127u)
		return -1;

	memset(frame, 0, BLUEBEE_GEN_PREAMBLE_BYTES);
	off += BLUEBEE_GEN_PREAMBLE_BYTES;
	frame[off++] = BLUEBEE_GEN_SFD;
	frame[off++] = (uint8_t)mac_len;
	memcpy(&frame[off], payload, payload_len);
	off += payload_len;

	fcs = crc16_ccitt_reflected(payload, payload_len);
	frame[off++] = (uint8_t)(fcs & 0xFFu);
	frame[off++] = (uint8_t)(fcs >> 8);

	*frame_len = off;

	return 0;
}

static uint8_t get_frame_bit_lsb_first(const uint8_t *frame, uint32_t bit_idx)
{
	return (uint8_t)((frame[bit_idx >> 3] >> (bit_idx & 7u)) & 1u);
}

static uint8_t get_python_symbol(const uint8_t *frame, uint32_t bit_idx)
{
	uint8_t symbol = 0u;

	for (uint32_t i = 0u; i < 4u; i++) {
		symbol <<= 1;
		symbol |= get_frame_bit_lsb_first(frame, bit_idx + i);
	}

	return symbol;
}

static uint8_t symbol_hamming_distance(uint16_t bluebee_bits,
				       const char *zigbee_chips)
{
	uint8_t dist = 0u;

	for (uint32_t chip = 0u; chip < 32u; chip++) {
		uint8_t emulated =
			(uint8_t)((bluebee_bits >> (chip >> 1)) & 1u);
		uint8_t ref = (uint8_t)(zigbee_chips[chip] == '1');

		if (emulated != ref)
			dist++;
	}

	return dist;
}

static uint8_t verify_projected_symbol(uint8_t symbol,
				       uint8_t *best_distance)
{
	uint16_t bluebee_bits = g_bluebee_gfsk_symbol_map[symbol];
	uint8_t best_sym = 0u;
	uint8_t best_dist = 33u;

	for (uint8_t ref_sym = 0u; ref_sym < 16u; ref_sym++) {
		uint8_t dist = symbol_hamming_distance(
			bluebee_bits, g_zigbee_chip_map[ref_sym]);

		if (dist < best_dist) {
			best_dist = dist;
			best_sym = ref_sym;
		}
	}

	*best_distance = best_dist;

	return (uint8_t)(best_sym == symbol);
}

static int32_t zigbee_frame_to_gfsk_bits(const uint8_t *frame,
					 uint32_t frame_len,
					 uint8_t *gfsk_bits,
					 uint8_t *gfsk_bytes,
					 uint32_t *gfsk_bit_count,
					 uint8_t *projection_ok,
					 uint8_t *distance_min,
					 uint8_t *distance_max)
{
	uint32_t frame_bits = frame_len * 8u;
	uint32_t out = 0u;
	uint8_t ok = 1u;
	uint8_t min_dist = 0xFFu;
	uint8_t max_dist = 0u;

	if ((frame_bits % 4u) != 0u)
		return -1;
	if ((frame_len * BLUEBEE_GEN_GFSK_BITS_PER_FRAME_BYTE) >
	    BLUEBEE_GEN_MAX_GFSK_BITS)
		return -1;

	memset(gfsk_bytes, 0, BLUEBEE_GEN_MAX_GFSK_BYTES);

	for (uint32_t bit = 0u; bit < frame_bits; bit += 4u) {
		uint8_t symbol = get_python_symbol(frame, bit);
		uint16_t mapped = g_bluebee_gfsk_symbol_map[symbol];
		uint8_t best_dist = 0u;

		if (!verify_projected_symbol(symbol, &best_dist))
			ok = 0u;
		if (best_dist < min_dist)
			min_dist = best_dist;
		if (best_dist > max_dist)
			max_dist = best_dist;

		for (uint32_t k = 0u; k < 16u; k++) {
			uint8_t gfsk_bit = (uint8_t)((mapped >> k) & 1u);

			gfsk_bits[out] = gfsk_bit;
			if (gfsk_bit)
				gfsk_bytes[out >> 3] |=
					(uint8_t)(1u << (out & 7u));
			out++;
		}
	}

	*gfsk_bit_count = out;
	*projection_ok = ok;
	*distance_min = min_dist;
	*distance_max = max_dist;

	return 0;
}

static int32_t build_iq_words_from_gfsk_bits(const uint8_t *bits,
					     uint32_t bit_count,
					     uint32_t *iq,
					     uint32_t *iq_word_count)
{
	uint32_t high_count = bit_count * BLUEBEE_GEN_SPS_HIGH;
	uint32_t out_samples = ((high_count - 1u) / BLUEBEE_GEN_DECIM) + 1u;
	uint32_t out_words = (out_samples * 2u) + BLUEBEE_GEN_POST_PAD_WORDS;
	float phase_step =
		(float)M_PI / (2.0f * (float)BLUEBEE_GEN_SPS_HIGH);
	float phase_step_decim = phase_step * (float)BLUEBEE_GEN_DECIM;
	float phase = 0.0f;
	uint32_t w = 0u;

	if (out_words > BLUEBEE_GEN_MAX_IQ_WORDS)
		return -1;

	init_gfsk_taps();

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
				float sym = bits[bit_idx] ? 1.0f : -1.0f;

				acc += g_gfsk_taps[k] * sym;
			}
		}

		phase += acc * phase_step_decim;
		phase = wrap_pi(phase);

		ii = round_float_to_int(cosf(phase) *
					(float)BLUEBEE_GEN_IQ_AMPLITUDE);
		qq = round_float_to_int(sinf(phase) *
					(float)BLUEBEE_GEN_IQ_AMPLITUDE);

		if (ii > 32767)
			ii = 32767;
		if (ii < -32768)
			ii = -32768;
		if (qq > 32767)
			qq = 32767;
		if (qq < -32768)
			qq = -32768;

		iq[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
		iq[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
	}

	for (uint32_t pad = 0u; pad < BLUEBEE_GEN_POST_PAD_WORDS; pad++)
		iq[w++] = 0u;

	*iq_word_count = w;

	return 0;
}

int32_t bluebee_gen_build_payload(const uint8_t *payload, uint32_t payload_len)
{
	uint32_t frame_len = 0u;
	uint32_t gfsk_bit_count = 0u;
	uint32_t iq_word_count = 0u;
	uint8_t projection_ok = 0u;
	uint8_t distance_min = 0u;
	uint8_t distance_max = 0u;

	if (!payload || payload_len == 0u ||
	    payload_len > BLUEBEE_GEN_MAX_PAYLOAD_BYTES)
		return -1;

	memcpy(g_payload, payload, payload_len);

	if (build_zigbee_phy_frame(g_payload, payload_len,
				   g_frame, &frame_len) < 0)
		return -1;

	if (zigbee_frame_to_gfsk_bits(g_frame, frame_len,
				      g_gfsk_bits, g_gfsk_bytes,
				      &gfsk_bit_count, &projection_ok,
				      &distance_min, &distance_max) < 0)
		return -1;

	if (build_iq_words_from_gfsk_bits(g_gfsk_bits, gfsk_bit_count,
					  g_iq_words, &iq_word_count) < 0)
		return -1;

	g_meta.payload = g_payload;
	g_meta.payload_len = payload_len;
	g_meta.frame = g_frame;
	g_meta.frame_len = frame_len;
	g_meta.gfsk_bytes = g_gfsk_bytes;
	g_meta.gfsk_bit_count = gfsk_bit_count;
	g_meta.gfsk_byte_count = (gfsk_bit_count + 7u) / 8u;
	g_meta.iq_words = g_iq_words;
	g_meta.iq_word_count = iq_word_count;
	g_meta.iq_byte_count = iq_word_count * sizeof(uint32_t);
	g_meta.air_us = gfsk_bit_count;
	g_meta.post_pad_us = BLUEBEE_GEN_POST_PAD_US;
	g_meta.zigbee_projection_ok = projection_ok;
	g_meta.symbol_distance_min = distance_min;
	g_meta.symbol_distance_max = distance_max;
	g_meta.tx_lo_hz = BLUEBEE_GEN_TX_LO_HZ;

	return 0;
}

int32_t bluebee_gen_build_default(void)
{
	return bluebee_gen_build_payload(g_default_payload,
					 sizeof(g_default_payload));
}

const struct bluebee_gen_meta *bluebee_gen_get_last_meta(void)
{
	return &g_meta;
}
