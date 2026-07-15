#include <math.h>
#include <stdint.h>
#include <string.h>

#include "ble_exadv_secondary_gen.h"

#define BLE_EXADV_DEFAULT_CHANNEL          39u
#define BLE_EXADV_PREAMBLE_AND_AA_LEN      5u
#define BLE_EXADV_CRC_LEN                  3u
#define BLE_EXADV_MAX_PDU_BYTES            257u
#define BLE_EXADV_MAX_LL_PAYLOAD_BYTES \
	(BLE_EXADV_PREAMBLE_AND_AA_LEN + BLE_EXADV_MAX_PDU_BYTES + \
	 BLE_EXADV_CRC_LEN)
#define BLE_EXADV_MAX_IQ_WORDS             132000u
#define BLE_EXADV_SPS_HIGH                 768u
#define BLE_EXADV_DECIM                    25u
#define BLE_EXADV_SPAN                     4u
#define BLE_EXADV_TAPS                     (BLE_EXADV_SPAN * BLE_EXADV_SPS_HIGH)
#define BLE_EXADV_BT                       0.5f
#define BLE_EXADV_IQ_AMPLITUDE             10000
#define BLE_EXADV_OUTPUT_SAMPLE_RATE       30720000u
#define BLE_EXADV_POST_PAD_US              10u
#define BLE_EXADV_POST_PAD_WORDS \
	((uint32_t)((((uint64_t)BLE_EXADV_OUTPUT_SAMPLE_RATE * \
		      BLE_EXADV_POST_PAD_US) + 500000ULL) / 1000000ULL) * 2u)

#define BLE_EXT_ADV_MODE_CONNECTABLE       0x01u
#define BLE_EXT_HDR_FLAG_ADVA              0x01u
#define BLE_EXT_HDR_FLAG_ADI               0x08u
#define BLE_AD_TYPE_FLAGS                  0x01u
#define BLE_AD_TYPE_COMPLETE_LOCAL_NAME    0x09u
#define BLE_AD_TYPE_MANUFACTURER           0xFFu
#define BLE_PDU_TYPE_ADV_EXT_IND           0x07u

#define ZIGBEE_PREAMBLE_BYTES              4u
#define ZIGBEE_SFD                         0xA7u
#define ZIGBEE_MAX_FRAME_BYTES \
	(ZIGBEE_PREAMBLE_BYTES + 1u + 1u + \
	 BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES + 2u)
#define BLUEBEE_MAX_BYTES                  ((ZIGBEE_MAX_FRAME_BYTES * 32u) / 8u)
#define BLE_EXADV_ADV_DATA_MAX_BYTES       255u

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const uint8_t g_ble_preamble_and_aa[BLE_EXADV_PREAMBLE_AND_AA_LEN] = {
	0xAAu, 0xD6u, 0xBEu, 0x89u, 0x8Eu,
};

static const uint8_t g_default_mac[6] = {
	0xC1u, 0xA2u, 0xA3u, 0xA4u, 0xA5u, 0xA6u,
};

static const char g_default_name[] = "S";

static const uint8_t
g_default_zigbee_payload[BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES] = {
	0x00u, 0x01u, 0x02u, 0x03u, 0x04u, 0x05u, 0x06u, 0x07u,
	0x08u, 0x09u, 0x0Au, 0x0Bu, 0x0Cu, 0x0Du, 0x0Eu, 0x0Fu,
	0x10u, 0x11u, 0x12u, 0x13u, 0x14u, 0x15u, 0x16u, 0x17u,
	0x18u, 0x19u, 0x1Au, 0x1Bu, 0x1Cu, 0x1Du, 0x1Eu, 0x1Fu,
	0x20u, 0x21u, 0x22u, 0x23u, 0x24u, 0x25u, 0x26u, 0x27u,
	0x28u, 0x29u, 0x2Au, 0x2Bu, 0x2Cu, 0x2Du,
};

