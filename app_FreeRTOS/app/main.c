/***************************************************************************//**
 *   @file   ad9361/src/main.c
 *   @brief  Implementation of Main Function.
 *   @author DBogdan (dragos.bogdan@analog.com)
********************************************************************************
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
#include <inttypes.h>
#include <string.h>
#include "app_config.h"
#include "ad9361_api.h"
#include "parameters.h"
#include "no_os_spi.h"
#include "no_os_gpio.h"
#include "no_os_delay.h"
#ifdef XILINX_PLATFORM
#include <xparameters.h>
#include <xil_cache.h>
#include "spi_extra.h"
#include "gpio_extra.h"
#include "no_os_irq.h"
#endif
#ifdef FREERTOS_INTEGRATION
#include "FreeRTOS.h"
#include "task.h"
#include "freertos_irq_glue.h"
#endif
#ifdef LINUX_PLATFORM
#include "linux_spi.h"
#include "linux_gpio.h"
#else
#include "irq_extra.h"
#endif //LINUX

#include "axi_adc_core.h"
#include "axi_dac_core.h"
#include "axi_dmac.h"
#include "no_os_error.h"

#ifdef IIO_SUPPORT

#include "iio_axi_adc.h"
#include "iio_axi_dac.h"
#include "iio_ad9361.h"
#include "no_os_uart.h"
#include "iio_app.h"

#ifdef XILINX_PLATFORM
#include "uart_extra.h"
#include "xil_cache.h"
#endif //XILINX

#if defined LINUX_PLATFORM || defined GENERIC_PLATFORM
static uint8_t in_buff[MAX_SIZE_BASE_ADDR];
static uint8_t out_buff[MAX_SIZE_BASE_ADDR];
#endif

#endif // IIO_SUPPORT

#ifdef DAC_DMA_EXAMPLE
#include <string.h>
#endif

#ifdef CONSOLE_COMMANDS
#include "command.h"
#include "console.h"
#include "ble_tx_adv.h"
#include "bluebee_perf.h"
#endif

/******************************************************************************/
/************************ Variables Definitions *******************************/
/******************************************************************************/

#if defined(DAC_DMA_EXAMPLE) || defined(IIO_SUPPORT) || defined(PHASE2_SELFTEST)
uint32_t dac_buffer[DAC_BUFFER_SAMPLES] __attribute__ ((aligned));
uint16_t adc_buffer[ADC_BUFFER_SAMPLES * ADC_CHANNELS] __attribute__ ((
			aligned));
#endif

#define AD9361_ADC_DAC_BYTES_PER_SAMPLE 2

#ifdef XILINX_PLATFORM
struct xil_spi_init_param xil_spi_param = {
#ifdef PLATFORM_MB
	.type = SPI_PL,
#else
	.type = SPI_PS,
#endif
	.flags = 0
};

struct xil_gpio_init_param xil_gpio_param = {
#ifdef PLATFORM_MB
	.type = GPIO_PL,
#else
	.type = GPIO_PS,
#endif
	.device_id = GPIO_DEVICE_ID
};

#define GPIO_OPS	&xil_gpio_ops
#define SPI_OPS		&xil_spi_ops
#define GPIO_PARAM	&xil_gpio_param
#define SPI_PARAM	&xil_spi_param
#endif

#ifdef GENERIC_PLATFORM
#define GPIO_OPS	&generic_gpio_ops
#define SPI_OPS		&generic_spi_ops
#define GPIO_PARAM	NULL
#define SPI_PARAM	NULL
#endif
#ifdef XILINX_PLATFORM
#endif
#ifdef LINUX_PLATFORM
#define GPIO_OPS	&linux_gpio_ops
#define SPI_OPS		&linux_spi_ops
#define GPIO_PARAM	NULL
#define SPI_PARAM	NULL
#endif

struct axi_adc_init rx_adc_init = {
	"cf-ad9361-lpc",
	RX_CORE_BASEADDR,
	4
};
struct axi_dac_init tx_dac_init = {
	"cf-ad9361-dds-core-lpc",
	TX_CORE_BASEADDR,
	4,
	NULL
};
struct axi_dmac_init rx_dmac_init = {
	"rx_dmac",
	CF_AD9361_RX_DMA_BASEADDR,
#if defined(ADC_DMA_IRQ_EXAMPLE) || defined(PHASE2_SELFTEST)
	IRQ_ENABLED
#else
	IRQ_DISABLED
#endif
};
struct axi_dmac *rx_dmac;
struct axi_dmac_init tx_dmac_init = {
	"tx_dmac",
	CF_AD9361_TX_DMA_BASEADDR,
#ifdef ADC_DMA_IRQ_EXAMPLE
	IRQ_ENABLED
#else
	IRQ_DISABLED
#endif
};
struct axi_dmac *tx_dmac;

#ifdef CONSOLE_COMMANDS
char				received_cmd[CONSOLE_MAX_COMMAND_LEN] = {0};
#endif

