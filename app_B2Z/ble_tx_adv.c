#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "ad9361_api.h"
#include "axi_dac_core.h"
#include "axi_dmac.h"
#include "ble_rx.h"
#include "ble_tx_adv.h"
#include "no_os_axi_io.h"
#include "no_os_delay.h"

#ifdef XILINX_PLATFORM
extern void Xil_DCacheFlush(void);
extern void Xil_DCacheFlushRange(uintptr_t adr, uint32_t len);
#endif

#define BLE_ADV_CH37_FREQ_HZ (2402000000ULL)
#define BLE_TX_SAMPLE_RATE_HZ (30720000.0f)
#define BLE_TX_SYMBOL_RATE_HZ (1000000.0f)
#define BLE_TX_IQ_AMPLITUDE (12000)
#define BLE_MAX_PDU_LEN (39u)
#define BLE_MAX_PACKET_BYTES (1u + 4u + BLE_MAX_PDU_LEN)
#define BLE_MAX_SAMPLE_WORDS (16000u)
#define BLE_GFSK_SPS_HIGH (768u)
#define BLE_GFSK_DECIM (25u)
#define BLE_GFSK_SPAN (3u)
#define BLE_GFSK_BT (0.5f)
#define BLE_GFSK_TAPS (BLE_GFSK_SPAN * BLE_GFSK_SPS_HIGH)
#define BLE_GFSK_LUT_PHASES (BLE_GFSK_SPS_HIGH)

#ifndef M_PI
#define M_PI (3.14159265358979323846)
#endif

extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *tx_dmac;

static uint32_t ble_adv_iq_words[BLE_MAX_SAMPLE_WORDS] __attribute__((aligned(64)));
static float ble_gfsk_taps[BLE_GFSK_TAPS];
static uint8_t ble_gfsk_taps_ready = 0u;
static float ble_gfsk_phase_lut[BLE_GFSK_LUT_PHASES][8];
static uint8_t ble_gfsk_phase_lut_ready = 0u;

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

static void fast_sin_cos(float x, float *out_sin, float *out_cos)
{
    float x2;
    float x4;

    x = wrap_pi(x);
    x2 = x * x;
    x4 = x2 * x2;

    *out_sin = x * (1.0f - (x2 * 0.16666667f) + (x4 * 0.008333333f));
    *out_cos = 1.0f - (x2 * 0.5f) + (x4 * 0.041666667f);
}

static int32_t round_float_to_int(float x)
{
    return (int32_t)(x >= 0.0f ? (x + 0.5f) : (x - 0.5f));
}

static void init_ble_gfsk_taps(void)
{
    if (ble_gfsk_taps_ready)
        return;

    const float alpha = sqrtf(logf(2.0f) / 2.0f) / BLE_GFSK_BT;
    const float inv_sps = 1.0f / (float)BLE_GFSK_SPS_HIGH;
    const float half = (float)BLE_GFSK_TAPS / 2.0f;
    float sum = 0.0f;

    for (uint32_t n = 0; n < BLE_GFSK_TAPS; n++) {
        float t = ((float)n - half) * inv_sps;
        float x = (float)M_PI * t / alpha;
        float h = (sqrtf((float)M_PI) / alpha) * expf(-(x * x));
        ble_gfsk_taps[n] = h;
        sum += h;
    }

    if (sum != 0.0f) {
        float inv_sum = 1.0f / sum;
        for (uint32_t n = 0; n < BLE_GFSK_TAPS; n++)
            ble_gfsk_taps[n] *= inv_sum;
    }

    ble_gfsk_taps_ready = 1u;
}

