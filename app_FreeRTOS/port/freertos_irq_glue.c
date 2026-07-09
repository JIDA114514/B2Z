/*
 * FreeRTOS IRQ Glue — bridges the FreeRTOS ARM_CA9 IRQ entry point
 * and the Xilinx SCU GIC driver.
 *
 * FreeRTOS_IRQ_Handler (portASM.S):
 *   1. Reads ICCIAR → interrupt ID
 *   2. Calls vApplicationIRQHandler(interrupt_id)  <-- we are here
 *   3. Writes ICCEOIR
 *
 * Because the assembly handler already reads ICCIAR and writes ICCEOIR,
 * we cannot call XScuGic_InterruptHandler() (which also reads ICCIAR).
 * Instead, we dispatch directly from the XScuGic handler table.
 */

/* FreeRTOS headers */
#include "FreeRTOS.h"
#include "task.h"

/* Xilinx headers */
#include "xscugic.h"
#include "xil_exception.h"

/* no-OS project */
#include "irq_extra.h"
#include "console.h"

/*-----------------------------------------------------------*/

/* GIC instance — set by xilinx_irq.c during hw_init() */
static XScuGic * g_gic_instance = NULL;

/* Incremented each time the tick ISR fires — visible to the monitor task
 * for confirming the timer interrupt is being serviced. */
volatile uint32_t g_tick_isr_count = 0UL;
volatile uint32_t g_tick_handler_return_count = 0UL;
volatile uint32_t g_context_restore_stage = 0UL;

/*-----------------------------------------------------------*/

void vFreeRTOSExceptionHandler( uint32_t ulExceptionId,
                                uint32_t ulLR,
                                uint32_t ulSPSR )
{
    char * pcName = "UNKNOWN";

    switch( ulExceptionId )
    {
        case 1U:
            pcName = "UNDEFINED";
            break;
        case 2U:
            pcName = "PREFETCH_ABORT";
            break;
        case 3U:
            pcName = "DATA_ABORT";
            break;
        case 4U:
            pcName = "FIQ";
            break;
        default:
            break;
    }

    console_print_unlocked( "\r\n[EXC] %s id=%d lr=%x spsr=%x restore_stage=%d\r\n",
                            pcName,
                            ( long ) ulExceptionId,
                            ( long ) ulLR,
                            ( long ) ulSPSR,
                            ( long ) g_context_restore_stage );

    __asm volatile ( "CPSID i" ::: "memory" );
    __asm volatile ( "DSB" ::: "memory" );
    __asm volatile ( "ISB" ::: "memory" );

    for( ; ; )
    {
        __asm volatile ( "NOP" );
    }
}

/*-----------------------------------------------------------*/

static void prvTickConfigError( char * pcMessage, uint32_t ulValue )
{
    const uint32_t ulTimerCtrlReg = 0xF8F00600UL + 0x08UL;

    *( volatile uint32_t * ) ulTimerCtrlReg = 0x00000000UL;

    console_print( "\r\n[ERR] vConfigureTickInterrupt: " );
    console_print( pcMessage );
    console_print( " value=%d\r\n", ( long ) ulValue );

    __asm volatile ( "CPSID i" ::: "memory" );
    __asm volatile ( "DSB" ::: "memory" );
    __asm volatile ( "ISB" ::: "memory" );

    for( ; ; )
    {
        __asm volatile ( "NOP" );
    }
}

/*-----------------------------------------------------------*/

void freertos_irq_set_gic_instance( XScuGic * gic )
{
    g_gic_instance = gic;
}

/*-----------------------------------------------------------*/

/*
 * Called from FreeRTOS_IRQ_Handler (portASM.S) with the interrupt ID
 * that was already read from ICCIAR.  The assembly wrapper handles
 * ICCEOIR write, context-save, and context-switch on exit.
 *
 * We look up the handler in XScuGic's table and call it directly —
 * we do NOT call XScuGic_InterruptHandler() because it would read
 * ICCIAR a second time (losing the interrupt).
 */
