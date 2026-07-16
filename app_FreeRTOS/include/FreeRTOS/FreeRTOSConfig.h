/*
 * FreeRTOS Kernel V11.3.0
 * Configuration for Zynq-7020 (ANTSDR E310) — ARM Cortex-A9
 *
 * This file is part of the FreeRTOS porting effort for the B2Z project.
 * See CLAUDE.md for the full porting plan.
 */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/*-----------------------------------------------------------
 * Hardware specifics — MUST be defined for ARM_CA9 port
 *----------------------------------------------------------*/

/* Zynq-7020 GIC base addresses.
 *
 * FreeRTOS ARM_CA9 expects BASE = distributor.  CPU interface registers
 * are accessed at BASE + CPU_INTERFACE_OFFSET.  The Zynq GIC has the CPU
 * interface BELOW the distributor in physical memory, so the offset is
 * negative — this works because 32-bit unsigned arithmetic wraps around.
 *
 *   Distributor:    0xF8F01000
 *   CPU Interface:  0xF8F00100  →  offset = 0xF8F00100 - 0xF8F01000
 *
 * The priority-check code in xPortStartScheduler() uses BASE + 0x400,
 * which MUST hit the distributor's IPRIORITY registers (0xF8F01400).
 * With the old config (BASE=CPU_IF) it hit a reserved area → assert fail. */
#define configINTERRUPT_CONTROLLER_BASE_ADDRESS              0xF8F01000
#define configINTERRUPT_CONTROLLER_CPU_INTERFACE_OFFSET      ( 0xF8F00100UL - 0xF8F01000UL )

/* Zynq PL390 GIC implements 5 priority bits → 32 unique levels. */
#define configUNIQUE_INTERRUPT_PRIORITIES                    32

/* Priorities 18–31 are masked during critical sections.
 * Must be > (configUNIQUE_INTERRUPT_PRIORITIES / 2) = 16.
 * Tick (PPI 29) runs at priority 30. Priority 31 encodes to 0xF8, equal to
 * the GIC PMR value read back after writing 0xFF, so it remains masked. */
#define configMAX_API_CALL_INTERRUPT_PRIORITY                18

/*-----------------------------------------------------------
 * Tick configuration — Cortex-A9 Private Timer @ 0xF8F00600
 *----------------------------------------------------------*/

/* Called by xPortStartScheduler() to initialise the tick hardware.
 * Implemented in freertos_irq_glue.c */
extern void vConfigureTickInterrupt( void );
#define configSETUP_TICK_INTERRUPT()                         vConfigureTickInterrupt()

/* Clear the Private Timer interrupt flag (write 1 to ISR bit 0). */
#define configCLEAR_TICK_INTERRUPT() \
    ( *( volatile uint32_t * ) ( 0xF8F00600UL + 0x0CUL ) ) = 0x1UL

/*-----------------------------------------------------------
 * Kernel behaviour
 *----------------------------------------------------------*/

#define configCPU_CLOCK_HZ                                   ( 666666687UL )
#define configTICK_RATE_HZ                                   ( 1000 )
#define configMAX_PRIORITIES                                 ( 16 )
#define configMINIMAL_STACK_SIZE                             ( 256 )
#define configTOTAL_HEAP_SIZE                                ( 1024 * 1024 )  /* 1 MB */
#define configMAX_TASK_NAME_LEN                              ( 16 )

#define configUSE_PREEMPTION                                 1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION              1
#define configUSE_16_BIT_TICKS                               0

/* Synchronisation primitives */
#define configUSE_MUTEXES                                    1
#define configUSE_COUNTING_SEMAPHORES                        1
#define configUSE_TASK_NOTIFICATIONS                         1

/* Stats and debugging */
#define configUSE_TRACE_FACILITY                             1
#define configUSE_STATS_FORMATTING_FUNCTIONS                 1
#define configCHECK_FOR_STACK_OVERFLOW                       2  /* Method 2: canary check */

/* Hook functions */
#define configUSE_IDLE_HOOK                                  1
#define configUSE_TICK_HOOK                                  0
#define configUSE_MALLOC_FAILED_HOOK                         1
#define configUSE_DAEMON_TASK_STARTUP_HOOK                   0

/* Tickless idle — keep disabled (BLE needs deterministic tick) */
#define configUSE_TICKLESS_IDLE                              0

/*-----------------------------------------------------------
 * FPU — V11 uses configUSE_TASK_FPU_SUPPORT
 * 2 = all tasks created with FPU context by default
 *----------------------------------------------------------*/
#define configUSE_TASK_FPU_SUPPORT                           2

/*-----------------------------------------------------------
 * Runtime stats (disabled for now — re-enable with global
 * timer after Phase 1 verification)
 *----------------------------------------------------------*/
#define configGENERATE_RUN_TIME_STATS                        0

/*-----------------------------------------------------------
 * Assert — halt on failure for JTAG debugging
 *----------------------------------------------------------*/
#define configASSERT( x )                                    \
    if( ( x ) == 0 )                                         \
    {                                                        \
        portDISABLE_INTERRUPTS();                            \
        for( ; ; ) __asm volatile ( "NOP" );                 \
    }

/*-----------------------------------------------------------
 * Optional features explicitly disabled
 *----------------------------------------------------------*/
#define configUSE_TIMERS                                     0
#define configTIMER_TASK_PRIORITY                            10
#define configTIMER_QUEUE_LENGTH                             8
#define configTIMER_TASK_STACK_DEPTH                         512  /* 2 KB in words */

#define configUSE_RECURSIVE_MUTEXES                          0
#define configUSE_QUEUE_SETS                                 0

/*-----------------------------------------------------------
 * FreeRTOS V11: define inline functions in the main FreeRTOS.h
 *----------------------------------------------------------*/
#define INCLUDE_xTaskGetSchedulerState                       1
#define INCLUDE_vTaskDelete                                  1
#define INCLUDE_vTaskDelayUntil                              1
#define INCLUDE_vTaskDelay                                   1
#define INCLUDE_uxTaskGetStackHighWaterMark                  1
#define INCLUDE_xTaskGetIdleTaskHandle                       1
#define INCLUDE_eTaskGetState                                1
#define INCLUDE_xTaskGetHandle                               1
#define INCLUDE_xSemaphoreGetMutexHolder                     1

/* The MSB of the 32-bit GIC priority field holds the group priority,
 * the next bits are subpriority.  With BPR=0 all bits are group priority
 * and none are subpriority. */
#define configKERNEL_INTERRUPT_PRIORITY                      30  /* Tick = lowest usable priority */
#define configMAX_SYSCALL_INTERRUPT_PRIORITY                 18

/* ARM Erratum 752419 — required on some Cortex-A9 r2pX.  Safe to leave as
 * default (not defined = disabled). */

#endif /* FREERTOS_CONFIG_H */
