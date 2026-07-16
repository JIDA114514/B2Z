#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "ad9361_api.h"
#include "axi_dac_core.h"
#include "axi_dmac.h"
#include "ble_tx_adv.h"
#include "console.h"
#include "no_os_axi_io.h"
#include "no_os_delay.h"
#include "no_os_gpio.h"

#ifdef XILINX_PLATFORM
#include <xil_cache.h>
#endif

#define BLE_ADV_DEFAULT_NAME        "SDR_BLE"
#define BLE_ADV_CHANNEL_COUNT       1u
#define BLE_ADV_FLAGS_AD_LEN        3u
#define BLE_ADV_ADDR_LEN            6u
#define BLE_ADV_PDU_HEADER_LEN      2u
#define BLE_ADV_CRC_LEN             3u
#define BLE_ADV_ACCESS_ADDR_LEN     4u
#define BLE_ADV_PREAMBLE_LEN        1u
#define BLE_ADV_MAX_ADV_DATA_LEN    31u
#define BLE_ADV_MAX_PDU_PAYLOAD_LEN (BLE_ADV_ADDR_LEN + BLE_ADV_MAX_ADV_DATA_LEN)
#define BLE_ADV_MAX_PDU_BYTES       (BLE_ADV_PDU_HEADER_LEN + BLE_ADV_MAX_PDU_PAYLOAD_LEN + BLE_ADV_CRC_LEN)
#define BLE_ADV_MAX_PACKET_BYTES    (BLE_ADV_PREAMBLE_LEN + BLE_ADV_ACCESS_ADDR_LEN + BLE_ADV_MAX_PDU_BYTES)
#define BLE_ADV_MAX_IQ_WORDS        24576u
#define BLE_ADV_IQ_AMPLITUDE        10000
#define BLE_ADV_LO_SETTLE_US        1000u
#define BLE_ADV_POST_TX_GUARD_US    900u
#define BLE_ADV_IDLE_DELAY_MS       10u
#define BLE_ADV_HOP_DELAY_MS        1u
#define BLE_GFSK_SPS_HIGH           768u
#define BLE_GFSK_DECIM              25u
#define BLE_GFSK_SPAN               4u
#define BLE_GFSK_BT                 0.5f
#define BLE_GFSK_TAPS               (BLE_GFSK_SPAN * BLE_GFSK_SPS_HIGH)
#define BLE_GFSK_LUT_PHASES         BLE_GFSK_SPS_HIGH
#define BLE_AXI_DAC_REG_SYNC_CONTROL 0x44u
#define BLE_AXI_DAC_SYNC            0x1u

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *tx_dmac;

struct ble_adv_channel_waveform {
	uint8_t channel;
	uint64_t freq_hz;
	uint32_t iq_words;
	uint32_t iq[BLE_ADV_MAX_IQ_WORDS] __attribute__((aligned(64)));
};

static struct ble_adv_channel_waveform g_ble_adv_waves[BLE_ADV_CHANNEL_COUNT] = {
	{ 37u, 2402000000ULL, 0u, { 0u } },
};

static SemaphoreHandle_t g_ble_adv_state_mutex;
static SemaphoreHandle_t g_ble_adv_tx_mutex;
static volatile uint8_t g_ble_adv_running;
static volatile uint8_t g_ble_adv_rebuild;
static char g_ble_adv_pending_name[BLE_TX_ADV_NAME_MAX_LEN + 1u] = BLE_ADV_DEFAULT_NAME;
static char g_ble_adv_active_name[BLE_TX_ADV_NAME_MAX_LEN + 1u] = BLE_ADV_DEFAULT_NAME;
static float g_ble_gfsk_taps[BLE_GFSK_TAPS];
static uint8_t g_ble_gfsk_taps_ready;

static uint32_t pack_iq_word(int16_t i, int16_t q)
{
	return (uint32_t)(uint16_t)i | ((uint32_t)(uint16_t)q << 16);
}

