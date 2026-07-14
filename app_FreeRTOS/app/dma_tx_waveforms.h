#ifndef DMA_TX_WAVEFORMS_H_
#define DMA_TX_WAVEFORMS_H_

#include <stdint.h>
#include <stddef.h>

enum dma_tx_waveform_id {
	DMA_TX_WAVEFORM_ZIGBEE = 0,
	DMA_TX_WAVEFORM_BLUEBEE,
	DMA_TX_WAVEFORM_EXADV_SECONDARY,
	DMA_TX_WAVEFORM_COUNT
};

struct dma_tx_waveform_desc {
	const char *name;
	const uint32_t *data;
	size_t bytes;
	uint64_t tx_lo_hz;
};

extern const struct dma_tx_waveform_desc
	g_dma_tx_waveforms[DMA_TX_WAVEFORM_COUNT];

#endif
