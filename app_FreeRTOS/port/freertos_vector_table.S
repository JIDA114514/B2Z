/*
 * FreeRTOS vector table for ARM Cortex-A9 (Zynq-7020).
 *
 * In FreeRTOS V11, the application must provide the vector table.
 * This overrides the Xilinx asm_vectors.S table at runtime by setting VBAR.
 *
 * The table uses the LDR PC, [PC, #offset] pattern — each entry loads the
 * handler address from the literal pool immediately after the table.
 */

    .section .text.freertos_vectors, "ax"
    .align 5                         /* 32-byte aligned (required by ARM) */
    .global _freertos_vector_table
    .extern vFreeRTOSExceptionHandler
    .syntax unified

_freertos_vector_table:
    LDR     PC, _reset_addr
    LDR     PC, _undef_addr
    LDR     PC, _svc_addr
    LDR     PC, _prefetch_addr
    LDR     PC, _data_addr
    NOP                              /* reserved entry */
    LDR     PC, _irq_addr
    LDR     PC, _fiq_addr

    .align 4
_reset_addr:    .word   _start
_undef_addr:    .word   UndefinedExceptionHandler
_svc_addr:      .word   FreeRTOS_SWI_Handler
_prefetch_addr: .word   PrefetchAbortExceptionHandler
_data_addr:     .word   DataAbortExceptionHandler
_irq_addr:      .word   FreeRTOS_IRQ_Handler
_fiq_addr:      .word   FIQExceptionHandler

/*
 * Handlers for exceptions that should not occur during normal FreeRTOS
 * operation.  Pass (exception_id, lr, spsr) to C so the UART log shows which
 * exception was taken instead of silently spinning at B .
 */
    .global UndefinedExceptionHandler
    .type   UndefinedExceptionHandler, %function
UndefinedExceptionHandler:
    MOV     R0, #1
    MOV     R1, LR
    MRS     R2, SPSR
    B       vFreeRTOSExceptionHandler

    .global PrefetchAbortExceptionHandler
    .type   PrefetchAbortExceptionHandler, %function
PrefetchAbortExceptionHandler:
    MOV     R0, #2
    MOV     R1, LR
    MRS     R2, SPSR
    B       vFreeRTOSExceptionHandler

    .global DataAbortExceptionHandler
    .type   DataAbortExceptionHandler, %function
DataAbortExceptionHandler:
    MOV     R0, #3
    MOV     R1, LR
    MRS     R2, SPSR
    B       vFreeRTOSExceptionHandler

    .global FIQExceptionHandler
    .type   FIQExceptionHandler, %function
FIQExceptionHandler:
    MOV     R0, #4
    MOV     R1, LR
    MRS     R2, SPSR
    B       vFreeRTOSExceptionHandler
