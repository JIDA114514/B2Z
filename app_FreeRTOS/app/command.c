/**************************************************************************//**
 *   @file   command.c
 *   @brief  Implementation of AD9361 Command Driver.
 *   @author DBogdan (dragos.bogdan@analog.com)
 *******************************************************************************
 * Copyright 2013(c) Analog Devices, Inc.
 *
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *  - Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  - Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 *  - Neither the name of Analog Devices, Inc. nor the names of its
 *    contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *  - The use of this software may or may not infringe the patent rights
 *    of one or more patent holders.  This license does not release you
 *    from the requirement that you obtain separate licenses from these
 *    patent holders to use this software.
 *  - Use of the software either in source or binary form, must be run
 *    on or directly connected to an Analog Devices Inc. component.
 *
 * THIS SOFTWARE IS PROVIDED BY ANALOG DEVICES "AS IS" AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, NON-INFRINGEMENT,
 * MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 * IN NO EVENT SHALL ANALOG DEVICES BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, INTELLECTUAL PROPERTY RIGHTS, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*******************************************************************************/

/******************************************************************************/
/***************************** Include Files **********************************/
/******************************************************************************/
#include "command.h"
#include "console.h"
#include "ad9361_api.h"
#include "axi_dac_core.h"
//#include "platform.h"
#include "parameters.h"
#include "app_config.h"
#include "axi_dmac.h"
#include "ble_exadv_secondary_gen.h"
#include "ble_tx_adv.h"
#include "bluebee_gen.h"
#include "dma_tx_waveforms.h"
#include "no_os_gpio.h"
#ifdef XILINX_PLATFORM
#include <xil_cache.h>
#endif

