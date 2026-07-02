#include "ble_rx.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define BLE_PREAMBLE 0xAAu
#define BLE_ACCESS_ADDR_B0 0xD6u
#define BLE_ACCESS_ADDR_B1 0xBEu
#define BLE_ACCESS_ADDR_B2 0x89u
#define BLE_ACCESS_ADDR_B3 0x8Eu

#define BLE_PDU_HDR_LEN 2u
#define BLE_CRC_LEN 3u
#define BLE_MIN_FRAME_LEN (1u + 4u + BLE_PDU_HDR_LEN + 6u + BLE_CRC_LEN)

static uint8_t bt_swap_bits(uint8_t v);
static float fast_absf(float v);

/*
 * Function: ble_sync_detect
 * Purpose : Detect BLE preamble + access address with optional invert/bit-reverse variants.
 * Params  : p      - Pointer to 5 bytes [preamble + 4-byte access address].
 *           invert - Output flag, true if matched pattern is inverted.
 *           bitrev - Output flag, true if matched pattern is bit-reversed.
 * Return  : true if sync pattern matched, false otherwise.
 * Principle: Real sampled bitstreams may be polarity-inverted or bit-order reversed,
 *            so this matcher checks all combinations to improve lock robustness.
 */
static bool ble_sync_detect(const uint8_t *p, bool *invert, bool *bitrev)
{
    static const uint8_t aa[4] = {
        BLE_ACCESS_ADDR_B0,
        BLE_ACCESS_ADDR_B1,
        BLE_ACCESS_ADDR_B2,
        BLE_ACCESS_ADDR_B3,
    };
    uint8_t inv;
    uint8_t rev;
    size_t i;

    if (!p)
        return false;

    if (!(p[0] == 0xAAu || p[0] == 0x55u))
        return false;

    for (rev = 0u; rev < 2u; rev++) {
        for (inv = 0u; inv < 2u; inv++) {
            bool match = true;
            for (i = 0; i < 4u; i++) {
                uint8_t b = aa[i];
                if (rev)
                    b = bt_swap_bits(b);
                if (inv)
                    b ^= 0xFFu;
                if (p[1u + i] != b) {
                    match = false;
                    break;
                }
            }
            if (match) {
                *invert = (inv != 0u);
                *bitrev = (rev != 0u);
                return true;
            }
        }
    }

    return false;
}

/*
 * Function: get_shifted_byte
 * Purpose : Extract one byte from a bit-shifted stream.
 * Params  : src      - Source byte stream.
 *           src_len  - Source length in bytes.
 *           byte_pos - Base byte index.
 *           bit_off  - Right shift offset [0..7].
 *           ok       - Output validity flag.
 * Return  : Shifted byte value; undefined if *ok=false.
 * Principle: BLE sync may not align on byte boundary after hard slicing,
 *            so bytes are reconstructed from adjacent source bytes.
 */
static uint8_t get_shifted_byte(const uint8_t *src, size_t src_len,
                                size_t byte_pos, uint8_t bit_off, bool *ok)
{
    if (byte_pos >= src_len) {
        *ok = false;
        return 0u;
    }

    if (bit_off == 0u)
        return src[byte_pos];

    if (byte_pos + 1u >= src_len) {
        *ok = false;
        return 0u;
    }

    return (uint8_t)((src[byte_pos] >> bit_off) |
                     (src[byte_pos + 1u] << (8u - bit_off)));
}

/*
 * Function: apply_sync_transform
 * Purpose : Apply bit-order and polarity normalization to one byte.
 * Params  : b      - Input byte.
 *           invert - Whether to invert all bits.
 *           bitrev - Whether to reverse bit order.
 * Return  : Transformed byte.
 */
static uint8_t apply_sync_transform(uint8_t b, bool invert, bool bitrev)
{
    if (bitrev)
        b = bt_swap_bits(b);
    if (invert)
        b ^= 0xFFu;
    return b;
}

/*
 * Function: bt_swap_bits
 * Purpose : Reverse bit order in one byte.
 * Params  : v - Input byte.
 * Return  : Bit-reversed byte.
 */
static uint8_t bt_swap_bits(uint8_t v)
{
    v = (uint8_t)(((v & 0xF0u) >> 4) | ((v & 0x0Fu) << 4));
    v = (uint8_t)(((v & 0xCCu) >> 2) | ((v & 0x33u) << 2));
    v = (uint8_t)(((v & 0xAAu) >> 1) | ((v & 0x55u) << 1));
    return v;
}

