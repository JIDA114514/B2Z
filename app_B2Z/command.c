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
#include "no_os_delay.h"
#include "no_os_axi_io.h"
#include "xtime_l.h"
#include "ble.h"
#include "ble_tx_adv.h"
#include "zigbee_tx.h"
#include "ble_exadv.h"
#include "bluebee_waveform.h"
//#include "../../../../../../python/std_ble/ble_exadv_waveform_30_72M.h"

static void ble_exadv_tx_cmd(double *param, char param_no);
static void ble_exadv_stop_cmd(double *param, char param_no);

/******************************************************************************/
/************************ Constants Definitions *******************************/
/******************************************************************************/
command cmd_list[] = {
	{"help?", "Displays all available commands.", "", get_help},
	// {"register?", "Gets the specified register value.", "", get_register},
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
	{"debug_information?", "Gets debug information", "", debug_information},
	{"dma_tx_demo?", "Sends data in dma", "", dma_tx_demo},
	{"ble_tx_demo?", "Sends BLE data in dma", "", ble_tx_demo},
	{"ble_tx_adv_name?", "Generate and send BLE ADV name SDR_BLE", "", ble_tx_adv_name_demo},
	{"ble_exadv_tx?", "Start BLE extended advertising same-channel diagnostic: primary ch37 then secondary ch37", "ble_exadv_tx? 30000 40000 0", ble_exadv_tx_cmd},
	{"ble_exadv_stop?", "Stop BLE extended advertising loop", "", ble_exadv_stop_cmd},
	{"ble_tx_stop?", "stop BLE TX demo, and set DDS", "", ble_tx_stop},
	{"change_freq?", "change BLE TX chan to next freq", "", change_freq},
	{"ble_rx_demo?", "Receive BLE packet", "", ble_rx_service_start},
	{"ble_rx_stop?", "Stop receiving BLE packet", "", ble_rx_service_stop},
	{"dma_switch?", "change dma context", "", change_dma_context}
};
	
const char cmd_no = (sizeof(cmd_list) / sizeof(command));

/******************************************************************************/
/************************ Variables Definitions *******************************/
/******************************************************************************/

extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *tx_dmac;
extern const uint32_t custom_iq_lut[768 * 2] __attribute__((aligned));
// extern const uint32_t neg_custom_iq_lut[768 * 2];
extern const uint32_t ble_iq_ch37[13764] __attribute__((aligned));
extern const uint32_t ble_iq_ch38[13764] __attribute__((aligned));
extern const uint32_t ble_iq_ch39[13764] __attribute__((aligned));
extern const uint32_t bluebee_iq_ch39[145982] __attribute__((aligned(64)));
static struct axi_dma_transfer transfer = {
	// Number of bytes to write/read; double because of 2T2R mode
	.size = sizeof(custom_iq_lut),
	// Transfer done flag
	.transfer_done = 0,
	// Signal transfer mode
	.cyclic = CYCLIC,
	// Address of data source
	.src_addr = (uintptr_t)custom_iq_lut,
	// Address of data destination
	.dest_addr = 0};

static uint8_t is_ble_tx_active = 0;
static uint8_t current_channel = 0;
static XTime last_hop_time = 0;
#define HOP_INTERVAL_TICKS (COUNTS_PER_SECOND / 50)
#define LO_FREQ_CH37 			(2402000000)
#define LO_FREQ_CH38 			(2426000000)
#define LO_FREQ_CH39 			(2480000000)
#define ZIGBEE_CHANNEL_11		(2405000000)
#define ZIGBEE_CHANNEL_12		(2410000000)
#define ZIGBEE_CHANNEL_26		(2480000000)

enum dma_context {
	IDLE,
	BLE_ADV_CH39,
	ZIGBEE_PREM_CH26,
//	SINWAVE,
	BLUEBEE_CH39,
	EXADV_PRI_37
};

static uint8_t context = 0;