AD9361_InitParam default_init_param = {
	/* Device selection */
	ID_AD9361,	// dev_sel
	/* Reference Clock */
	40000000UL,	//reference_clk_rate
	/* Base Configuration */
	1,		//two_rx_two_tx_mode_enable *** adi,2rx-2tx-mode-enable
	1,		//one_rx_one_tx_mode_use_rx_num *** adi,1rx-1tx-mode-use-rx-num
	1,		//one_rx_one_tx_mode_use_tx_num *** adi,1rx-1tx-mode-use-tx-num
	1,		//frequency_division_duplex_mode_enable *** adi,frequency-division-duplex-mode-enable
	0,		//frequency_division_duplex_independent_mode_enable *** adi,frequency-division-duplex-independent-mode-enable
	0,		//tdd_use_dual_synth_mode_enable *** adi,tdd-use-dual-synth-mode-enable
	0,		//tdd_skip_vco_cal_enable *** adi,tdd-skip-vco-cal-enable
	0,		//tx_fastlock_delay_ns *** adi,tx-fastlock-delay-ns
	0,		//rx_fastlock_delay_ns *** adi,rx-fastlock-delay-ns
	0,		//rx_fastlock_pincontrol_enable *** adi,rx-fastlock-pincontrol-enable
	0,		//tx_fastlock_pincontrol_enable *** adi,tx-fastlock-pincontrol-enable
	0,		//external_rx_lo_enable *** adi,external-rx-lo-enable
	0,		//external_tx_lo_enable *** adi,external-tx-lo-enable
	5,		//dc_offset_tracking_update_event_mask *** adi,dc-offset-tracking-update-event-mask
	6,		//dc_offset_attenuation_high_range *** adi,dc-offset-attenuation-high-range
	5,		//dc_offset_attenuation_low_range *** adi,dc-offset-attenuation-low-range
	0x28,	//dc_offset_count_high_range *** adi,dc-offset-count-high-range
	0x32,	//dc_offset_count_low_range *** adi,dc-offset-count-low-range
	0,		//split_gain_table_mode_enable *** adi,split-gain-table-mode-enable
	MAX_SYNTH_FREF,	//trx_synthesizer_target_fref_overwrite_hz *** adi,trx-synthesizer-target-fref-overwrite-hz
	0,		// qec_tracking_slow_mode_enable *** adi,qec-tracking-slow-mode-enable
	/* ENSM Control */
	0,		//ensm_enable_pin_pulse_mode_enable *** adi,ensm-enable-pin-pulse-mode-enable
	0,		//ensm_enable_txnrx_control_enable *** adi,ensm-enable-txnrx-control-enable
	/* LO Control */
	2400000000UL,	//rx_synthesizer_frequency_hz *** adi,rx-synthesizer-frequency-hz
	2400000000UL,	//tx_synthesizer_frequency_hz *** adi,tx-synthesizer-frequency-hz
	1,				//tx_lo_powerdown_managed_enable *** adi,tx-lo-powerdown-managed-enable
	/* Rate & BW Control */
	{983040000, 245760000, 122880000, 61440000, 30720000, 30720000},// rx_path_clock_frequencies[6] *** adi,rx-path-clock-frequencies
	{983040000, 122880000, 122880000, 61440000, 30720000, 30720000},// tx_path_clock_frequencies[6] *** adi,tx-path-clock-frequencies
	18000000,//rf_rx_bandwidth_hz *** adi,rf-rx-bandwidth-hz
	18000000,//rf_tx_bandwidth_hz *** adi,rf-tx-bandwidth-hz
	/* RF Port Control */
	0,		//rx_rf_port_input_select *** adi,rx-rf-port-input-select
	0,		//tx_rf_port_input_select *** adi,tx-rf-port-input-select
	/* TX Attenuation Control */
	10000,	//tx_attenuation_mdB *** adi,tx-attenuation-mdB
	0,		//update_tx_gain_in_alert_enable *** adi,update-tx-gain-in-alert-enable
	/* Reference Clock Control */
	0,		//xo_disable_use_ext_refclk_enable *** adi,xo-disable-use-ext-refclk-enable
	{8, 5920},	//dcxo_coarse_and_fine_tune[2] *** adi,dcxo-coarse-and-fine-tune
	CLKOUT_DISABLE,	//clk_output_mode_select *** adi,clk-output-mode-select
	/* Gain Control */
	2,		//gc_rx1_mode *** adi,gc-rx1-mode
	2,		//gc_rx2_mode *** adi,gc-rx2-mode
	58,		//gc_adc_large_overload_thresh *** adi,gc-adc-large-overload-thresh
	4,		//gc_adc_ovr_sample_size *** adi,gc-adc-ovr-sample-size
	47,		//gc_adc_small_overload_thresh *** adi,gc-adc-small-overload-thresh
	8192,	//gc_dec_pow_measurement_duration *** adi,gc-dec-pow-measurement-duration
	0,		//gc_dig_gain_enable *** adi,gc-dig-gain-enable
	800,	//gc_lmt_overload_high_thresh *** adi,gc-lmt-overload-high-thresh
	704,	//gc_lmt_overload_low_thresh *** adi,gc-lmt-overload-low-thresh
	24,		//gc_low_power_thresh *** adi,gc-low-power-thresh
	15,		//gc_max_dig_gain *** adi,gc-max-dig-gain
	0,		//gc_use_rx_fir_out_for_dec_pwr_meas_enable *** adi,gc-use-rx-fir-out-for-dec-pwr-meas-enable
	/* Gain MGC Control */
	2,		//mgc_dec_gain_step *** adi,mgc-dec-gain-step
	2,		//mgc_inc_gain_step *** adi,mgc-inc-gain-step
	0,		//mgc_rx1_ctrl_inp_enable *** adi,mgc-rx1-ctrl-inp-enable
	0,		//mgc_rx2_ctrl_inp_enable *** adi,mgc-rx2-ctrl-inp-enable
	0,		//mgc_split_table_ctrl_inp_gain_mode *** adi,mgc-split-table-ctrl-inp-gain-mode
	/* Gain AGC Control */
	10,		//agc_adc_large_overload_exceed_counter *** adi,agc-adc-large-overload-exceed-counter
	2,		//agc_adc_large_overload_inc_steps *** adi,agc-adc-large-overload-inc-steps
	0,		//agc_adc_lmt_small_overload_prevent_gain_inc_enable *** adi,agc-adc-lmt-small-overload-prevent-gain-inc-enable
	10,		//agc_adc_small_overload_exceed_counter *** adi,agc-adc-small-overload-exceed-counter
	4,		//agc_dig_gain_step_size *** adi,agc-dig-gain-step-size
	3,		//agc_dig_saturation_exceed_counter *** adi,agc-dig-saturation-exceed-counter
	1000,	// agc_gain_update_interval_us *** adi,agc-gain-update-interval-us
	0,		//agc_immed_gain_change_if_large_adc_overload_enable *** adi,agc-immed-gain-change-if-large-adc-overload-enable
	0,		//agc_immed_gain_change_if_large_lmt_overload_enable *** adi,agc-immed-gain-change-if-large-lmt-overload-enable
	10,		//agc_inner_thresh_high *** adi,agc-inner-thresh-high
	1,		//agc_inner_thresh_high_dec_steps *** adi,agc-inner-thresh-high-dec-steps
	12,		//agc_inner_thresh_low *** adi,agc-inner-thresh-low
	1,		//agc_inner_thresh_low_inc_steps *** adi,agc-inner-thresh-low-inc-steps
	10,		//agc_lmt_overload_large_exceed_counter *** adi,agc-lmt-overload-large-exceed-counter
	2,		//agc_lmt_overload_large_inc_steps *** adi,agc-lmt-overload-large-inc-steps
	10,		//agc_lmt_overload_small_exceed_counter *** adi,agc-lmt-overload-small-exceed-counter
	5,		//agc_outer_thresh_high *** adi,agc-outer-thresh-high
	2,		//agc_outer_thresh_high_dec_steps *** adi,agc-outer-thresh-high-dec-steps
	18,		//agc_outer_thresh_low *** adi,agc-outer-thresh-low
	2,		//agc_outer_thresh_low_inc_steps *** adi,agc-outer-thresh-low-inc-steps
	1,		//agc_attack_delay_extra_margin_us; *** adi,agc-attack-delay-extra-margin-us
	0,		//agc_sync_for_gain_counter_enable *** adi,agc-sync-for-gain-counter-enable
	/* Fast AGC */
	64,		//fagc_dec_pow_measuremnt_duration ***  adi,fagc-dec-pow-measurement-duration
	260,	//fagc_state_wait_time_ns ***  adi,fagc-state-wait-time-ns
	/* Fast AGC - Low Power */
	0,		//fagc_allow_agc_gain_increase ***  adi,fagc-allow-agc-gain-increase-enable
	5,		//fagc_lp_thresh_increment_time ***  adi,fagc-lp-thresh-increment-time
	1,		//fagc_lp_thresh_increment_steps ***  adi,fagc-lp-thresh-increment-steps
	/* Fast AGC - Lock Level (Lock Level is set via slow AGC inner high threshold) */
	1,		//fagc_lock_level_lmt_gain_increase_en ***  adi,fagc-lock-level-lmt-gain-increase-enable
	5,		//fagc_lock_level_gain_increase_upper_limit ***  adi,fagc-lock-level-gain-increase-upper-limit
	/* Fast AGC - Peak Detectors and Final Settling */
	1,		//fagc_lpf_final_settling_steps ***  adi,fagc-lpf-final-settling-steps
	1,		//fagc_lmt_final_settling_steps ***  adi,fagc-lmt-final-settling-steps
	3,		//fagc_final_overrange_count ***  adi,fagc-final-overrange-count
	/* Fast AGC - Final Power Test */
	0,		//fagc_gain_increase_after_gain_lock_en ***  adi,fagc-gain-increase-after-gain-lock-enable
	/* Fast AGC - Unlocking the Gain */
	0,		//fagc_gain_index_type_after_exit_rx_mode ***  adi,fagc-gain-index-type-after-exit-rx-mode
	1,		//fagc_use_last_lock_level_for_set_gain_en ***  adi,fagc-use-last-lock-level-for-set-gain-enable
	1,		//fagc_rst_gla_stronger_sig_thresh_exceeded_en ***  adi,fagc-rst-gla-stronger-sig-thresh-exceeded-enable
	5,		//fagc_optimized_gain_offset ***  adi,fagc-optimized-gain-offset
	10,		//fagc_rst_gla_stronger_sig_thresh_above_ll ***  adi,fagc-rst-gla-stronger-sig-thresh-above-ll
	1,		//fagc_rst_gla_engergy_lost_sig_thresh_exceeded_en ***  adi,fagc-rst-gla-engergy-lost-sig-thresh-exceeded-enable
	1,		//fagc_rst_gla_engergy_lost_goto_optim_gain_en ***  adi,fagc-rst-gla-engergy-lost-goto-optim-gain-enable
	10,		//fagc_rst_gla_engergy_lost_sig_thresh_below_ll ***  adi,fagc-rst-gla-engergy-lost-sig-thresh-below-ll
	8,		//fagc_energy_lost_stronger_sig_gain_lock_exit_cnt ***  adi,fagc-energy-lost-stronger-sig-gain-lock-exit-cnt
	1,		//fagc_rst_gla_large_adc_overload_en ***  adi,fagc-rst-gla-large-adc-overload-enable
	1,		//fagc_rst_gla_large_lmt_overload_en ***  adi,fagc-rst-gla-large-lmt-overload-enable
	0,		//fagc_rst_gla_en_agc_pulled_high_en ***  adi,fagc-rst-gla-en-agc-pulled-high-enable
	0,		//fagc_rst_gla_if_en_agc_pulled_high_mode ***  adi,fagc-rst-gla-if-en-agc-pulled-high-mode
	64,		//fagc_power_measurement_duration_in_state5 ***  adi,fagc-power-measurement-duration-in-state5
	2,		//fagc_large_overload_inc_steps *** adi,fagc-adc-large-overload-inc-steps
	/* RSSI Control */
	1,		//rssi_delay *** adi,rssi-delay
	1000,	//rssi_duration *** adi,rssi-duration
	3,		//rssi_restart_mode *** adi,rssi-restart-mode
	0,		//rssi_unit_is_rx_samples_enable *** adi,rssi-unit-is-rx-samples-enable
	1,		//rssi_wait *** adi,rssi-wait
	/* Aux ADC Control */
	256,	//aux_adc_decimation *** adi,aux-adc-decimation
	40000000UL,	//aux_adc_rate *** adi,aux-adc-rate
	/* AuxDAC Control */
	1,		//aux_dac_manual_mode_enable ***  adi,aux-dac-manual-mode-enable
	0,		//aux_dac1_default_value_mV ***  adi,aux-dac1-default-value-mV
	0,		//aux_dac1_active_in_rx_enable ***  adi,aux-dac1-active-in-rx-enable
	0,		//aux_dac1_active_in_tx_enable ***  adi,aux-dac1-active-in-tx-enable
	0,		//aux_dac1_active_in_alert_enable ***  adi,aux-dac1-active-in-alert-enable
	0,		//aux_dac1_rx_delay_us ***  adi,aux-dac1-rx-delay-us
	0,		//aux_dac1_tx_delay_us ***  adi,aux-dac1-tx-delay-us
	0,		//aux_dac2_default_value_mV ***  adi,aux-dac2-default-value-mV
	0,		//aux_dac2_active_in_rx_enable ***  adi,aux-dac2-active-in-rx-enable
	0,		//aux_dac2_active_in_tx_enable ***  adi,aux-dac2-active-in-tx-enable
	0,		//aux_dac2_active_in_alert_enable ***  adi,aux-dac2-active-in-alert-enable
	0,		//aux_dac2_rx_delay_us ***  adi,aux-dac2-rx-delay-us
	0,		//aux_dac2_tx_delay_us ***  adi,aux-dac2-tx-delay-us
	/* Temperature Sensor Control */
	256,	//temp_sense_decimation *** adi,temp-sense-decimation
	1000,	//temp_sense_measurement_interval_ms *** adi,temp-sense-measurement-interval-ms
	0xCE,	//temp_sense_offset_signed *** adi,temp-sense-offset-signed
	1,		//temp_sense_periodic_measurement_enable *** adi,temp-sense-periodic-measurement-enable
	/* Control Out Setup */
	0xFF,	//ctrl_outs_enable_mask *** adi,ctrl-outs-enable-mask
	0,		//ctrl_outs_index *** adi,ctrl-outs-index
	/* External LNA Control */
	0,		//elna_settling_delay_ns *** adi,elna-settling-delay-ns
	0,		//elna_gain_mdB *** adi,elna-gain-mdB
	0,		//elna_bypass_loss_mdB *** adi,elna-bypass-loss-mdB
	0,		//elna_rx1_gpo0_control_enable *** adi,elna-rx1-gpo0-control-enable
	0,		//elna_rx2_gpo1_control_enable *** adi,elna-rx2-gpo1-control-enable
	0,		//elna_gaintable_all_index_enable *** adi,elna-gaintable-all-index-enable
	/* Digital Interface Control */
	0,		//digital_interface_tune_skip_mode *** adi,digital-interface-tune-skip-mode
	0,		//digital_interface_tune_fir_disable *** adi,digital-interface-tune-fir-disable
	1,		//pp_tx_swap_enable *** adi,pp-tx-swap-enable
	1,		//pp_rx_swap_enable *** adi,pp-rx-swap-enable
	0,		//tx_channel_swap_enable *** adi,tx-channel-swap-enable
	0,		//rx_channel_swap_enable *** adi,rx-channel-swap-enable
	1,		//rx_frame_pulse_mode_enable *** adi,rx-frame-pulse-mode-enable
	0,		//two_t_two_r_timing_enable *** adi,2t2r-timing-enable
	0,		//invert_data_bus_enable *** adi,invert-data-bus-enable
	0,		//invert_data_clk_enable *** adi,invert-data-clk-enable
	0,		//fdd_alt_word_order_enable *** adi,fdd-alt-word-order-enable
	0,		//invert_rx_frame_enable *** adi,invert-rx-frame-enable
	0,		//fdd_rx_rate_2tx_enable *** adi,fdd-rx-rate-2tx-enable
	0,		//swap_ports_enable *** adi,swap-ports-enable
	0,		//single_data_rate_enable *** adi,single-data-rate-enable
	1,		//lvds_mode_enable *** adi,lvds-mode-enable
	0,		//half_duplex_mode_enable *** adi,half-duplex-mode-enable
	0,		//single_port_mode_enable *** adi,single-port-mode-enable
	0,		//full_port_enable *** adi,full-port-enable
	0,		//full_duplex_swap_bits_enable *** adi,full-duplex-swap-bits-enable
	0,		//delay_rx_data *** adi,delay-rx-data
	0,		//rx_data_clock_delay *** adi,rx-data-clock-delay
	4,		//rx_data_delay *** adi,rx-data-delay
	7,		//tx_fb_clock_delay *** adi,tx-fb-clock-delay
	0,		//tx_data_delay *** adi,tx-data-delay
#ifdef ALTERA_PLATFORM
	300,	//lvds_bias_mV *** adi,lvds-bias-mV
#else
	150,	//lvds_bias_mV *** adi,lvds-bias-mV
#endif
	1,		//lvds_rx_onchip_termination_enable *** adi,lvds-rx-onchip-termination-enable
	0,		//rx1rx2_phase_inversion_en *** adi,rx1-rx2-phase-inversion-enable
	0xFF,	//lvds_invert1_control *** adi,lvds-invert1-control
	0x0F,	//lvds_invert2_control *** adi,lvds-invert2-control
	/* GPO Control */
	0,		//gpo_manual_mode_enable *** adi,gpo-manual-mode-enable
	0,		//gpo_manual_mode_enable_mask *** adi,gpo-manual-mode-enable-mask
	0,		//gpo0_inactive_state_high_enable *** adi,gpo0-inactive-state-high-enable
	0,		//gpo1_inactive_state_high_enable *** adi,gpo1-inactive-state-high-enable
	0,		//gpo2_inactive_state_high_enable *** adi,gpo2-inactive-state-high-enable
	0,		//gpo3_inactive_state_high_enable *** adi,gpo3-inactive-state-high-enable
	0,		//gpo0_slave_rx_enable *** adi,gpo0-slave-rx-enable
	0,		//gpo0_slave_tx_enable *** adi,gpo0-slave-tx-enable
	0,		//gpo1_slave_rx_enable *** adi,gpo1-slave-rx-enable
	0,		//gpo1_slave_tx_enable *** adi,gpo1-slave-tx-enable
	0,		//gpo2_slave_rx_enable *** adi,gpo2-slave-rx-enable
	0,		//gpo2_slave_tx_enable *** adi,gpo2-slave-tx-enable
	0,		//gpo3_slave_rx_enable *** adi,gpo3-slave-rx-enable
	0,		//gpo3_slave_tx_enable *** adi,gpo3-slave-tx-enable
	0,		//gpo0_rx_delay_us *** adi,gpo0-rx-delay-us
	0,		//gpo0_tx_delay_us *** adi,gpo0-tx-delay-us
	0,		//gpo1_rx_delay_us *** adi,gpo1-rx-delay-us
	0,		//gpo1_tx_delay_us *** adi,gpo1-tx-delay-us
	0,		//gpo2_rx_delay_us *** adi,gpo2-rx-delay-us
	0,		//gpo2_tx_delay_us *** adi,gpo2-tx-delay-us
	0,		//gpo3_rx_delay_us *** adi,gpo3-rx-delay-us
	0,		//gpo3_tx_delay_us *** adi,gpo3-tx-delay-us
	/* Tx Monitor Control */
	37000,	//low_high_gain_threshold_mdB *** adi,txmon-low-high-thresh
	0,		//low_gain_dB *** adi,txmon-low-gain
	24,		//high_gain_dB *** adi,txmon-high-gain
	0,		//tx_mon_track_en *** adi,txmon-dc-tracking-enable
	0,		//one_shot_mode_en *** adi,txmon-one-shot-mode-enable
	511,	//tx_mon_delay *** adi,txmon-delay
	8192,	//tx_mon_duration *** adi,txmon-duration
	2,		//tx1_mon_front_end_gain *** adi,txmon-1-front-end-gain
	2,		//tx2_mon_front_end_gain *** adi,txmon-2-front-end-gain
	48,		//tx1_mon_lo_cm *** adi,txmon-1-lo-cm
	48,		//tx2_mon_lo_cm *** adi,txmon-2-lo-cm
	/* GPIO definitions */
	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_resetb *** reset-gpios
	/* MCS Sync */
	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_sync *** sync-gpios

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_cal_sw1 *** cal-sw1-gpios

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_cal_sw2 *** cal-sw2-gpios
	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_rx1_ctrl_h *** gpio_rx1_ctrl_h

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_rx1_ctrl_l *** gpio_rx1_ctrl_l

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_tx1_ctrl_h *** gpio_tx1_ctrl_h

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_tx1_ctrl_l *** gpio_tx1_ctrl_l

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_rx2_ctrl_h *** gpio_rx2_ctrl_h

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM

	},		//gpio_rx2_ctrl_l *** gpio_rx2_ctrl_l

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_tx2_ctrl_h *** gpio_tx2_ctrl_h

	{
		.number = -1,
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	},		//gpio_tx2_ctrl_l *** gpio_tx2_ctrl_l

	{
		.device_id = SPI_DEVICE_ID,
		.mode = NO_OS_SPI_MODE_1,
		.chip_select = SPI_CS,
		.platform_ops = SPI_OPS,
		.extra = SPI_PARAM
	},

	/* External LO clocks */
	NULL,	//(*ad9361_rfpll_ext_recalc_rate)()
	NULL,	//(*ad9361_rfpll_ext_round_rate)()
	NULL,	//(*ad9361_rfpll_ext_set_rate)()
