#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ble.h"
#include "xtime_l.h"

#include "ad9361_api.h"
#include "ble_rx_adi_glue.h"
#include "ble_rx.h"

#define BLE_ADC_BUFFER_BYTES (262144u)
#define BLE_SAMPLE_RATE_HZ (30720000u)
#define BLE_SYMBOL_RATE_HZ (1000000u)
#define BLE_CHANNEL (37u)
#define BLE_DMA_STRIDE_WORDS (4u)
#define BLE_STATUS_PRINT_PERIOD (100u)
#define BLE_SYNC_REPORT_BYTES (32u)
#define BLE_AUTO_SELECT_WORDS (32768u)
#define BLE_HOP_INTERVAL_US (20000u)

extern struct ad9361_rf_phy *ad9361_phy;
extern struct axi_dmac *rx_dmac;

static int16_t ble_adc_buffer[BLE_ADC_BUFFER_BYTES / sizeof(int16_t)]
    __attribute__((aligned(64)));

static volatile uint32_t g_pkt_count;
static uint32_t g_last_pkt_count;
static uint32_t g_good_pkt_count;
static uint32_t g_stall_periods;
static bool g_service_inited;
static bool g_service_running;
static ble_rx_port_t g_rx;
static ble_adi_dma_ctx_t g_dma_ctx;
static uint64_t g_rf_hz;
static const uint8_t g_adv_channels[3] = {37u, 38u, 39u};
static uint8_t g_adv_idx;
static XTime g_last_hop_tick;
static uint64_t g_hop_ticks;

typedef struct {
    uint8_t i_index;
    uint8_t q_index;
    bool invert_metric;
    uint8_t symbol_phase;
    uint32_t aa_hits;
    uint32_t preamble_hits;
} ble_combo_t;

static uint8_t g_i_index = 0u;
static uint8_t g_q_index = 1u;
static bool g_invert_metric = false;
static uint8_t g_symbol_phase = 0u;
static uint8_t g_last_i_index = 0u;
static uint8_t g_last_q_index = 1u;
static bool g_last_invert_metric = false;
static uint8_t g_last_symbol_phase = 0u;

/*
 * Function: adv_pdu_name
 * Purpose : Convert advertising PDU type nibble to human-readable name.
 * Params  : t - PDU type nibble.
 * Return  : Constant string with type name.
 */
static const char *adv_pdu_name(uint8_t t)
{
    switch (t & 0x0Fu) {
    case 0x00u: return "ADV_IND";
    case 0x01u: return "ADV_DIRECT_IND";
    case 0x02u: return "ADV_NONCONN_IND";
    case 0x03u: return "SCAN_REQ";
    case 0x04u: return "SCAN_RSP";
    case 0x05u: return "CONNECT_REQ";
    case 0x06u: return "ADV_SCAN_IND";
    default: return "UNKNOWN";
    }
}

/*
 * Function: print_addr
 * Purpose : Print BLE address in sniffer style (MSB first, colon separated).
 * Params  : addr - Pointer to 6-byte address in on-air order.
 * Return  : None.
 */
static void print_addr(const uint8_t *addr)
{
    size_t i;
    for (i = 0; i < 6u; i++)
        printf("%02X%s", addr[5u - i], (i == 5u) ? "" : ":");
}

/*
 * Function: print_ad_list
 * Purpose : Decode and print AD structures from advertising data.
 * Params  : ad     - Pointer to AD payload.
 *           ad_len - AD payload length in bytes.
 * Return  : None.
 * Principle: AD payload is LTV encoded as [len][type][value...], repeated.
 */
static void print_ad_list(const uint8_t *ad, size_t ad_len)
{
    size_t pos = 0u;
    while (pos + 1u < ad_len) {
        uint8_t l = ad[pos];
        uint8_t t;
        size_t i;
        if (l == 0u || pos + 1u + l > ad_len)
            break;
        t = ad[pos + 1u];
        printf(" AD(type=0x%02X,len=%u,val=", t, (unsigned)(l - 1u));
        for (i = 0u; i < (size_t)(l - 1u); i++)
            printf("%02X", ad[pos + 2u + i]);
        if ((t == 0x08u || t == 0x09u) && l > 1u) {
            printf(",name=");
            for (i = 0u; i < (size_t)(l - 1u); i++) {
                uint8_t c = ad[pos + 2u + i];
                printf("%c", (c >= 32u && c <= 126u) ? (char)c : '.');
            }
        }
        printf(")");
        pos += 1u + l;
    }
}

