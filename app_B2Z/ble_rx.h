#ifndef BLE_RX_PORT_H
#define BLE_RX_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BLE_ELG_MAX_SAMPLES 64u
#define BLE_FIR_TAP_COUNT 9u

typedef void (*ble_packet_handler_t)(const uint8_t *ble_pdu, size_t len,
                                     void *ctx);

typedef int (*ble_dma_capture_fn_t)(void *dma_ctx, void *dst, uint32_t bytes,
                                    uint32_t timeout_ms);

typedef struct {
    uint32_t sample_rate_hz;
    uint32_t symbol_rate_hz;
    uint8_t ble_channel;
    bool strict_crc;
    bool invert_metric;
    uint8_t symbol_phase;

    float samples_per_symbol;
    float samples_per_symbol_decim;
    float decim_step;
    float decim_phase;
    float decim_lp_i;
    float decim_lp_q;
    float decim_lp_alpha;
    int16_t decim_prev_i;
    int16_t decim_prev_q;
    bool decim_have_prev;

    float fir_taps[BLE_FIR_TAP_COUNT];
    float fir_state_i[BLE_FIR_TAP_COUNT];
    float fir_state_q[BLE_FIR_TAP_COUNT];
    uint8_t fir_index;
    uint8_t fir_decim_count;
    float timing_offset;
    float timing_mu;
    float elg_early_sum;
    float elg_late_sum;
    float elg_err_sum;
    float elg_err_hist[8];
    float elg_samples[BLE_ELG_MAX_SAMPLES];
    uint8_t elg_sample_count;
    uint8_t elg_err_idx;
    uint8_t elg_err_count;
    bool have_prev;
    int16_t prev_i;
    int16_t prev_q;
    float prev_i_f;
    float prev_q_f;
    uint32_t sample_count;
    float phase_acc;
    float sym_metric_sum;
    float metric_acc;
    uint32_t sym_count;

    uint8_t bit_acc;
    uint8_t bit_count;

    uint8_t frame_buf[512];
    size_t frame_buf_len;

    uint32_t candidate_frames;
    uint32_t raw_sync_frames;
    uint32_t sync_hits;
    uint32_t emitted_frames;
    uint32_t crc_ok_frames;
    uint32_t crc_fail_frames;
    uint32_t dma_loops;

    ble_packet_handler_t on_packet;
    void *on_packet_ctx;
} ble_rx_port_t;

int ble_rx_port_init(ble_rx_port_t *rx, uint32_t sample_rate_hz,
                     uint32_t symbol_rate_hz, uint8_t ble_channel,
                     bool strict_crc, ble_packet_handler_t on_packet,
                     void *on_packet_ctx);

uint64_t ble_rx_channel_to_freq_hz(uint8_t ble_channel);

uint8_t ble_channel_to_data_idx(uint8_t ch);

size_t bt_whiten(const uint8_t *in, size_t len, uint8_t ch_idx, uint8_t *out);

void ble_rx_port_reset(ble_rx_port_t *rx);

void ble_rx_port_process_iq_i16(ble_rx_port_t *rx, const int16_t *iq,
                                size_t iq_pair_count);

void ble_rx_port_process_iq_i16_gardner(ble_rx_port_t *rx, const int16_t *iq,
                                        size_t iq_pair_count);

void ble_rx_port_process_iq_i16_strided(ble_rx_port_t *rx,
                                        const int16_t *samples,
                                        size_t sample_word_count,
                                        uint8_t i_index,
                                        uint8_t q_index,
                                        uint8_t stride_words);

void ble_rx_port_default_printer(const uint8_t *ble_pdu, size_t len, void *ctx);

int ble_rx_port_dma_capture_and_process(
    ble_rx_port_t *rx,
    ble_dma_capture_fn_t dma_capture,
    void *dma_ctx,
    void *adc_buf,
    uint32_t adc_bytes,
    uint32_t timeout_ms,
    void (*cache_invalidate)(uintptr_t addr, uint32_t bytes));

int ble_rx_port_dma_capture_and_process_strided(
    ble_rx_port_t *rx,
    ble_dma_capture_fn_t dma_capture,
    void *dma_ctx,
    void *adc_buf,
    uint32_t adc_bytes,
    uint32_t timeout_ms,
    uint8_t i_index,
    uint8_t q_index,
    uint8_t stride_words,
    void (*cache_invalidate)(uintptr_t addr, uint32_t bytes));

void bt_crc24(const uint8_t *data, size_t length, uint8_t out[3]);

#endif