static float fast_absf(float v)
{
    return (v < 0.0f) ? -v : v;
}

static void ble_fir_iq_i16(ble_rx_port_t *rx, int16_t i, int16_t q,
                           float *out_i, float *out_q)
{
    uint8_t t;
    float acc_i = 0.0f;
    float acc_q = 0.0f;

    if (!rx || !out_i || !out_q) {
        return;
    }

    rx->fir_state_i[rx->fir_index] = (float)i;
    rx->fir_state_q[rx->fir_index] = (float)q;
    rx->fir_index++;
    if (rx->fir_index >= BLE_FIR_TAP_COUNT)
        rx->fir_index = 0u;

    for (t = 0u; t < BLE_FIR_TAP_COUNT; t++) {
        uint8_t idx = (uint8_t)((rx->fir_index + BLE_FIR_TAP_COUNT - 1u - t) % BLE_FIR_TAP_COUNT);
        acc_i += rx->fir_taps[t] * rx->fir_state_i[idx];
        acc_q += rx->fir_taps[t] * rx->fir_state_q[idx];
    }

    *out_i = acc_i;
    *out_q = acc_q;
}

static bool ble_decim_iq_i16(ble_rx_port_t *rx, int16_t i, int16_t q,
                             int16_t *out_i, int16_t *out_q)
{
    uint8_t t;
    float acc_i;
    float acc_q;

    float prev_i;
    float prev_q;
    float curr_i;
    float curr_q;
    float frac;

    if (!rx || !out_i || !out_q)
        return false;

    curr_i = (float)i;
    curr_q = (float)q;
    rx->decim_lp_i += rx->decim_lp_alpha * (curr_i - rx->decim_lp_i);
    rx->decim_lp_q += rx->decim_lp_alpha * (curr_q - rx->decim_lp_q);
    curr_i = rx->decim_lp_i;
    curr_q = rx->decim_lp_q;

    rx->fir_state_i[rx->fir_index] = curr_i;
    rx->fir_state_q[rx->fir_index] = curr_q;
    rx->fir_index++;
    if (rx->fir_index >= BLE_FIR_TAP_COUNT)
        rx->fir_index = 0u;

    rx->fir_decim_count++;
    if (rx->fir_decim_count < 4u) {
        return false;
    }
    rx->fir_decim_count = 0u;

    acc_i = 0.0f;
    acc_q = 0.0f;
    for (t = 0u; t < BLE_FIR_TAP_COUNT; t++) {
        uint8_t idx = (uint8_t)((rx->fir_index + BLE_FIR_TAP_COUNT - 1u - t) % BLE_FIR_TAP_COUNT);
        acc_i += rx->fir_taps[t] * rx->fir_state_i[idx];
        acc_q += rx->fir_taps[t] * rx->fir_state_q[idx];
    }

    curr_i = acc_i;
    curr_q = acc_q;

    if (!rx->decim_have_prev) {
        rx->decim_prev_i = (int16_t)curr_i;
        rx->decim_prev_q = (int16_t)curr_q;
        rx->decim_have_prev = true;
        rx->decim_phase = 0.0f;
        return false;
    }

    prev_i = (float)rx->decim_prev_i;
    prev_q = (float)rx->decim_prev_q;

    rx->decim_phase += 1.0f;
    if (rx->decim_phase >= rx->decim_step) {
        float overshoot = rx->decim_phase - rx->decim_step;
        rx->decim_phase = overshoot;
        frac = 1.0f - overshoot;
        if (frac < 0.0f)
            frac = 0.0f;
        if (frac > 1.0f)
            frac = 1.0f;
        *out_i = (int16_t)(prev_i + frac * (curr_i - prev_i));
        *out_q = (int16_t)(prev_q + frac * (curr_q - prev_q));
        rx->decim_prev_i = (int16_t)curr_i;
        rx->decim_prev_q = (int16_t)curr_q;
        return true;
    }

    rx->decim_prev_i = (int16_t)curr_i;
    rx->decim_prev_q = (int16_t)curr_q;
    return false;
}

/*
 * Function: ble_channel_to_data_idx
 * Purpose : Convert BLE logical channel number to whitening data index.
 * Params  : ch - BLE channel number (0..39).
 * Return  : Whitening index used by LFSR init.
 */
uint8_t ble_channel_to_data_idx(uint8_t ch)
{
    if (ch == 37u)
        return 0u;
    if (ch <= 10u)
        return (uint8_t)(ch + 1u);
    if (ch == 38u)
        return 12u;
    if (ch <= 36u)
        return (uint8_t)(ch + 2u);
    return 39u;
}