static const uint16_t g_bluebee_gfsk_symbol_map[16] = {
	0x419Fu, 0x0E77u, 0x999Eu, 0x667Au,
	0x9DC3u, 0x770Eu, 0xDC39u, 0x70E7u,
	0xBCF5u, 0xB3D7u, 0xCD5Fu, 0x357Fu,
	0xD5FCu, 0x57F3u, 0x5BCFu, 0x6F3Du,
};

static uint8_t g_zigbee_payload[BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES];
static uint8_t g_zigbee_frame[ZIGBEE_MAX_FRAME_BYTES];
static uint8_t g_bluebee_bytes[BLUEBEE_MAX_BYTES];
static uint8_t g_adv_data[BLE_EXADV_ADV_DATA_MAX_BYTES];
static uint8_t g_pdu[BLE_EXADV_MAX_PDU_BYTES];
static uint8_t g_crc[BLE_EXADV_CRC_LEN];
static uint8_t g_ll_payload[BLE_EXADV_MAX_LL_PAYLOAD_BYTES];
static uint32_t g_iq_words[BLE_EXADV_MAX_IQ_WORDS]
	__attribute__((aligned(64)));
static float g_gfsk_taps[BLE_EXADV_TAPS];
static uint8_t g_gfsk_taps_ready;
static struct ble_exadv_secondary_gen_meta g_meta;

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
	const float alpha = sqrtf(logf(2.0f) / 2.0f) / BLE_EXADV_BT;
	const float inv_sps = 1.0f / (float)BLE_EXADV_SPS_HIGH;
	const float half = (float)BLE_EXADV_TAPS / 2.0f;
	float sum = 0.0f;

	if (g_gfsk_taps_ready)
		return;

	for (uint32_t n = 0u; n < BLE_EXADV_TAPS; n++) {
		float t = ((float)n - half) * inv_sps;
		float x = (float)M_PI * t / alpha;
		float h = (sqrtf((float)M_PI) / alpha) * expf(-(x * x));

		g_gfsk_taps[n] = h;
		sum += h;
	}

	if (sum != 0.0f) {
		float inv_sum = 1.0f / sum;

		for (uint32_t n = 0u; n < BLE_EXADV_TAPS; n++)
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

static int32_t build_zigbee_frame(const uint8_t *payload,
				  uint32_t payload_len,
				  uint32_t *frame_len)
{
	uint16_t fcs;
	uint32_t off = 0u;

	if (!payload || payload_len == 0u ||
	    payload_len > BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES)
		return -1;

	memcpy(g_zigbee_payload, payload, payload_len);
	memset(g_zigbee_frame, 0, ZIGBEE_PREAMBLE_BYTES);
	off += ZIGBEE_PREAMBLE_BYTES;
	g_zigbee_frame[off++] = ZIGBEE_SFD;
	g_zigbee_frame[off++] = (uint8_t)(payload_len + 2u);
	memcpy(&g_zigbee_frame[off], g_zigbee_payload, payload_len);
	off += payload_len;

	fcs = crc16_ccitt_reflected(g_zigbee_payload, payload_len);
	g_zigbee_frame[off++] = (uint8_t)(fcs & 0xFFu);
	g_zigbee_frame[off++] = (uint8_t)(fcs >> 8);

	*frame_len = off;

	return 0;
}

static uint8_t get_frame_bit_lsb_first(uint32_t bit_idx)
{
	return (uint8_t)((g_zigbee_frame[bit_idx >> 3] >>
			  (bit_idx & 7u)) & 1u);
}

static uint8_t get_python_symbol(uint32_t bit_idx)
{
	uint8_t symbol = 0u;

	for (uint32_t i = 0u; i < 4u; i++) {
		symbol <<= 1;
		symbol |= get_frame_bit_lsb_first(bit_idx + i);
	}

	return symbol;
}

static uint32_t build_bluebee_bytes(uint32_t frame_len)
{
	uint32_t out_bit = 0u;
	uint32_t bluebee_byte_count;

	memset(g_bluebee_bytes, 0, sizeof(g_bluebee_bytes));

	for (uint32_t bit = 0u; bit < (frame_len * 8u); bit += 4u) {
		uint8_t symbol = get_python_symbol(bit);
		uint16_t mapped = g_bluebee_gfsk_symbol_map[symbol];

		for (uint32_t k = 0u; k < 16u; k++) {
			if ((mapped >> k) & 1u)
				g_bluebee_bytes[out_bit >> 3] |=
					(uint8_t)(1u << (out_bit & 7u));
			out_bit++;
		}
	}

	bluebee_byte_count = (out_bit + 7u) / 8u;

	return bluebee_byte_count;
}

static uint32_t append_complete_local_name(uint8_t *out, uint32_t off)
{
	uint32_t name_len = sizeof(g_default_name) - 1u;

	out[off++] = (uint8_t)(name_len + 1u);
	out[off++] = BLE_AD_TYPE_COMPLETE_LOCAL_NAME;
	memcpy(&out[off], g_default_name, name_len);
	off += name_len;

	return off;
}

static int32_t build_adv_data(uint32_t bluebee_byte_count,
			      uint32_t *bluebee_start,
			      uint32_t *adv_data_len)
{
	uint32_t off = 0u;
	uint32_t ad_len = bluebee_byte_count + 3u;

	g_adv_data[off++] = 0x02u;
	g_adv_data[off++] = BLE_AD_TYPE_FLAGS;
	g_adv_data[off++] = 0x06u;
	off = append_complete_local_name(g_adv_data, off);

	*bluebee_start = off + 4u;
	if ((off + 4u + bluebee_byte_count) > sizeof(g_adv_data) ||
	    ad_len > 0xFFu)
		return -1;

	g_adv_data[off++] = (uint8_t)ad_len;
	g_adv_data[off++] = BLE_AD_TYPE_MANUFACTURER;
	g_adv_data[off++] = 0xFFu;
	g_adv_data[off++] = 0xFFu;
	memcpy(&g_adv_data[off], g_bluebee_bytes, bluebee_byte_count);
	off += bluebee_byte_count;

	*adv_data_len = off;

	return 0;
}

static uint8_t bt_swap_bits(uint8_t v)
{
	uint8_t r = 0u;

	for (uint8_t i = 0u; i < 8u; i++) {
		r <<= 1;
		r |= (uint8_t)(v & 1u);
		v >>= 1;
	}

	return r;
}

static void bt_crc24_adv(const uint8_t *data, uint32_t length, uint8_t out[3])
{
	out[0] = 0x55u;
	out[1] = 0x55u;
	out[2] = 0x55u;

	for (uint32_t i = 0u; i < length; i++) {
		uint8_t d = data[i];

		for (uint8_t b = 0u; b < 8u; b++) {
			uint8_t t = (uint8_t)((out[0] >> 7) & 1u);

			out[0] <<= 1;
			if (out[1] & 0x80u)
				out[0] |= 1u;

			out[1] <<= 1;
			if (out[2] & 0x80u)
				out[1] |= 1u;

			out[2] <<= 1;

			if ((d & 1u) != t) {
				out[2] ^= 0x5Bu;
				out[1] ^= 0x06u;
			}

			d >>= 1;
		}
	}

	out[0] = bt_swap_bits(out[0]);
	out[1] = bt_swap_bits(out[1]);
	out[2] = bt_swap_bits(out[2]);
}

static void bt_whiten(const uint8_t *in, uint32_t len,
		      uint8_t channel, uint8_t *out)
{
	uint8_t lfsr = (uint8_t)(bt_swap_bits(channel) | 0x02u);

	for (uint32_t n = 0u; n < len; n++) {
		uint8_t d = bt_swap_bits(in[n]);

		for (uint8_t mask = 0x80u; mask != 0u; mask >>= 1) {
			if (lfsr & 0x80u) {
				lfsr ^= 0x11u;
				d ^= mask;
			}
			lfsr <<= 1;
		}

		out[n] = bt_swap_bits(d);
	}
}

static int32_t build_secondary_ll_payload(uint32_t adv_data_len,
					  uint32_t bluebee_start,
					  uint32_t bluebee_byte_count,
					  uint32_t *pdu_len,
					  uint32_t *ll_payload_len)
{
	uint8_t ext_header[9];
	uint8_t whiten_in[BLE_EXADV_MAX_PDU_BYTES + BLE_EXADV_CRC_LEN];
	uint8_t whitening_mask[BLE_EXADV_MAX_PDU_BYTES + BLE_EXADV_CRC_LEN];
	uint32_t off = 0u;
	uint32_t ext_payload_len;
	uint32_t bluebee_pdu_start;

	ext_header[0] = BLE_EXT_HDR_FLAG_ADVA | BLE_EXT_HDR_FLAG_ADI;
	for (uint32_t i = 0u; i < sizeof(g_default_mac); i++)
		ext_header[1u + i] =
			g_default_mac[sizeof(g_default_mac) - 1u - i];
	ext_header[7] = 0xC8u;
	ext_header[8] = 0x0Du;

	ext_payload_len = 1u + sizeof(ext_header) + adv_data_len;
	if (ext_payload_len > 255u)
		return -1;

	g_pdu[off++] = 0x40u | BLE_PDU_TYPE_ADV_EXT_IND;
	g_pdu[off++] = (uint8_t)ext_payload_len;
	g_pdu[off++] = (uint8_t)(sizeof(ext_header) |
				 (BLE_EXT_ADV_MODE_CONNECTABLE << 6));
	memcpy(&g_pdu[off], ext_header, sizeof(ext_header));
	off += sizeof(ext_header);
	memcpy(&g_pdu[off], g_adv_data, adv_data_len);
	off += adv_data_len;

	bluebee_pdu_start = 2u + 1u + sizeof(ext_header) + bluebee_start;
	memset(whiten_in, 0, off + BLE_EXADV_CRC_LEN);
	bt_whiten(whiten_in, off + BLE_EXADV_CRC_LEN,
		  BLE_EXADV_DEFAULT_CHANNEL, whitening_mask);
	for (uint32_t i = 0u; i < bluebee_byte_count; i++)
		g_pdu[bluebee_pdu_start + i] ^=
			whitening_mask[bluebee_pdu_start + i];

	bt_crc24_adv(g_pdu, off, g_crc);
	memcpy(whiten_in, g_pdu, off);
	memcpy(&whiten_in[off], g_crc, sizeof(g_crc));
	memcpy(g_ll_payload, g_ble_preamble_and_aa,
	       sizeof(g_ble_preamble_and_aa));
	bt_whiten(whiten_in, off + sizeof(g_crc), BLE_EXADV_DEFAULT_CHANNEL,
		  &g_ll_payload[sizeof(g_ble_preamble_and_aa)]);

	*pdu_len = off;
	*ll_payload_len = sizeof(g_ble_preamble_and_aa) + off + sizeof(g_crc);

	return 0;
}

static uint8_t get_ll_bit_lsb_first(const uint8_t *bytes, uint32_t bit_idx)
{
	return (uint8_t)((bytes[bit_idx >> 3] >> (bit_idx & 7u)) & 1u);
}

static int32_t build_iq_from_ll_payload(const uint8_t *ll_payload,
					uint32_t ll_payload_len,
					uint32_t *iq_word_count)
{
	uint32_t bit_count = ll_payload_len * 8u;
	uint32_t high_count = bit_count * BLE_EXADV_SPS_HIGH;
	uint32_t out_samples = ((high_count - 1u) / BLE_EXADV_DECIM) + 1u;
	uint32_t out_words = (out_samples * 2u) + BLE_EXADV_POST_PAD_WORDS;
	float phase_step =
		(float)M_PI / (2.0f * (float)BLE_EXADV_SPS_HIGH);
	float phase_step_decim = phase_step * (float)BLE_EXADV_DECIM;
	float phase = 0.0f;
	uint32_t w = 0u;

	if (out_words > BLE_EXADV_MAX_IQ_WORDS)
		return -1;

	init_gfsk_taps();

	for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
		uint32_t n = n_out * BLE_EXADV_DECIM;
		int32_t start = (int32_t)n - (int32_t)(BLE_EXADV_TAPS / 2u);
		float acc = 0.0f;
		int32_t ii;
		int32_t qq;

		for (uint32_t k = 0u; k < BLE_EXADV_TAPS; k++) {
			int32_t idx = start + (int32_t)k;

			if (idx >= 0 && idx < (int32_t)high_count) {
				uint32_t bit_idx =
					(uint32_t)idx / BLE_EXADV_SPS_HIGH;
				float sym = get_ll_bit_lsb_first(ll_payload,
								  bit_idx) ?
					    1.0f : -1.0f;

				acc += g_gfsk_taps[k] * sym;
			}
		}

		phase += acc * phase_step_decim;
		phase = wrap_pi(phase);
		ii = round_float_to_int(cosf(phase) *
					(float)BLE_EXADV_IQ_AMPLITUDE);
		qq = round_float_to_int(sinf(phase) *
					(float)BLE_EXADV_IQ_AMPLITUDE);

		if (ii > 32767)
			ii = 32767;
		if (ii < -32768)
			ii = -32768;
		if (qq > 32767)
			qq = 32767;
		if (qq < -32768)
			qq = -32768;

		g_iq_words[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
		g_iq_words[w++] = pack_iq_word((int16_t)ii, (int16_t)qq);
	}

	for (uint32_t pad = 0u; pad < BLE_EXADV_POST_PAD_WORDS; pad++)
		g_iq_words[w++] = 0u;

	*iq_word_count = w;

	return 0;
}

int32_t ble_exadv_secondary_gen_build_payload(const uint8_t *payload,
					      uint32_t payload_len)
{
	uint32_t bluebee_start = 0u;
	uint32_t frame_len = 0u;
	uint32_t bluebee_byte_count;
	uint32_t adv_data_len = 0u;
	uint32_t pdu_len = 0u;
	uint32_t ll_payload_len = 0u;
	uint32_t iq_word_count = 0u;

	if (build_zigbee_frame(payload, payload_len, &frame_len) < 0)
		return -1;
	bluebee_byte_count = build_bluebee_bytes(frame_len);

	if (build_adv_data(bluebee_byte_count, &bluebee_start,
			   &adv_data_len) < 0)
		return -1;
	if (build_secondary_ll_payload(adv_data_len, bluebee_start,
				       bluebee_byte_count, &pdu_len,
				       &ll_payload_len) < 0)
		return -1;
	if (build_iq_from_ll_payload(g_ll_payload, ll_payload_len,
				     &iq_word_count) < 0)
		return -1;

	g_meta.zigbee_payload = g_zigbee_payload;
	g_meta.zigbee_payload_len = payload_len;
	g_meta.zigbee_frame = g_zigbee_frame;
	g_meta.zigbee_frame_len = frame_len;
	g_meta.bluebee_bytes = g_bluebee_bytes;
	g_meta.bluebee_byte_count = bluebee_byte_count;
	g_meta.adv_data = g_adv_data;
	g_meta.adv_data_len = adv_data_len;
	g_meta.pdu = g_pdu;
	g_meta.pdu_len = pdu_len;
	g_meta.crc = g_crc;
	g_meta.crc_len = sizeof(g_crc);
	g_meta.ll_payload = g_ll_payload;
	g_meta.ll_payload_len = ll_payload_len;
	g_meta.iq_words = g_iq_words;
	g_meta.iq_word_count = iq_word_count;
	g_meta.iq_byte_count = iq_word_count * sizeof(uint32_t);
	g_meta.air_us = ll_payload_len * 8u;
	g_meta.post_pad_us = BLE_EXADV_POST_PAD_US;
	g_meta.whitening_channel = BLE_EXADV_DEFAULT_CHANNEL;
	g_meta.tx_lo_hz = BLE_EXADV_SECONDARY_GEN_TX_LO_HZ;

	return 0;
}

int32_t ble_exadv_secondary_gen_build_default(void)
{
	return ble_exadv_secondary_gen_build_payload(
		g_default_zigbee_payload, sizeof(g_default_zigbee_payload));
}

const struct ble_exadv_secondary_gen_meta *
ble_exadv_secondary_gen_get_last_meta(void)
{
	return &g_meta;
}