static void init_ble_gfsk_phase_lut(void)
{
    if (ble_gfsk_phase_lut_ready)
        return;

    init_ble_gfsk_taps();

    for (uint32_t phase_idx = 0u; phase_idx < BLE_GFSK_LUT_PHASES; phase_idx++) {
        uint32_t r = (phase_idx * BLE_GFSK_DECIM) % BLE_GFSK_SPS_HIGH;
        int32_t n_high = (int32_t)BLE_GFSK_SPS_HIGH + (int32_t)r;
        int32_t start = n_high - (int32_t)(BLE_GFSK_TAPS / 2u);

        for (uint32_t pat = 0u; pat < 8u; pat++) {
            float acc = 0.0f;
            float sym_prev = (pat & 0x4u) ? 1.0f : -1.0f;
            float sym_cur = (pat & 0x2u) ? 1.0f : -1.0f;
            float sym_next = (pat & 0x1u) ? 1.0f : -1.0f;

            for (uint32_t k = 0u; k < BLE_GFSK_TAPS; k++) {
                int32_t idx = start + (int32_t)k;
                if (idx >= 0 && idx < (int32_t)(3u * BLE_GFSK_SPS_HIGH)) {
                    uint32_t rel = (uint32_t)idx / BLE_GFSK_SPS_HIGH;
                    float sym = (rel == 0u) ? sym_prev : ((rel == 1u) ? sym_cur : sym_next);
                    acc += ble_gfsk_taps[k] * sym;
                }
            }

            ble_gfsk_phase_lut[phase_idx][pat] = acc;
        }
    }

    ble_gfsk_phase_lut_ready = 1u;
}

static int32_t build_adv_packet_bytes(uint8_t *pkt, uint32_t *pkt_len)
{
    static const uint8_t adv_addr[6] = {0xFFu, 0x11u, 0x22u, 0x33u, 0x44u, 0xFFu};
    static const uint8_t flags_ad[] = {0x02u, 0x01u, 0x06u};
    static const uint8_t name_ad[] = {0x08u, 0x09u, 'S', 'D', 'R', '_', 'B', 'L', 'E'};

    uint8_t pdu[2 + 6 + sizeof(flags_ad) + sizeof(name_ad) + 3];
    uint8_t crc[3];
    uint8_t whitened[sizeof(pdu)];
    uint8_t whiten_ch_idx;
    pdu[0] = 0x42u;
    pdu[1] = (uint8_t)(sizeof(adv_addr) + sizeof(flags_ad) + sizeof(name_ad));

    for (uint32_t i = 0; i < sizeof(adv_addr); i++)
        pdu[2 + i] = adv_addr[sizeof(adv_addr) - 1u - i];
    memcpy(&pdu[2 + sizeof(adv_addr)], flags_ad, sizeof(flags_ad));
    memcpy(&pdu[2 + sizeof(adv_addr) + sizeof(flags_ad)], name_ad, sizeof(name_ad));

    bt_crc24(pdu, sizeof(pdu) - 3u, crc);
    pdu[sizeof(pdu) - 3u] = crc[0];
    pdu[sizeof(pdu) - 2u] = crc[1];
    pdu[sizeof(pdu) - 1u] = crc[2];

    whiten_ch_idx = 37u;
    bt_whiten(pdu, sizeof(pdu), whiten_ch_idx, whitened);

    pkt[0] = 0xAAu;
    pkt[1] = 0xD6u;
    pkt[2] = 0xBEu;
    pkt[3] = 0x89u;
    pkt[4] = 0x8Eu;
    memcpy(&pkt[5], whitened, sizeof(whitened));

    *pkt_len = (uint32_t)sizeof(pdu) + 5u;

    return 0;
}