#ifndef AXI_ADC_NOT_PRESENT
	&rx_adc_init,	// *rx_adc_init
	&tx_dac_init,   // *tx_dac_init
#endif
};

AD9361_RXFIRConfig rx_fir_config = {	// BPF PASSBAND 3/20 fs to 1/4 fs
	3, // rx
	0, // rx_gain
	1, // rx_dec
	{
		-4, -6, -37, 35, 186, 86, -284, -315,
			107, 219, -4, 271, 558, -307, -1182, -356,
			658, 157, 207, 1648, 790, -2525, -2553, 748,
			865, -476, 3737, 6560, -3583, -14731, -5278, 14819,
			14819, -5278, -14731, -3583, 6560, 3737, -476, 865,
			748, -2553, -2525, 790, 1648, 207, 157, 658,
			-356, -1182, -307, 558, 271, -4, 219, 107,
			-315, -284, 86, 186, 35, -37, -6, -4,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0
		}, // rx_coef[128]
	64, // rx_coef_size
	{0, 0, 0, 0, 0, 0}, //rx_path_clks[6]
	0 // rx_bandwidth
};

AD9361_TXFIRConfig tx_fir_config = {	// BPF PASSBAND 3/20 fs to 1/4 fs
	3, // tx
	-6, // tx_gain
	1, // tx_int
	{
		-4, -6, -37, 35, 186, 86, -284, -315,
			107, 219, -4, 271, 558, -307, -1182, -356,
			658, 157, 207, 1648, 790, -2525, -2553, 748,
			865, -476, 3737, 6560, -3583, -14731, -5278, 14819,
			14819, -5278, -14731, -3583, 6560, 3737, -476, 865,
			748, -2553, -2525, 790, 1648, 207, 157, 658,
			-356, -1182, -307, 558, 271, -4, 219, 107,
			-315, -284, 86, 186, 35, -37, -6, -4,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0
		}, // tx_coef[128]
	64, // tx_coef_size
	{0, 0, 0, 0, 0, 0}, // tx_path_clks[6]
	0 // tx_bandwidth
};
struct ad9361_rf_phy *ad9361_phy;
#ifdef FMCOMMS5
struct ad9361_rf_phy *ad9361_phy_b;
#endif

/***************************************************************************//**
 * @brief main
*******************************************************************************/
#ifdef FREERTOS_INTEGRATION

/* FreeRTOS vector table — defined in freertos_vector_table.S */
extern const uint32_t _freertos_vector_table[ 8 ];

static struct no_os_irq_ctrl_desc *freertos_irq_desc;

static int32_t freertos_no_os_irq_init(void)
{
	struct xil_irq_init_param xil_irq_init_par = {
		.type = IRQ_PS,
	};
	struct no_os_irq_init_param irq_init_param = {
		.irq_ctrl_id = INTC_DEVICE_ID,
		.platform_ops = &xil_irq_ops,
		.extra = &xil_irq_init_par,
	};

	if (freertos_irq_desc)
		return 0;

	return no_os_irq_ctrl_init(&freertos_irq_desc, &irq_init_param);
}

#ifdef PHASE2_SELFTEST

#define PHASE2_TASK_PRIORITY        4
#define PHASE2_TASK_STACK_WORDS     2048
#define PHASE2_CHILD_PRIORITY       3
#define PHASE2_CHILD_STACK_WORDS    512
#define PHASE2_SPI_ITERATIONS       64
#define PHASE2_CONSOLE_LINES        20
#define PHASE2_ADC_DMA_SAMPLES      4096
#define PHASE2_ADC_DMA_BSP_IRQ_ID   XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR
#define PHASE2_GIC_DIST_BASE        0xF8F01000UL
#define PHASE2_GIC_CPU_BASE         0xF8F00100UL
#define PHASE2_GIC_DIST_CTLR        0x000U
#define PHASE2_GIC_ENABLE_SET       0x100U
#define PHASE2_GIC_PENDING_SET      0x200U
#define PHASE2_GIC_ACTIVE           0x300U
#define PHASE2_GIC_PRIORITY         0x400U
#define PHASE2_GIC_TARGET           0x800U
#define PHASE2_GIC_CONFIG           0xC00U
#define PHASE2_GIC_CPU_PMR          0x004U
#define PHASE2_ADC_DMA_IRQ_PRIORITY 0xA0U

struct phase2_child_ctx {
	TaskHandle_t parent;
	char *name;
	volatile int32_t failures;
	volatile uint32_t iterations;
};