/******************************************************************************/
/************************ Constants Definitions *******************************/
/******************************************************************************/
command cmd_list[] = {
	{"help?", "Displays all available commands.", "", get_help},
	{"register?", "Gets the specified register value.", "", get_register},
	{"tx_lo_freq?", "Gets current TX LO frequency [MHz].", "", get_tx_lo_freq},
	{"tx_lo_freq=", "Sets the TX LO frequency [MHz].", "", set_tx_lo_freq},
	{"tx_samp_freq?", "Gets current TX sampling frequency [Hz].", "", get_tx_samp_freq},
	{"tx_samp_freq=", "Sets the TX sampling frequency [Hz].", "", set_tx_samp_freq},
	{"tx_rf_bandwidth?", "Gets current TX RF bandwidth [Hz].", "", get_tx_rf_bandwidth},
	{"tx_rf_bandwidth=", "Sets the TX RF bandwidth [Hz].", "", set_tx_rf_bandwidth},
	{"tx1_attenuation?", "Gets current TX1 attenuation [mdB].", "", get_tx1_attenuation},
	{"tx1_attenuation=", "Sets the TX1 attenuation [mdB].", "", set_tx1_attenuation},
	{"tx2_attenuation?", "Gets current TX2 attenuation [mdB].", "", get_tx2_attenuation},
	{"tx2_attenuation=", "Sets the TX2 attenuation [mdB].", "", set_tx2_attenuation},
	{"tx_fir_en?", "Gets current TX FIR state.", "", get_tx_fir_en},
	{"tx_fir_en=", "Sets the TX FIR state.", "", set_tx_fir_en},
	{"rx_lo_freq?", "Gets current RX LO frequency [MHz].", "", get_rx_lo_freq},
	{"rx_lo_freq=", "Sets the RX LO frequency [MHz].", "", set_rx_lo_freq},
	{"rx_samp_freq?", "Gets current RX sampling frequency [Hz].", "", get_rx_samp_freq},
	{"rx_samp_freq=", "Sets the RX sampling frequency [Hz].", "", set_rx_samp_freq},
	{"rx_rf_bandwidth?", "Gets current RX RF bandwidth [Hz].", "", get_rx_rf_bandwidth},
	{"rx_rf_bandwidth=", "Sets the RX RF bandwidth [Hz].", "", set_rx_rf_bandwidth},
	{"rx1_gc_mode?", "Gets current RX1 GC mode.", "", get_rx1_gc_mode},
	{"rx1_gc_mode=", "Sets the RX1 GC mode.", "", set_rx1_gc_mode},
	{"rx2_gc_mode?", "Gets current RX2 GC mode.", "", get_rx2_gc_mode},
	{"rx2_gc_mode=", "Sets the RX2 GC mode.", "", set_rx2_gc_mode},
	{"rx1_rf_gain?", "Gets current RX1 RF gain.", "", get_rx1_rf_gain},
	{"rx1_rf_gain=", "Sets the RX1 RF gain.", "", set_rx1_rf_gain},
	{"rx2_rf_gain?", "Gets current RX2 RF gain.", "", get_rx2_rf_gain},
	{"rx2_rf_gain=", "Sets the RX2 RF gain.", "", set_rx2_rf_gain},
	{"rx_fir_en?", "Gets current RX FIR state.", "", get_rx_fir_en},
	{"rx_fir_en=", "Sets the RX FIR state.", "", set_rx_fir_en},
	{"dds_tx1_tone1_freq?", "Gets current DDS TX1 Tone 1 frequency [Hz].", "", get_dds_tx1_tone1_freq},
	{"dds_tx1_tone1_freq=", "Sets the DDS TX1 Tone 1 frequency [Hz].", "", set_dds_tx1_tone1_freq},
	{"dds_tx1_tone2_freq?", "Gets current DDS TX1 Tone 2 frequency [Hz].", "", get_dds_tx1_tone2_freq},
	{"dds_tx1_tone2_freq=", "Sets the DDS TX1 Tone 2 frequency [Hz].", "", set_dds_tx1_tone2_freq},
	{"dds_tx1_tone1_phase?", "Gets current DDS TX1 Tone 1 phase [degrees].", "", get_dds_tx1_tone1_phase},
	{"dds_tx1_tone1_phase=", "Sets the DDS TX1 Tone 1 phase [degrees].", "", set_dds_tx1_tone1_phase},
	{"dds_tx1_tone2_phase?", "Gets current DDS TX1 Tone 2 phase [degrees].", "", get_dds_tx1_tone2_phase},
	{"dds_tx1_tone2_phase=", "Sets the DDS TX1 Tone 2 phase [degrees].", "", set_dds_tx1_tone2_phase},
	{"dds_tx1_tone1_scale?", "Gets current DDS TX1 Tone 1 scale.", "", get_dds_tx1_tone1_scale},
	{"dds_tx1_tone1_scale=", "Sets the DDS TX1 Tone 1 scale.", "", set_dds_tx1_tone1_scale},
	{"dds_tx1_tone2_scale?", "Gets current DDS TX1 Tone 2 scale.", "", get_dds_tx1_tone2_scale},
	{"dds_tx1_tone2_scale=", "Sets the DDS TX1 Tone 2 scale.", "", set_dds_tx1_tone2_scale},
	{"dds_tx2_tone1_freq?", "Gets current DDS TX2 Tone 1 frequency [Hz].", "", get_dds_tx2_tone1_freq},
	{"dds_tx2_tone1_freq=", "Sets the DDS TX2 Tone 1 frequency [Hz].", "", set_dds_tx2_tone1_freq},
	{"dds_tx2_tone2_freq?", "Gets current DDS TX2 Tone 2 frequency [Hz].", "", get_dds_tx2_tone2_freq},
	{"dds_tx2_tone2_freq=", "Sets the DDS TX2 Tone 2 frequency [Hz].", "", set_dds_tx2_tone2_freq},
	{"dds_tx2_tone1_phase?", "Gets current DDS TX2 Tone 1 phase [degrees].", "", get_dds_tx2_tone1_phase},
	{"dds_tx2_tone1_phase=", "Sets the DDS TX2 Tone 1 phase [degrees].", "", set_dds_tx2_tone1_phase},
	{"dds_tx2_tone2_phase?", "Gets current DDS TX2 Tone 2 phase [degrees].", "", get_dds_tx2_tone2_phase},
	{"dds_tx2_tone2_phase=", "Sets the DDS TX2 Tone 2 phase [degrees].", "", set_dds_tx2_tone2_phase},
	{"dds_tx2_tone1_scale?", "Gets current DDS TX2 Tone 1 scale.", "", get_dds_tx2_tone1_scale},
	{"dds_tx2_tone1_scale=", "Sets the DDS TX2 Tone 1 scale.", "", set_dds_tx2_tone1_scale},
	{"dds_tx2_tone2_scale?", "Gets current DDS TX2 Tone 2 scale.", "", dds_tx2_tone2_scale},
	{"dds_tx2_tone2_scale=", "Sets the DDS TX2 Tone 2 scale.", "", set_dds_tx2_tone2_scale},
	{"ble_tx_adv_name=", "Sets BLE legacy advertising name and starts 37/38/39 TX.", "", ble_tx_adv_name_cmd},
	{"ble_tx_stop?", "Stops BLE advertising TX and restores DDS.", "", ble_tx_adv_stop_cmd},
	{"dma_tx_demo?", "Sends BLE ch39 legacy advertising waveform in DMA.", "", dma_tx_demo},
	{"dma_switch?", "Switches cyclic DMA waveform.", "", change_dma_context},
	{"bluebee_gen_demo?", "Builds BlueBee ZigBee frame at runtime and starts cyclic TX DMA.", "bluebee_gen_demo? 11 22 33 44", bluebee_gen_demo},
	{"ble_exadv_secondary_gen?", "Builds BLE extended advertising secondary packet and starts cyclic TX DMA on ch39.", "ble_exadv_secondary_gen? 11 22 33 44", ble_exadv_secondary_gen_cmd},
};
const char cmd_no = (sizeof(cmd_list) / sizeof(command));

/******************************************************************************/
/************************ Variables Definitions *******************************/
/******************************************************************************/
extern struct dds_state dds_st;
extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *tx_dmac;

static enum dma_tx_waveform_id dma_tx_context = DMA_TX_WAVEFORM_ZIGBEE;
static struct axi_dma_transfer dma_tx_transfer = {
	.size = 0,
	.transfer_done = 0,
	.cyclic = CYCLIC,
	.src_addr = 0,
	.dest_addr = 0,
};

static int32_t dma_tx_start_waveform(enum dma_tx_waveform_id id)
{
	const struct dma_tx_waveform_desc *waveform;
	int32_t ret;

	if (id >= DMA_TX_WAVEFORM_COUNT)
		return -1;
	if (!ad9361_phy || !ad9361_phy->tx_dac || !tx_dmac)
		return -1;

	ble_tx_adv_stop(0u);
	ble_tx_adv_tx_lock();

	waveform = &g_dma_tx_waveforms[id];

	axi_dmac_transfer_stop(tx_dmac);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);

	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ad9361_set_tx_lo_freq(ad9361_phy, waveform->tx_lo_hz);

