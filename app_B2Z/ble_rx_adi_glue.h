#ifndef BLE_RX_ADI_GLUE_H
#define BLE_RX_ADI_GLUE_H

#include <stdint.h>

struct axi_dmac;

typedef struct {
    struct axi_dmac *rx_dmac;
} ble_adi_dma_ctx_t;

int ble_adi_dma_capture(void *dma_ctx, void *dst, uint32_t bytes,
                        uint32_t timeout_ms);

void ble_adi_cache_invalidate(uintptr_t addr, uint32_t bytes);

#endif