static int32_t phase2_fail(char *name, char *detail, int32_t code)
{
	console_print("[P2][FAIL] %s %s code=%d\r\n", name, detail, (long)code);

	return -1;
}

static void phase2_pass(char *name, char *detail, int32_t value)
{
	console_print("[P2][PASS] %s %s=%d\r\n", name, detail, (long)value);
}

static uint32_t phase2_mmio_read32(uint32_t addr)
{
	return *(volatile uint32_t *)addr;
}

static uint8_t phase2_mmio_read8(uint32_t addr)
{
	return *(volatile uint8_t *)addr;
}

static uint32_t phase2_gic_irq_bit(uint32_t irq_id, uint32_t offset)
{
	uint32_t reg = phase2_mmio_read32(PHASE2_GIC_DIST_BASE + offset +
					  ((irq_id / 32U) * 4U));

	return (reg >> (irq_id % 32U)) & 0x1U;
}

static void phase2_reset_adc_dma_irq_diag(void)
{
	uint32_t i;

	g_irq_last_id = 0xFFFFFFFFUL;
	g_irq_dispatch_count[PHASE2_ADC_DMA_BSP_IRQ_ID] = 0;
	g_irq_unhandled_count[PHASE2_ADC_DMA_BSP_IRQ_ID] = 0;
	g_adc_dma_gic_dispatch_count = 0;
	g_adc_dma_irq_enter_count = 0;
	g_adc_dma_irq_eot_count = 0;
	g_adc_dma_irq_sem_give_count = 0;
	g_adc_dma_irq_sem_woken_count = 0;
	g_adc_dma_poll_count = 0;
	g_adc_dma_poll_eot_count = 0;
	g_adc_dma_poll_sem_give_count = 0;
	g_adc_dma_irq_fallback_count = 0;
	g_adc_dma_irq_fallback_pending = 0;

	for (i = 0; i < AXI_DMAC_GIC_FABRIC_DIAG_COUNT; i++) {
		g_adc_dma_gic_fabric_enable[i] = 0;
		g_adc_dma_gic_fabric_pending[i] = 0;
		g_adc_dma_gic_fabric_active[i] = 0;
	}
}

static void phase2_print_adc_dma_irq_diag(char *tag)
{
	uint32_t irq_id = PHASE2_ADC_DMA_BSP_IRQ_ID;
	uint32_t cfg = phase2_mmio_read32(PHASE2_GIC_DIST_BASE +
					  PHASE2_GIC_CONFIG +
					  ((irq_id / 16U) * 4U));
	uint32_t trigger = (cfg >> ((irq_id % 16U) * 2U)) & 0x3U;
	uint8_t priority = phase2_mmio_read8(PHASE2_GIC_DIST_BASE +
					     PHASE2_GIC_PRIORITY + irq_id);
	uint8_t target = phase2_mmio_read8(PHASE2_GIC_DIST_BASE +
					   PHASE2_GIC_TARGET + irq_id);
	uint32_t pmr = phase2_mmio_read32(PHASE2_GIC_CPU_BASE +
					  PHASE2_GIC_CPU_PMR);
	uint32_t dist_ctl = phase2_mmio_read32(PHASE2_GIC_DIST_BASE +
					       PHASE2_GIC_DIST_CTLR);
	uint32_t ctrl = 0;
	uint32_t irq_mask = 0;
	uint32_t irq_pending = 0;
	uint32_t submit = 0;
	uint32_t done = 0;
	uintptr_t handler = 0;
	uintptr_t callback = 0;
	uint32_t gic_fabric_nonzero = 0;
	uint32_t i;

	if (rx_dmac) {
		axi_dmac_read(rx_dmac, AXI_DMAC_REG_CTRL, &ctrl);
		axi_dmac_read(rx_dmac, AXI_DMAC_REG_IRQ_MASK, &irq_mask);
		axi_dmac_read(rx_dmac, AXI_DMAC_REG_IRQ_PENDING, &irq_pending);
		axi_dmac_read(rx_dmac, AXI_DMAC_REG_TRANSFER_SUBMIT, &submit);
		axi_dmac_read(rx_dmac, AXI_DMAC_REG_TRANSFER_DONE, &done);
	}

	if (freertos_irq_desc && freertos_irq_desc->extra) {
		struct xil_irq_desc *xil_dev = freertos_irq_desc->extra;
		XScuGic *gic = xil_dev->instance;

		if (gic && gic->Config) {
			handler = (uintptr_t)
				gic->Config->HandlerTable[irq_id].Handler;
			callback = (uintptr_t)
				gic->Config->HandlerTable[irq_id].CallBackRef;
		}
	}

	console_print("[P2][IRQ] %s id=%d last=%d gic=%d unhandled=%d enter=%d eot=%d sem=%d woken=%d\r\n",
		      tag, (long)irq_id, (long)g_irq_last_id,
		      (long)g_adc_dma_gic_dispatch_count,
		      (long)g_irq_unhandled_count[irq_id],
		      (long)g_adc_dma_irq_enter_count,
		      (long)g_adc_dma_irq_eot_count,
		      (long)g_adc_dma_irq_sem_give_count,
		      (long)g_adc_dma_irq_sem_woken_count);
	console_print("[P2][GIC] en=%d pend=%d act=%d target=0x%02x prio=0x%02x trig=0x%x pmr=0x%08x dist=0x%08x\r\n",
		      (long)phase2_gic_irq_bit(irq_id, PHASE2_GIC_ENABLE_SET),
		      (long)phase2_gic_irq_bit(irq_id, PHASE2_GIC_PENDING_SET),
		      (long)phase2_gic_irq_bit(irq_id, PHASE2_GIC_ACTIVE),
		      (long)target, (long)priority, (long)trigger,
		      (long)pmr, (long)dist_ctl);
	console_print("[P2][IRQH] handler=0x%x cb=0x%x rx_dmac=0x%x\r\n",
		      (long)handler, (long)callback, (long)(uintptr_t)rx_dmac);
	console_print("[P2][DMA] ctrl=0x%08x irq_mask=0x%08x irq_pending=0x%08x submit=0x%08x done=0x%08x remaining=%d dir=%d\r\n",
		      (long)ctrl, (long)irq_mask, (long)irq_pending,
		      (long)submit, (long)done,
		      rx_dmac ? (long)rx_dmac->remaining_size : -1L,
		      rx_dmac ? (long)rx_dmac->direction : -1L);
	console_print("[P2][DMACFB] count=%d pending_before_clear=0x%08x\r\n",
		      (long)g_adc_dma_irq_fallback_count,
		      (long)g_adc_dma_irq_fallback_pending);
	console_print("[P2][DMACPOLL] count=%d eot=%d sem=%d\r\n",
		      (long)g_adc_dma_poll_count,
		      (long)g_adc_dma_poll_eot_count,
		      (long)g_adc_dma_poll_sem_give_count);
	for (i = 0; i < AXI_DMAC_GIC_FABRIC_DIAG_COUNT; i++) {
		if (g_adc_dma_gic_fabric_enable[i] ||
		    g_adc_dma_gic_fabric_pending[i] ||
		    g_adc_dma_gic_fabric_active[i])
			gic_fabric_nonzero++;
	}
	console_print("[P2][GICSCAN] first=%d count=%d nonzero=%d\r\n",
		      (long)AXI_DMAC_GIC_FABRIC_DIAG_FIRST_ID,
		      (long)AXI_DMAC_GIC_FABRIC_DIAG_COUNT,
		      (long)gic_fabric_nonzero);
	for (i = 0; i < AXI_DMAC_GIC_FABRIC_DIAG_COUNT; i++) {
		uint32_t fab_id = AXI_DMAC_GIC_FABRIC_DIAG_FIRST_ID + i;

		if (fab_id != PHASE2_ADC_DMA_BSP_IRQ_ID &&
		    !g_adc_dma_gic_fabric_enable[i] &&
		    !g_adc_dma_gic_fabric_pending[i] &&
		    !g_adc_dma_gic_fabric_active[i])
			continue;

		console_print("[P2][GICFAB] id=%d en=%d pend=%d act=%d\r\n",
			      (long)fab_id,
			      (long)g_adc_dma_gic_fabric_enable[i],
			      (long)g_adc_dma_gic_fabric_pending[i],
			      (long)g_adc_dma_gic_fabric_active[i]);
	}
}

static int32_t phase2_read_product_id(uint8_t *product_id)
{
	uint16_t cmd = AD_READ | AD_CNT(1) | AD_ADDR(REG_PRODUCT_ID);
	uint8_t buf[3];
	int32_t ret;

	buf[0] = cmd >> 8;
	buf[1] = cmd & 0xFF;
	buf[2] = 0;

	ret = no_os_spi_write_and_read(ad9361_phy->spi, buf, sizeof(buf));
	if (ret < 0)
		return ret;

	*product_id = buf[2];

	return 0;
}

static void phase2_spi_child_task(void *pvParameters)
{
	struct phase2_child_ctx *ctx = pvParameters;
	uint32_t i;
	uint8_t product_id = 0;
	int32_t ret;

	for (i = 0; i < PHASE2_SPI_ITERATIONS; i++) {
		ret = phase2_read_product_id(&product_id);
		if ((ret < 0) ||
		    ((product_id & PRODUCT_ID_MASK) != PRODUCT_ID_9361)) {
			ctx->failures++;
			break;
		}
		ctx->iterations++;
		vTaskDelay(pdMS_TO_TICKS(1));
	}

	xTaskNotifyGive(ctx->parent);
	vTaskDelete(NULL);
}

static int32_t phase2_test_spi_mutex(void)
{
	TaskHandle_t parent = xTaskGetCurrentTaskHandle();
	struct phase2_child_ctx ctx_a = { parent, "SPI_A", 0, 0 };
	struct phase2_child_ctx ctx_b = { parent, "SPI_B", 0, 0 };
	BaseType_t rc_a;
	BaseType_t rc_b;
	TaskHandle_t task_a = NULL;
	TaskHandle_t task_b = NULL;
	uint32_t total;

	if (!ad9361_phy || !ad9361_phy->spi)
		return phase2_fail("spi_mutex", "ad9361 spi missing", -1);

	rc_a = xTaskCreate(phase2_spi_child_task, "P2SPIA",
			   PHASE2_CHILD_STACK_WORDS, &ctx_a,
			   PHASE2_CHILD_PRIORITY, &task_a);
	rc_b = xTaskCreate(phase2_spi_child_task, "P2SPIB",
			   PHASE2_CHILD_STACK_WORDS, &ctx_b,
			   PHASE2_CHILD_PRIORITY, &task_b);

	if ((rc_a != pdPASS) || (rc_b != pdPASS)) {
		if (task_a)
			vTaskDelete(task_a);
		if (task_b)
			vTaskDelete(task_b);
		return phase2_fail("spi_mutex", "task create", -1);
	}

	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

	if (ctx_a.failures || ctx_b.failures)
		return phase2_fail("spi_mutex", "read product_id", -1);

	total = ctx_a.iterations + ctx_b.iterations;
	phase2_pass("spi_mutex", "reads", total);

	return 0;
}