/*
 * Function: score_combo_parser
 * Purpose : Evaluate one IQ mapping/phase candidate using real parser statistics.
 * Params  : buf            - Captured sample buffer.
 *           words          - Number of int16 words.
 *           i_index        - I lane index in stride.
 *           q_index        - Q lane index in stride.
 *           invert_metric  - Whether to invert discriminator sign.
 *           symbol_phase   - Initial symbol phase.
 *           sync_hits      - Optional output sync count.
 *           candidate_hits - Optional output candidate frame count.
 *           crc_ok_hits    - Optional output CRC-pass count.
 * Return  : Weighted score (higher is better).
 */
static uint32_t score_combo_parser(const int16_t *buf, size_t words,
                                   uint8_t i_index, uint8_t q_index,
                                   bool invert_metric, uint8_t symbol_phase,
                                   uint32_t *sync_hits,
                                   uint32_t *candidate_hits,
                                   uint32_t *crc_ok_hits)
{
    ble_rx_port_t t;
    if (ble_rx_port_init(&t, BLE_SAMPLE_RATE_HZ, BLE_SYMBOL_RATE_HZ,
                         BLE_CHANNEL, true, NULL, NULL) < 0)
        return 0u;

    t.invert_metric = invert_metric;
    t.symbol_phase = symbol_phase;
    ble_rx_port_reset(&t);
    ble_rx_port_process_iq_i16_strided(&t, buf, words, i_index, q_index,
                                       BLE_DMA_STRIDE_WORDS);

    if (sync_hits)
        *sync_hits = t.sync_hits;
    if (candidate_hits)
        *candidate_hits = t.candidate_frames;
    if (crc_ok_hits)
        *crc_ok_hits = t.crc_ok_frames;

    return t.crc_ok_frames * 1000u + t.candidate_frames * 20u + t.sync_hits;
}

/*
 * Function: probe_combo
 * Purpose : Quickly estimate sync likelihood for one IQ candidate.
 * Params  : buf           - Captured sample buffer.
 *           words         - Number of int16 words.
 *           i_index       - I lane index in stride.
 *           q_index       - Q lane index in stride.
 *           invert_metric - Whether to invert discriminator sign.
 *           symbol_phase  - Initial symbol phase.
 *           preamble_hits - Output preamble hit counter.
 *           aa_hits       - Output access-address hit counter.
 * Return  : None.
 * Principle: Uses lightweight hard slicing and window matching to rank
 *            possible IQ/phase combinations before full parser run.
 */