/*
 * Function: ble_rx_channel_to_freq_hz
 * Purpose : Convert BLE channel number to RF center frequency.
 * Params  : ble_channel - BLE channel number (0..39).
 * Return  : Frequency in Hz.
 */
uint64_t ble_rx_channel_to_freq_hz(uint8_t ble_channel)
{
    uint8_t idx = ble_channel_to_data_idx(ble_channel);
    return 2402000000ULL + (uint64_t)idx * 2000000ULL;
}

/*
 * Function: bt_whiten
 * Purpose : Whiten/de-whiten BLE payload/header bytes using channel-dependent LFSR.
 * Params  : in     - Input bytes.
 *           len    - Byte length.
 *           ch_idx - Whitening channel index.
 *           out    - Output bytes.
 * Return  : Processed byte count.
 * Principle: BLE whitening is XOR with PN sequence; receiver regenerates PN
 *            from channel index and applies same XOR to recover original bits.
 */
size_t bt_whiten(const uint8_t *in, size_t len, uint8_t ch_idx, uint8_t *out)
{
    size_t n;
    uint8_t lfsr = (uint8_t)(bt_swap_bits(ch_idx) | 0x02u);

    for (n = 0; n < len; n++) {
        uint8_t d = bt_swap_bits(in[n]);
        uint8_t mask;

        for (mask = 0x80u; mask != 0u; mask >>= 1) {
            if (lfsr & 0x80u) {
                lfsr ^= 0x11u;
                d ^= mask;
            }
            lfsr <<= 1;
        }

        out[n] = bt_swap_bits(d);
    }

    return len;
}

/*
 * Function: bt_crc24
 * Purpose : Compute BLE 24-bit CRC for PDU header+payload.
 * Params  : data   - Input bytes.
 *           length - Byte count.
 *           out    - Output CRC bytes [3].
 * Return  : None.
 * Principle: Implements BLE bit-serial CRC with init 0x555555 and polynomial
 *            equivalent taps used by advertising channels.
 */
void bt_crc24(const uint8_t *data, size_t length, uint8_t out[3])
{
    size_t i;
    out[0] = 0x55u;
    out[1] = 0x55u;
    out[2] = 0x55u;

    for (i = 0; i < length; i++) {
        uint8_t d = data[i];
        uint8_t b;
        for (b = 0; b < 8u; b++) {
            uint8_t t = (uint8_t)((out[0] >> 7) & 1u);  //取crc最高位

            out[0] <<= 1;               //crc整体左移
            if (out[1] & 0x80u)
                out[0] |= 1u;

            out[1] <<= 1;
            if (out[2] & 0x80u)
                out[1] |= 1u;

            out[2] <<= 1;

            if ((d & 1u) != t) {        //取当前数据最低位
                out[2] ^= 0x5Bu;        //BLE CRC24 poly:0x165B
                out[1] ^= 0x06u;
            }

            d >>= 1;
        }
    }

    out[0] = bt_swap_bits(out[0]);     //反转字节位序（BLE强制要求）
    out[1] = bt_swap_bits(out[1]);
    out[2] = bt_swap_bits(out[2]);
}

/*
 * Function: pdu_type_valid
 * Purpose : Validate advertising PDU type range.
 * Params  : t - PDU type nibble.
 * Return  : true if in supported range, false otherwise.
 */
static bool pdu_type_valid(uint8_t t)
{
    return t <= 0x06u;
}

/*
 * Function: consume_frame_buf
 * Purpose : Drop consumed bytes from frame assembly buffer.
 * Params  : rx       - Receiver context.
 *           consumed - Number of bytes to discard from head.
 * Return  : None.
 */
static void consume_frame_buf(ble_rx_port_t *rx, size_t consumed)
{
    size_t left;
    if (consumed >= rx->frame_buf_len) {
        rx->frame_buf_len = 0;
        return;
    }
    left = rx->frame_buf_len - consumed;
    //memmove支持重叠内存复制
    memmove(rx->frame_buf, rx->frame_buf + consumed, left);
    rx->frame_buf_len = left;
}

/*
 * Function: parse_frames
 * Purpose : Parse assembled hard-sliced bytes into BLE frames.
 * Params  : rx - Receiver context.
 * Return  : None.
 * Principle: Continuously searches sync word (with bit offset), normalizes
 *            bit polarity/order, de-whitens header/payload, validates length
 *            and CRC, then emits parsed PDU via callback.
 */