static uint8_t get_bit_lsb_first(const uint8_t *bytes, uint32_t bit_idx)
{
	uint8_t b = bytes[bit_idx >> 3];

	return (uint8_t)((b >> (bit_idx & 7u)) & 0x01u);
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

static int32_t round_float_to_int(float x)
{
	return (int32_t)(x >= 0.0f ? (x + 0.5f) : (x - 0.5f));
}

static void init_ble_gfsk_taps(void)
{
	const float alpha = sqrtf(logf(2.0f) / 2.0f) / BLE_GFSK_BT;
	const float inv_sps = 1.0f / (float)BLE_GFSK_SPS_HIGH;
	const float half = (float)BLE_GFSK_TAPS / 2.0f;
	float sum = 0.0f;

	if (g_ble_gfsk_taps_ready)
		return;

	for (uint32_t n = 0u; n < BLE_GFSK_TAPS; n++) {
		float t = ((float)n - half) * inv_sps;
		float x = (float)M_PI * t / alpha;
		float h = (sqrtf((float)M_PI) / alpha) * expf(-(x * x));

		g_ble_gfsk_taps[n] = h;
		sum += h;
	}

	if (sum != 0.0f) {
		float inv_sum = 1.0f / sum;

		for (uint32_t n = 0u; n < BLE_GFSK_TAPS; n++)
			g_ble_gfsk_taps[n] *= inv_sum;
	}

	g_ble_gfsk_taps_ready = 1u;
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

static void bt_crc24_adv(const uint8_t *data, size_t length, uint8_t out[3])
{
	out[0] = 0x55u;
	out[1] = 0x55u;
	out[2] = 0x55u;

	for (size_t i = 0u; i < length; i++) {
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

static void bt_whiten_adv(const uint8_t *in, size_t len,
			  uint8_t ch_idx, uint8_t *out)
{
	uint8_t lfsr = (uint8_t)(bt_swap_bits(ch_idx) | 0x02u);

	for (size_t n = 0u; n < len; n++) {
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

static void ble_adv_copy_or_default_name(char *dst, const char *src)
{
	uint32_t len = 0u;
	uint8_t valid = 1u;

	if (src) {
		while (src[len] != '\0' && src[len] != '\r' && src[len] != '\n') {
			unsigned char c = (unsigned char)src[len];

			if (c < 0x20u || c > 0x7eu) {
				valid = 0u;
				break;
			}
			len++;
			if (len > BLE_TX_ADV_NAME_MAX_LEN) {
				valid = 0u;
				break;
			}
		}
	} else {
		valid = 0u;
	}

	if (!valid || len == 0u) {
		strcpy(dst, BLE_ADV_DEFAULT_NAME);
		return;
	}

	memcpy(dst, src, len);
	dst[len] = '\0';
}

static uint32_t ble_adv_name_len(const char *name)
{
	uint32_t len = 0u;

	while (name[len] != '\0')
		len++;

	return len;
}

static int32_t build_adv_packet_bytes(uint8_t channel, const char *name,
				      uint8_t *pkt, uint32_t *pkt_len)
{
	static const uint8_t adv_addr[BLE_ADV_ADDR_LEN] = {
		0xFFu, 0x22u, 0x33u, 0x44u, 0x55u, 0xFFu
	};
	static const uint8_t flags_ad[BLE_ADV_FLAGS_AD_LEN] = {
		0x02u, 0x01u, 0x06u
	};
	uint8_t pdu[BLE_ADV_MAX_PDU_BYTES];
	uint8_t crc[BLE_ADV_CRC_LEN];
	uint8_t whitened[BLE_ADV_MAX_PDU_BYTES];
	uint32_t name_len = ble_adv_name_len(name);
	uint32_t payload_len;
	uint32_t pdu_len_no_crc;
	uint32_t off;

	if (name_len == 0u || name_len > BLE_TX_ADV_NAME_MAX_LEN)
		return -1;

	payload_len = BLE_ADV_ADDR_LEN + sizeof(flags_ad) + 2u + name_len;
	if (payload_len > BLE_ADV_MAX_PDU_PAYLOAD_LEN)
		return -1;

	pdu[0] = 0x42u;
	pdu[1] = (uint8_t)payload_len;

	for (uint32_t i = 0u; i < sizeof(adv_addr); i++)
		pdu[BLE_ADV_PDU_HEADER_LEN + i] =
			adv_addr[sizeof(adv_addr) - 1u - i];

	off = BLE_ADV_PDU_HEADER_LEN + BLE_ADV_ADDR_LEN;
	memcpy(&pdu[off], flags_ad, sizeof(flags_ad));
	off += sizeof(flags_ad);
	pdu[off++] = (uint8_t)(name_len + 1u);
	pdu[off++] = 0x09u;
	memcpy(&pdu[off], name, name_len);
	off += name_len;

	pdu_len_no_crc = off;
	bt_crc24_adv(pdu, pdu_len_no_crc, crc);
	memcpy(&pdu[off], crc, sizeof(crc));
	off += sizeof(crc);

	bt_whiten_adv(pdu, off, channel, whitened);

	pkt[0] = 0xAAu;
	pkt[1] = 0xD6u;
	pkt[2] = 0xBEu;
	pkt[3] = 0x89u;
	pkt[4] = 0x8Eu;
	memcpy(&pkt[BLE_ADV_PREAMBLE_LEN + BLE_ADV_ACCESS_ADDR_LEN],
	       whitened, off);

	*pkt_len = off + BLE_ADV_PREAMBLE_LEN + BLE_ADV_ACCESS_ADDR_LEN;

	return 0;
}

static int32_t build_adv_iq_words_gfsk(const uint8_t *pkt,
				       uint32_t pkt_len,
				       uint32_t *iq,
				       uint32_t *out_word_count)
{
	uint32_t total_bits = pkt_len * 8u;
	uint32_t high_count = total_bits * BLE_GFSK_SPS_HIGH;
	uint32_t out_samples = ((high_count - 1u) / BLE_GFSK_DECIM) + 1u;
	float phase_step = (float)M_PI / (2.0f * (float)BLE_GFSK_SPS_HIGH);
	float phase_step_decim = phase_step * (float)BLE_GFSK_DECIM;
	float phase = 0.0f;
	uint32_t w = 0u;

	if ((out_samples * 2u) > BLE_ADV_MAX_IQ_WORDS)
		return -1;

	init_ble_gfsk_taps();

	for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
		uint32_t n = n_out * BLE_GFSK_DECIM;
		int32_t start = (int32_t)n - (int32_t)(BLE_GFSK_TAPS / 2u);
		float acc = 0.0f;
		float fi;
		float fq;
		int32_t ii;
		int32_t iqv;
		int16_t oi;
		int16_t oq;

		for (uint32_t k = 0u; k < BLE_GFSK_TAPS; k++) {
			int32_t idx = start + (int32_t)k;

			if (idx >= 0 && idx < (int32_t)high_count) {
				uint32_t bit_idx = (uint32_t)idx /
						   BLE_GFSK_SPS_HIGH;
				uint8_t bit = get_bit_lsb_first(pkt, bit_idx);
				float sym = bit ? 1.0f : -1.0f;

				acc += g_ble_gfsk_taps[k] * sym;
			}
		}

		phase += acc * phase_step_decim;

		phase = wrap_pi(phase);
		fi = cosf(phase);
		fq = sinf(phase);
		ii = round_float_to_int(fi * (float)BLE_ADV_IQ_AMPLITUDE);
		iqv = round_float_to_int(fq * (float)BLE_ADV_IQ_AMPLITUDE);

		if (ii > 32767)
			ii = 32767;
		if (ii < -32768)
			ii = -32768;
		if (iqv > 32767)
			iqv = 32767;
		if (iqv < -32768)
			iqv = -32768;

		oi = (int16_t)ii;
		oq = (int16_t)iqv;
		iq[w++] = pack_iq_word(oi, oq);
		iq[w++] = pack_iq_word(oi, oq);
	}

	*out_word_count = w;

	return 0;
}

static int32_t ble_adv_build_all_channels(const char *name)
{
	uint8_t packet[BLE_ADV_MAX_PACKET_BYTES];
	uint32_t packet_len = 0u;

	for (uint32_t i = 0u; i < BLE_ADV_CHANNEL_COUNT; i++) {
		int32_t ret;

		ret = build_adv_packet_bytes(g_ble_adv_waves[i].channel, name,
					     packet, &packet_len);
		if (ret < 0)
			return ret;

		ret = build_adv_iq_words_gfsk(packet, packet_len,
					      g_ble_adv_waves[i].iq,
					      &g_ble_adv_waves[i].iq_words);
		if (ret < 0)
			return ret;
	}

	return 0;
}

int32_t ble_tx_adv_init(void)
{
	if (!g_ble_adv_state_mutex) {
		g_ble_adv_state_mutex = xSemaphoreCreateMutex();
		if (!g_ble_adv_state_mutex)
			return -1;
	}

	if (!g_ble_adv_tx_mutex) {
		g_ble_adv_tx_mutex = xSemaphoreCreateMutex();
		if (!g_ble_adv_tx_mutex)
			return -1;
	}

	return 0;
}

void ble_tx_adv_tx_lock(void)
{
	if (ble_tx_adv_init() < 0)
		return;

	xSemaphoreTake(g_ble_adv_tx_mutex, portMAX_DELAY);
}

void ble_tx_adv_tx_unlock(void)
{
	if (g_ble_adv_tx_mutex)
		xSemaphoreGive(g_ble_adv_tx_mutex);
}

int32_t ble_tx_adv_start_name(const char *name)
{
	char clean_name[BLE_TX_ADV_NAME_MAX_LEN + 1u];

	if (ble_tx_adv_init() < 0)
		return -1;

	ble_adv_copy_or_default_name(clean_name, name);

	xSemaphoreTake(g_ble_adv_state_mutex, portMAX_DELAY);
	strcpy(g_ble_adv_pending_name, clean_name);
	g_ble_adv_rebuild = 1u;
	g_ble_adv_running = 1u;
	xSemaphoreGive(g_ble_adv_state_mutex);

	console_print("BLE ADV start requested, name=%s\r\n", clean_name);

	return 0;
}

void ble_tx_adv_stop(uint8_t restore_dds)
{
	if (ble_tx_adv_init() == 0) {
		xSemaphoreTake(g_ble_adv_state_mutex, portMAX_DELAY);
		g_ble_adv_running = 0u;
		g_ble_adv_rebuild = 0u;
		xSemaphoreGive(g_ble_adv_state_mutex);
	}

	if (restore_dds && ad9361_phy && ad9361_phy->tx_dac && tx_dmac) {
		ble_tx_adv_tx_lock();
		axi_dmac_transfer_stop(tx_dmac);
		axi_dac_set_datasel(ad9361_phy->tx_dac, -1,
				     AXI_DAC_DATA_SEL_DDS);
		ble_tx_adv_tx_unlock();
	}
}

static uint8_t ble_adv_get_state(char *name, uint8_t *rebuild)
{
	uint8_t running;

	xSemaphoreTake(g_ble_adv_state_mutex, portMAX_DELAY);
	running = g_ble_adv_running;
	*rebuild = g_ble_adv_rebuild;
	if (g_ble_adv_rebuild) {
		strcpy(name, g_ble_adv_pending_name);
		g_ble_adv_rebuild = 0u;
	}
	xSemaphoreGive(g_ble_adv_state_mutex);

	return running;
}

static void ble_adv_set_stopped(void)
{
	xSemaphoreTake(g_ble_adv_state_mutex, portMAX_DELAY);
	g_ble_adv_running = 0u;
	g_ble_adv_rebuild = 0u;
	xSemaphoreGive(g_ble_adv_state_mutex);
}

static int32_t ble_adv_send_channel(struct ble_adv_channel_waveform *wave)
{
	struct axi_dma_transfer transfer;
	int32_t ret;

	if (!tx_dmac || !ad9361_phy || !ad9361_phy->tx_dac)
		return -1;
	if (!wave->iq_words)
		return -1;

	axi_dmac_transfer_stop(tx_dmac);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);

	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ad9361_set_tx_lo_freq(ad9361_phy, wave->freq_hz);
	no_os_udelay(BLE_ADV_LO_SETTLE_US);

#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)wave->iq,
			     wave->iq_words * sizeof(uint32_t));
#endif

	transfer.size = wave->iq_words * sizeof(uint32_t);
	transfer.transfer_done = 0;
	transfer.cyclic = NO;
	transfer.src_addr = (uintptr_t)wave->iq;
	transfer.dest_addr = 0;

	no_os_axi_io_write(ad9361_phy->tx_dac->base,
			   BLE_AXI_DAC_REG_SYNC_CONTROL,
			   BLE_AXI_DAC_SYNC);
	ret = axi_dmac_transfer_start(tx_dmac, &transfer);
	if (ret < 0)
		return ret;

	no_os_udelay(BLE_ADV_POST_TX_GUARD_US);

	return 0;
}

void ble_tx_adv_task(void *pvParameters)
{
	uint32_t channel_idx = 0u;
	char build_name[BLE_TX_ADV_NAME_MAX_LEN + 1u];

	(void)pvParameters;

	if (ble_tx_adv_init() < 0) {
		console_print("BLE ADV init failed\r\n");
		vTaskDelete(NULL);
	}

	for (;;) {
		uint8_t rebuild = 0u;

		if (!ble_adv_get_state(build_name, &rebuild)) {
			vTaskDelay(pdMS_TO_TICKS(BLE_ADV_IDLE_DELAY_MS));
			continue;
		}

		if (rebuild) {
			if (ble_adv_build_all_channels(build_name) < 0) {
				console_print("BLE ADV build failed\r\n");
				ble_adv_set_stopped();
				continue;
			}
			strcpy(g_ble_adv_active_name, build_name);
			channel_idx = 0u;
			console_print("BLE ADV ch37 running, name=%s words=%d\r\n",
				      g_ble_adv_active_name,
				      (long)g_ble_adv_waves[0].iq_words);
		}

		ble_tx_adv_tx_lock();
		if (g_ble_adv_running) {
			if (ble_adv_send_channel(&g_ble_adv_waves[channel_idx]) < 0) {
				console_print("BLE ADV ch%d tx failed\r\n",
					      (long)g_ble_adv_waves[channel_idx].channel);
				ble_adv_set_stopped();
			}
		}
		ble_tx_adv_tx_unlock();

		channel_idx = 0u;

		vTaskDelay(pdMS_TO_TICKS(BLE_ADV_HOP_DELAY_MS));
	}
}

void ble_tx_adv_name_cmd(double *param, char param_no)
{
	(void)param;
	(void)param_no;

	ble_tx_adv_start_name(BLE_ADV_DEFAULT_NAME);
}

void ble_tx_adv_stop_cmd(double *param, char param_no)
{
	(void)param;
	(void)param_no;

	ble_tx_adv_stop(1u);
	console_print("BLE ADV stopped\r\n");
}