static int32_t phase2_check_gpio(char *name, struct no_os_gpio_desc *gpio,
				 uint32_t *checked)
{
	uint8_t direction = 0;
	uint8_t value = 0;
	int32_t ret;

	if (!gpio)
		return 0;

	ret = no_os_gpio_get_direction(gpio, &direction);
	if (ret < 0)
		return phase2_fail(name, "get_direction", ret);

	ret = no_os_gpio_get_value(gpio, &value);
	if (ret < 0)
		return phase2_fail(name, "get_value", ret);

	(*checked)++;

	return 0;
}

static int32_t phase2_test_gpio_mutex(void)
{
	uint32_t checked = 0;

	if (!ad9361_phy)
		return phase2_fail("gpio_mutex", "ad9361 missing", -1);

	if (phase2_check_gpio("gpio_resetb", ad9361_phy->gpio_desc_resetb,
			      &checked) < 0)
		return -1;
	if (phase2_check_gpio("gpio_sync", ad9361_phy->gpio_desc_sync,
			      &checked) < 0)
		return -1;
	if (phase2_check_gpio("gpio_cal_sw1", ad9361_phy->gpio_desc_cal_sw1,
			      &checked) < 0)
		return -1;
	if (phase2_check_gpio("gpio_cal_sw2", ad9361_phy->gpio_desc_cal_sw2,
			      &checked) < 0)
		return -1;

	if (!checked)
		return phase2_fail("gpio_mutex", "no gpio descriptors", -1);

	phase2_pass("gpio_mutex", "checked", checked);

	return 0;
}

static void phase2_console_child_task(void *pvParameters)
{
	struct phase2_child_ctx *ctx = pvParameters;
	uint32_t i;

	for (i = 0; i < PHASE2_CONSOLE_LINES; i++) {
		console_print("[P2][TOKEN] %s line=%d\r\n", ctx->name, (long)i);
		ctx->iterations++;
		vTaskDelay(pdMS_TO_TICKS(1));
	}

	xTaskNotifyGive(ctx->parent);
	vTaskDelete(NULL);
}

static int32_t phase2_test_console_mutex(void)
{
	TaskHandle_t parent = xTaskGetCurrentTaskHandle();
	struct phase2_child_ctx ctx_a = { parent, "CONSOLE_A", 0, 0 };
	struct phase2_child_ctx ctx_b = { parent, "CONSOLE_B", 0, 0 };
	BaseType_t rc_a;
	BaseType_t rc_b;
	TaskHandle_t task_a = NULL;
	TaskHandle_t task_b = NULL;
	uint32_t total;

	rc_a = xTaskCreate(phase2_console_child_task, "P2CONA",
			   PHASE2_CHILD_STACK_WORDS, &ctx_a,
			   PHASE2_CHILD_PRIORITY, &task_a);
	rc_b = xTaskCreate(phase2_console_child_task, "P2CONB",
			   PHASE2_CHILD_STACK_WORDS, &ctx_b,
			   PHASE2_CHILD_PRIORITY, &task_b);

	if ((rc_a != pdPASS) || (rc_b != pdPASS)) {
		if (task_a)
			vTaskDelete(task_a);
		if (task_b)
			vTaskDelete(task_b);
		return phase2_fail("console_mutex", "task create", -1);
	}

	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

	total = ctx_a.iterations + ctx_b.iterations;
	if (total != (PHASE2_CONSOLE_LINES * 2U))
		return phase2_fail("console_mutex", "line count", total);

	phase2_pass("console_mutex", "lines", total);

	return 0;
}

static int32_t phase2_register_adc_dma_irq(void)
{
	struct no_os_callback_desc rx_dmac_callback = {
		.ctx = rx_dmac,
		.callback = axi_dmac_default_isr,
	};
	int32_t status;

	status = freertos_no_os_irq_init();
	if (status < 0)
		return status;

	status = no_os_irq_global_enable(freertos_irq_desc);
	if (status < 0)
		return status;

	status = no_os_irq_register_callback(
		freertos_irq_desc,
		PHASE2_ADC_DMA_BSP_IRQ_ID,
		&rx_dmac_callback);
	if (status < 0)
		return status;

	status = no_os_irq_trigger_level_set(
		freertos_irq_desc,
		PHASE2_ADC_DMA_BSP_IRQ_ID,
		NO_OS_IRQ_LEVEL_HIGH);
	if (status < 0)
		return status;

	if (freertos_irq_desc && freertos_irq_desc->extra) {
		struct xil_irq_desc *xil_dev = freertos_irq_desc->extra;
		XScuGic *gic = xil_dev->instance;

		if (gic)
			XScuGic_SetPriorityTriggerType(
				gic, PHASE2_ADC_DMA_BSP_IRQ_ID,
				PHASE2_ADC_DMA_IRQ_PRIORITY,
				NO_OS_IRQ_LEVEL_HIGH);
	}

	return no_os_irq_enable(freertos_irq_desc, PHASE2_ADC_DMA_BSP_IRQ_ID);
}

static int32_t phase2_test_adc_dma_irq(void)
{
	struct axi_dma_transfer read_transfer;
	uint32_t dma_bytes;
	int32_t status;

	if (!rx_dmac)
		return phase2_fail("adc_dma_irq", "rx_dmac missing", -1);
	if (rx_dmac->irq_option != IRQ_ENABLED)
		return phase2_fail("adc_dma_irq", "irq disabled", -1);

	status = phase2_register_adc_dma_irq();
	if (status < 0)
		return phase2_fail("adc_dma_irq", "irq register", status);

	phase2_reset_adc_dma_irq_diag();

	dma_bytes = PHASE2_ADC_DMA_SAMPLES *
		    AD9361_ADC_DAC_BYTES_PER_SAMPLE *
		    rx_adc_init.num_channels;
	if (dma_bytes > sizeof(adc_buffer))
		dma_bytes = sizeof(adc_buffer);

	axi_dmac_write(rx_dmac, AXI_DMAC_REG_IRQ_PENDING,
		       AXI_DMAC_IRQ_SOT | AXI_DMAC_IRQ_EOT);

	read_transfer.size = dma_bytes;
	read_transfer.transfer_done = 0;
	read_transfer.cyclic = NO;
	read_transfer.src_addr = 0;
	read_transfer.dest_addr = (uintptr_t)adc_buffer;

	status = axi_dmac_transfer_start(rx_dmac, &read_transfer);
	if (status < 0)
		return phase2_fail("adc_dma_irq", "transfer_start", status);

	status = axi_dmac_transfer_wait_completion(rx_dmac, 500);
	if (status < 0) {
		phase2_print_adc_dma_irq_diag("fail");
		return phase2_fail("adc_dma_irq", "wait_completion", status);
	}

	phase2_print_adc_dma_irq_diag("done");

#ifdef XILINX_PLATFORM
	Xil_DCacheInvalidateRange((uintptr_t)adc_buffer, dma_bytes);
#endif

	phase2_pass("adc_dma_irq", "bytes", dma_bytes);

	return 0;
}

static int32_t phase2_test_tick(void)
{
	TickType_t tick_start = xTaskGetTickCount();
	uint32_t isr_start = g_tick_isr_count;
	TickType_t tick_delta;
	uint32_t isr_delta;

	vTaskDelay(pdMS_TO_TICKS(1000));

	tick_delta = xTaskGetTickCount() - tick_start;
	isr_delta = g_tick_isr_count - isr_start;

	if ((tick_delta < pdMS_TO_TICKS(900)) || (isr_delta < 900U))
		return phase2_fail("tick", "too small", (int32_t)tick_delta);

	phase2_pass("tick", "tick_delta", tick_delta);
	phase2_pass("tick_irq", "isr_delta", isr_delta);

	return 0;
}

static int32_t phase2_test_delay(void)
{
	TickType_t tick_start = xTaskGetTickCount();
	TickType_t tick_delta;

	no_os_mdelay(100);
	tick_delta = xTaskGetTickCount() - tick_start;

	if (tick_delta < pdMS_TO_TICKS(90))
		return phase2_fail("delay", "too small", (int32_t)tick_delta);

	phase2_pass("delay", "tick_delta", tick_delta);

	return 0;
}

static void vPhase2SelfTestTask(void *pvParameters)
{
	(void)pvParameters;

	console_print("[P2] Phase 2 self-test start tick=%d\r\n",
		      (long)xTaskGetTickCount());

	if (phase2_test_tick() < 0)
		goto fail;
	if (phase2_test_delay() < 0)
		goto fail;
	if (phase2_test_spi_mutex() < 0)
		goto fail;
	if (phase2_test_gpio_mutex() < 0)
		goto fail;
	if (phase2_test_console_mutex() < 0)
		goto fail;
	if (phase2_test_adc_dma_irq() < 0)
		goto fail;

	console_print("[P2][PASS] all detail=complete\r\n");
	vTaskDelete(NULL);

fail:
	console_print("[P2] self-test stopped after failure tick=%d\r\n",
		      (long)xTaskGetTickCount());
	vTaskDelete(NULL);
}

#endif /* PHASE2_SELFTEST */

/*-----------------------------------------------------------*/
/* FreeRTOS application tasks                               */
/*-----------------------------------------------------------*/

#define FREERTOS_CONSOLE_TASK_PRIORITY        7
#define FREERTOS_CONSOLE_TASK_STACK_WORDS     2048
#define FREERTOS_BLE_CONTROL_TASK_PRIORITY    5
#define FREERTOS_BLE_CONTROL_TASK_STACK_WORDS 2048
#define FREERTOS_BLE_TX_ADV_TASK_PRIORITY     8
#define FREERTOS_BLE_TX_ADV_TASK_STACK_WORDS  4096
#define FREERTOS_BLUEBEE_PERF_TASK_PRIORITY   6
#define FREERTOS_BLUEBEE_PERF_TASK_STACK_WORDS 4096
#define FREERTOS_DMAC_POLL_TASK_PRIORITY      8
#define FREERTOS_DMAC_POLL_TASK_STACK_WORDS   512
#define FREERTOS_DMAC_POLL_PERIOD_MS          1