static void probe_combo(const int16_t *buf, size_t words, uint8_t i_index,
                        uint8_t q_index, bool invert_metric,
                        uint8_t symbol_phase, uint32_t *preamble_hits,
                        uint32_t *aa_hits)
{
    size_t n;
    uint8_t byte = 0u;
    uint8_t bits = 0u;
    uint8_t win[BLE_SYNC_REPORT_BYTES];
    size_t win_len = 0u;
    float sps = (float)BLE_SAMPLE_RATE_HZ / (float)BLE_SYMBOL_RATE_HZ;
    float ph = (float)symbol_phase;
    int16_t pi = 0;
    int16_t pq = 0;
    bool have_prev = false;

    *preamble_hits = 0u;
    *aa_hits = 0u;
    if (sps < 1.0f)
        sps = 1.0f;

    for (n = 0; n + BLE_DMA_STRIDE_WORDS <= words; n += BLE_DMA_STRIDE_WORDS) {
        int16_t i = buf[n + i_index];
        int16_t q = buf[n + q_index];
        float metric;
        uint8_t bit;

        if (!have_prev) {
            pi = i;
            pq = q;
            have_prev = true;
            continue;
        }

        metric = (float)i * (float)pq - (float)q * (float)pi;
        pi = i;
        pq = q;
        if (invert_metric)
            metric = -metric;

        ph += 1.0f;
        if (ph < sps) {
            continue;
        }
        ph -= sps;

        bit = (metric >= 0.0f) ? 1u : 0u;
        byte |= (uint8_t)(bit << bits);
        bits++;

        if (bits == 8u) {
            if (win_len < BLE_SYNC_REPORT_BYTES) {
                win[win_len++] = byte;
            } else {
                memmove(win, win + 1u, BLE_SYNC_REPORT_BYTES - 1u);
                win[BLE_SYNC_REPORT_BYTES - 1u] = byte;
            }

            if (byte == 0xAAu || byte == 0x55u)
                (*preamble_hits)++;

            if (win_len >= 5u) {
                uint8_t aa0 = win[win_len - 4u];
                uint8_t aa1 = win[win_len - 3u];
                uint8_t aa2 = win[win_len - 2u];
                uint8_t aa3 = win[win_len - 1u];
                bool pre = (win[win_len - 5u] == 0xAAu || win[win_len - 5u] == 0x55u);
                bool normal = (aa0 == 0xD6u && aa1 == 0xBEu && aa2 == 0x89u && aa3 == 0x8Eu);
                bool inv = (aa0 == 0x29u && aa1 == 0x41u && aa2 == 0x76u && aa3 == 0x71u);
                bool bitrev = (aa0 == 0x6Bu && aa1 == 0x7Du && aa2 == 0x91u && aa3 == 0x71u);
                bool bitrev_inv = (aa0 == 0x94u && aa1 == 0x82u && aa2 == 0x6Eu && aa3 == 0x8Eu);
                if (pre && (normal || inv || bitrev || bitrev_inv))
                    (*aa_hits)++;
            }

            byte = 0u;
            bits = 0u;
        }
    }

}

/*
 * Function: swap_bits8
 * Purpose : Reverse bit order in one byte.
 * Params  : v - Input byte.
 * Return  : Bit-reversed byte.
 */
static uint8_t swap_bits8(uint8_t v)
{
    v = (uint8_t)(((v & 0xF0u) >> 4) | ((v & 0x0Fu) << 4));
    v = (uint8_t)(((v & 0xCCu) >> 2) | ((v & 0x33u) << 2));
    v = (uint8_t)(((v & 0xAAu) >> 1) | ((v & 0x55u) << 1));
    return v;
}

/*
 * Function: advdata_valid_prefix
 * Purpose : Find valid LTV prefix length inside AD payload.
 * Params  : adv     - Pointer to AD payload.
 *           adv_len - AD payload length.
 * Return  : Prefix length that is LTV-consistent.
 */
static size_t advdata_valid_prefix(const uint8_t *adv, size_t adv_len)
{
    size_t pos = 0u;

    while (pos < adv_len) {
        uint8_t l = adv[pos];
        if (l == 0u)
            return pos + 1u;
        if (pos + 1u + l > adv_len)
            return pos;
        pos += 1u + l;
    }

    return adv_len;
}

/*
 * Function: adv_type_has_advdata
 * Purpose : Check whether a PDU type carries AdvA + AD payload.
 * Params  : pdu_type - Advertising PDU type.
 * Return  : true if type has AD payload, false otherwise.
 */
static bool adv_type_has_advdata(uint8_t pdu_type)
{
    return (pdu_type == 0x00u || pdu_type == 0x02u ||
            pdu_type == 0x04u || pdu_type == 0x06u);
}

/*
 * Function: find_local_name_ad
 * Purpose : Locate local name AD (0x08/0x09) in AD payload.
 * Params  : ad       - AD payload pointer.
 *           ad_len   - AD payload length.
 *           name_ptr - Output pointer to name bytes.
 *           name_len - Output name length.
 * Return  : true if found, false otherwise.
 */
static bool find_local_name_ad(const uint8_t *ad, size_t ad_len,
                               const uint8_t **name_ptr, size_t *name_len)
{
    size_t pos = 0u;

    while (pos + 1u < ad_len) {
        uint8_t l = ad[pos];
        uint8_t t;

        if (l == 0u)
            break;
        if (pos + 1u + l > ad_len)
            break;

        t = ad[pos + 1u];
        if ((t == 0x08u || t == 0x09u) && l >= 2u) {
            *name_ptr = &ad[pos + 2u];
            *name_len = (size_t)l - 1u;
            return true;
        }

        pos += 1u + l;
    }

    return false;
}