static void parse_frames(ble_rx_port_t *rx)
{
    uint8_t dewhite[260];
    uint8_t raw_in[260];
    size_t pos = 0;
    uint8_t ch_idx_a = ble_channel_to_data_idx(rx->ble_channel);
    uint8_t ch_idx_b = rx->ble_channel;

    //缓冲区长度大于最小帧长度就开始尝试解析BLE信号
    while (rx->frame_buf_len - pos >= BLE_MIN_FRAME_LEN + 1u) {
        size_t start;
        uint8_t bit_off;
        bool found = false;
        bool sync_invert = false;
        bool sync_bitrev = false;
        uint8_t hdr[2];
        uint8_t hdr_raw[2];
        uint8_t hdr_inv[2];
        uint8_t pdu_type;
        uint8_t payload_len;
        uint8_t used_ch_idx;
        size_t need;
        size_t src_need;
        size_t need_raw;
        size_t src_need_raw;
        uint8_t crc_calc[3];
        size_t pkt_start = 0;
        uint8_t pkt_off = 0;
        
        //搜索前导码和接入地址，考虑到可能的比特偏移，需要额外搜索
        for (start = pos; start + 5u <= rx->frame_buf_len; start++) {
            for (bit_off = 0u; bit_off < 8u; bit_off++) {
                uint8_t s[5];
                bool ok = true;
                size_t k;
                
                //遍历可能的比特偏移
                for (k = 0; k < 5u; k++)
                    s[k] = get_shifted_byte(rx->frame_buf, rx->frame_buf_len, start + k, bit_off, &ok);
                if (!ok)
                    continue;
                
                //检测前导码和接入地址是否存在
                if (ble_sync_detect(s, &sync_invert, &sync_bitrev)) {
                    pkt_start = start;
                    pkt_off = bit_off;
                    found = true;
                    break;
                }
            }
            if (found)
                break;
        }

        if (!found) {
            if (rx->frame_buf_len > 5u) {
                //清空缓冲区
                consume_frame_buf(rx, rx->frame_buf_len - 5u);
            }
            return;
        }

        rx->sync_hits++;

        {   
            //读取PDU header
            bool ok = true;
            raw_in[0] = apply_sync_transform(
                get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                 pkt_start + 5u, pkt_off, &ok),
                sync_invert, sync_bitrev);
            raw_in[1] = apply_sync_transform(
                get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                 pkt_start + 6u, pkt_off, &ok),
                sync_invert, sync_bitrev);
            if (!ok) {
                if (pkt_start > 0u)
                    consume_frame_buf(rx, pkt_start);
                return;
            }

            used_ch_idx = ch_idx_a;
            //解白化
            bt_whiten(raw_in, BLE_PDU_HDR_LEN, used_ch_idx, hdr);
        }

        pdu_type = (uint8_t)(hdr[0] & 0x0Fu);
        payload_len = (uint8_t)(hdr[1] & 0x3Fu);

        //信道A失败后尝试信道B解码
        if ((!pdu_type_valid(pdu_type) || payload_len > 37u) &&
            ch_idx_b != ch_idx_a) {
            used_ch_idx = ch_idx_b;
            bt_whiten(raw_in, BLE_PDU_HDR_LEN, used_ch_idx, hdr);
            pdu_type = (uint8_t)(hdr[0] & 0x0Fu);
            payload_len = (uint8_t)(hdr[1] & 0x3Fu);
        }
        
        //如果仍然失败，尝试反转比特
        if (!pdu_type_valid(pdu_type) || payload_len > 37u) {
            bool ok = true;
            hdr_raw[0] = apply_sync_transform(
                get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                 pkt_start + 5u, pkt_off, &ok),
                sync_invert, sync_bitrev);
            hdr_raw[1] = apply_sync_transform(
                get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                 pkt_start + 6u, pkt_off, &ok),
                sync_invert, sync_bitrev);
            if (ok) {
                hdr_inv[0] = (uint8_t)(hdr_raw[0] ^ 0xFFu);
                hdr_inv[1] = (uint8_t)(hdr_raw[1] ^ 0xFFu);
                pdu_type = (uint8_t)(hdr_raw[0] & 0x0Fu);
                payload_len = (uint8_t)(hdr_raw[1] & 0x3Fu);
                if (pdu_type_valid(pdu_type) && payload_len <= 37u) {
                    size_t i;
                    size_t nbytes = BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN;
                    need_raw = 1u + 4u + BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN;
                    src_need_raw = need_raw + (pkt_off ? 1u : 0u);
                    if (rx->frame_buf_len - pkt_start < src_need_raw) {
                        //如果发现当前缓冲区只有部分包，就继续读取
                        if (pkt_start > 0u)
                            consume_frame_buf(rx, pkt_start);
                        return;
                    }

                    raw_in[0] = hdr_raw[0];
                    raw_in[1] = hdr_raw[1];
                    for (i = 2u; i < nbytes; i++) {
                        raw_in[i] = apply_sync_transform(
                            get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                             pkt_start + 5u + i, pkt_off, &ok),
                            sync_invert, sync_bitrev);
                        if (!ok)
                            break;
                    }
                    if (!ok) {
                        if (pkt_start > 0u)
                            consume_frame_buf(rx, pkt_start);
                        return;
                    }

                    rx->raw_sync_frames++;
                    rx->emitted_frames++;
//                    if (rx->on_packet)
                    //此时包解析其实仍然失败了，只完成报头分析，输出以debug
//                        rx->on_packet(raw_in, nbytes, rx->on_packet_ctx);
                    consume_frame_buf(rx, pkt_start + src_need_raw);
                    pos = 0;
                    continue;
                }
            }
        }

        if (!pdu_type_valid(pdu_type) || payload_len > 37u) {
            pos = pkt_start + 1u;
            continue;
        }

        rx->candidate_frames++;

        need = 1u + 4u + BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN;
        src_need = need + (pkt_off ? 1u : 0u);
        if (rx->frame_buf_len - pkt_start < src_need) {
            //判断当前缓冲区内容是否足够解包
            if (pkt_start > 0u)
                consume_frame_buf(rx, pkt_start);
            return;
        }

        {
            size_t i;
            size_t nbytes = BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN;
            bool ok = true;
            for (i = 0; i < nbytes; i++) {
                uint8_t b = get_shifted_byte(rx->frame_buf, rx->frame_buf_len,
                                             pkt_start + 5u + i, pkt_off, &ok);
                if (!ok)
                    break;
                b = apply_sync_transform(b, sync_invert, sync_bitrev);
                raw_in[i] = b;
            }
            if (!ok) {
                if (pkt_start > 0u)
                    consume_frame_buf(rx, pkt_start);
                return;
            }
            bt_whiten(raw_in, nbytes, used_ch_idx, dewhite);
        }
        bt_crc24(dewhite, BLE_PDU_HDR_LEN + payload_len, crc_calc);

        if ((crc_calc[0] == dewhite[BLE_PDU_HDR_LEN + payload_len]) &&
            (crc_calc[1] == dewhite[BLE_PDU_HDR_LEN + payload_len + 1u]) &&
            (crc_calc[2] == dewhite[BLE_PDU_HDR_LEN + payload_len + 2u])) {
            rx->crc_ok_frames++;
            rx->emitted_frames++;
            if (rx->on_packet)
                rx->on_packet(dewhite, BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN,
                              rx->on_packet_ctx);
            consume_frame_buf(rx, pkt_start + src_need);
            pos = 0;
        } else {
            rx->crc_fail_frames++;
            if (rx->strict_crc) {
                pos = pkt_start + 1u;
            } else {
                rx->emitted_frames++;
                if (rx->on_packet)
                    rx->on_packet(dewhite,
                                  BLE_PDU_HDR_LEN + payload_len + BLE_CRC_LEN,
                                  rx->on_packet_ctx);
                consume_frame_buf(rx, pkt_start + src_need);
                pos = 0;
            }
        }
    }

    if (pos > 0)
        consume_frame_buf(rx, pos);
}