#ifdef CONSOLE_COMMANDS
static void vConsoleCommandTask(void *pvParameters)
{
	(void)pvParameters;

	get_help(NULL, 0);

	for (;;) {
		memset(received_cmd, 0, sizeof(received_cmd));

		console_get_command(received_cmd);

		if (!command_dispatch_line(received_cmd))
			console_print("Invalid command!\n");

		taskYIELD();
	}
}
#endif

static void vDmacPollTask(void *pvParameters)
{
	(void)pvParameters;

	for (;;) {
		if (rx_dmac && (rx_dmac->irq_option == IRQ_ENABLED))
			axi_dmac_poll_pending(rx_dmac);
		if (tx_dmac && (tx_dmac->irq_option == IRQ_ENABLED))
			axi_dmac_poll_pending(tx_dmac);

		vTaskDelay(pdMS_TO_TICKS(FREERTOS_DMAC_POLL_PERIOD_MS));
	}
}

#ifdef FREERTOS_ENABLE_COUNTER_TEST_TASKS
static volatile uint32_t g_task1_ticks = 0;
static volatile uint32_t g_task2_ticks = 0;

/* Task 1: increment counter every 100 ms */
static void vCounterTask1( void * pvParameters )
{
    ( void ) pvParameters;
    console_print( "[TASK] Cnt1 OK tick=%d count=%d\r\n",
                   ( long ) xTaskGetTickCount(),
                   ( long ) g_task1_ticks );

    for( ; ; )
    {
        vTaskDelay( pdMS_TO_TICKS( 100 ) );
        g_task1_ticks++;

        if( ( g_task1_ticks % 50UL ) == 0UL )
        {
            console_print( "[TASK] Cnt1 OK tick=%d count=%d\r\n",
                           ( long ) xTaskGetTickCount(),
                           ( long ) g_task1_ticks );
        }
    }
}
#endif

/* Required by FreeRTOS when configCHECK_FOR_STACK_OVERFLOW is enabled */
void vApplicationStackOverflowHook( TaskHandle_t xTask, char * pcTaskName )
{
    ( void ) xTask;
    console_print( "\r\n!!! STACK OVERFLOW: " );
    console_print( pcTaskName );
    console_print( " !!!\r\n" );
    portDISABLE_INTERRUPTS();
    for( ; ; ) { __asm volatile ( "NOP" ); }
}

void vApplicationMallocFailedHook( void )
{
    console_print( "\r\n!!! MALLOC FAILED: heap=%d !!!\r\n",
                   ( long ) xPortGetFreeHeapSize() );
    portDISABLE_INTERRUPTS();
    for( ; ; ) { __asm volatile ( "NOP" ); }
}

void vApplicationIdleHook( void )
{
    const uint32_t ulGicCpuPmrReg = 0xF8F00104UL;
    const uint32_t ulGicPending0Reg = 0xF8F01200UL;
    const uint32_t ulTimerIsrReg = 0xF8F0060CUL;
    uint32_t ulPmr;
    uint32_t ulPending0;
    uint32_t ulTimerIsr;

    ulPmr = *( volatile uint32_t * ) ulGicCpuPmrReg;
    ulPending0 = *( volatile uint32_t * ) ulGicPending0Reg;
    ulTimerIsr = *( volatile uint32_t * ) ulTimerIsrReg;

    if( ( ( ulPending0 & 0x20000000UL ) != 0UL ) &&
        ( ( ulTimerIsr & 0x00000001UL ) != 0UL ) &&
        ( ulPmr != 0x000000FFUL ) )
    {
        *( volatile uint32_t * ) ulGicCpuPmrReg = 0x000000FFUL;
        __asm volatile ( "DSB" ::: "memory" );
        __asm volatile ( "ISB" ::: "memory" );
    }

    __asm volatile ( "NOP" );
}

#ifdef FREERTOS_ENABLE_COUNTER_TEST_TASKS
/* Task 2: increment counter every 250 ms */
static void vCounterTask2( void * pvParameters )
{
    ( void ) pvParameters;
    console_print( "[TASK] Cnt2 OK tick=%d count=%d\r\n",
                   ( long ) xTaskGetTickCount(),
                   ( long ) g_task2_ticks );

    for( ; ; )
    {
        vTaskDelay( pdMS_TO_TICKS( 250 ) );
        g_task2_ticks++;

        if( ( g_task2_ticks % 20UL ) == 0UL )
        {
            console_print( "[TASK] Cnt2 OK tick=%d count=%d\r\n",
                           ( long ) xTaskGetTickCount(),
                           ( long ) g_task2_ticks );
        }
    }
}
#endif

#endif /* FREERTOS_INTEGRATION */

int main(void)
{
	int32_t status;
#ifdef XILINX_PLATFORM
	Xil_ICacheEnable();
	Xil_DCacheEnable();
	default_init_param.spi_param.extra = &xil_spi_param;
	default_init_param.spi_param.platform_ops = &xil_spi_ops;
#endif

#ifdef ALTERA_PLATFORM
	default_init_param.spi_param.platform_ops = &altera_spi_ops;

	if (altera_bridge_init()) {
		printf("Altera Bridge Init Error!\n");
		return -1;
	}
#endif

	// NOTE: The user has to choose the GPIO numbers according to desired
	// carrier board.
	default_init_param.gpio_resetb.number = GPIO_RESET_PIN;

	default_init_param.gpio_rx1_ctrl_h.number = GPIO_RX1_BAND_SEL_H;
	default_init_param.gpio_rx1_ctrl_l.number = GPIO_RX1_BAND_SEL_L;
	default_init_param.gpio_tx1_ctrl_h.number = GPIO_TX1_BAND_SEL_H;
	default_init_param.gpio_tx1_ctrl_l.number = GPIO_TX1_BAND_SEL_L;
	default_init_param.gpio_rx2_ctrl_h.number = GPIO_RX2_BAND_SEL_H;
	default_init_param.gpio_rx2_ctrl_l.number = GPIO_RX2_BAND_SEL_L;
	default_init_param.gpio_tx2_ctrl_h.number = GPIO_TX2_BAND_SEL_H;
	default_init_param.gpio_tx2_ctrl_l.number = GPIO_TX2_BAND_SEL_L;

#ifdef FMCOMMS5
	default_init_param.gpio_sync.number = GPIO_SYNC_PIN;
	default_init_param.gpio_cal_sw1.number = GPIO_CAL_SW1_PIN;
	default_init_param.gpio_cal_sw2.number = GPIO_CAL_SW2_PIN;
	default_init_param.rx1rx2_phase_inversion_en = 1;
#else
	default_init_param.gpio_sync.number = -1;
	default_init_param.gpio_cal_sw1.number = -1;
	default_init_param.gpio_cal_sw2.number = -1;
#endif

	if (AD9364_DEVICE)
		default_init_param.dev_sel = ID_AD9364;
	if (AD9363A_DEVICE)
		default_init_param.dev_sel = ID_AD9363A;

#if defined FMCOMMS5 || defined ADI_RF_SOM || defined ADI_RF_SOM_CMOS
	default_init_param.xo_disable_use_ext_refclk_enable = 1;
#endif

#ifdef ADI_RF_SOM_CMOS
	default_init_param.swap_ports_enable = 1;
	default_init_param.lvds_mode_enable = 0;
	default_init_param.lvds_rx_onchip_termination_enable = 0;
	default_init_param.full_port_enable = 1;
	default_init_param.digital_interface_tune_fir_disable = 1;
#endif

	ad9361_init(&ad9361_phy, &default_init_param);

	ad9361_set_tx_fir_config(ad9361_phy, tx_fir_config);
	ad9361_set_rx_fir_config(ad9361_phy, rx_fir_config);

#ifdef FMCOMMS5
#ifdef LINUX_PLATFORM
	gpio_init(default_init_param.gpio_sync);
#endif
	default_init_param.spi_param.chip_select = SPI_CS_2;
	default_init_param.gpio_resetb.number = GPIO_RESET_PIN_2;
#ifdef LINUX_PLATFORM
	gpio_init(default_init_param.gpio_resetb);
#endif
	default_init_param.gpio_sync.number = -1;
	default_init_param.gpio_cal_sw1.number = -1;
	default_init_param.gpio_cal_sw2.number = -1;
	default_init_param.rx_synthesizer_frequency_hz = 2300000000UL;
	default_init_param.tx_synthesizer_frequency_hz = 2300000000UL;

	rx_adc_init.base = AD9361_RX_1_BASEADDR;
	tx_dac_init.base = AD9361_TX_1_BASEADDR;

	ad9361_init(&ad9361_phy_b, &default_init_param);

	ad9361_set_tx_fir_config(ad9361_phy_b, tx_fir_config);
	ad9361_set_rx_fir_config(ad9361_phy_b, rx_fir_config);
#endif
	status = axi_dmac_init(&tx_dmac, &tx_dmac_init);
	if (status < 0) {
		printf("axi_dmac_init tx init error: %"PRIi32"\n", status);
		return status;
	}
	status = axi_dmac_init(&rx_dmac, &rx_dmac_init);
	if (status < 0) {
		printf("axi_dmac_init rx init error: %"PRIi32"\n", status);
		return status;
	}
#ifndef AXI_ADC_NOT_PRESENT
#if defined XILINX_PLATFORM || defined LINUX_PLATFORM || defined ALTERA_PLATFORM
#ifdef DAC_DMA_EXAMPLE
#ifdef FMCOMMS5
	axi_dac_init(&ad9361_phy->tx_dac, &tx_dac_init);
	axi_dac_set_datasel(ad9361_phy_b->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);
#endif
	axi_dac_init(&ad9361_phy->tx_dac, &tx_dac_init);
	axi_adc_init(&ad9361_phy->rx_adc, &rx_adc_init);
	extern const uint32_t sine_lut_iq[1024];
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);
	axi_dac_load_custom_data(ad9361_phy->tx_dac, sine_lut_iq,
				 NO_OS_ARRAY_SIZE(sine_lut_iq),
				 (uintptr_t)dac_buffer);
#ifdef XILINX_PLATFORM
	Xil_DCacheFlush();
#endif
#else
#ifdef FMCOMMS5
	axi_dac_init(&ad9361_phy_b->tx_dac, &tx_dac_init);
	axi_dac_set_datasel(ad9361_phy_b->tx_dac, -1, AXI_DAC_DATA_SEL_DDS);