static const char *datasel_to_str(enum axi_dac_data_sel s)
{
	switch (s)
	{
	case AXI_DAC_DATA_SEL_DDS:
		return "DDS";
	case AXI_DAC_DATA_SEL_SED:
		return "SED";
	case AXI_DAC_DATA_SEL_DMA:
		return "DMA";
	case AXI_DAC_DATA_SEL_ZERO:
		return "ZERO";
	case AXI_DAC_DATA_SEL_PN7:
		return "PN7";
	case AXI_DAC_DATA_SEL_PN15:
		return "PN15";
	case AXI_DAC_DATA_SEL_PN23:
		return "PN23";
	case AXI_DAC_DATA_SEL_PN31:
		return "PN31";
	case AXI_DAC_DATA_SEL_LB:
		return "LB";
	case AXI_DAC_DATA_SEL_PNXX:
		return "PNXX";
	default:
		return "UNKNOWN";
	}
}

void debug_information(double *param, char param_no)
{
	uint32_t raw;
	uint32_t ret;
	uint32_t p, f, s;
	uint32_t mode;
	uint32_t tx_samp_rate;
	uint32_t tx_lo_freq;

	ret = ad9361_get_en_state_machine_mode(ad9361_phy, mode);
	if (ret == 0)
		printf("machine mode: %d\n", mode);
	else
		printf("machine mode read error\n");

	printf("base=0x%08lx num_channels=%u clock_hz=%llu\n", ad9361_phy->tx_dac->base,
		   ad9361_phy->tx_dac->num_channels,
		   (unsigned long long)ad9361_phy->tx_dac->clock_hz);

	for (int i = 0; i < 4; i++)
	{
		axi_dac_read(ad9361_phy->tx_dac, AXI_DAC_REG_DATA_SELECT(i), &raw);
		enum axi_dac_data_sel sel = (enum axi_dac_data_sel)(raw & 0xF);
		printf("CH%u datasel_raw=0x%08lx datasel=%s(%ld)\n",
			   i, (unsigned long)raw, datasel_to_str(sel), (long)sel);
	}
	for (int d = 0; d < 8; d++)
	{
		ret = axi_dac_dds_get_frequency(ad9361_phy->tx_dac, d, &f);
		ret |= axi_dac_dds_get_phase(ad9361_phy->tx_dac, d, &p);
		ret |= axi_dac_dds_get_scale(ad9361_phy->tx_dac, d, &s);
		if (ret == 0)
		{
			printf("DDS[%u]: freq=%lu Hz phase=%lu mdeg scale=%ld u\n",
				   d, (unsigned long)f, (unsigned long)p, (long)s);
		}
		else
		{
			printf("DDS[%u]: read_failed ret=%ld\n", d, (long)ret);
		}
	}
	ad9361_get_tx_sampling_freq(ad9361_phy, &tx_samp_rate);
	printf("tx_sampling_freq:%d\n", tx_samp_rate);
}

void dma_tx_demo(double *param, char param_no)
{
	is_ble_tx_active = 0;
	ble_exadv_stop(0);
    axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
    ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
//    ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH39);
    ad9361_set_tx_lo_freq(ad9361_phy, ZIGBEE_CHANNEL_26);
	printf("dma data loaded!\n");
	Xil_DCacheFlush();
	/* Flush cache data. */
//	Xil_DCacheInvalidateRange((uintptr_t)ble_iq_ch39, sizeof(ble_iq_ch39));
	Xil_DCacheFlushRange((uintptr_t)ble_exadv_secondary_iq_ch3, sizeof(ble_exadv_secondary_iq_ch3));
	Xil_DCacheFlushRange((uintptr_t)bluebee_zigbee_frame_iq, sizeof(bluebee_zigbee_frame_iq));
	Xil_DCacheFlushRange((uintptr_t)zigbee_iq, sizeof(zigbee_iq));
	/* Transfer the data. */
	axi_dac_write(ad9361_phy->tx_dac, AXI_DAC_REG_SYNC_CONTROL, AXI_DAC_SYNC);
	transfer.cyclic = CYCLIC;
	transfer.size = sizeof(zigbee_iq);
	transfer.src_addr = (uintptr_t)zigbee_iq;
	int ret = axi_dmac_transfer_start(tx_dmac, &transfer);
	if (ret == 0)
	{
		printf("start transfer!(zigbee frame)\n");
		context = IDLE;
	}
	else
	{
		printf("dma start failed\n");
	}
	//
//	no_os_mdelay(1000);
}