/*
 * Function: append_byte_and_parse
 * Purpose : Push one demodulated byte into parser FIFO and trigger parsing.
 * Params  : rx - Receiver context.
 *           b  - New byte.
 * Return  : None.
 */
static void append_byte_and_parse(ble_rx_port_t *rx, uint8_t b)
{
    if (rx->frame_buf_len >= sizeof(rx->frame_buf)) {
        //如果接收缓冲区满，就将后一半的数据搬移到前一半，覆盖原始数据
        consume_frame_buf(rx, rx->frame_buf_len / 2u);
    }
    rx->frame_buf[rx->frame_buf_len++] = b;
    if (rx->frame_buf_len >= BLE_MIN_FRAME_LEN)
        parse_frames(rx);
}

/*
 * Function: ble_rx_port_init
 * Purpose : Initialize BLE receiver context.
 * Params  : rx             - Receiver context output.
 *           sample_rate_hz - ADC sample rate.
 *           symbol_rate_hz - BLE symbol rate.
 *           ble_channel    - Initial BLE channel.
 *           strict_crc     - true: drop CRC-failed PDUs, false: emit fallback PDUs.
 *           on_packet      - Callback for emitted BLE PDU.
 *           on_packet_ctx  - User context for callback.
 * Return  : 0 on success, negative on invalid arguments.
 */