#endif
	axi_dac_init(&ad9361_phy->tx_dac, &tx_dac_init);
	axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DDS);
#endif
#endif
#endif

#ifdef FMCOMMS5
	ad9361_do_mcs(ad9361_phy, ad9361_phy_b);
#endif

#ifndef AXI_ADC_NOT_PRESENT
#if (defined XILINX_PLATFORM || defined ALTERA_PLATFORM) && \
	(defined ADC_DMA_EXAMPLE) && !defined(FREERTOS_INTEGRATION)
	uint32_t samples = 16384;
#if (defined ADC_DMA_IRQ_EXAMPLE)
#ifndef FREERTOS_INTEGRATION
	/**
	 * Xilinx platform dependent initialization for IRQ.
	 */
	struct xil_irq_init_param xil_irq_init_par = {
		.type = IRQ_PS,
	};

	/**
	 * IRQ initial configuration.
	 */
	struct no_os_irq_init_param irq_init_param = {
		.irq_ctrl_id = INTC_DEVICE_ID,
		.platform_ops = &xil_irq_ops,
		.extra = &xil_irq_init_par,
	};
#endif

	/**
	 * IRQ instance.
	 */
	struct no_os_irq_ctrl_desc *irq_desc;

#ifdef FREERTOS_INTEGRATION
	status = freertos_no_os_irq_init();
	if(status < 0)
		return status;
	irq_desc = freertos_irq_desc;
#else
	status = no_os_irq_ctrl_init(&irq_desc, &irq_init_param);
	if(status < 0)
		return status;
#endif

	status = no_os_irq_global_enable(irq_desc);
	if (status < 0)
		return status;

	struct no_os_callback_desc rx_dmac_callback = {
		.ctx = rx_dmac,
		.legacy_callback = axi_dmac_default_isr,
	};

	status = no_os_irq_register_callback(irq_desc,
					     XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR, &rx_dmac_callback);
	if(status < 0)
		return status;

	status = no_os_irq_trigger_level_set(irq_desc,
					     XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR, NO_OS_IRQ_LEVEL_HIGH);
	if(status < 0)
		return status;

	status = no_os_irq_enable(irq_desc, XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR);
	if(status < 0)
		return status;

	samples = 2097150;
#endif
	// NOTE: To prevent unwanted data loss, it's recommended to invalidate
	// cache after each axi_dmac_transfer_start() call, keeping in mind that the
	// size of the capture and the start address must be aligned to the size
	// of the cache line.

#ifdef DAC_DMA_EXAMPLE
#ifdef ADC_DMA_IRQ_EXAMPLE
	struct no_os_callback_desc tx_dmac_callback = {
		.ctx = tx_dmac,
		.legacy_callback = axi_dmac_default_isr,
	};

	status = no_os_irq_register_callback(irq_desc,
					     XPAR_FABRIC_AXI_AD9361_DAC_DMA_IRQ_INTR, &tx_dmac_callback);
	if(status < 0)
		return status;

	status = no_os_irq_enable(irq_desc, XPAR_FABRIC_AXI_AD9361_DAC_DMA_IRQ_INTR);
	if(status < 0)
		return status;
#endif

#ifdef FMCOMMS5
	struct axi_dma_transfer transfer = {
		// Number of bytes to write/read
		.size = samples * AD9361_ADC_DAC_BYTES_PER_SAMPLE *
		(ad9361_phy_b->tx_dac->num_channels + ad9361_phy->tx_dac->num_channels),
		// Transfer done flag
		.transfer_done = 0,
		// Signal transfer mode
		.cyclic = CYCLIC,
		// Address of data source
		.src_addr = (uintptr_t)DAC_DDR_BASEADDR,
		// Address of data destination
		.dest_addr = 0
	};

	/* Transfer the data. */
	axi_dmac_transfer_start(tx_dmac, &transfer);

	/* Flush cache data. */
	Xil_DCacheInvalidateRange((uintptr_t)DAC_DDR_BASEADDR,
				  samples * AD9361_ADC_DAC_BYTES_PER_SAMPLE *
				  (ad9361_phy_b->tx_dac->num_channels + ad9361_phy->tx_dac->num_channels));

	no_os_mdelay(1000);

#else
	struct axi_dma_transfer transfer = {
		// Number of bytes to write/read
		.size = sizeof(sine_lut_iq),
		// Transfer done flag
		.transfer_done = 0,
		// Signal transfer mode
		.cyclic = CYCLIC,
		// Address of data source
		.src_addr = (uintptr_t)dac_buffer,
		// Address of data destination
		.dest_addr = 0
	};

	/* Transfer the data. */
	axi_dmac_transfer_start(tx_dmac, &transfer);

	/* Flush cache data. */
	Xil_DCacheInvalidateRange((uintptr_t)dac_buffer,sizeof(sine_lut_iq));

	no_os_mdelay(1000);
#endif
#endif
#ifdef FMCOMMS5
	struct axi_dma_transfer read_transfer = {
		// Number of bytes to write/read
		.size = samples * AD9361_ADC_DAC_BYTES_PER_SAMPLE *
		(ad9361_phy_b->rx_adc->num_channels + ad9361_phy->rx_adc->num_channels),
		// Transfer done flag
		.transfer_done = 0,
		// Signal transfer mode
		.cyclic = NO,
		// Address of data source
		.src_addr = 0,
		// Address of data destination
		.dest_addr = (uintptr_t)ADC_DDR_BASEADDR
	};

	/* Read the data from the ADC DMA. */
	axi_dmac_transfer_start(rx_dmac, &read_transfer);

	/* Wait until transfer finishes */
	status = axi_dmac_transfer_wait_completion(rx_dmac, 500);
	if(status < 0)
		return status;
#else
	struct axi_dma_transfer read_transfer = {
		// Number of bytes to write/read
		.size = sizeof(adc_buffer),
		// Transfer done flag
		.transfer_done = 0,
		// Signal transfer mode
		.cyclic = NO,
		// Address of data source
		.src_addr = 0,
		// Address of data destination
		.dest_addr = (uintptr_t)adc_buffer
	};

	/* Read the data from the ADC DMA. */
	axi_dmac_transfer_start(rx_dmac, &read_transfer);

	/* Wait until transfer finishes */
	status = axi_dmac_transfer_wait_completion(rx_dmac, 500);
	if(status < 0)
		return status;
#endif
#ifdef XILINX_PLATFORM
#ifdef FMCOMMS5
	Xil_DCacheInvalidateRange(ADC_DDR_BASEADDR,
				  samples * AD9361_ADC_DAC_BYTES_PER_SAMPLE * (ad9361_phy_b->rx_adc->num_channels
						  +
						  ad9361_phy->rx_adc->num_channels));
#else
	Xil_DCacheInvalidateRange((uintptr_t)adc_buffer, sizeof(adc_buffer));
#endif
	printf("DAC_DMA_EXAMPLE: address=%#lx samples=%lu channels=%u bits=%lu\n",
	       (uintptr_t)adc_buffer, NO_OS_ARRAY_SIZE(adc_buffer), rx_adc_init.num_channels,
	       8 * sizeof(adc_buffer[0]));
#endif
#endif
#endif

#ifdef IIO_SUPPORT

	/**
	 * iio application configurations.
	 */
	//struct iio_init_param iio_init_par;

	/**
	 * iio axi adc configurations.
	 */
	struct iio_axi_adc_init_param iio_axi_adc_init_par;

	/**
	 * iio axi dac configurations.
	 */
	struct iio_axi_dac_init_param iio_axi_dac_init_par;

	/**
	 * iio ad9361 configurations.
	 */
	struct iio_ad9361_init_param iio_ad9361_init_param;

	/**
	 * iio instance descriptor.
	 */
	struct iio_axi_adc_desc *iio_axi_adc_desc;

	/**
	 * iio instance descriptor.
	 */
	struct iio_axi_dac_desc *iio_axi_dac_desc;

	/**
	 * iio ad9361 instance descriptor.
	 */
	struct iio_ad9361_desc *iio_ad9361_desc;

	/**
	 * iio devices corresponding to every device.
	 */
	struct iio_device *adc_dev_desc, *dac_dev_desc, *ad9361_dev_desc;

	status = axi_dmac_init(&tx_dmac, &tx_dmac_init);
	if(status < 0)
		return status;

	iio_axi_adc_init_par = (struct iio_axi_adc_init_param) {
		.rx_adc = ad9361_phy->rx_adc,
		.rx_dmac = rx_dmac,
#ifndef PLATFORM_MB
		.dcache_invalidate_range = (void (*)(uint32_t,
						     uint32_t))Xil_DCacheInvalidateRange
#endif
	};

	status = iio_axi_adc_init(&iio_axi_adc_desc, &iio_axi_adc_init_par);
	if(status < 0)
		return status;
	iio_axi_adc_get_dev_descriptor(iio_axi_adc_desc, &adc_dev_desc);
	struct iio_data_buffer read_buff = {
		.buff = (void *)ADC_DDR_BASEADDR,
		.size = 0xFFFFFFFF,
	};

	iio_axi_dac_init_par = (struct iio_axi_dac_init_param) {
		.tx_dac = ad9361_phy->tx_dac,
		.tx_dmac = tx_dmac,
#ifndef PLATFORM_MB
		.dcache_flush_range = (void (*)(uint32_t, uint32_t))Xil_DCacheFlushRange,
#endif
	};

	status = iio_axi_dac_init(&iio_axi_dac_desc, &iio_axi_dac_init_par);
	if (status < 0)
		return status;
	iio_axi_dac_get_dev_descriptor(iio_axi_dac_desc, &dac_dev_desc);

	struct iio_data_buffer write_buff = {
		.buff = (void *)DAC_DDR_BASEADDR,
		.size = 0xFFFFFFFF,
	};

	iio_ad9361_init_param = (struct iio_ad9361_init_param) {
		.ad9361_phy = ad9361_phy,
	};

	status = iio_ad9361_init(&iio_ad9361_desc, &iio_ad9361_init_param);
	if (status < 0)
		return status;
	iio_ad9361_get_dev_descriptor(iio_ad9361_desc, &ad9361_dev_desc);

	struct iio_app_device devices[] = {
		IIO_APP_DEVICE("cf-ad9361-lpc", iio_axi_adc_desc, adc_dev_desc, &read_buff, NULL),
		IIO_APP_DEVICE("cf-ad9361-dds-core-lpc", iio_axi_dac_desc, dac_dev_desc, NULL, &write_buff),
		IIO_APP_DEVICE("ad9361-phy", ad9361_phy, ad9361_dev_desc, NULL, NULL)
	};

	iio_app_run(devices, NO_OS_ARRAY_SIZE(devices));

