#include "ble_rx_adi_glue.h"

#include <stdbool.h>

#include "axi_dmac.h"
#include "app_config.h"

#ifdef XILINX_PLATFORM
#include <xil_cache.h>
#endif

/*
 * Function: ble_adi_dma_capture
 * Purpose : Start one RX DMA transfer and wait for completion.
 * Params  : dma_ctx    - Pointer to ble_adi_dma_ctx_t, must contain valid rx_dmac.
 *           dst        - Destination DDR buffer for ADC samples.
 *           bytes      - Transfer length in bytes.
 *           timeout_ms - Completion timeout in milliseconds.
 * Return  : 0 on success, negative value on error.
 */
int ble_adi_dma_capture(void *dma_ctx, void *dst, uint32_t bytes,
                        uint32_t timeout_ms)
{
    uint32_t status;
    struct axi_dma_transfer transfer;
    ble_adi_dma_ctx_t *ctx = (ble_adi_dma_ctx_t *)dma_ctx;

    if (!ctx || !ctx->rx_dmac || !dst || bytes == 0u)
        return -1;

    /* Program a non-cyclic memory write transfer from ADC DMA to DDR. */
    transfer.size = bytes;
    transfer.transfer_done = false;
    transfer.cyclic = NO;
    transfer.src_addr = 0u;
    transfer.dest_addr = (uint32_t)(uintptr_t)dst;

    /* Submit descriptor then block until hardware reports completion. */
    status = axi_dmac_transfer_start(ctx->rx_dmac, &transfer);
    if (status < 0)
        return (int)status;

    status = axi_dmac_transfer_wait_completion(ctx->rx_dmac, timeout_ms);
    if (status < 0)
        return (int)status;

    return 0;
}

/*
 * Function: ble_adi_cache_invalidate
 * Purpose : Invalidate CPU cache for DMA-written memory region.
 * Params  : addr  - Buffer start address.
 *           bytes - Buffer size in bytes.
 * Return  : None.
 */
void ble_adi_cache_invalidate(uintptr_t addr, uint32_t bytes)
{
#ifdef XILINX_PLATFORM
    Xil_DCacheInvalidateRange(addr, bytes);
#else
    (void)addr;
    (void)bytes;
#endif
}
