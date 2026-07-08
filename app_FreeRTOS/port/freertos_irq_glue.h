/*
 * FreeRTOS IRQ Glue — public declarations
 * See freertos_irq_glue.c for implementation details.
 */

#ifndef FREERTOS_IRQ_GLUE_H
#define FREERTOS_IRQ_GLUE_H

#include "xscugic.h"

/* Register the XScuGic instance so vApplicationIRQHandler can dispatch.
 * Called from hw_init() before vTaskStartScheduler(). */
void freertos_irq_set_gic_instance( XScuGic * gic );

/* Configure the Cortex-A9 Private Timer as the FreeRTOS tick source.
 * Called by configSETUP_TICK_INTERRUPT() macro during vTaskStartScheduler(). */
void vConfigureTickInterrupt( void );

#endif /* FREERTOS_IRQ_GLUE_H */