#endif // IIO_SUPPORT

#ifdef FREERTOS_INTEGRATION
	/*
	 * Phase 1: FreeRTOS kernel verification.
	 * Use the no-OS IRQ controller path, then start the scheduler.
	 */
	{
		BaseType_t       rc_dmac_poll;
		TaskHandle_t     h_dmac_poll = NULL;
#ifdef CONSOLE_COMMANDS
		BaseType_t       rc_console;
		BaseType_t       rc_ble_control;
		BaseType_t       rc_ble_tx_adv;
		BaseType_t       rc_bluebee_perf;
		TaskHandle_t     h_console = NULL;
		TaskHandle_t     h_ble_control = NULL;
		TaskHandle_t     h_ble_tx_adv = NULL;
		TaskHandle_t     h_bluebee_perf = NULL;
#endif
#ifdef FREERTOS_ENABLE_COUNTER_TEST_TASKS
		BaseType_t       rc_cnt1;
		BaseType_t       rc_cnt2;
		TaskHandle_t     h_cnt1 = NULL;
		TaskHandle_t     h_cnt2 = NULL;
#endif
#ifdef PHASE2_SELFTEST
		BaseType_t       rc_p2;
		TaskHandle_t     h_p2 = NULL;
#endif

		status = freertos_no_os_irq_init();
		if( status < 0 )
		{
			console_print( "[ERR] FreeRTOS no-OS IRQ init failed; scheduler not started\r\n" );
			for( ; ; ) { __asm volatile ( "NOP" ); }
		}

		rc_dmac_poll = xTaskCreate( vDmacPollTask, "DmacPoll",
					    FREERTOS_DMAC_POLL_TASK_STACK_WORDS,
					    NULL,
					    FREERTOS_DMAC_POLL_TASK_PRIORITY,
					    &h_dmac_poll );
#ifdef CONSOLE_COMMANDS
		if( ble_tx_adv_init() < 0 )
		{
			console_print( "[ERR] BLE ADV TX init failed; scheduler not started\r\n" );
			for( ; ; ) { __asm volatile ( "NOP" ); }
		}
		if( ble_command_service_init() < 0 )
		{
			console_print( "[ERR] BLE command service init failed; scheduler not started\r\n" );
			for( ; ; ) { __asm volatile ( "NOP" ); }
		}

		rc_console = xTaskCreate( vConsoleCommandTask, "Console",
					  FREERTOS_CONSOLE_TASK_STACK_WORDS,
					  NULL,
					  FREERTOS_CONSOLE_TASK_PRIORITY,
					  &h_console );
		rc_ble_control = xTaskCreate( ble_command_service_task, "BLE_CTRL",
					      FREERTOS_BLE_CONTROL_TASK_STACK_WORDS,
					      NULL,
					      FREERTOS_BLE_CONTROL_TASK_PRIORITY,
					      &h_ble_control );
		rc_ble_tx_adv = xTaskCreate( ble_tx_adv_task, "BLE_TX_ADV",
					     FREERTOS_BLE_TX_ADV_TASK_STACK_WORDS,
					     NULL,
					     FREERTOS_BLE_TX_ADV_TASK_PRIORITY,
					     &h_ble_tx_adv );
		rc_bluebee_perf = xTaskCreate( bluebee_perf_task, "BLUEBEE_PERF",
					       FREERTOS_BLUEBEE_PERF_TASK_STACK_WORDS,
					       NULL,
					       FREERTOS_BLUEBEE_PERF_TASK_PRIORITY,
					       &h_bluebee_perf );
#endif
#ifdef FREERTOS_ENABLE_COUNTER_TEST_TASKS
		rc_cnt1 = xTaskCreate( vCounterTask1, "Cnt1", 512, NULL, 2, &h_cnt1 );
		rc_cnt2 = xTaskCreate( vCounterTask2, "Cnt2", 512, NULL, 1, &h_cnt2 );
#endif
#ifdef PHASE2_SELFTEST
		rc_p2 = xTaskCreate( vPhase2SelfTestTask, "P2SelfTest",
				     PHASE2_TASK_STACK_WORDS, NULL,
				     PHASE2_TASK_PRIORITY, &h_p2 );
#endif

		if( ( rc_dmac_poll != pdPASS )
#ifdef CONSOLE_COMMANDS
		    || ( rc_console != pdPASS )
		    || ( rc_ble_control != pdPASS )
		    || ( rc_ble_tx_adv != pdPASS )
		    || ( rc_bluebee_perf != pdPASS )
#endif
#ifdef FREERTOS_ENABLE_COUNTER_TEST_TASKS
		    || ( rc_cnt1 != pdPASS ) || ( rc_cnt2 != pdPASS )
#endif
#ifdef PHASE2_SELFTEST
		    || ( rc_p2 != pdPASS )
#endif
		  )
		{
			console_print( "[ERR] FreeRTOS task creation failed; scheduler not started\r\n" );
			for( ; ; ) { __asm volatile ( "NOP" ); }
		}

		/*
		 * Install the FreeRTOS vector table BEFORE starting the scheduler.
		 * V11 does NOT do this automatically (unlike V10).
		 * The vector table maps:
		 *   IRQ → FreeRTOS_IRQ_Handler  (portASM.S)
		 *   SVC → FreeRTOS_SWI_Handler  (portASM.S, used by portYIELD)
		 */
		__asm volatile ( "MCR p15, 0, %0, c12, c0, 0" :: "r" ( &_freertos_vector_table ) : "memory" );
		__asm volatile ( "DSB" ::: "memory" );
		__asm volatile ( "ISB" ::: "memory" );

		/* Never returns */
		vTaskStartScheduler();

		/* Should never reach here */
		for( ; ; ) { __asm volatile ( "NOP" ); }
	}

#elif defined( CONSOLE_COMMANDS )
	get_help(NULL, 0);

	while(1)
	{
		console_get_command(received_cmd);
		if (!command_dispatch_line(received_cmd))
			console_print("Invalid command!\n");
	}
#endif
	printf("Done.\n");

#ifdef TDD_SWITCH_STATE_EXAMPLE
	uint32_t ensm_mode;
	struct no_os_gpio_init_param  gpio_init = {
		.platform_ops = GPIO_OPS,
		.extra = GPIO_PARAM
	};
	struct no_os_gpio_desc 	*gpio_enable_pin;
	struct no_os_gpio_desc 	*gpio_txnrx_pin;
	if (!ad9361_phy->pdata->fdd) {
		if (ad9361_phy->pdata->ensm_pin_ctrl) {
			gpio_init.number = GPIO_ENABLE_PIN;
			status = no_os_gpio_get(&gpio_enable_pin, &gpio_init);
			if (status != 0) {
				printf("no_os_gpio_get() error: %"PRIi32"\n", status);
				return status;
			}
			no_os_gpio_direction_output(gpio_enable_pin, 1);
			gpio_init.number = GPIO_TXNRX_PIN;
			status = no_os_gpio_get(&gpio_txnrx_pin, &gpio_init);
			if (status != 0) {
				printf("no_os_gpio_get() error: %"PRIi32"\n", status);
				return status;
			}
			no_os_gpio_direction_output(gpio_txnrx_pin, 0);
			no_os_udelay(10);
			ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
			printf("TXNRX control - Alert: %s\n",
			       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
			no_os_mdelay(1000);

			if (ad9361_phy->pdata->ensm_pin_pulse_mode) {
				while(1) {
					no_os_gpio_set_value(gpio_txnrx_pin, 0);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 0);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX Pulse control - RX: %s\n",
					       ensm_mode == ENSM_MODE_RX ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 0);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX Pulse control - Alert: %s\n",
					       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_txnrx_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 0);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX Pulse control - TX: %s\n",
					       ensm_mode == ENSM_MODE_TX ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 0);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX Pulse control - Alert: %s\n",
					       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
					no_os_mdelay(1000);
				}
			} else {
				while(1) {
					no_os_gpio_set_value(gpio_txnrx_pin, 0);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX control - RX: %s\n",
					       ensm_mode == ENSM_MODE_RX ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_enable_pin, 0);
					no_os_udelay(10);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX control - Alert: %s\n",
					       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_txnrx_pin, 1);
					no_os_udelay(10);
					no_os_gpio_set_value(gpio_enable_pin, 1);
					no_os_udelay(10);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX control - TX: %s\n",
					       ensm_mode == ENSM_MODE_TX ? "OK" : "Error");
					no_os_mdelay(1000);

					no_os_gpio_set_value(gpio_enable_pin, 0);
					no_os_udelay(10);
					ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
					printf("TXNRX control - Alert: %s\n",
					       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
					no_os_mdelay(1000);
				}
			}
		} else {
			while(1) {
				ad9361_set_en_state_machine_mode(ad9361_phy, ENSM_MODE_RX);
				ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
				printf("SPI control - RX: %s\n",
				       ensm_mode == ENSM_MODE_RX ? "OK" : "Error");
				no_os_mdelay(1000);

				ad9361_set_en_state_machine_mode(ad9361_phy, ENSM_MODE_ALERT);
				ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
				printf("SPI control - Alert: %s\n",
				       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
				no_os_mdelay(1000);

				ad9361_set_en_state_machine_mode(ad9361_phy, ENSM_MODE_TX);
				ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
				printf("SPI control - TX: %s\n",
				       ensm_mode == ENSM_MODE_TX ? "OK" : "Error");
				no_os_mdelay(1000);

				ad9361_set_en_state_machine_mode(ad9361_phy, ENSM_MODE_ALERT);
				ad9361_get_en_state_machine_mode(ad9361_phy, &ensm_mode);
				printf("SPI control - Alert: %s\n",
				       ensm_mode == ENSM_MODE_ALERT ? "OK" : "Error");
				no_os_mdelay(1000);
			}
		}
	}
#endif

	ad9361_remove(ad9361_phy);
#ifdef FMCOMMS5
	ad9361_remove(ad9361_phy_b);
#endif

#ifdef XILINX_PLATFORM
	Xil_DCacheDisable();
	Xil_ICacheDisable();
#endif

#ifdef ALTERA_PLATFORM
	if (altera_bridge_uninit()) {
		printf("Altera Bridge Uninit Error!\n");
		return -1;
	}
#endif

	return 0;
}
