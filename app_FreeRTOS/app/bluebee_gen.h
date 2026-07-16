#ifndef BLUEBEE_GEN_H_
#define BLUEBEE_GEN_H_

#include <stddef.h>
#include <stdint.h>

#define BLUEBEE_GEN_MAX_PAYLOAD_BYTES 46u
#define BLUEBEE_GEN_TX_LO_HZ          2480000000ULL

struct bluebee_gen_meta {
	const uint8_t *payload;
	uint32_t payload_len;
	const uint8_t *frame;
	uint32_t frame_len;
	const uint8_t *gfsk_bytes;
	uint32_t gfsk_bit_count;
	uint32_t gfsk_byte_count;
	const uint32_t *iq_words;
	uint32_t iq_word_count;
	uint32_t iq_byte_count;
	uint32_t air_us;
	uint32_t post_pad_us;
	uint8_t zigbee_projection_ok;
	uint8_t symbol_distance_min;
	uint8_t symbol_distance_max;
	uint64_t tx_lo_hz;
};

int32_t bluebee_gen_build_default(void);
int32_t bluebee_gen_build_payload(const uint8_t *payload, uint32_t payload_len);
const struct bluebee_gen_meta *bluebee_gen_get_last_meta(void);

#endif