#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)waveform->data, waveform->bytes);
#endif
	dma_tx_transfer.cyclic = CYCLIC;
	dma_tx_transfer.size = waveform->bytes;
	dma_tx_transfer.src_addr = (uintptr_t)waveform->data;
	dma_tx_transfer.dest_addr = 0;

	ret = axi_dmac_transfer_start(tx_dmac, &dma_tx_transfer);
	if (ret == 0)
		dma_tx_context = id;

	ble_tx_adv_tx_unlock();

	return ret;
}

static void print_hex_bytes(const char *prefix, const uint8_t *data,
			    uint32_t len)
{
	console_print((char *)prefix);
	for (uint32_t i = 0u; i < len; i++)
		console_print("%02x%s", (long)data[i],
			      (i + 1u == len) ? "\n" : " ");
}

static int32_t dma_tx_start_bluebee_generated(
	const struct bluebee_gen_meta *meta)
{
	int32_t ret;

	if (!meta || !meta->iq_words || meta->iq_byte_count == 0u)
		return -1;
	if (!ad9361_phy || !ad9361_phy->tx_dac || !tx_dmac)
		return -1;

	ble_tx_adv_stop(0u);
	ble_tx_adv_tx_lock();

	axi_dmac_transfer_stop(tx_dmac);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);

	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ad9361_set_tx_lo_freq(ad9361_phy, meta->tx_lo_hz);

#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)meta->iq_words, meta->iq_byte_count);
#endif
	dma_tx_transfer.cyclic = CYCLIC;
	dma_tx_transfer.size = meta->iq_byte_count;
	dma_tx_transfer.src_addr = (uintptr_t)meta->iq_words;
	dma_tx_transfer.dest_addr = 0;

	ret = axi_dmac_transfer_start(tx_dmac, &dma_tx_transfer);

	ble_tx_adv_tx_unlock();

	return ret;
}

static int32_t dma_tx_start_exadv_secondary_generated(
	const struct ble_exadv_secondary_gen_meta *meta)
{
	int32_t ret;

	if (!meta || !meta->iq_words || meta->iq_byte_count == 0u)
		return -1;
	if (!ad9361_phy || !ad9361_phy->tx_dac || !tx_dmac)
		return -1;

	ble_tx_adv_stop(0u);
	ble_tx_adv_tx_lock();

	axi_dmac_transfer_stop(tx_dmac);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);

	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ad9361_set_tx_lo_freq(ad9361_phy, meta->tx_lo_hz);

#ifdef XILINX_PLATFORM
	Xil_DCacheFlushRange((uintptr_t)meta->iq_words, meta->iq_byte_count);
#endif
	dma_tx_transfer.cyclic = CYCLIC;
	dma_tx_transfer.size = meta->iq_byte_count;
	dma_tx_transfer.src_addr = (uintptr_t)meta->iq_words;
	dma_tx_transfer.dest_addr = 0;

	ret = axi_dmac_transfer_start(tx_dmac, &dma_tx_transfer);

	ble_tx_adv_tx_unlock();

	return ret;
}

static uint8_t is_payload_separator(char c)
{
	return (uint8_t)(c == ' ' || c == '\t' || c == ',' ||
			 c == ':' || c == ';');
}

static uint8_t is_line_end(char c)
{
	return (uint8_t)(c == '\0' || c == '\r' || c == '\n');
}

static int8_t hex_value(char c)
{
	if (c >= '0' && c <= '9')
		return (int8_t)(c - '0');
	if (c >= 'a' && c <= 'f')
		return (int8_t)(c - 'a' + 10);
	if (c >= 'A' && c <= 'F')
		return (int8_t)(c - 'A' + 10);
	return -1;
}

static int32_t parse_bluebee_payload_text(const char *text,
					  uint8_t *payload,
					  uint32_t *payload_len,
					  uint32_t max_payload_len)
{
	uint32_t out = 0u;

	if (!text || !payload || !payload_len || max_payload_len == 0u)
		return -1;

	while (is_payload_separator(*text))
		text++;

	if (is_line_end(*text)) {
		*payload_len = 0u;
		return 0;
	}

	while (!is_line_end(*text)) {
		uint8_t token_digits = 0u;
		uint8_t token_has_prefix = 0u;

		while (is_payload_separator(*text))
			text++;
		if (is_line_end(*text))
			break;

		if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
			token_has_prefix = 1u;
			text += 2;
		}

		while (!is_line_end(*text) && !is_payload_separator(*text)) {
			int8_t v = hex_value(*text);

			if (v < 0)
				return -1;
			if (token_has_prefix && token_digits >= 2u)
				return -1;
			if (!token_has_prefix && token_digits >= 2u)
				return -1;
			if (out >= max_payload_len)
				return -1;

			if ((token_digits & 1u) == 0u) {
				payload[out] = (uint8_t)v;
			} else {
				payload[out] =
					(uint8_t)((payload[out] << 4) |
						  (uint8_t)v);
				out++;
			}
			token_digits++;
			text++;
		}

		if (token_digits == 0u)
			return -1;
		if (token_digits == 1u) {
			payload[out] = payload[out] & 0x0Fu;
			out++;
		}
	}

	*payload_len = out;

	return 0;
}

static void print_bluebee_gen_usage(void)
{
	console_print("Usage: bluebee_gen_demo? [hex payload bytes]\n");
	console_print("Example: bluebee_gen_demo? 11 22 33 44\n");
	console_print("Max payload bytes: %d\n",
		      (long)BLUEBEE_GEN_MAX_PAYLOAD_BYTES);
}