/*
 * Function: print_sync_hits
 * Purpose : Print lightweight sync probe counters for current IQ settings.
 * Params  : buf   - Sample buffer.
 *           words - Number of int16 words.
 * Return  : None.
 */
static void print_sync_hits(const int16_t *buf, size_t words)
{
    uint32_t preamble_hits;
    uint32_t aa_hits;

    probe_combo(buf, words, g_i_index, g_q_index, g_invert_metric,
                g_symbol_phase, &preamble_hits, &aa_hits);

    printf("sync_probe: preamble_hits=%" PRIu32 " aa_hits=%" PRIu32
           " (IQ=(%u,%u), inv=%u, phase=%u)\n",
           preamble_hits, aa_hits,
           g_i_index, g_q_index, g_invert_metric ? 1u : 0u, g_symbol_phase);
}

/*
 * Function: auto_select_iq_combo
 * Purpose : Auto-select best IQ lane, sign, and phase configuration.
 * Params  : buf   - Sample buffer.
 *           words - Number of int16 words.
 * Return  : None.
 * Principle: Brute-force candidates and rank by parser score + sync probes,
 *            then store best configuration into global runtime state.
 */
static void auto_select_iq_combo(const int16_t *buf, size_t words)
{
    static const uint8_t pairs[4][2] = {{0u, 1u}, {1u, 0u}, {2u, 3u}, {3u, 2u}};
    float sps_f = (float)BLE_SAMPLE_RATE_HZ / (float)BLE_SYMBOL_RATE_HZ;
    uint8_t sps;
    ble_combo_t best;
    uint32_t p;
    uint8_t pair_id;
    uint8_t inv;
    size_t used_words = words;

    best.i_index = 0u;
    best.q_index = 1u;
    best.invert_metric = false;
    best.symbol_phase = 0u;
    best.aa_hits = 0u;
    best.preamble_hits = 0u;

    if (sps_f < 1.0f)
        sps_f = 1.0f;
    sps = (uint8_t)sps_f;
    if (sps == 0u)
        sps = 1u;

    if (used_words > BLE_AUTO_SELECT_WORDS)
        used_words = BLE_AUTO_SELECT_WORDS;

    for (pair_id = 0u; pair_id < 4u; pair_id++) {
        for (inv = 0u; inv < 2u; inv++) {
            for (p = 0u; p < sps; p++) {
                uint32_t phits;
                uint32_t ahits;
                uint32_t shits;
                uint32_t chits;
                uint32_t crchits;
                uint32_t score;
                probe_combo(buf, used_words, pairs[pair_id][0], pairs[pair_id][1],
                            inv != 0u, (uint8_t)p, &phits, &ahits);

                score = score_combo_parser(buf, used_words,
                                           pairs[pair_id][0], pairs[pair_id][1],
                                           inv != 0u, (uint8_t)p,
                                           &shits, &chits, &crchits);
                score += ahits * 50u;

                if (score > (best.aa_hits * 50u + best.preamble_hits)) {
                    best.i_index = pairs[pair_id][0];
                    best.q_index = pairs[pair_id][1];
                    best.invert_metric = (inv != 0u);
                    best.symbol_phase = (uint8_t)p;
                    best.aa_hits = ahits + chits + crchits;
                    best.preamble_hits = phits + shits;
                }
            }
        }
    }

    g_i_index = best.i_index;
    g_q_index = best.q_index;
    g_invert_metric = best.invert_metric;
    g_symbol_phase = best.symbol_phase;
    g_last_i_index = g_i_index;
    g_last_q_index = g_q_index;
    g_last_invert_metric = g_invert_metric;
    g_last_symbol_phase = g_symbol_phase;

    printf("auto_select: IQ=(%u,%u) invert=%u phase=%u probe=%" PRIu32
           " score=%" PRIu32 "\n",
           g_i_index, g_q_index, g_invert_metric ? 1u : 0u, g_symbol_phase,
           best.preamble_hits, best.aa_hits);
}