void vApplicationIRQHandler( uint32_t ulICCIAR )
{
    /*
     * The ID field is the low 10 bits of ICCIAR.
     * XSCUGIC_ACK_INTID_MASK = 0x3FF from xscugic_hw.h
     */
    const uint32_t interrupt_id = ulICCIAR & 0x3FFUL;

    /* Count tick interrupts for debug visibility */
    if( interrupt_id == 29U )
    {
        g_tick_isr_count++;
    }

    if( ( g_gic_instance != NULL ) &&
        ( interrupt_id < XSCUGIC_MAX_NUM_INTR_INPUTS ) )
    {
        XScuGic_VectorTableEntry * table =
            &( g_gic_instance->Config->HandlerTable[ interrupt_id ] );

        if( ( table != NULL ) && ( table->Handler != NULL ) )
        {
            table->Handler( table->CallBackRef );
        }
    }

    if( interrupt_id == 29U )
    {
        g_tick_handler_return_count++;
    }

    /*
     * Return to portASM.S which will:
     *  - Write ICCEOIR
     *  - Restore interrupt nesting count
     *  - Check ulPortYieldRequired and context-switch if needed
     */
}

/*-----------------------------------------------------------*/

/*
 * Called by xPortStartScheduler() via configSETUP_TICK_INTERRUPT()
 * to configure the Cortex-A9 Private Timer as the FreeRTOS tick source.
 *
 * Private Timer base: 0xF8F00600 (Zynq-7020)
 * Clock: CPU_CLK / 2 ≈ 333.33 MHz
 * Tick rate: 1000 Hz → Load = 333333
 * PPI: ID 29
 *
 * This function re-uses functionality from the FreeRTOS ARM_CA9 port
 * but adds the XScuGic registration layer.
 */
void vConfigureTickInterrupt( void )
{
    const uint32_t ulTimerBase      = 0xF8F00600UL;
    const uint32_t ulTimerLoad      = ( configCPU_CLOCK_HZ / 2UL ) / configTICK_RATE_HZ;
    const uint32_t ulTimerLoadReg   = ulTimerBase + 0x00UL;
    const uint32_t ulTimerCtrlReg   = ulTimerBase + 0x08UL;
    const uint32_t ulTimerIsrReg    = ulTimerBase + 0x0CUL;
    const uint32_t ulGicCpuPmrReg   = 0xF8F00100UL + 0x04UL;
    const uint8_t  ucTickPriority   = ( uint8_t ) ( configKERNEL_INTERRUPT_PRIORITY << portPRIORITY_SHIFT );
    int32_t        lStatus;
    uint8_t        ucReadPriority;
    uint8_t        ucReadTrigger;

    *( volatile uint32_t * ) ulGicCpuPmrReg = 0x000000FFUL;

    /* 1. Ensure timer is stopped before configuring */
    *( volatile uint32_t * ) ulTimerCtrlReg = 0x00000000UL;

    /* 2. Set the load value */
    *( volatile uint32_t * ) ulTimerLoadReg = ulTimerLoad;

    /* 3. Clear any pending interrupt */
    *( volatile uint32_t * ) ulTimerIsrReg = 0x00000001UL;

    /*
     * 4. Register FreeRTOS_Tick_Handler with XScuGic for PPI 29.
     *    The handler is defined in port.c and calls xTaskIncrementTick().
     */
    if( g_gic_instance == NULL )
    {
        prvTickConfigError( "g_gic_instance is NULL", 0U );
    }

    lStatus = XScuGic_Connect( g_gic_instance,
                               29U,
                               ( Xil_InterruptHandler ) FreeRTOS_Tick_Handler,
                               NULL );

    if( lStatus != 0 )
    {
        prvTickConfigError( "XScuGic_Connect failed", ( uint32_t ) lStatus );
    }

    /* Set tick interrupt to the lowest usable priority. */
    XScuGic_SetPriorityTriggerType( g_gic_instance,
                                    29U,
                                    ucTickPriority,
                                    0x01U );  /* level-sensitive, per GIC spec */

    XScuGic_GetPriorityTriggerType( g_gic_instance,
                                    29U,
                                    &ucReadPriority,
                                    &ucReadTrigger );

    if( ucReadPriority != ucTickPriority )
    {
        prvTickConfigError( "PPI29 priority verify failed", ucReadPriority );
    }

    /* Enable the PPI in the GIC distributor */
    XScuGic_Enable( g_gic_instance, 29U );

    /*
     * 5. Start the timer: auto-reload, IRQ enable, timer enable.
     *    Control bits: 0=Enable, 1=AutoReload, 2=IRQEnable
     */
    *( volatile uint32_t * ) ulTimerCtrlReg = 0x00000007UL;
    *( volatile uint32_t * ) ulGicCpuPmrReg = 0x000000FFUL;
}