int32_t bluebee_gen_start_payload(const uint8_t *payload, uint32_t payload_len)
{
	const struct bluebee_gen_meta *meta;
	int32_t ret;

	if (payload && payload_len > 0u)
		ret = bluebee_gen_build_payload(payload, payload_len);
	else
		ret = bluebee_gen_build_default();

	if (ret < 0) {
		console_print("bluebee_gen build failed\n");
		return ret;
	}

	meta = bluebee_gen_get_last_meta();

	print_hex_bytes("bluebee payload: ", meta->payload, meta->payload_len);
	print_hex_bytes("zigbee frame: ", meta->frame, meta->frame_len);
	console_print("bluebee gfsk_bits=%d gfsk_bytes=%d iq_words=%d\n",
		      (long)meta->gfsk_bit_count,
		      (long)meta->gfsk_byte_count,
		      (long)meta->iq_word_count);
	console_print("bluebee air_us=%d post_pad_us=%d tx_lo=%d MHz\n",
		      (long)meta->air_us,
		      (long)meta->post_pad_us,
		      (long)(meta->tx_lo_hz / 1000000ULL));
	console_print("bluebee projection=%s dist=%d-%d\n",
		      meta->zigbee_projection_ok ? "OK" : "FAIL",
		      (long)meta->symbol_distance_min,
		      (long)meta->symbol_distance_max);

	ret = dma_tx_start_bluebee_generated(meta);
	if (ret == 0)
		console_print("bluebee_gen DMA running bytes=%d\n",
			      (long)meta->iq_byte_count);
	else
		console_print("bluebee_gen dma start failed\n");

	return ret;
}

int32_t bluebee_gen_demo_cmdline(const char *payload_text)
{
	uint8_t payload[BLUEBEE_GEN_MAX_PAYLOAD_BYTES];
	uint32_t payload_len = 0u;

	if (parse_bluebee_payload_text(payload_text ? payload_text : "",
				       payload, &payload_len,
				       BLUEBEE_GEN_MAX_PAYLOAD_BYTES) < 0) {
		console_print("bluebee_gen invalid payload\n");
		print_bluebee_gen_usage();
		return -1;
	}

	return bluebee_gen_start_payload(payload_len ? payload : NULL,
					 payload_len);
}

static void print_exadv_secondary_gen_usage(void)
{
	console_print("Usage: ble_exadv_secondary_gen? [hex ZigBee payload bytes]\n");
	console_print("Example: ble_exadv_secondary_gen? 11 22 33 44\n");
	console_print("Max payload bytes: %d\n",
		      (long)BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES);
}

int32_t ble_exadv_secondary_gen_start_payload(const uint8_t *payload,
					      uint32_t payload_len)
{
	const struct ble_exadv_secondary_gen_meta *meta;
	int32_t ret;

	console_print("ble_exadv_secondary_gen: generating waveform...\n");

	if (payload && payload_len > 0u)
		ret = ble_exadv_secondary_gen_build_payload(payload, payload_len);
	else
		ret = ble_exadv_secondary_gen_build_default();
	if (ret < 0) {
		console_print("ble_exadv_secondary_gen build failed\n");
		return ret;
	}

	meta = ble_exadv_secondary_gen_get_last_meta();

	print_hex_bytes("exadv secondary zigbee payload: ",
			meta->zigbee_payload, meta->zigbee_payload_len);
	print_hex_bytes("exadv secondary zigbee frame: ",
			meta->zigbee_frame, meta->zigbee_frame_len);
	console_print("exadv secondary bluebee_bytes=%d adv_data=%d pdu=%d ll=%d\n",
		      (long)meta->bluebee_byte_count,
		      (long)meta->adv_data_len,
		      (long)meta->pdu_len,
		      (long)meta->ll_payload_len);
	print_hex_bytes("exadv secondary pdu: ", meta->pdu, meta->pdu_len);
	print_hex_bytes("exadv secondary crc: ", meta->crc, meta->crc_len);
	console_print("exadv secondary air_us=%d post_pad_us=%d iq_words=%d tx_lo=%d MHz whiten_ch=%d\n",
		      (long)meta->air_us,
		      (long)meta->post_pad_us,
		      (long)meta->iq_word_count,
		      (long)(meta->tx_lo_hz / 1000000ULL),
		      (long)meta->whitening_channel);

	ret = dma_tx_start_exadv_secondary_generated(meta);
	if (ret == 0)
		console_print("ble_exadv_secondary_gen DMA running bytes=%d\n",
			      (long)meta->iq_byte_count);
	else
		console_print("ble_exadv_secondary_gen dma start failed\n");

	return ret;
}

int32_t ble_exadv_secondary_gen_cmdline(const char *payload_text)
{
	uint8_t payload[BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES];
	uint32_t payload_len = 0u;

	if (parse_bluebee_payload_text(payload_text ? payload_text : "",
				       payload, &payload_len,
				       BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES) < 0) {
		console_print("ble_exadv_secondary_gen invalid payload\n");
		print_exadv_secondary_gen_usage();
		return -1;
	}

	return ble_exadv_secondary_gen_start_payload(payload_len ? payload : NULL,
						    payload_len);
}

void dma_tx_demo(double *param, char param_no)
{
	int32_t ret;

	(void)param;
	(void)param_no;

	ret = dma_tx_start_waveform(DMA_TX_WAVEFORM_BLE_CH39);
	if (ret == 0)
		console_print("start transfer!(%s)\n",
			      g_dma_tx_waveforms[DMA_TX_WAVEFORM_BLE_CH39].name);
	else
		console_print("dma start failed\n");
}