static int32_t build_adv_iq_words(const uint8_t *pkt, uint32_t pkt_len,
                                  uint32_t *out_word_count)
{
    const int32_t c = 32724;    //cos(2.93)
    const int32_t s = 1675;
    const float samples_per_symbol = BLE_TX_SAMPLE_RATE_HZ / BLE_TX_SYMBOL_RATE_HZ;
    const uint32_t total_bits = pkt_len * 8u;
    const uint32_t sample_count = (uint32_t)(samples_per_symbol * (float)total_bits + 0.999f);

    int32_t i = BLE_TX_IQ_AMPLITUDE;
    int32_t q = 0;
    float sym_acc = 0.0f;
    uint32_t bit_idx = 0u;
    uint32_t n;
    uint32_t w = 0u;

    if ((sample_count * 2u) > BLE_MAX_SAMPLE_WORDS)
        return -1;

    for (n = 0u; n < sample_count; n++) {
        uint8_t bit = get_bit_lsb_first(pkt, bit_idx);
        int32_t rot_s = bit ? s : -s;
        int32_t ni = (i * c - q * rot_s) >> 15;
        int32_t nq = (i * rot_s + q * c) >> 15;
        int16_t oi;
        int16_t oq;

        i = ni;
        q = nq;

        if (i > 32767)
            i = 32767;
        if (i < -32768)
            i = -32768;
        if (q > 32767)
            q = 32767;
        if (q < -32768)
            q = -32768;

        oi = (int16_t)i;
        oq = (int16_t)q;
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);

        sym_acc += 1.0f;
        if (sym_acc >= samples_per_symbol) {
            sym_acc -= samples_per_symbol;
            if (bit_idx + 1u < total_bits)
                bit_idx++;
        }
    }

    *out_word_count = w;
    return 0;
}

static int32_t build_adv_iq_words_gfsk(const uint8_t *pkt, uint32_t pkt_len,
                                       uint32_t *out_word_count)
{
    const uint32_t total_bits = pkt_len * 8u;
    const uint32_t high_count = total_bits * BLE_GFSK_SPS_HIGH;
    const uint32_t out_samples = ((high_count - 1u) / BLE_GFSK_DECIM) + 1u;
    const float phase_step = (float)M_PI / (2.0f * (float)BLE_GFSK_SPS_HIGH);
    const float phase_step_decim = phase_step * (float)BLE_GFSK_DECIM;
    float phase = 0.0f;
    uint32_t w = 0u;

    if ((out_samples * 2u) > BLE_MAX_SAMPLE_WORDS)
        return -1;

    init_ble_gfsk_taps();

    for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
        uint32_t n = n_out * BLE_GFSK_DECIM;
        float acc = 0.0f;
        int32_t start = (int32_t)n - (int32_t)(BLE_GFSK_TAPS / 2u);

        for (uint32_t k = 0u; k < BLE_GFSK_TAPS; k++) {
            int32_t idx = start + (int32_t)k;
            if ((uint32_t)idx < high_count) {
                uint32_t bit_idx = (uint32_t)idx / BLE_GFSK_SPS_HIGH;
                uint8_t bit = get_bit_lsb_first(pkt, bit_idx);
                float sym = bit ? 1.0f : -1.0f;
                acc += ble_gfsk_taps[k] * sym;
            }
        }

        phase += acc * phase_step_decim;

        float fi;
        float fq;
        int32_t ii;
        int32_t iq;
        int16_t oi;
        int16_t oq;

        fast_sin_cos(phase, &fq, &fi);
        ii = round_float_to_int(fi * (float)BLE_TX_IQ_AMPLITUDE);
        iq = round_float_to_int(fq * (float)BLE_TX_IQ_AMPLITUDE);

        if (ii > 32767)
            ii = 32767;
        if (ii < -32768)
            ii = -32768;
        if (iq > 32767)
            iq = 32767;
        if (iq < -32768)
            iq = -32768;

        oi = (int16_t)ii;
        oq = (int16_t)iq;
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);
    }

    *out_word_count = w;
    return 0;
}

