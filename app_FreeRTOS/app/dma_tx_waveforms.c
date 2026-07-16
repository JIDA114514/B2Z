#include "dma_tx_waveforms.h"

#define BLE_EXADV_WAVEFORM_DEFINE_ARRAYS
#include "dma_tx_waveforms/dma_tx_ble_exadv_waveform_30_72M.h"
#include "dma_tx_waveforms/dma_tx_ble_waveform_30_72M.h"
#include "dma_tx_waveforms/dma_tx_bluebee_waveform.h"

extern const uint32_t zigbee_iq[14018] __attribute__((aligned(64)));

#define DMA_TX_FREQ_CH39_HZ 2480000000ULL

const struct dma_tx_waveform_desc
	g_dma_tx_waveforms[DMA_TX_WAVEFORM_COUNT] = {
	[DMA_TX_WAVEFORM_ZIGBEE] = {
		.name = "legacy zigbee",
		.data = zigbee_iq,
		.bytes = sizeof(zigbee_iq),
		.tx_lo_hz = DMA_TX_FREQ_CH39_HZ,
	},
	[DMA_TX_WAVEFORM_BLUEBEE] = {
		.name = "bluebee, BLE channel 39",
		.data = bluebee_zigbee_frame_iq,
		.bytes = sizeof(bluebee_zigbee_frame_iq),
		.tx_lo_hz = DMA_TX_FREQ_CH39_HZ,
	},
	[DMA_TX_WAVEFORM_EXADV_SECONDARY] = {
		.name = "exadv secondary",
		.data = ble_exadv_secondary_iq_ch3,
		.bytes = sizeof(ble_exadv_secondary_iq_ch3),
		.tx_lo_hz = DMA_TX_FREQ_CH39_HZ,
	},
	[DMA_TX_WAVEFORM_BLE_CH39] = {
		.name = "BLE legacy advertising ch39",
		.data = ble_iq_ch39,
		.bytes = sizeof(ble_iq_ch39),
		.tx_lo_hz = DMA_TX_FREQ_CH39_HZ,
	},
};
