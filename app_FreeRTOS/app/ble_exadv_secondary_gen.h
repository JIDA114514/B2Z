#ifndef BLE_EXADV_SECONDARY_GEN_H_
#define BLE_EXADV_SECONDARY_GEN_H_

#include <stdint.h>

#define BLE_EXADV_SECONDARY_GEN_TX_LO_HZ 2480000000ULL
#define B2Z_CONTROL_SECONDARY_CH3_TX_LO_HZ 2410000000ULL
#define B2Z_CONTROL_RF_SAME_CHANNEL 0u
#define B2Z_CONTROL_RF_STANDARD_CH3 1u
#define B2Z_CONTROL_RF_SEPARATE_CH3 2u
#define B2Z_CONTROL_SEPARATE_GAP_US 1000u
#define B2Z_CONTROL_DIAGNOSTIC_AUX_OFFSET_US 30000u
#define B2Z_CONTROL_STANDARD_AUX_OFFSET_US 300000u
#define BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES 46u
#define B2Z_CONTROL_RECORD_BYTES 35u
#define B2Z_CAPACITY_RECORD_BASE 36u
#define B2Z_CAPACITY_MAX_BLE_EXTRA 26u

struct b2z_control_packet {
	uint16_t run_id;
	uint32_t slot_index;
	uint32_t ref_tick_ms;
	uint16_t period_ms;
	uint32_t command_id;
	uint32_t execute_at_ms;
	uint32_t valid_until_ms;
	uint16_t ble_target;
	uint8_t ble_opcode;
	uint16_t ble_arg;
	uint16_t zigbee_target;
	uint8_t zigbee_opcode;
	uint16_t zigbee_arg;
};

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
	const uint8_t *ble_control_record;
	const uint32_t *primary_iq_words;
	uint32_t primary_iq_byte_count;
	uint32_t primary_air_us;
	uint8_t aux_ptr_channel;
	uint32_t aux_offset_us;
	uint8_t rf_mode;
	const uint8_t *primary_pdu;
	uint32_t primary_pdu_len;
	/* Mode 2: independent, unwhitened BlueBee waveform (not native O-QPSK). */
	const uint32_t *ieee_iq_words;
	uint32_t ieee_iq_byte_count;
	uint32_t ieee_air_us;
	uint32_t ble_control_record_len;
};

int32_t ble_exadv_secondary_gen_build_default(void);
int32_t ble_exadv_secondary_gen_build_payload(const uint8_t *payload,
					      uint32_t payload_len);
/* Legacy same-channel wrapper; AuxPtr remains diagnostic in this mode. */
int32_t ble_exadv_secondary_gen_build_control(
	const struct b2z_control_packet *packet);
int32_t ble_exadv_secondary_gen_build_control_mode(
	const struct b2z_control_packet *packet, uint8_t rf_mode);
/* v2 joint-only budget, checked before allocating/generating a waveform. */
int32_t b2z_capacity_budget(uint32_t ble_extra, uint32_t ieee_extra);
int32_t ble_exadv_secondary_gen_build_capacity(
    const struct b2z_control_packet *packet, uint32_t ble_extra, uint32_t ieee_extra);
const struct ble_exadv_secondary_gen_meta *
ble_exadv_secondary_gen_get_last_meta(void);

#endif