/*
 * Function: ble_verbose_printer
 * Purpose : Packet callback that prints BLE frames in sniffer-like format.
 * Params  : ble_pdu - Parsed PDU bytes [header+payload+crc].
 *           len     - PDU length in bytes.
 *           ctx     - User context (unused).
 * Return  : None.
 * Principle: Validates CRC interpretation, optionally bit-reverses representation,
 *            then prints PDU type, address, AD list, and optional local name.
 */
static void ble_verbose_printer(const uint8_t *ble_pdu, size_t len, void *ctx)
{
    size_t i;
    size_t payload_len;
    uint8_t pdu0;
    uint8_t pdu1;
    uint8_t pdu0_sw;
    uint8_t pdu1_sw;
    uint8_t type_a;
    uint8_t type_b;
    uint8_t len_a;
    uint8_t len_b;
    uint8_t used_type;
    const uint8_t *adv;
    uint8_t crc_a[3];
    uint8_t crc_b[3];
    bool crc_ok_a = false;
    bool crc_ok_b = false;
    bool use_swapped = false;
    bool header_ok = false;
    bool data_ok = false;
    uint8_t adv_local[40];
    size_t adv_prefix;
    size_t print_len;
    const uint8_t *name_ptr = NULL;
    size_t name_len = 0u;
    bool has_name = false;
    uint8_t txadd;
    uint8_t rxadd;
    (void)ctx;
    g_pkt_count++;

    if (!ble_pdu || len < 2u)
        return;

    pdu0 = ble_pdu[0];
    pdu1 = ble_pdu[1];
    pdu0_sw = swap_bits8(pdu0);
    pdu1_sw = swap_bits8(pdu1);

    type_a = (uint8_t)(pdu0 & 0x0Fu);
    len_a = (uint8_t)(pdu1 & 0x3Fu);
    type_b = (uint8_t)(pdu0_sw & 0x0Fu);
    len_b = (uint8_t)(pdu1_sw & 0x3Fu);

    adv = ble_pdu + 2u;

    /* Try raw header interpretation first, then bit-reversed interpretation. */
    if (len_a <= 37u && len >= (size_t)(2u + len_a + 3u)) {
        bt_crc24(ble_pdu, 2u + len_a, crc_a);
        crc_ok_a = (crc_a[0] == ble_pdu[2u + len_a] &&
                    crc_a[1] == ble_pdu[2u + len_a + 1u] &&
                    crc_a[2] == ble_pdu[2u + len_a + 2u]);
    }

    if (len_b <= 37u && len >= (size_t)(2u + len_b + 3u)) {
        size_t j;
        uint8_t tmp[64];
        for (j = 0u; j < (size_t)(2u + len_b + 3u) && j < sizeof(tmp); j++)
            tmp[j] = swap_bits8(ble_pdu[j]);
        bt_crc24(tmp, 2u + len_b, crc_b);
        crc_ok_b = (crc_b[0] == tmp[2u + len_b] &&
                    crc_b[1] == tmp[2u + len_b + 1u] &&
                    crc_b[2] == tmp[2u + len_b + 2u]);
    }

    if (crc_ok_a && len_a <= 37u && len >= (size_t)(2u + len_a)) {
        payload_len = len_a;
        header_ok = true;
    } else if (crc_ok_b && len_b <= 37u && len >= (size_t)(2u + len_b)) {
        payload_len = len_b;
        use_swapped = true;
        header_ok = true;
    } else {
        payload_len = (len >= 5u) ? (len - 5u) : 0u;
    }

    /* Apply selected interpretation and run payload sanity checks. */
    if (header_ok && payload_len >= 8u) {
        size_t j;
        if (use_swapped) {
            for (j = 0; j < payload_len && j < sizeof(adv_local); j++)
                adv_local[j] = swap_bits8(ble_pdu[2u + j]);
            adv = adv_local;
        }

        used_type = use_swapped ? type_b : type_a;
        if (payload_len > 6u && adv_type_has_advdata(used_type)) {
            adv_prefix = advdata_valid_prefix(adv + 6u, payload_len - 6u);
            (void)adv_prefix;
            has_name = find_local_name_ad(adv + 6u, payload_len - 6u,
                                          &name_ptr, &name_len);
        }

        {
            uint8_t a0 = adv[0u];
            uint8_t a1 = adv[1u];
            uint8_t a2 = adv[2u];
            uint8_t a3 = adv[3u];
            uint8_t a4 = adv[4u];
            uint8_t a5 = adv[5u];
            if (!((a0 == a1) && (a1 == a2) && (a2 == a3) && (a3 == a4) && (a4 == a5)) &&
                !((a0 == 0u) && (a1 == 0u) && (a2 == 0u) && (a3 == 0u) && (a4 == 0u) && (a5 == 0u)) &&
                !((a0 == 0xFFu) && (a1 == 0xFFu) && (a2 == 0xFFu) && (a3 == 0xFFu) && (a4 == 0xFFu) && (a5 == 0xFFu))) {
                data_ok = true;
            }
        }
    }

    if (!(header_ok && data_ok))
        return;

    g_good_pkt_count++;

    print_len = payload_len;

    txadd = (uint8_t)(((use_swapped ? pdu0_sw : pdu0) >> 6) & 1u);
    rxadd = (uint8_t)((use_swapped ? pdu0_sw : pdu0) >> 7) & 1u;

    printf("[BLE][ch%u][pkt=%" PRIu32 "] %s len=%u txadd=%u rxadd=%u fmt=%s crc=ok\n",
           g_rx.ble_channel, g_pkt_count, adv_pdu_name(used_type),
           (unsigned)payload_len, txadd, rxadd,
           use_swapped ? "bitrev" : "raw");

    if (payload_len >= 6u) {
        printf("  AdvA: ");
        print_addr(adv);
        printf("\n");
    }

    if (payload_len > 6u && adv_type_has_advdata(used_type)) {
        printf("  AD:");
        print_ad_list(adv + 6u, payload_len - 6u);
        printf("\n");
    }

    printf("  RawPDU: ");
    for (i = 0u; i < print_len && (2u + i) < len; i++)
        printf("%02X ", adv[i]);
    printf("\n");

    if (has_name && name_ptr && name_len > 0u) {
        printf("  Name: ");
        for (i = 0u; i < name_len; i++) {
            uint8_t c = name_ptr[i];
            printf("%c", (c >= 32u && c <= 126u) ? (char)c : '.');
        }
        printf("\n");
    }
}