static int32_t build_adv_iq_words_gfsk_lut(const uint8_t *pkt, uint32_t pkt_len,
                                           uint32_t *out_word_count)
{
    const uint32_t total_bits = pkt_len * 8u;
    const uint32_t high_count = total_bits * BLE_GFSK_SPS_HIGH;
    const uint32_t out_samples = ((high_count - 1u) / BLE_GFSK_DECIM) + 1u;
    const float phase_step = (float)M_PI / (2.0f * (float)BLE_GFSK_SPS_HIGH);
    const float phase_step_decim = phase_step * (float)BLE_GFSK_DECIM;
    float phase = 0.0f;
    uint32_t w = 0u;

    if ((out_samples * 2u) > BLE_MAX_SAMPLE_WORDS)
        return -1;

    init_ble_gfsk_phase_lut();

    for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
        uint32_t n = n_out * BLE_GFSK_DECIM;
        uint32_t bit_idx = n / BLE_GFSK_SPS_HIGH;
        uint8_t prev = (bit_idx > 0u) ? get_bit_lsb_first(pkt, bit_idx - 1u) : 0u;
        uint8_t cur = (bit_idx < total_bits) ? get_bit_lsb_first(pkt, bit_idx) : 0u;
        uint8_t next = (bit_idx + 1u < total_bits) ? get_bit_lsb_first(pkt, bit_idx + 1u) : 0u;
        uint32_t pat = ((uint32_t)prev << 2) | ((uint32_t)cur << 1) | (uint32_t)next;
        uint32_t phase_idx = n_out % BLE_GFSK_LUT_PHASES;
        float acc = ble_gfsk_phase_lut[phase_idx][pat];

        phase += acc * phase_step_decim;

        float fi;
        float fq;
        int32_t ii;
        int32_t iq;
        int16_t oi;
        int16_t oq;

        fast_sin_cos(phase, &fq, &fi);
        ii = round_float_to_int(fi * (float)BLE_TX_IQ_AMPLITUDE);
        iq = round_float_to_int(fq * (float)BLE_TX_IQ_AMPLITUDE);

        if (ii > 32767)
            ii = 32767;
        if (ii < -32768)
            ii = -32768;
        if (iq > 32767)
            iq = 32767;
        if (iq < -32768)
            iq = -32768;

        oi = (int16_t)ii;
        oq = (int16_t)iq;
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);
        ble_adv_iq_words[w++] = pack_iq_word(oi, oq);
    }

    *out_word_count = w;
    return 0;
}

void ble_tx_adv_name_demo(double *param, char param_no)
{
    uint8_t packet[BLE_MAX_PACKET_BYTES];
    uint32_t packet_len = 0u;
    uint32_t iq_words = 0u;
    struct axi_dma_transfer transfer;
    int32_t ret;

    (void)param;
    (void)param_no;

    if (tx_dmac == NULL || ad9361_phy == NULL || ad9361_phy->tx_dac == NULL) {
        printf("ble adv tx init error\n");
        return;
    }

    ret = build_adv_packet_bytes(packet, &packet_len);
    if (ret < 0) {
        printf("build ble adv packet failed\n");
        return;
    }

    // ret = build_adv_iq_words(packet, packet_len, &iq_words);
    ret = build_adv_iq_words_gfsk_lut(packet, packet_len, &iq_words);
    if (ret < 0) {
        printf("build ble adv iq failed\n");
        return;
    }

    axi_dac_set_datasel(ad9361_phy->tx_dac, -1, AXI_DAC_DATA_SEL_DMA);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_h, 0);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx1_ctrl_l, 1);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_h, 0);
    no_os_gpio_set_value(ad9361_phy->gpio_desc_tx2_ctrl_l, 1);
    ad9361_set_tx_rf_port_output(ad9361_phy, TXB);
    ad9361_set_tx_lo_freq(ad9361_phy, BLE_ADV_CH37_FREQ_HZ);

    Xil_DCacheFlush();
    Xil_DCacheFlushRange((uintptr_t)ble_adv_iq_words, iq_words * sizeof(uint32_t));

    transfer.size = iq_words * sizeof(uint32_t);
    transfer.transfer_done = 0;
    transfer.cyclic = NO;
    transfer.src_addr = (uintptr_t)ble_adv_iq_words;
    transfer.dest_addr = 0;

    no_os_mdelay(1);
    no_os_axi_io_write(ad9361_phy->tx_dac->base,
                       AXI_DAC_REG_SYNC_CONTROL,
                       AXI_DAC_SYNC);
    ret = axi_dmac_transfer_start(tx_dmac, &transfer);
    if (ret < 0) {
        printf("ble adv dma start failed\n");
        return;
    }

    printf("BLE ADV sent on ch37, name=SDR_BLE, bytes=%lu, iq_words=%lu\n",
           (unsigned long)packet_len,
           (unsigned long)iq_words);
}