void change_dma_context(double *param, char param_no)
{
	enum dma_tx_waveform_id next;
	int32_t ret;

	(void)param;
	(void)param_no;

	next = (enum dma_tx_waveform_id)((dma_tx_context + 1) %
					 DMA_TX_WAVEFORM_COUNT);

	ret = dma_tx_start_waveform(next);
	if (ret == 0)
		console_print("dma set to %s\n", g_dma_tx_waveforms[next].name);
	else
		console_print("dma change failed\n");
}

void bluebee_gen_demo(double *param, char param_no)
{
	(void)param;
	(void)param_no;

	bluebee_gen_start_payload(NULL, 0u);
}

void ble_exadv_secondary_gen_cmd(double *param, char param_no)
{
	(void)param;
	(void)param_no;

	ble_exadv_secondary_gen_start_payload(NULL, 0u);
}

/**************************************************************************//***
 * @brief Show the invalid parameter message.
 *
 * @return None.
*******************************************************************************/
void show_invalid_param_message(unsigned char cmd_no)
{
	console_print("Invalid parameter!\n");
	console_print("%s  - %s\n", (char*)cmd_list[cmd_no].name, (char*)cmd_list[cmd_no].description);
	console_print("Example: %s\n", (char*)cmd_list[cmd_no].example);
}

/**************************************************************************//***
 * @brief Displays all available commands.
 *
 * @return None.
*******************************************************************************/
void get_help(double* param, char param_no) // "help?" command
{
	unsigned char display_cmd;

	console_print("Available commands:\n");
	for(display_cmd = 0; display_cmd < cmd_no; display_cmd++)
	{
		console_print("%s  - %s\n", (char*)cmd_list[display_cmd].name,
								  (char*)cmd_list[display_cmd].description);
	}
}

/**************************************************************************//***
 * @brief Displays all available commands.
 *
 * @return None.
*******************************************************************************/
void get_register(double* param, char param_no) // "register?" command
{
	uint16_t reg_addr;
	int32_t reg_val;

	if(param_no >= 1)
	{
		reg_addr = param[0];
		reg_val = ad9361_spi_read(ad9361_phy->spi, reg_addr);
		console_print("register[0x%x]=0x%x\n", reg_addr, reg_val);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current TX LO frequency [MHz].
 *
 * @return None.
*******************************************************************************/
void get_tx_lo_freq(double* param, char param_no) // "tx_lo_freq?" command
{
	uint64_t lo_freq_hz;

	ad9361_get_tx_lo_freq(ad9361_phy, &lo_freq_hz);
#ifdef ANTSDR_E310
	/* set tx rf switch */
	if(lo_freq_hz <= 3000000000){
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h   ,0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l   ,1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h   ,0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l   ,1);
		ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	}
	else {
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h   ,1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l   ,0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h   ,1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l   ,0);
		ad9361_set_tx_rf_port_output(ad9361_phy, TXA);
	}
#else
		ad9361_set_tx_rf_port_output(ad9361_phy, TXA);
#endif

	lo_freq_hz /= 1000000;
	console_print("tx_lo_freq=%d\n", (uint32_t)lo_freq_hz);
}

/**************************************************************************//***
 * @brief Sets the TX LO frequency [MHz].
 *
 * @return None.
*******************************************************************************/
void set_tx_lo_freq(double* param, char param_no) // "tx_lo_freq=" command
{
	uint64_t lo_freq_hz;

	if(param_no >= 1)
	{
		lo_freq_hz = param[0];
		lo_freq_hz *= 1000000;
#ifdef ANTSDR_E310
		/* set tx rf switch */
		if(lo_freq_hz <= 3000000000){
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l   ,1);
			ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
		}
		else {
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l   ,0);
			ad9361_set_tx_rf_port_output(ad9361_phy, TXA);
		}
#else
		ad9361_set_tx_rf_port_output(ad9361_phy, TXA);
#endif

		ad9361_set_tx_lo_freq(ad9361_phy, lo_freq_hz);
		lo_freq_hz /= 1000000;
		console_print("tx_lo_freq=%d\n", (uint32_t)lo_freq_hz);
	}
}

/**************************************************************************//***
 * @brief Gets current sampling frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_tx_samp_freq(double* param, char param_no) // "tx_samp_freq?" command
{
	uint32_t sampling_freq_hz;

	ad9361_get_tx_sampling_freq(ad9361_phy, &sampling_freq_hz);
	console_print("tx_samp_freq=%d\n", sampling_freq_hz);
}

/**************************************************************************//***
 * @brief Sets the sampling frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_tx_samp_freq(double* param, char param_no) // "tx_samp_freq=" command
{
	uint32_t sampling_freq_hz;

	if(param_no >= 1)
	{
		sampling_freq_hz = (uint32_t)param[0];
		ad9361_set_tx_sampling_freq(ad9361_phy, sampling_freq_hz);
		ad9361_get_tx_sampling_freq(ad9361_phy, &sampling_freq_hz);
//		dds_update(ad9361_phy);
		console_print("tx_samp_freq=%d\n", sampling_freq_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current TX RF bandwidth [Hz].
 *
 * @return None.
*******************************************************************************/
void get_tx_rf_bandwidth(double* param, char param_no) // "tx_rf_bandwidth?" command
{
	uint32_t bandwidth_hz;

	ad9361_get_tx_rf_bandwidth(ad9361_phy, &bandwidth_hz);
	console_print("tx_rf_bandwidth=%d\n", bandwidth_hz);
}