/*
 * Function: print_iq_stats
 * Purpose : Print min/max/average statistics for selected IQ lanes.
 * Params  : buf   - Sample buffer.
 *           words - Number of int16 words.
 * Return  : None.
 */
static void print_iq_stats(const int16_t *buf, size_t words)
{
    size_t n;
    size_t cnt = 0;
    int64_t sum_i = 0;
    int64_t sum_q = 0;
    int16_t min_i = 32767;
    int16_t max_i = -32768;
    int16_t min_q = 32767;
    int16_t max_q = -32768;

    for (n = 0; n + BLE_DMA_STRIDE_WORDS <= words; n += BLE_DMA_STRIDE_WORDS) {
        int16_t i = buf[n + g_i_index];
        int16_t q = buf[n + g_q_index];
        sum_i += i;
        sum_q += q;
        cnt++;
        if (i < min_i)
            min_i = i;
        if (i > max_i)
            max_i = i;
        if (q < min_q)
            min_q = q;
        if (q > max_q)
            max_q = q;
    }

    if (cnt == 0u) {
        printf("IQ stats: no samples\n");
        return;
    }

    printf("IQ stats: I[min=%d max=%d avg=%" PRIi64 "] Q[min=%d max=%d avg=%" PRIi64 "]\n",
           min_i, max_i, sum_i / (int64_t)cnt,
           min_q, max_q, sum_q / (int64_t)cnt);
}

/*
 * Function: ble_rx_service_init_once
 * Purpose : One-time initialization of BLE RX service and RF front-end setup.
 * Params  : None.
 * Return  : 0 on success, negative on failure.
 * Principle: Configure AD9361 clocks/LO, run one capture for IQ auto-select,
 *            then reset parser state and mark service initialized.
 */