void change_dma_context(double *param, char param_no){
	is_ble_tx_active = 0;
	ble_exadv_stop(0);
	axi_dmac_transfer_stop(tx_dmac);
	if(context == IDLE){
		transfer.size = sizeof(bluebee_zigbee_frame_iq);
		transfer.src_addr = (uintptr_t)bluebee_zigbee_frame_iq;
		context = BLUEBEE_CH39;
		printf("dma set to bluebee, BLE channel 39\n");
	}
	else if(context == BLUEBEE_CH39){
		transfer.size = sizeof(ble_exadv_secondary_iq_ch3);
		transfer.src_addr = (uintptr_t)ble_exadv_secondary_iq_ch3;
		context = BLE_ADV_CH39;
		printf("dma set to exadv secondary\n");
	}
	else{
		transfer.size = sizeof(zigbee_iq);
		transfer.src_addr = (uintptr_t)zigbee_iq;
		context = IDLE;
//		ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH39);
		printf("dma set to legacy zigbee\n");
	}
	int ret = axi_dmac_transfer_start(tx_dmac, &transfer);
	if(ret == 0){
		printf("dma set\n");
	}
	else{
		printf("dma change failed\n");
	}
}

void ble_tx_demo(double *param, char param_no){
	ble_exadv_stop(0);
	if(tx_dmac == NULL || ad9361_phy->tx_dac == NULL){
		printf("errors in dma or dac\n");
		return;
	}
	is_ble_tx_active = 1;
	current_channel = 37;

	XTime_GetTime(&last_hop_time);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
	no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
	ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH37);
	// printf("dma data loaded!\n");
	Xil_DCacheFlush();
	/* Flush cache data. */
	Xil_DCacheFlushRange((uintptr_t)ble_iq_ch37, sizeof(ble_iq_ch37));
	Xil_DCacheFlushRange((uintptr_t)ble_iq_ch38, sizeof(ble_iq_ch38));
	Xil_DCacheFlushRange((uintptr_t)ble_iq_ch39, sizeof(ble_iq_ch39));

	transfer.cyclic = NO;
	transfer.size = sizeof(ble_iq_ch37);
	transfer.src_addr = (uintptr_t)ble_iq_ch37;
	no_os_mdelay(1);
	axi_dac_write(ad9361_phy->tx_dac, AXI_DAC_REG_SYNC_CONTROL, AXI_DAC_SYNC);
	int ret = axi_dmac_transfer_start(tx_dmac, &transfer);
	if (ret == 0)
		printf("hopping between, 2.402GHz, 2.426GHz, 2.480GHz\n");
	else
	{
		printf("dma start failed\n");
	}
}

static void ble_exadv_tx_cmd(double *param, char param_no)
{
	is_ble_tx_active = 0;
	ble_exadv_stop(0);
	ble_exadv_tx_demo(param, param_no);
}

static void ble_exadv_stop_cmd(double *param, char param_no)
{
	(void)param;
	(void)param_no;
	ble_exadv_stop(1);
	printf("BLE EXT ADV stopped\n");
}

void ble_tx_stop(double *param, char param_no){
	is_ble_tx_active = 0;
	ble_exadv_stop(1);
	if(tx_dmac != NULL){
		axi_dmac_transfer_stop(tx_dmac);
		axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DDS);
		printf("dma stoped and running DDS\n");
	}
}

void change_freq(double *param, char param_no){
	ble_exadv_stop(0);
	// current_channel = 38;
	if (current_channel == 37)
	{
		/* code */
		current_channel = 38;
		printf("current channel: 38\n");
	}
	else if(current_channel == 38){
		current_channel = 38;
		printf("current channel: 37\n");
	}
	else{
		current_channel = 37;
		printf("current channel: 38\n");
	}
	
}

void ble_tx_task_tick(void){
	if(!is_ble_tx_active){
		return;
	}
	XTime current_time;
	XTime_GetTime(&current_time);

	if((current_time - last_hop_time) >= HOP_INTERVAL_TICKS){
		axi_dmac_transfer_stop(tx_dmac);
		uint32_t offset = 0;

		/* Cycle through channels: 37 → 38 → 39 → 37 → … */
		if(current_channel == 37){
			current_channel = 38;
			transfer.size = sizeof(ble_iq_ch38);
			transfer.src_addr = (uintptr_t)ble_iq_ch38;
			ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH38 - offset);
		}
		else if(current_channel == 38){
			current_channel = 39;
			transfer.size = sizeof(ble_iq_ch39);
			transfer.src_addr = (uintptr_t)ble_iq_ch39;
			ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH39 - offset);
		}
		else{
			current_channel = 37;
			transfer.size = sizeof(ble_iq_ch37);
			transfer.src_addr = (uintptr_t)ble_iq_ch37;
			ad9361_set_tx_lo_freq(ad9361_phy, LO_FREQ_CH37 - offset);
		}
		no_os_mdelay(1);	//make sure tx_lo_freq stable
		axi_dmac_transfer_start(tx_dmac, &transfer);
		last_hop_time = current_time;
	}
}