/**************************************************************************//***
 * @brief Sets the TX RF bandwidth [Hz].
 *
 * @return None.
*******************************************************************************/
void set_tx_rf_bandwidth(double* param, char param_no) // "tx_rf_bandwidth=" command
{
	uint32_t bandwidth_hz;

	if(param_no >= 1)
	{
		bandwidth_hz = param[0];
		ad9361_set_tx_rf_bandwidth(ad9361_phy, bandwidth_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current TX1 attenuation [mdB].
 *
 * @return None.
*******************************************************************************/
void get_tx1_attenuation(double* param, char param_no) // "tx1_attenuation?" command
{
	uint32_t attenuation_mdb;

	ad9361_get_tx_attenuation(ad9361_phy, 0, &attenuation_mdb);
	console_print("tx1_attenuation=%d\n", attenuation_mdb);
}

/**************************************************************************//***
 * @brief Sets the TX1 attenuation [mdB].
 *
 * @return None.
*******************************************************************************/
void set_tx1_attenuation(double* param, char param_no) // "tx1_attenuation=" command
{
	uint32_t attenuation_mdb;

	if(param_no >= 1)
	{
		attenuation_mdb = param[0];
		ad9361_set_tx_attenuation(ad9361_phy, 0, attenuation_mdb);
		console_print("tx1_attenuation=%d\n", attenuation_mdb);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current TX2 attenuation [mdB].
 *
 * @return None.
*******************************************************************************/
void get_tx2_attenuation(double* param, char param_no) // "tx1_attenuation?" command
{
	uint32_t attenuation_mdb;

	ad9361_get_tx_attenuation(ad9361_phy, 1, &attenuation_mdb);
	console_print("tx2_attenuation=%d\n", attenuation_mdb);
}

/**************************************************************************//***
 * @brief Sets the TX2 attenuation [mdB].
 *
 * @return None.
*******************************************************************************/
void set_tx2_attenuation(double* param, char param_no) // "tx1_attenuation=" command
{
	uint32_t attenuation_mdb;

	if(param_no >= 1)
	{
		attenuation_mdb = param[0];
		ad9361_set_tx_attenuation(ad9361_phy, 1, attenuation_mdb);
		console_print("tx2_attenuation=%d\n", attenuation_mdb);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current TX FIR state.
 *
 * @return None.
*******************************************************************************/
void get_tx_fir_en(double* param, char param_no) // "tx_fir_en?" command
{
	uint8_t en_dis;

	ad9361_get_tx_fir_en_dis(ad9361_phy, &en_dis);
	console_print("tx_fir_en=%d\n", en_dis);
}

/**************************************************************************//***
 * @brief Sets the TX FIR state.
 *
 * @return None.
*******************************************************************************/
void set_tx_fir_en(double* param, char param_no) // "tx_fir_en=" command
{
	uint8_t en_dis;

	if(param_no >= 1)
	{
		en_dis = param[0];
		ad9361_set_tx_fir_en_dis(ad9361_phy, en_dis);
		console_print("tx_fir_en=%d\n", en_dis);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX LO frequency [MHz].
 *
 * @return None.
*******************************************************************************/
void get_rx_lo_freq(double* param, char param_no) // "rx_lo_freq?" command
{
	uint64_t lo_freq_hz;

	ad9361_get_rx_lo_freq(ad9361_phy, &lo_freq_hz);
	lo_freq_hz /= 1000000;
	console_print("rx_lo_freq=%d\n", (uint32_t)lo_freq_hz);
}

/**************************************************************************//***
 * @brief Sets the RX LO frequency [MHz].
 *
 * @return None.
*******************************************************************************/
void set_rx_lo_freq(double* param, char param_no) // "rx_lo_freq=" command
{
	uint64_t lo_freq_hz;

	if(param_no >= 1)
	{
		lo_freq_hz = param[0];
		lo_freq_hz *= 1000000;
#ifdef ANTSDR_E310
		/* set rx rf swicth */
		if(lo_freq_hz <= 3000000000){
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_h   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_l   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_h   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_l   ,1);
			ad9361_set_rx_rf_port_input(ad9361_phy, B_BALANCED);
		}
		else {
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_h   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_l   ,0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_h   ,1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_l   ,0);
			ad9361_set_rx_rf_port_input(ad9361_phy, A_BALANCED);
		}

#else
		ad9361_set_rx_rf_port_input(ad9361_phy, A_BALANCED);
#endif
		ad9361_set_rx_lo_freq(ad9361_phy, lo_freq_hz);
		lo_freq_hz /= 1000000;
		console_print("rx_lo_freq=%d\n", (uint32_t)lo_freq_hz);
	}
}

/**************************************************************************//***
 * @brief Gets current RX sampling frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_rx_samp_freq(double* param, char param_no) // "rx_samp_freq?" command
{
	uint32_t sampling_freq_hz;

	ad9361_get_rx_sampling_freq(ad9361_phy, &sampling_freq_hz);
	console_print("rx_samp_freq=%d\n", sampling_freq_hz);
}

/**************************************************************************//***
 * @brief Sets the RX sampling frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_rx_samp_freq(double* param, char param_no) // "rx_samp_freq=" command
{
	uint32_t sampling_freq_hz;

	if(param_no >= 1)
	{
		sampling_freq_hz = (uint32_t)param[0];
		ad9361_set_rx_sampling_freq(ad9361_phy, sampling_freq_hz);
		ad9361_get_rx_sampling_freq(ad9361_phy, &sampling_freq_hz);
//		dds_update(ad9361_phy);
		console_print("rx_samp_freq=%d\n", sampling_freq_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX RF bandwidth [Hz].
 *
 * @return None.
*******************************************************************************/
void get_rx_rf_bandwidth(double* param, char param_no) // "rx_rf_bandwidth?" command
{
	uint32_t bandwidth_hz;

	ad9361_get_rx_rf_bandwidth(ad9361_phy, &bandwidth_hz);
	console_print("rx_rf_bandwidth=%d\n", bandwidth_hz);
}

/**************************************************************************//***
 * @brief Sets the RX RF bandwidth [Hz].
 *
 * @return None.
*******************************************************************************/
void set_rx_rf_bandwidth(double* param, char param_no) // "rx_rf_bandwidth=" command
{
	uint32_t bandwidth_hz;

	if(param_no >= 1)
	{
		bandwidth_hz = param[0];
		ad9361_set_rx_rf_bandwidth(ad9361_phy, bandwidth_hz);
		console_print("rx_rf_bandwidth=%d\n", bandwidth_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX1 GC mode.
 *
 * @return None.
*******************************************************************************/
void get_rx1_gc_mode(double* param, char param_no) // "rx1_gc_mode?" command
{
	uint8_t gc_mode;

	ad9361_get_rx_gain_control_mode(ad9361_phy, 0, &gc_mode);
	console_print("rx1_gc_mode=%d\n", gc_mode);
}

/**************************************************************************//***
 * @brief Sets the RX1 GC mode.
 *
 * @return None.
*******************************************************************************/
void set_rx1_gc_mode(double* param, char param_no) // "rx1_gc_mode=" command
{
	uint8_t gc_mode;

	if(param_no >= 1)
	{
		gc_mode = param[0];
		ad9361_set_rx_gain_control_mode(ad9361_phy, 0, gc_mode);
		console_print("rx1_gc_mode=%d\n", gc_mode);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX2 GC mode.
 *
 * @return None.
*******************************************************************************/
void get_rx2_gc_mode(double* param, char param_no) // "rx2_gc_mode?" command
{
	uint8_t gc_mode;

	ad9361_get_rx_gain_control_mode(ad9361_phy, 1, &gc_mode);
	console_print("rx2_gc_mode=%d\n", gc_mode);
}

/**************************************************************************//***
 * @brief Sets the RX2 GC mode.
 *
 * @return None.
*******************************************************************************/
void set_rx2_gc_mode(double* param, char param_no) // "rx2_gc_mode=" command
{
	uint8_t gc_mode;

	if(param_no >= 1)
	{
		gc_mode = param[0];
		ad9361_set_rx_gain_control_mode(ad9361_phy, 1, gc_mode);
		console_print("rx2_gc_mode=%d\n", gc_mode);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX1 RF gain.
 *
 * @return None.
*******************************************************************************/
void get_rx1_rf_gain(double* param, char param_no) // "rx1_rf_gain?" command
{
	int32_t gain_db;

	ad9361_get_rx_rf_gain (ad9361_phy, 0, &gain_db);
	console_print("rx1_rf_gain=%d\n", gain_db);
}

/**************************************************************************//***
 * @brief Sets the RX1 RF gain.
 *
 * @return None.
*******************************************************************************/
void set_rx1_rf_gain(double* param, char param_no) // "rx1_rf_gain=" command
{
	int32_t gain_db;

	if(param_no >= 1)
	{
		gain_db = param[0];
		ad9361_set_rx_rf_gain (ad9361_phy, 0, gain_db);
		console_print("rx1_rf_gain=%d\n", gain_db);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX2 RF gain.
 *
 * @return None.
*******************************************************************************/
void get_rx2_rf_gain(double* param, char param_no) // "rx2_rf_gain?" command
{
	int32_t gain_db;

	ad9361_get_rx_rf_gain (ad9361_phy, 1, &gain_db);
	console_print("rx2_rf_gain=%d\n", gain_db);
}

/**************************************************************************//***
 * @brief Sets the RX2 RF gain.
 *
 * @return None.
*******************************************************************************/
void set_rx2_rf_gain(double* param, char param_no) // "rx2_rf_gain=" command
{
	int32_t gain_db;

	if(param_no >= 1)
	{
		gain_db = param[0];
		ad9361_set_rx_rf_gain (ad9361_phy, 1, gain_db);
		console_print("rx2_rf_gain=%d\n", gain_db);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current RX FIR state.
 *
 * @return None.
*******************************************************************************/
void get_rx_fir_en(double* param, char param_no) // "rx_fir_en?" command
{
	uint8_t en_dis;

	ad9361_get_rx_fir_en_dis(ad9361_phy, &en_dis);
	console_print("rx_fir_en=%d\n", en_dis);
}

/**************************************************************************//***
 * @brief Sets the RX FIR state.
 *
 * @return None.
*******************************************************************************/
void set_rx_fir_en(double* param, char param_no) // "rx_fir_en=" command
{
	uint8_t en_dis;

	if(param_no >= 1)
	{
		en_dis = param[0];
		ad9361_set_rx_fir_en_dis(ad9361_phy, en_dis);
		console_print("rx_fir_en=%d\n", en_dis);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 1 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone1_freq(double* param, char param_no)	// dds_tx1_tone1_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &freq);
	console_print("dds_tx1_tone1_freq=%d\n", freq);
}
/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 1 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone1_freq(double* param, char param_no)	// dds_tx1_tone1_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, freq);
		console_print("dds_tx1_tone1_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 2 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone2_freq(double* param, char param_no)	// dds_tx1_tone2_freq?
{
	uint32_t freq ;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &freq);
	console_print("dds_tx1_tone2_freq=%d\n", freq);
}

/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 2 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone2_freq(double* param, char param_no)	// dds_tx1_tone2_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, freq);
		console_print("dds_tx1_tone2_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 1 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone1_phase(double* param, char param_no)	// dds_tx1_tone1_phase?
{
	uint32_t phase ;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &phase);
	phase /= 1000;
	console_print("dds_tx1_tone1_phase=%d\n", phase);
}

/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 1 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone1_phase(double* param, char param_no)	// dds_tx1_tone1_phase=
{
	int32_t phase = (uint32_t)param[0];
	uint32_t read_phase;

	if(param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &read_phase);
		phase = read_phase / 1000;
		console_print("dds_tx1_tone1_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 2 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone2_phase(double* param, char param_no)	// dds_tx1_tone2_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &phase);
	phase /= 1000;
	console_print("dds_tx1_tone2_phase=%d\n", phase);
}

/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 2 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone2_phase(double* param, char param_no)	// dds_tx1_tone2_phase=
{
	int32_t phase = (uint32_t)param[0];
	uint32_t read_phase;

	if(param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &read_phase);
		phase = read_phase / 1000;
		console_print("dds_tx1_tone2_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 1 scale.
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone1_scale(double* param, char param_no)	// dds_tx1_tone1_scale?
{
	int32_t scale ;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &scale);
	console_print("dds_tx1_tone1_scale=%d\n", scale);
}

/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 1 scale.
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone1_scale(double* param, char param_no)	// dds_tx1_tone1_scale=
{
	int32_t scale = (int32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &scale);
		console_print("dds_tx1_tone1_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX1 Tone 2 scale.
 *
 * @return None.
*******************************************************************************/
void get_dds_tx1_tone2_scale(double* param, char param_no)	// dds_tx1_tone2_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &scale);
	console_print("dds_tx1_tone2_scale=%d\n", scale);
}

/**************************************************************************//***
 * @brief Sets the DDS TX1 Tone 2 scale.
 *
 * @return None.
*******************************************************************************/
void set_dds_tx1_tone2_scale(double* param, char param_no)	// dds_tx1_tone2_scale=
{
	int32_t scale = (int32_t)param[0];

	if(param_no >= 1)
	{

		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &scale);
		console_print("dds_tx1_tone2_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 1 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx2_tone1_freq(double* param, char param_no)	// dds_tx2_tone1_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &freq);
	console_print("dds_tx2_tone1_freq=%d\n", freq);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 1 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone1_freq(double* param, char param_no)	// dds_tx2_tone1_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, freq);
		console_print("dds_tx2_tone1_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 2 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx2_tone2_freq(double* param, char param_no)	// dds_tx2_tone2_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &freq);
	console_print("dds_tx2_tone2_freq=%d\n", freq);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 2 frequency [Hz].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone2_freq(double* param, char param_no)	// dds_tx2_tone2_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, freq);
		console_print("dds_tx2_tone2_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 1 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx2_tone1_phase(double* param, char param_no)	// dds_tx2_tone1_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &phase);
	phase /= 1000;
	console_print("dds_tx2_tone1_phase=%d\n", phase);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 1 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone1_phase(double* param, char param_no)	// dds_tx2_tone1_phase=
{
	int32_t phase = (uint32_t)param[0];
	uint32_t read_phase;

	if(param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, (uint32_t)((phase - 90) * 1000));

		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &read_phase);
		phase = read_phase / 1000;
		console_print("dds_tx2_tone1_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 2 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void get_dds_tx2_tone2_phase(double* param, char param_no)	// dds_tx2_tone2_phase?
{
	uint32_t phase ;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &phase);
	phase /= 1000;
	console_print("dds_tx2_f2_phase=%d\n", phase);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 2 phase [degrees].
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone2_phase(double* param, char param_no)	// dds_tx2_tone2_phase=
{
	int32_t phase = (uint32_t)param[0];
	uint32_t read_phase;

	if(param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &read_phase);
		phase = read_phase / 1000;
		console_print("dds_tx2_tone2_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 1 scale.
 *
 * @return None.
*******************************************************************************/
void get_dds_tx2_tone1_scale(double* param, char param_no)	// dds_tx2_tone1_scale?
{
	int32_t scale ;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &scale);
	console_print("dds_tx2_tone1_scale=%d\n", scale);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 1 scale.
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone1_scale(double* param, char param_no)	// dds_tx2_tone1_scale=
{
	int32_t scale = (int32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &scale);
		console_print("dds_tx2_tone1_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************//***
 * @brief Gets current DDS TX2 Tone 2 scale.
 *
 * @return None.
*******************************************************************************/
void dds_tx2_tone2_scale(double* param, char param_no)	// dds_tx2_tone2_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &scale);

	console_print("dds_tx2_tone2_scale=%d\n", scale);
}

/**************************************************************************//***
 * @brief Sets the DDS TX2 Tone 2 scale.
 *
 * @return None.
*******************************************************************************/
void set_dds_tx2_tone2_scale(double* param, char param_no)	// dds_tx2_tone2_scale=
{
	int32_t scale = (int32_t)param[0];

	if(param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &scale);
		console_print("dds_tx2_tone2_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}