static int32_t ble_rx_service_init_once(void)
{
    int32_t status;
    XTime now;

    if (g_service_inited)
        return 0;

    status = ble_rx_port_init(&g_rx, BLE_SAMPLE_RATE_HZ, BLE_SYMBOL_RATE_HZ,
                              BLE_CHANNEL, false,
                              ble_verbose_printer, NULL);
    if (status < 0)
        return status;

    g_dma_ctx.rx_dmac = rx_dmac;
    g_adv_idx = 0u;
    g_rx.ble_channel = g_adv_channels[g_adv_idx];
    g_rf_hz = ble_rx_channel_to_freq_hz(g_rx.ble_channel);
    g_hop_ticks = (COUNTS_PER_SECOND / 20);
    if (g_hop_ticks == 0u)
        g_hop_ticks = 1u;
    XTime_GetTime(&now);
    g_last_hop_tick = now;

    status = ad9361_set_rx_sampling_freq(ad9361_phy, BLE_SAMPLE_RATE_HZ);
    if (status < 0)
        return status;
    status = ad9361_set_rx_rf_bandwidth(ad9361_phy, 2000000u);
    if (status < 0)
        return status;
    status = ad9361_set_rx_lo_freq(ad9361_phy, g_rf_hz);
    if (status < 0)
        return status;

    status = ble_rx_port_dma_capture_and_process_strided(
        &g_rx,
        ble_adi_dma_capture,
        &g_dma_ctx,
        ble_adc_buffer,
        BLE_ADC_BUFFER_BYTES,
        500u,
        0u,
        1u,
        BLE_DMA_STRIDE_WORDS,
        ble_adi_cache_invalidate);
    if (status == 0)
        auto_select_iq_combo(ble_adc_buffer,
                             BLE_ADC_BUFFER_BYTES / sizeof(ble_adc_buffer[0]));

    g_rx.invert_metric = g_invert_metric;
    g_rx.symbol_phase = g_symbol_phase;
    ble_rx_port_reset(&g_rx);

    g_service_inited = true;
    printf("BLE service init: ch=%u freq=%" PRIu64
           "Hz, stride=%u words, IQ=(%u,%u), invert=%u, phase=%u, hop=20ms(37/38/39)\n",
           g_rx.ble_channel, g_rf_hz, BLE_DMA_STRIDE_WORDS,
           g_i_index, g_q_index, g_invert_metric ? 1u : 0u, g_symbol_phase);
    return 0;
}

/*
 * Function: ble_rx_service_start
 * Purpose : Start BLE RX service state machine.
 * Params  : Not used.
 * Return  : None.
 */
void ble_rx_service_start(double *param, char param_no)
{
	printf("BLE service starting!\n");
    int32_t status = ble_rx_service_init_once();
    if (status < 0) {
        printf("ble_rx_service_start failed: %" PRIi32 "\n", status);
        return;
    }

    if (!g_service_running) {
        g_service_running = true;
        printf("BLE service started\n");
    }
}

/*
 * Function: ble_rx_service_stop
 * Purpose : Stop BLE RX service and clear runtime states to defaults.
 * Params  : Not used.
 * Return  : None.
 */
void ble_rx_service_stop(double *param, char param_no)
{
    g_service_running = false;

    ble_rx_port_reset(&g_rx);
    memset(&g_rx, 0, sizeof(g_rx));
    g_dma_ctx.rx_dmac = NULL;

    g_service_inited = false;
    g_pkt_count = 0u;
    g_last_pkt_count = 0u;
    g_good_pkt_count = 0u;
    g_stall_periods = 0u;

    g_i_index = 0u;
    g_q_index = 1u;
    g_invert_metric = false;
    g_symbol_phase = 0u;

    g_adv_idx = 0u;
    g_rf_hz = 0u;
    g_last_hop_tick = 0u;
    g_hop_ticks = 0u;

    memset(ble_adc_buffer, 0, sizeof(ble_adc_buffer));

    printf("BLE service stopped and reset\n");
}