int ble_rx_port_init(ble_rx_port_t *rx, uint32_t sample_rate_hz,
                     uint32_t symbol_rate_hz, uint8_t ble_channel,
                     bool strict_crc, ble_packet_handler_t on_packet,
                     void *on_packet_ctx)
{
    float decim_rate_hz = 4000000.0f;
    if (!rx || symbol_rate_hz == 0u || sample_rate_hz < symbol_rate_hz)
        return -1;

    memset(rx, 0, sizeof(*rx));
    rx->sample_rate_hz = sample_rate_hz;
    rx->symbol_rate_hz = symbol_rate_hz;
    rx->ble_channel = ble_channel;
    rx->strict_crc = strict_crc;
    rx->samples_per_symbol = (float)sample_rate_hz / (float)symbol_rate_hz;
    if (rx->samples_per_symbol < 1.0f)
        rx->samples_per_symbol = 1.0f;
    rx->samples_per_symbol_decim = decim_rate_hz / (float)symbol_rate_hz;
    if (rx->samples_per_symbol_decim < 1.0f)
        rx->samples_per_symbol_decim = 1.0f;
    rx->decim_step = (float)sample_rate_hz / decim_rate_hz;
    if (rx->decim_step < 1.0f)
        rx->decim_step = 1.0f;
    rx->decim_phase = 0.0f;
    rx->decim_lp_alpha = 0.12f;
    rx->decim_lp_i = 0.0f;
    rx->decim_lp_q = 0.0f;
    rx->decim_have_prev = false;
    rx->decim_prev_i = 0;
    rx->decim_prev_q = 0;
    {
        static const float taps[BLE_FIR_TAP_COUNT] = {
            0.02f, 0.05f, 0.08f, 0.12f, 0.46f,
            0.12f, 0.08f, 0.05f, 0.02f
        };
        memcpy(rx->fir_taps, taps, sizeof(taps));
    }
    memset(rx->fir_state_i, 0, sizeof(rx->fir_state_i));
    memset(rx->fir_state_q, 0, sizeof(rx->fir_state_q));
    rx->fir_index = 0u;
    rx->fir_decim_count = 0u;
    rx->timing_offset = 0.0f;
    rx->timing_mu = 0.0001f;
    rx->elg_early_sum = 0.0f;
    rx->elg_late_sum = 0.0f;
    rx->elg_err_sum = 0.0f;
    rx->elg_err_idx = 0u;
    rx->elg_err_count = 0u;
    rx->elg_sample_count = 0u;
    memset(rx->elg_err_hist, 0, sizeof(rx->elg_err_hist));
    memset(rx->elg_samples, 0, sizeof(rx->elg_samples));
    rx->symbol_phase = 0u;
    rx->invert_metric = false;
    rx->on_packet = on_packet;
    rx->on_packet_ctx = on_packet_ctx;

    return 0;
}

/*
 * Function: ble_rx_port_reset
 * Purpose : Reset runtime demod/parser states while keeping configuration.
 * Params  : rx - Receiver context.
 * Return  : None.
 */
