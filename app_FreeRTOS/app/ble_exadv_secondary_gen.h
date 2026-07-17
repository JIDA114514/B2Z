#ifndef BLE_EXADV_SECONDARY_GEN_H_
#define BLE_EXADV_SECONDARY_GEN_H_

#include <stdint.h>

#define BLE_EXADV_SECONDARY_GEN_TX_LO_HZ 2480000000ULL
#define BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES 46u

struct ble_exadv_secondary_gen_meta {
	const uint8_t *zigbee_payload;
	uint32_t zigbee_payload_len;
	const uint8_t *zigbee_frame;
	uint32_t zigbee_frame_len;
	const uint8_t *bluebee_bytes;
	uint32_t bluebee_byte_count;
	const uint8_t *adv_data;
	uint32_t adv_data_len;
	const uint8_t *pdu;
	uint32_t pdu_len;
	const uint8_t *crc;
	uint32_t crc_len;
	const uint8_t *ll_payload;
	uint32_t ll_payload_len;
	const uint32_t *iq_words;
	uint32_t iq_word_count;
	uint32_t iq_byte_count;
	uint32_t air_us;
	uint32_t post_pad_us;
	uint32_t frame_time_us;
	uint32_t mapping_time_us;
	uint32_t gfsk_time_us;
	uint32_t total_time_us;
	uint32_t whitening_channel;
	uint64_t tx_lo_hz;
};

int32_t ble_exadv_secondary_gen_build_default(void);
int32_t ble_exadv_secondary_gen_build_payload(const uint8_t *payload,
					      uint32_t payload_len);
const struct ble_exadv_secondary_gen_meta *
ble_exadv_secondary_gen_get_last_meta(void);

#endif