/*
 * Function: ble_rx_service_poll
 * Purpose : Execute one service iteration (hop channel + DMA capture + decode).
 * Params  : None.
 * Return  : None.
 * Principle: Called from main loop; performs time-based channel hopping every
 *            20 ms and continuously feeds DMA samples into BLE parser.
 */
void ble_rx_service_poll(void)
{
    int32_t status;
    XTime now;

    if (!g_service_running)
        return;

    /* Time-sliced hop among 37/38/39 to cover BLE advertising channels. */
//    XTime_GetTime(&now);
//    if ((now - g_last_hop_tick) >= g_hop_ticks) {
//        g_last_hop_tick = now;
//        g_adv_idx = (uint8_t)((g_adv_idx + 1u) % 3u);
//        g_rx.ble_channel = g_adv_channels[g_adv_idx];
//        g_rf_hz = ble_rx_channel_to_freq_hz(g_rx.ble_channel);
//        status = ad9361_set_rx_lo_freq(ad9361_phy, g_rf_hz);
//        if (status >= 0) {
//            printf("hop: ch=%u rx_lo=%" PRIu64 "Hz\n",
//                   g_rx.ble_channel, g_rf_hz);
//        }
//    }

    /* Capture one DMA block and decode selected IQ pair. */
    status = ble_rx_port_dma_capture_and_process_strided(
        &g_rx,
        ble_adi_dma_capture,
        &g_dma_ctx,
        ble_adc_buffer,
        BLE_ADC_BUFFER_BYTES,
        500u,
        g_i_index,
        g_q_index,
        BLE_DMA_STRIDE_WORDS,
        ble_adi_cache_invalidate);

    if (status < 0) {
        printf("BLE DMA capture error: %" PRIi32 "\n", status);
        return;
    }

    if ((g_rx.dma_loops % BLE_STATUS_PRINT_PERIOD) == 0u) {
        printf("run: loops=%" PRIu32 " samples=%" PRIu32
               " sync=%" PRIu32 " raw=%" PRIu32
               " candidates=%" PRIu32 " emitted=%" PRIu32
               " crc_ok=%" PRIu32 " crc_fail=%" PRIu32
               " packets=%" PRIu32 " good=%" PRIu32 " metric_abs=%" PRIu32 "\n",
               g_rx.dma_loops,
               g_rx.sample_count,
               g_rx.sync_hits,
               g_rx.raw_sync_frames,
               g_rx.candidate_frames,
               g_rx.emitted_frames,
               g_rx.crc_ok_frames,
               g_rx.crc_fail_frames,
               g_pkt_count,
               g_good_pkt_count,
               (uint32_t)(g_rx.sym_count ? (g_rx.metric_acc / (float)g_rx.sym_count) : 0.0f));
        print_iq_stats(ble_adc_buffer,
                       BLE_ADC_BUFFER_BYTES / sizeof(ble_adc_buffer[0]));
        print_sync_hits(ble_adc_buffer,
                        BLE_ADC_BUFFER_BYTES / sizeof(ble_adc_buffer[0]));

        if (g_pkt_count == g_last_pkt_count) {
            g_stall_periods++;

            if (g_stall_periods >= 5u) {
                auto_select_iq_combo(ble_adc_buffer,
                                     BLE_ADC_BUFFER_BYTES / sizeof(ble_adc_buffer[0]));
                g_rx.invert_metric = g_invert_metric;
                g_rx.symbol_phase = g_symbol_phase;
                ble_rx_port_reset(&g_rx);
                g_stall_periods = 0u;
                printf("reacquire: IQ=(%u,%u) invert=%u phase=%u\n",
                       g_i_index, g_q_index, g_invert_metric ? 1u : 0u,
                       g_symbol_phase);
            }
        } else {
            g_stall_periods = 0u;
        }
        g_last_pkt_count = g_pkt_count;
    }
}

/*
 * Function: ble_rx_run_example_forever
 * Purpose : Backward-compatible blocking runner.
 * Params  : None.
 * Return  : None.
 */
void ble_rx_run_example_forever(void)
{
    ble_rx_service_start(0 ,0);
    while (1)
        ble_rx_service_poll();
}