/**************************************************************************/
/***
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
		console_print("%s  - %s\n", (char *)cmd_list[display_cmd].name,
					  (char *)cmd_list[display_cmd].description);
	}
}

/**************************************************************************//***
 * @brief Displays all available commands.
 *
 * @return None.
 *******************************************************************************/
void get_register(double *param, char param_no) // "register?" command
{
	uint16_t reg_addr;
	uint8_t reg_val;
	struct spi_device spi;

	if (param_no >= 1)
	{
		spi.id_no = 0;
		reg_addr = param[0];
		reg_val = ad9361_spi_read(&spi, reg_addr);
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
void get_tx_lo_freq(double *param, char param_no)							 // "tx_lo_freq?" command
{
	uint64_t lo_freq_hz;

	ad9361_get_tx_lo_freq(ad9361_phy, &lo_freq_hz);
#ifdef ANTSDR_E310
	/* set tx rf switch */
	if (lo_freq_hz <= 3000000000)
	{
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
		ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
	}
	else
	{
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 0);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 1);
		no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 0);
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
void set_tx_lo_freq(double *param, char param_no)							 // "tx_lo_freq=" command
{
	uint64_t lo_freq_hz;

	if (param_no >= 1)
	{
		lo_freq_hz = param[0];
		lo_freq_hz *= 1000000;
#ifdef ANTSDR_E310
		/* set tx rf switch */
		if (lo_freq_hz <= 3000000000)
		{
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
			ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
		}
		else
		{
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 0);
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
void get_tx_samp_freq(double *param, char param_no)							 // "tx_samp_freq?" command
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
void set_tx_samp_freq(double *param, char param_no)							 // "tx_samp_freq=" command
{
	uint32_t sampling_freq_hz;

	if (param_no >= 1)
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

/**************************************************************************/ /***
																			  * @brief Gets current TX RF bandwidth [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_tx_rf_bandwidth(double *param, char param_no)						 // "tx_rf_bandwidth?" command
{
	uint32_t bandwidth_hz;

	ad9361_get_tx_rf_bandwidth(ad9361_phy, &bandwidth_hz);
	console_print("tx_rf_bandwidth=%d\n", bandwidth_hz);
}

/**************************************************************************/ /***
																			  * @brief Sets the TX RF bandwidth [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_tx_rf_bandwidth(double *param, char param_no)						 // "tx_rf_bandwidth=" command
{
	uint32_t bandwidth_hz;

	if (param_no >= 1)
	{
		bandwidth_hz = param[0];
		ad9361_set_tx_rf_bandwidth(ad9361_phy, bandwidth_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current TX1 attenuation [mdB].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_tx1_attenuation(double *param, char param_no)						 // "tx1_attenuation?" command
{
	uint32_t attenuation_mdb;

	ad9361_get_tx_attenuation(ad9361_phy, 0, &attenuation_mdb);
	console_print("tx1_attenuation=%d\n", attenuation_mdb);
}

/**************************************************************************/ /***
																			  * @brief Sets the TX1 attenuation [mdB].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_tx1_attenuation(double *param, char param_no)						 // "tx1_attenuation=" command
{
	uint32_t attenuation_mdb;

	if (param_no >= 1)
	{
		attenuation_mdb = param[0];
		ad9361_set_tx_attenuation(ad9361_phy, 0, attenuation_mdb);
		console_print("tx1_attenuation=%d\n", attenuation_mdb);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current TX2 attenuation [mdB].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_tx2_attenuation(double *param, char param_no)						 // "tx1_attenuation?" command
{
	uint32_t attenuation_mdb;

	ad9361_get_tx_attenuation(ad9361_phy, 1, &attenuation_mdb);
	console_print("tx2_attenuation=%d\n", attenuation_mdb);
}

/**************************************************************************/ /***
																			  * @brief Sets the TX2 attenuation [mdB].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_tx2_attenuation(double *param, char param_no)						 // "tx1_attenuation=" command
{
	uint32_t attenuation_mdb;

	if (param_no >= 1)
	{
		attenuation_mdb = param[0];
		ad9361_set_tx_attenuation(ad9361_phy, 1, attenuation_mdb);
		console_print("tx2_attenuation=%d\n", attenuation_mdb);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current TX FIR state.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_tx_fir_en(double *param, char param_no)							 // "tx_fir_en?" command
{
	uint8_t en_dis;

	ad9361_get_tx_fir_en_dis(ad9361_phy, &en_dis);
	console_print("tx_fir_en=%d\n", en_dis);
}

/**************************************************************************/ /***
																			  * @brief Sets the TX FIR state.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_tx_fir_en(double *param, char param_no)							 // "tx_fir_en=" command
{
	uint8_t en_dis;

	if (param_no >= 1)
	{
		en_dis = param[0];
		ad9361_set_tx_fir_en_dis(ad9361_phy, en_dis);
		console_print("tx_fir_en=%d\n", en_dis);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX LO frequency [MHz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx_lo_freq(double *param, char param_no)							 // "rx_lo_freq?" command
{
	uint64_t lo_freq_hz;

	ad9361_get_rx_lo_freq(ad9361_phy, &lo_freq_hz);
	lo_freq_hz /= 1000000;
	console_print("rx_lo_freq=%d\n", (uint32_t)lo_freq_hz);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX LO frequency [MHz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx_lo_freq(double *param, char param_no)							 // "rx_lo_freq=" command
{
	uint64_t lo_freq_hz;

	if (param_no >= 1)
	{
		lo_freq_hz = param[0];
		lo_freq_hz *= 1000000;
#ifdef ANTSDR_E310
		/* set rx rf swicth */
		if (lo_freq_hz <= 3000000000)
		{
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_h, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_l, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_h, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_l, 1);
			ad9361_set_rx_rf_port_input(ad9361_phy, B_BALANCED);
		}
		else
		{
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_h, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx1_ctrl_l, 0);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_h, 1);
			no_os_gpio_set_value(ad9361_phy->gpio_desc_rx2_ctrl_l, 0);
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

/**************************************************************************/ /***
																			  * @brief Gets current RX sampling frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx_samp_freq(double *param, char param_no)							 // "rx_samp_freq?" command
{
	uint32_t sampling_freq_hz;

	ad9361_get_rx_sampling_freq(ad9361_phy, &sampling_freq_hz);
	console_print("rx_samp_freq=%d\n", sampling_freq_hz);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX sampling frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx_samp_freq(double *param, char param_no)							 // "rx_samp_freq=" command
{
	uint32_t sampling_freq_hz;

	if (param_no >= 1)
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

/**************************************************************************/ /***
																			  * @brief Gets current RX RF bandwidth [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx_rf_bandwidth(double *param, char param_no)						 // "rx_rf_bandwidth?" command
{
	uint32_t bandwidth_hz;

	ad9361_get_rx_rf_bandwidth(ad9361_phy, &bandwidth_hz);
	console_print("rx_rf_bandwidth=%d\n", bandwidth_hz);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX RF bandwidth [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx_rf_bandwidth(double *param, char param_no)						 // "rx_rf_bandwidth=" command
{
	uint32_t bandwidth_hz;

	if (param_no >= 1)
	{
		bandwidth_hz = param[0];
		ad9361_set_rx_rf_bandwidth(ad9361_phy, bandwidth_hz);
		console_print("rx_rf_bandwidth=%d\n", bandwidth_hz);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX1 GC mode.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx1_gc_mode(double *param, char param_no)							 // "rx1_gc_mode?" command
{
	uint8_t gc_mode;

	ad9361_get_rx_gain_control_mode(ad9361_phy, 0, &gc_mode);
	console_print("rx1_gc_mode=%d\n", gc_mode);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX1 GC mode.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx1_gc_mode(double *param, char param_no)							 // "rx1_gc_mode=" command
{
	uint8_t gc_mode;

	if (param_no >= 1)
	{
		gc_mode = param[0];
		ad9361_set_rx_gain_control_mode(ad9361_phy, 0, gc_mode);
		console_print("rx1_gc_mode=%d\n", gc_mode);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX2 GC mode.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx2_gc_mode(double *param, char param_no)							 // "rx2_gc_mode?" command
{
	uint8_t gc_mode;

	ad9361_get_rx_gain_control_mode(ad9361_phy, 1, &gc_mode);
	console_print("rx2_gc_mode=%d\n", gc_mode);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX2 GC mode.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx2_gc_mode(double *param, char param_no)							 // "rx2_gc_mode=" command
{
	uint8_t gc_mode;

	if (param_no >= 1)
	{
		gc_mode = param[0];
		ad9361_set_rx_gain_control_mode(ad9361_phy, 1, gc_mode);
		console_print("rx2_gc_mode=%d\n", gc_mode);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX1 RF gain.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx1_rf_gain(double *param, char param_no)							 // "rx1_rf_gain?" command
{
	int32_t gain_db;

	ad9361_get_rx_rf_gain(ad9361_phy, 0, &gain_db);
	console_print("rx1_rf_gain=%d\n", gain_db);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX1 RF gain.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx1_rf_gain(double *param, char param_no)							 // "rx1_rf_gain=" command
{
	int32_t gain_db;

	if (param_no >= 1)
	{
		gain_db = param[0];
		ad9361_set_rx_rf_gain(ad9361_phy, 0, gain_db);
		console_print("rx1_rf_gain=%d\n", gain_db);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX2 RF gain.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx2_rf_gain(double *param, char param_no)							 // "rx2_rf_gain?" command
{
	int32_t gain_db;

	ad9361_get_rx_rf_gain(ad9361_phy, 1, &gain_db);
	console_print("rx2_rf_gain=%d\n", gain_db);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX2 RF gain.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx2_rf_gain(double *param, char param_no)							 // "rx2_rf_gain=" command
{
	int32_t gain_db;

	if (param_no >= 1)
	{
		gain_db = param[0];
		ad9361_set_rx_rf_gain(ad9361_phy, 1, gain_db);
		console_print("rx2_rf_gain=%d\n", gain_db);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current RX FIR state.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_rx_fir_en(double *param, char param_no)							 // "rx_fir_en?" command
{
	uint8_t en_dis;

	ad9361_get_rx_fir_en_dis(ad9361_phy, &en_dis);
	console_print("rx_fir_en=%d\n", en_dis);
}

/**************************************************************************/ /***
																			  * @brief Sets the RX FIR state.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_rx_fir_en(double *param, char param_no)							 // "rx_fir_en=" command
{
	uint8_t en_dis;

	if (param_no >= 1)
	{
		en_dis = param[0];
		ad9361_set_rx_fir_en_dis(ad9361_phy, en_dis);
		console_print("rx_fir_en=%d\n", en_dis);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 1 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone1_freq(double *param, char param_no)					 // dds_tx1_tone1_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &freq);
	console_print("dds_tx1_tone1_freq=%d\n", freq);
}
/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 1 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone1_freq(double *param, char param_no)					 // dds_tx1_tone1_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, freq);
		console_print("dds_tx1_tone1_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 2 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone2_freq(double *param, char param_no)					 // dds_tx1_tone2_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &freq);
	console_print("dds_tx1_tone2_freq=%d\n", freq);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 2 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone2_freq(double *param, char param_no)					 // dds_tx1_tone2_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, freq);
		console_print("dds_tx1_tone2_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 1 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone1_phase(double *param, char param_no)					 // dds_tx1_tone1_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &phase);
	phase /= 1000;
	console_print("dds_tx1_tone1_phase=%d\n", phase);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 1 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone1_phase(double *param, char param_no)					 // dds_tx1_tone1_phase=
{
	int32_t phase = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &phase);
		phase /= 1000;
		console_print("dds_tx1_tone1_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 2 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone2_phase(double *param, char param_no)					 // dds_tx1_tone2_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &phase);
	phase /= 1000;
	console_print("dds_tx1_tone2_phase=%d\n", phase);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 2 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone2_phase(double *param, char param_no)					 // dds_tx1_tone2_phase=
{
	int32_t phase = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &phase);
		phase /= 1000;
		console_print("dds_tx1_tone2_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 1 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone1_scale(double *param, char param_no)					 // dds_tx1_tone1_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &scale);
	console_print("dds_tx1_tone1_scale=%d\n", scale);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 1 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone1_scale(double *param, char param_no)					 // dds_tx1_tone1_scale=
{
	int32_t scale = (int32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F1, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F1, &scale);
		console_print("dds_tx1_tone1_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX1 Tone 2 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx1_tone2_scale(double *param, char param_no)					 // dds_tx1_tone2_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &scale);
	console_print("dds_tx1_tone2_scale=%d\n", scale);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX1 Tone 2 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx1_tone2_scale(double *param, char param_no)					 // dds_tx1_tone2_scale=
{
	int32_t scale = (int32_t)param[0];

	if (param_no >= 1)
	{

		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_Q_F2, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX1_I_F2, &scale);
		console_print("dds_tx1_tone2_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 1 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx2_tone1_freq(double *param, char param_no)					 // dds_tx2_tone1_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &freq);
	console_print("dds_tx2_tone1_freq=%d\n", freq);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 1 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone1_freq(double *param, char param_no)					 // dds_tx2_tone1_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, freq);
		console_print("dds_tx2_tone1_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 2 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx2_tone2_freq(double *param, char param_no)					 // dds_tx2_tone2_freq?
{
	uint32_t freq;
	axi_dac_dds_get_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &freq);
	console_print("dds_tx2_tone2_freq=%d\n", freq);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 2 frequency [Hz].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone2_freq(double *param, char param_no)					 // dds_tx2_tone2_freq=
{
	uint32_t freq = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, freq);
		axi_dac_dds_set_frequency(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, freq);
		console_print("dds_tx2_tone2_freq=%d\n", freq);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 1 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx2_tone1_phase(double *param, char param_no)					 // dds_tx2_tone1_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &phase);
	phase /= 1000;
	console_print("dds_tx2_tone1_phase=%d\n", phase);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 1 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone1_phase(double *param, char param_no)					 // dds_tx2_tone1_phase=
{
	int32_t phase = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, (uint32_t)((phase - 90) * 1000));

		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &phase);
		phase /= 1000;
		console_print("dds_tx2_tone1_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 2 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx2_tone2_phase(double *param, char param_no)					 // dds_tx2_tone2_phase?
{
	uint32_t phase;
	axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &phase);
	phase /= 1000;
	console_print("dds_tx2_f2_phase=%d\n", phase);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 2 phase [degrees].
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone2_phase(double *param, char param_no)					 // dds_tx2_tone2_phase=
{
	int32_t phase = (uint32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, (uint32_t)(phase * 1000));
		if ((phase - 90) < 0)
			phase += 360;
		axi_dac_dds_set_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, (uint32_t)((phase - 90) * 1000));
		axi_dac_dds_get_phase(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &phase);
		phase /= 1000;
		console_print("dds_tx2_tone2_phase=%d\n", phase);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 1 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void get_dds_tx2_tone1_scale(double *param, char param_no)					 // dds_tx2_tone1_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &scale);
	console_print("dds_tx2_tone1_scale=%d\n", scale);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 1 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone1_scale(double *param, char param_no)					 // dds_tx2_tone1_scale=
{
	int32_t scale = (int32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F1, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F1, &scale);
		console_print("dds_tx2_tone1_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}

/**************************************************************************/ /***
																			  * @brief Gets current DDS TX2 Tone 2 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void dds_tx2_tone2_scale(double *param, char param_no)						 // dds_tx2_tone2_scale?
{
	int32_t scale;
	axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &scale);

	console_print("dds_tx2_tone2_scale=%d\n", scale);
}

/**************************************************************************/ /***
																			  * @brief Sets the DDS TX2 Tone 2 scale.
																			  *
																			  * @return None.
																			  *******************************************************************************/
void set_dds_tx2_tone2_scale(double *param, char param_no)					 // dds_tx2_tone2_scale=
{
	int32_t scale = (int32_t)param[0];

	if (param_no >= 1)
	{
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, scale);
		axi_dac_dds_set_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_Q_F2, scale);
		axi_dac_dds_get_scale(ad9361_phy->tx_dac, DDS_CHAN_TX2_I_F2, &scale);
		console_print("dds_tx2_tone2_scale=%d\n", scale);
	}
	else
		show_invalid_param_message(1);
}