void ble_rx_port_reset(ble_rx_port_t *rx)
{
    if (!rx)
        return;
    rx->have_prev = false;
    rx->prev_i = 0;
    rx->prev_q = 0;
    rx->prev_i_f = 0.0f;
    rx->prev_q_f = 0.0f;
    rx->prev_i_f = 0.0f;
    rx->prev_q_f = 0.0f;
    rx->sample_count = 0;
    rx->phase_acc = 0.0f;
    rx->phase_acc = (float)rx->symbol_phase;
    rx->timing_offset = 0.0f;
    rx->samples_per_symbol_decim = (rx->samples_per_symbol / (rx->decim_step > 0.0f ? rx->decim_step : 1.0f));
    if (rx->samples_per_symbol_decim < 1.0f)
        rx->samples_per_symbol_decim = 1.0f;
    rx->decim_phase = 0.0f;
    rx->decim_lp_i = 0.0f;
    rx->decim_lp_q = 0.0f;
    rx->decim_lp_alpha = 0.12f;
    rx->decim_have_prev = false;
    rx->decim_prev_i = 0;
    rx->decim_prev_q = 0;
    {
        static const float taps[BLE_FIR_TAP_COUNT] = {
            0.02f, 0.05f, 0.08f, 0.12f, 0.46f,
            0.12f, 0.08f, 0.05f, 0.02f
        };
        memcpy(rx->fir_taps, taps, sizeof(taps));
    }
    memset(rx->fir_state_i, 0, sizeof(rx->fir_state_i));
    memset(rx->fir_state_q, 0, sizeof(rx->fir_state_q));
    rx->fir_index = 0u;
    rx->fir_decim_count = 0u;
    rx->elg_early_sum = 0.0f;
    rx->elg_late_sum = 0.0f;
    rx->elg_err_sum = 0.0f;
    rx->elg_err_idx = 0u;
    rx->elg_err_count = 0u;
    rx->elg_sample_count = 0u;
    rx->elg_early_sum = 0.0f;
    rx->elg_late_sum = 0.0f;
    rx->elg_err_sum = 0.0f;
    memset(rx->elg_err_hist, 0, sizeof(rx->elg_err_hist));
    memset(rx->elg_samples, 0, sizeof(rx->elg_samples));
    rx->sym_metric_sum = 0.0f;
    rx->metric_acc = 0.0f;
    rx->sym_count = 0;
    rx->bit_acc = 0;
    rx->bit_count = 0;
    rx->frame_buf_len = 0;
}

/*
 * Function: ble_rx_port_process_iq_i16
 * Purpose : Demodulate contiguous I/Q pairs and feed frame parser.
 * Params  : rx            - Receiver context.
 *           iq            - Interleaved int16 I,Q,I,Q... samples.
 *           iq_pair_count - Number of IQ pairs.
 * Return  : None.
 * Principle: Uses differential phase discriminator metric I[n]*Q[n-1]-Q[n]*I[n-1],
 *            integrates over one symbol interval, hard-slices to bits, packs bytes.
 */
void ble_rx_port_process_iq_i16(ble_rx_port_t *rx, const int16_t *iq,
                                size_t iq_pair_count)
{
    size_t k;
    if (!rx || !iq)
        return;

    for (k = 0; k < iq_pair_count; k++) {
        int16_t i = iq[2u * k + 0u];
        int16_t q = iq[2u * k + 1u];
        float metric;
        uint8_t bit;

        if (!rx->have_prev) {
            rx->prev_i = i;
            rx->prev_q = q;
            rx->have_prev = true;
            continue;
        }
        
        //差分正交解调：相位差=当前IQ * 前一个IQ共轭的虚部(复指数相乘的等价运算)
        metric = (float)i * (float)rx->prev_q - (float)q * (float)rx->prev_i;
        rx->prev_i = i;
        rx->prev_q = q;

        if (rx->invert_metric)
            metric = -metric;

        if (metric >= 0.0f)
            rx->metric_acc += metric;
        else
            rx->metric_acc -= metric;
        rx->sym_metric_sum += metric;       //判决指标
        rx->phase_acc += 1.0f;
        rx->sample_count++;

        if (rx->phase_acc >= rx->samples_per_symbol) {
            bit = (rx->sym_metric_sum >= 0.0f) ? 1u : 0u;
            rx->phase_acc -= (float)rx->samples_per_symbol;
            rx->bit_acc |= (uint8_t)(bit << rx->bit_count);
            rx->bit_count++;
            rx->sym_metric_sum = 0.0f;

            if (rx->bit_count == 8u) {
                rx->sym_count += 8u;
                append_byte_and_parse(rx, rx->bit_acc);
                rx->bit_acc = 0u;
                rx->bit_count = 0u;
            }
        }
    }
}

void ble_rx_port_process_iq_i16_gardner(ble_rx_port_t *rx, const int16_t *iq,
                                        size_t iq_pair_count)
{
    size_t k;
    if (!rx || !iq)
        return;

    for (k = 0; k < iq_pair_count; k++) {
        int16_t i = iq[2u * k + 0u];
        int16_t q = iq[2u * k + 1u];
        float metric;
        uint8_t bit;
        float i_f;
        float q_f;
        float tmp_i;
        float tmp_q;

        ble_fir_iq_i16(rx, i, q, &i_f, &q_f);
        tmp_i = i_f;
        tmp_q = q_f;

        if (!rx->have_prev) {
            rx->prev_i_f = tmp_i;
            rx->prev_q_f = tmp_q;
            rx->have_prev = true;
            continue;
        }

        metric = tmp_i * rx->prev_q_f - tmp_q * rx->prev_i_f;
        rx->prev_i_f = tmp_i;
        rx->prev_q_f = tmp_q;

        if (rx->invert_metric)
            metric = -metric;

        if (metric >= 0.0f)
            rx->metric_acc += metric;
        else
            rx->metric_acc -= metric;

        rx->sym_metric_sum += metric;
        rx->phase_acc += 1.0f;
        rx->sample_count++;

        if (rx->phase_acc >= rx->samples_per_symbol) {
            bit = (rx->sym_metric_sum >= 0.0f) ? 1u : 0u;
            rx->phase_acc -= (float)rx->samples_per_symbol;
            rx->bit_acc |= (uint8_t)(bit << rx->bit_count);
            rx->bit_count++;
            rx->sym_metric_sum = 0.0f;

            if (rx->bit_count == 8u) {
                rx->sym_count += 8u;
                append_byte_and_parse(rx, rx->bit_acc);
                rx->bit_acc = 0u;
                rx->bit_count = 0u;
            }
        }

    }
}

/*
 * Function: ble_rx_port_process_iq_i16_strided
 * Purpose : Demodulate selected IQ lanes from multi-channel DMA layout.
 * Params  : rx                - Receiver context.
 *           samples           - Raw sample words.
 *           sample_word_count - Number of int16 words.
 *           i_index           - I index inside one stride group.
 *           q_index           - Q index inside one stride group.
 *           stride_words      - Words per group.
 * Return  : None.
 */
void ble_rx_port_process_iq_i16_strided(ble_rx_port_t *rx,
                                        const int16_t *samples,
                                        size_t sample_word_count,
                                        uint8_t i_index,
                                        uint8_t q_index,
                                        uint8_t stride_words)
{
    size_t pos;
    int16_t pair[2];

    if (!rx || !samples || stride_words == 0u)
        return;
    if (i_index >= stride_words || q_index >= stride_words)
        return;

    for (pos = 0; pos + stride_words <= sample_word_count; pos += stride_words) {
        pair[0] = samples[pos + i_index];
        pair[1] = samples[pos + q_index];
        ble_rx_port_process_iq_i16_gardner(rx, pair, 1u);
    }
}

/*
 * Function: ble_rx_port_default_printer
 * Purpose : Basic packet callback for debug printing.
 * Params  : ble_pdu - Parsed BLE PDU bytes [header+payload+crc].
 *           len     - PDU length in bytes.
 *           ctx     - Unused user context.
 * Return  : None.
 */
void ble_rx_port_default_printer(const uint8_t *ble_pdu, size_t len, void *ctx)
{
    size_t i;
    (void)ctx;
    if (!ble_pdu || len < 8u)
        return;

    printf("BLE pdu type=0x%02X mac=", ble_pdu[0] & 0x0Fu);
    for (i = 0; i < 6u; i++)
        printf("%02X", ble_pdu[7u - i]);
    printf(" data=");
    for (i = 8u; i < len; i++)
        printf("%02X ", ble_pdu[i]);
    printf("\n");
}

/*
 * Function: ble_rx_port_dma_capture_and_process_strided
 * Purpose : Capture one DMA block and process selected IQ lanes from stride layout.
 * Params  : rx               - Receiver context.
 *           dma_capture      - Platform DMA capture callback.
 *           dma_ctx          - DMA callback context.
 *           adc_buf          - Destination buffer for samples.
 *           adc_bytes        - Capture bytes.
 *           timeout_ms       - DMA timeout.
 *           i_index          - I index inside stride.
 *           q_index          - Q index inside stride.
 *           stride_words     - Words per stride group.
 *           cache_invalidate - Optional cache invalidate callback.
 * Return  : 0 on success, negative on failure.
 */
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
    void (*cache_invalidate)(uintptr_t addr, uint32_t bytes))
{
    int status;

    if (!rx || !dma_capture || !adc_buf || adc_bytes == 0u)
        return -1;

    status = dma_capture(dma_ctx, adc_buf, adc_bytes, timeout_ms);
    if (status < 0)
        return status;
    rx->dma_loops++;

    if (cache_invalidate)
        cache_invalidate((uintptr_t)adc_buf, adc_bytes);

    ble_rx_port_process_iq_i16_strided(rx, (const int16_t *)adc_buf,
                                       (size_t)adc_bytes / 2u,
                                       i_index, q_index, stride_words);

    return 0;
}
