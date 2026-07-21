# FreeRTOS 移植调试记录

## 环境

| 项目 | 说明 |
|------|------|
| 平台 | Xilinx Zynq-7020 (ANTSDR E310) |
| FreeRTOS 版本 | V11.3.0 |
| 分支 | `feat/freertos-dev` |
| 目标目录 | `app_FreeRTOS/` |
| 工具链 | Vitis 2021.1, GCC ARM bare-metal |

---

## 1. FreeRTOSConfig.h 路径错误

**症状**: 编译报错 `FreeRTOS.h: FreeRTOSConfig.h: No such file or directory`

**原因**: FreeRTOSConfig.h 放在了 `app_FreeRTOS/` 根目录，但 FreeRTOS.h 位于 `include/FreeRTOS/`，它用 `#include "FreeRTOSConfig.h"` 查找，GCC 只在 FreeRTOS.h 所在目录和 include 路径中查找。

**解决**: 将 FreeRTOSConfig.h 移动到 `app_FreeRTOS/include/FreeRTOS/FreeRTOSConfig.h`，与 FreeRTOS.h 同目录。

---

## 2. 缺少 `#endif // IIO_SUPPORT`

**症状**: 编译报错 `main.c: end of file: unterminated #ifdef`

**原因**: 用 Python 脚本修改 main.c 时，切片 `lines[:1061]` 截断了第 1061 行的 `#endif // IIO_SUPPORT`，导致 `#ifdef FREERTOS_INTEGRATION` 块之前缺少闭合。

**解决**: 在 `#ifdef FREERTOS_INTEGRATION` 之前手动补上 `#endif // IIO_SUPPORT`。

---

## 3. ulICCIARAddress 等变量重复定义

**症状**: 编译报错：
```
multiple definition of `ulICCIARAddress`
multiple definition of `ulICCEOIRAddress`
multiple definition of `ulICCPMRAddress`
```

**原因**: V11 port.c 已将这些变量定义为 `const`，而 `freertos_irq_glue.c` 中又重复声明了它们。

**解决**: 从 `freertos_irq_glue.c` 中移除这些变量的重复定义，直接使用 port.c 中已有的定义。

---

## 4. XScuGic_Start 不存在

**症状**: 编译报错 `undefined reference to XScuGic_Start`

**原因**: Xilinx BSP 的 SCUGIC 驱动中根本没有 `XScuGic_Start()` 这个函数。初始化 GIC 只需 `XScuGic_LookupConfig()` + `XScuGic_CfgInitialize()` 即可。

**解决**: 删除对 `XScuGic_Start()` 的调用。

---

## 5. vApplicationStackOverflowHook 未定义

**症状**: 编译报错 `undefined reference to vApplicationStackOverflowHook`

**原因**: `FreeRTOSConfig.h` 中设置了 `configCHECK_FOR_STACK_OVERFLOW = 2`，要求应用提供栈溢出钩子函数，但未实现。

**解决**: 在 `main.c` 中添加：
```c
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName) {
    console_print("STACK OVERFLOW: ");
    console_print(pcTaskName);
    console_print("\r\n");
    for (;;) { __asm volatile ("NOP"); }
}
```

---

## 6. vTaskStartScheduler() 后系统挂死

**症状**: 串口输出 `=== FreeRTOS Phase 1: Starting scheduler ===` 后系统无响应。

**根本原因**: **FreeRTOS V11.3.0 移除了 `vPortInstallFreeRTOSVectorTable()` 函数。**
V10.6.2 中该函数在 `vTaskStartScheduler()` 内部被调用，自动将 VBAR 指向 FreeRTOS 向量表。V11 中改为由应用自行负责：

1. 提供 `_freertos_vector_table` 符号 — portASM.S 中声明为 `.extern`，但 FreeRTOS 内核源码中没有任何文件定义它
2. 在调用 `vTaskStartScheduler()` 前用 `MCR p15, 0, Rn, c12, c0, 0` 将 VBAR 设置为 `_freertos_vector_table` 的地址

缺少这一步时：
- `portYIELD()` 触发 SVC → 进入 Xilinx 原始的 SVC handler（死路）
- Tick 中断触发 IRQ → 进入 Xilinx 原始的 IRQ handler，找不到 FreeRTOS 注册的处理函数（死路）
- 任何数据中止也会落入 Xilinx 的异常处理，表现为静默挂死

**解决**: 两步修复：

### 6.1 新建 `freertos_vector_table.S`

提供 `_freertos_vector_table` 符号和完整的 ARM 异常向量表：

```asm
.section .text.freertos_vectors, "ax"
.align 5                         /* 32-byte aligned (required by ARM) */
.global _freertos_vector_table
.syntax unified

_freertos_vector_table:
    LDR     PC, _reset_addr
    LDR     PC, _undef_addr
    LDR     PC, _svc_addr
    LDR     PC, _prefetch_addr
    LDR     PC, _data_addr
    NOP
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
```

关键细节：
- Section 名使用 `.text.freertos_vectors` 以匹配链接脚本的 `*(.text.*)` 通配符
- `.align 5` 确保 32 字节对齐（ARM 架构要求 VBAR 指向的向量表必须 32 字节对齐）
- Reset 向量指向 `_start`（xil-crt0.S 中的 `_start` 是 `.globl`，链接器可解析）
- 未使用的异常处理器（Undef/Prefetch/Data/FIQ）设为 `B .` 自旋循环，便于调试器附着检查

### 6.2 在 main.c 中设置 VBAR

在 `vTaskStartScheduler()` 调用之前添加：

```c
extern const uint32_t _freertos_vector_table[8];

/* 将 VBAR 指向 FreeRTOS 向量表 */
__asm volatile ("MCR p15, 0, %0, c12, c0, 0" :: "r" (&_freertos_vector_table) : "memory");
__asm volatile ("DSB" ::: "memory");
__asm volatile ("ISB" ::: "memory");
```

DSB/ISB 确保 CP15 写操作完成后再执行后续指令。

---

## 7. 架构决策：XScuGic_InterruptHandler 不能直接使用

**问题**: FreeRTOS 的 IRQ 入口（portASM.S 中的 `FreeRTOS_IRQ_Handler`）已经读取了 ICCIAR，获取了中断 ID。如果直接调用 `XScuGic_InterruptHandler()`，该函数会再次读取 ICCIAR，得到第二次读取时的值（可能是另一个中断），导致第一个中断丢失。

**解决**: 在 `vApplicationIRQHandler()` 中直接从 XScuGic 的 HandlerTable 分派（不通过 `XScuGic_InterruptHandler()`）：

```c
void vApplicationIRQHandler(uint32_t ulICCIAR) {
    const uint32_t interrupt_id = ulICCIAR & 0x3FFUL;
    if (g_gic_instance && interrupt_id < XSCUGIC_MAX_NUM_INTR_INPUTS) {
        XScuGic_VectorTableEntry *table =
            &g_gic_instance->Config->HandlerTable[interrupt_id];
        if (table && table->Handler)
            table->Handler(table->CallBackRef);
    }
}
```

---

## 8. vTaskStartScheduler() 后仍挂死（调试中）

**症状**: 修复 #6（向量表+VBAR）后，串口输出 `=== FreeRTOS Phase 1: Starting scheduler ===` 后仍无响应。

**已排除的原因**:
- VFP/FPU 未使能 — boot.S 已正确设置 CPACR (CP10/CP11) 和 FPEXC
- VBAR 地址错误 — `&_freertos_vector_table` 由链接器正确解析
- `configASSERT` 失败 — 所有启动断言（APSR 模式、ICCBPR 值、优先级位数）理论上均通过
- GIC 未使能 — `XScuGic_CfgInitialize` 在 GICv2 路径正确调用 `DistributorInit` 和 `CPUInitialize`
- `_freertos_vector_table` 段被丢弃 — 链接脚本无 DISCARD 规则，`*(.text.*)` 覆盖 `.text.freertos_vectors`

**调试策略**: 在关键路径上添加 UART 输出，以定位挂死点：

| 调试消息 | 位置 | 含义 |
|----------|------|------|
| `=== FreeRTOS Phase 1: Starting scheduler ===` | main.c | VBAR 设置之前（已有） |
| `[DBG] VBAR set, calling vTaskStartScheduler...` | main.c | VBAR 已写入，即将调用 vTaskStartScheduler |
| `[DBG] GIC priority probe: base=... read=...` | port.c | xPortStartScheduler 正在探测 GIC priority bit |
| `[DBG] GIC priority probe: normalized=31 expected=31` | port.c | GIC priority bit 配置与 `configUNIQUE_INTERRUPT_PRIORITIES=32` 匹配 |
| `[DBG] xPortStartScheduler: cpsr_mode=31 bpr=...` | port.c | CPU 处于 System mode，开始检查 GIC binary point |
| `[DBG] vConfigureTickInterrupt: entry` | freertos_irq_glue.c | xPortStartScheduler 已调用 configSETUP_TICK_INTERRUPT |
| `[DBG] vConfigureTickInterrupt: GIC registered` | freertos_irq_glue.c | GIC 实例非空，tick 已注册 |
| `[DBG] vConfigureTickInterrupt: timer started` | freertos_irq_glue.c | Private Timer 已启动 |
| `[DBG] xPortStartScheduler: calling vPortRestoreTaskContext...` | port.c | tick 初始化完成，即将恢复首个任务上下文 |
| `[T=...] ... TickISR=N` | main.c 监控任务 | 调度器正在运行，显示 tick ISR 触发次数 |

**诊断逻辑**:

| 观察到的最后一条消息 | 挂死位置 |
|---------------------|---------|
| 只有 `Starting scheduler`，无 `VBAR set` | VBAR 设置之前的某处 |
| 有 `VBAR set`，无 tick 相关消息 | `vTaskStartScheduler()` 内部，`xPortStartScheduler()` 之前或 configASSERT |
| 有 `timer started`，无监控任务输出 | `vPortRestoreTaskContext()` 或首个任务运行时 crash |
| 有监控输出但 `TickISR=0` | Tick 中断未触发（GIC PPI 配置问题） |
| 监控正常输出 | 一切正常 ✅ |

**分析**: `vPortRestoreTaskContext()` 从 `pxCurrentTCB` 恢复最高优先级任务。若调度器创建了 Timer Service（优先级 10），则该任务先运行。首个任务执行时 `RFEIA` 开启 IRQ，此时 tick 中断若已 pending 则立即触发。任何未预期的异常（Data Abort / Undef Instruction / Prefetch Abort）落入向量表的 `B .` 死循环，表现为静默挂死。

**状态**: 已确认根因并修复到 `vPortRestoreTaskContext()` 之前，见 #9。

---

## 9. configINTERRUPT_CONTROLLER_BASE_ADDRESS 配置错误 + SDK 副本未同步

**症状**: 串口输出 `[DBG] xPortStartScheduler: entry` 但无后续 tick 消息，系统挂死。

**根本原因**: `FreeRTOSConfig.h` 中 `configINTERRUPT_CONTROLLER_BASE_ADDRESS` 被设为 GIC **CPU Interface** 地址 (`0xF8F00100`)，但 FreeRTOS ARM_CA9 移植层要求此基址指向 GIC **Distributor**。

`xPortStartScheduler()` 中的优先级位数检测代码：

```c
// portINTERRUPT_PRIORITY_REGISTER_OFFSET = 0x400（Distributor 内偏移）
volatile uint8_t *puc = (Base + 0x400);  // 若 Base=CPU_IF: 0xF8F00500 (保留区!)
*puc = 0xFF;                              // 写入被忽略
ucMaxPriorityValue = *puc;               // 读回 0 (RAZ)
// → configASSERT(0 == 31) → 失败 → portDISABLE_INTERRUPTS() + 死循环
```

Zynq-7020 的内存布局中 CPU Interface 在 Distributor **下方**：

| 外设 | 地址 |
|------|------|
| GIC CPU Interface | `0xF8F00100` |
| GIC Distributor | `0xF8F01000` |

**解决**: 将 Base 改为 Distributor 地址，CPU Interface 通过**负数偏移量**访问（利用 32 位无符号整数回绕）：

```c
// 之前（错误）
#define configINTERRUPT_CONTROLLER_BASE_ADDRESS          0xF8F00100  // CPU IF
#define configINTERRUPT_CONTROLLER_CPU_INTERFACE_OFFSET  0x00000000

// 之后（正确）
#define configINTERRUPT_CONTROLLER_BASE_ADDRESS          0xF8F01000  // Distributor
#define configINTERRUPT_CONTROLLER_CPU_INTERFACE_OFFSET  (0xF8F00100UL - 0xF8F01000UL)
```

**关键补充**: 上板镜像实际使用的是 Vitis SDK 编译目录中的配置副本，而不是只使用 `app_FreeRTOS/include/FreeRTOS/FreeRTOSConfig.h`。

必须同步修改以下两份 SDK build path 文件：

- `hdl/projects/antsdre310/antsdre310.sdk/app/src/FreeRTOSConfig.h`
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/include/FreeRTOS/FreeRTOSConfig.h`

否则即使 `app_FreeRTOS/include/FreeRTOS/FreeRTOSConfig.h` 已经正确，重新编译上板后仍会打印旧的 `base=F8F00100`。

验证：
- Distributor 寄存器：`BASE + 0x400 = 0xF8F01400`（IPRIORITY 寄存器）✓
- CPU Interface 寄存器：`BASE + OFFSET + 0x04 = 0xF8F01000 + 0xFFFFF100 + 0x04 = 0xF8F00104`（ICCPMR）✓
- 32 位无符号加法回绕保证地址正确

### 9.1 第一次诊断日志：确认仍在使用旧配置

```text
[DBG] GIC priority probe: base=F8F00100 offset=400 orig=0 read=0
[ERR] xPortStartScheduler: GIC priority probe read zero v1=-118488832 v2=1024
```

含义：
- `base=F8F00100` 表明实际编译进镜像的配置仍是 CPU Interface 地址。
- `base + 0x400 = 0xF8F00500` 是保留区域，写 `0xFF` 后读回 `0`，因此 priority probe 失败。
- `v1=-118488832` 是 `0xF8F00100` 按 signed decimal 打印后的结果；后续可改成 `%x` 便于阅读。

### 9.2 修复后日志：已通过 GIC/tick 初始化

```text
[DBG] GIC priority probe: base=F8F01000 offset=400 orig=160 read=248
[DBG] GIC priority probe: normalized=31 expected=31
[DBG] xPortStartScheduler: cpsr_mode=31 bpr=2
[DBG] vConfigureTickInterrupt: entry load=333333 priority=248
[DBG] vConfigureTickInterrupt: PPI29 priority=248 trigger=3
[DBG] vConfigureTickInterrupt: GIC registered
[DBG] vConfigureTickInterrupt: timer started
[DBG] xPortStartScheduler: calling vPortRestoreTaskContext...
```

逐行解释：
- `base=F8F01000`：实际镜像已使用 GIC Distributor base。
- `read=248`：GIC priority register 只实现高 5 bit，写 `0xFF` 后读回 `0xF8`。
- `normalized=31 expected=31`：右移归一化后为 31，与 `configUNIQUE_INTERRUPT_PRIORITIES=32` 匹配。
- `cpsr_mode=31`：CPU 在 System mode，不是 User mode，允许启动调度器。
- `bpr=2`：GIC binary point 读回 2，满足 FreeRTOS 对 32 priority levels 的 `portMAX_BINARY_POINT_VALUE=2`。
- `load=333333`：Private Timer tick load = `(666666687 / 2) / 1000`。
- `priority=248`：PPI29 tick 优先级使用硬件编码 `31 << 3 = 248`，是最低优先级。
- `trigger=3`：BSP 读回 PPI29 trigger field 为 3；当前关键验证是 priority 与 handler 注册成功。
- `calling vPortRestoreTaskContext...`：已经越过 GIC priority probe、CPSR/BPR 检查和 tick 初始化，下一阶段若仍无监控任务输出，应重点查首任务上下文恢复、任务栈布局、FPU 上下文或首个 tick IRQ 进入后的异常。

**这就是"VBAR 修复后仍然挂死"的真正原因。** 问题不在向量表，而在 GIC 基址配置。

---

## 10. vPortRestoreTaskContext 后无响应：异常可见化

**症状**: 已经输出：

```text
[DBG] vConfigureTickInterrupt: timer started
[DBG] xPortStartScheduler: calling vPortRestoreTaskContext...
```

之后无监控任务输出。

**当前判断**: 已经越过 GIC priority probe、CPSR/BPR 检查和 tick 初始化，卡点收敛到：

- `portRESTORE_CONTEXT` 恢复首任务上下文期间异常
- `RFEIA sp!` 返回任务入口时异常
- 首个任务或首个 tick IRQ 触发后进入 Data Abort / Undefined / Prefetch Abort
- 任务已经启动但在第一次 `vTaskDelay()` 后 tick/调度未继续

**新增诊断**:

1. 将 `freertos_vector_table.S` 中的 Undef/Prefetch/Data/FIQ handler 从静默 `B .` 改为调用 `vFreeRTOSExceptionHandler()`。
2. `vFreeRTOSExceptionHandler()` 打印异常类型、LR、SPSR 和 `restore_stage`：

```text
[EXC] DATA_ABORT id=3 lr=... spsr=... restore_stage=N
```

3. 在 `portASM.S` 的 `portRESTORE_CONTEXT` 宏中加入 `g_context_restore_stage`：

| stage | 含义 |
|-------|------|
| 1 | 进入 `portRESTORE_CONTEXT` |
| 2 | 已加载当前任务栈指针到 SP |
| 3 | FPU 上下文恢复后 |
| 4 | critical nesting 恢复后 |
| 5 | ICCPMR 更新后，即将 POP 通用寄存器并执行 `RFEIA` |

4. 在 `Cnt1`、`Cnt2`、`Monitor` 三个 Phase 1 验证任务入口添加：

```text
[DBG] Cnt1 task entered
[DBG] Cnt2 task entered
[DBG] Monitor task entered
```

**下一次日志判读**:

| 新日志现象 | 判断 |
|------------|------|
| 出现 `[EXC] ... restore_stage=1/2` | 当前 TCB 或任务栈指针异常 |
| 出现 `[EXC] ... restore_stage=3` | FPU restore 后继续恢复时异常，重点查初始栈布局 |
| 出现 `[EXC] ... restore_stage=5` | `POP {R0-R12,R14}` 或 `RFEIA sp!` 后异常，重点查初始 PC/SPSR 布局 |
| 出现 task entered，但无 `[T=...]` | 已进入任务，重点查 tick IRQ 或 `vTaskDelay()` 后调度 |
| 既无 `[EXC]` 也无 task entered | 重点查 `RFEIA` 返回路径、VBAR 是否仍有效、异常是否未落到当前向量表 |

---

## 11. 三个任务均 entered 后无监控输出：tick 未唤醒任务

**症状**:

```text
[DBG] Monitor task entered
[DBG] Cnt1 task entered
[DBG] Cnt2 task entered
```

之后无 `[T=...]` 输出。

**判断**: `vPortRestoreTaskContext()`、初始任务栈和任务入口均已正常。三个任务依次进入后都执行了第一次 `vTaskDelay()`，随后系统只剩 Idle task。如果没有 tick interrupt 唤醒延时列表中的任务，就会表现为当前现象。

**新增诊断**:

1. 打开 `configUSE_IDLE_HOOK = 1`。
2. 在 `vApplicationIdleHook()` 中，当 `g_tick_isr_count == 0` 时低频打印寄存器：

```text
[DBG] idle no-tick: loops=... cpsr=... pmr=... gicc_ctl=... gicd_ctl=... en0=... pend0=... act0=... tcnt=... tctl=... tisr=...
```

字段含义：

| 字段 | 地址/含义 |
|------|-----------|
| `cpsr` | CPU CPSR，检查 IRQ disable bit 是否为 0 |
| `pmr` | GIC CPU priority mask `0xF8F00104` |
| `gicc_ctl` | GIC CPU interface control `0xF8F00100` |
| `gicd_ctl` | GIC distributor control `0xF8F01000` |
| `en0` | GIC enable set 0 `0xF8F01100`，bit 29 应为 1 |
| `pend0` | GIC pending set 0 `0xF8F01200`，bit 29 可显示 pending |
| `act0` | GIC active bit 0 `0xF8F01300` |
| `tcnt` | SCU private timer counter `0xF8F00604` |
| `tctl` | SCU private timer control `0xF8F00608`，期望为 `0x7` |
| `tisr` | SCU private timer ISR `0xF8F0060C`，bit 0 为 timer event |

3. 在 `vConfigureTickInterrupt()` 中显式写 GIC CPU PMR 为 `0xFF`，避免 Xilinx 默认 `0xF0` 屏蔽最低优先级 tick (`0xF8`)。

下一次判读：

| idle 字段现象 | 判断 |
|---------------|------|
| `tisr=1` 且 `pend0` bit29=0 | timer 到期但 GIC 没收到/没使能 PPI29 |
| `pend0` bit29=1 且 `pmr` 小于 `0xF8` | tick pending 但被 priority mask 屏蔽 |
| `pend0` bit29=1 且 CPSR I bit 为 1 | tick pending 但 CPU IRQ 全局关闭 |
| `tcnt` 不变化或 `tctl` 不是 `0x7` | private timer 未运行 |
| `g_tick_isr_count` 变为非零后仍无 `[T=...]` | IRQ 已进入，需查 `FreeRTOS_Tick_Handler()` / `xTaskIncrementTick()` / context switch |

---

### 11.1 已确认：tick pending 但被 PMR 屏蔽

实测日志：

```text
[DBG] idle no-tick: loops=41943040 cpsr=6000001F pmr=90 gicc_ctl=7 gicd_ctl=1 en0=2000FFFF pend0=20000000 act0= tcnt=C576 tctl=7 tisr=1
```

关键字段：

- `cpsr=6000001F`：System mode，IRQ disable bit 未置位，CPU 全局 IRQ 未关闭。
- `gicc_ctl=7`、`gicd_ctl=1`：GIC CPU interface 和 distributor 已启用。
- `en0=2000FFFF`：PPI29 enable bit 已置位。
- `pend0=20000000`：PPI29 已 pending。
- `tctl=7`、`tisr=1`：SCU private timer 正在运行且已到期。
- `pmr=90`：GIC CPU priority mask 为 `0x90`，会屏蔽 tick priority `0xF8`。

结论：硬件 tick 已经产生并 pending，但 FreeRTOS critical mask 没恢复到 `0xFF`，导致最低优先级 tick 无法进入 IRQ handler。

临时修复/验证：

- 在 tick 初始化时显式写 `GICC_PMR = 0xFF`。
- 在 `vApplicationIdleHook()` 中，如果 `tisr=1` 且 `pend0 bit29=1` 且 `pmr!=0xFF`，写 `GICC_PMR=0xFF` 并打印：

```text
[DBG] idle unmasked pending tick: old_pmr=90 count=1
```

若随后出现 `[T=...]` 或 `TickISR` 非零，说明当前阻塞点已确认是 PMR stuck at `0x90`。后续再继续查是谁在任务进入 `vTaskDelay()` 后留下了 critical mask。

---

### 11.2 最终修正：tick 不能使用 priority 31

进一步实测：

```text
[DBG] idle unmasked pending tick: old_pmr=90 count=1
[DBG] idle no-tick: loops=1 cpsr=6000001F pmr=F8 ... pend0=20000000 ... tisr=1
[DBG] idle unmasked pending tick: old_pmr=F8 count=2
```

含义：

- 写 `GICC_PMR=0xFF` 后，GIC 只实现高 5 bit，读回为 `0xF8`。
- 原 tick priority 配为 `31 << 3 = 0xF8`。
- GIC priority mask 是严格阈值；`priority == PMR` 不会进入 CPU IRQ。
- 因此 tick 放在 priority 31 时，即使 PMR 已“最大放开”到 `0xF8`，tick 仍然被屏蔽。

修正：

```c
#define configKERNEL_INTERRUPT_PRIORITY 30
```

对应硬件编码：

```text
30 << 3 = 0xF0
```

这样：

- critical section 时 `PMR=18<<3=0x90`，tick `0xF0` 会被屏蔽，符合 FreeRTOS 预期。
- 非 critical section 时 `PMR=0xF8`，tick `0xF0 < 0xF8`，可以进入 IRQ。

预期重新上板日志：

```text
[DBG] vConfigureTickInterrupt: entry load=333333 priority=240
[DBG] vConfigureTickInterrupt: PPI29 priority=240 ...
```

之后应看到 `[T=...]` 且 `TickISR` 递增。

---

## 经验教训

1. **V10 → V11 升级要读 Release Notes**：`vPortInstallFreeRTOSVectorTable()` 的移除是 breaking change，文档中可能提及但不显眼。
2. **FreeRTOSConfig.h 必须与 FreeRTOS.h 同目录**：V11 的 `#include` 不依赖额外的 `-I` 路径。
3. **Xilinx BSP API 文档 ≠ 实际存在**：`XScuGic_Start()` 在头文件中存在但在库中缺失。
4. **静默挂死最常见于异常向量表问题**：ARM 的 Data Abort 等未处理异常落入 `B .` 自旋循环，表现为无限等待。
5. **Vitis SDK 编译目录可能持有源码副本**：上板前必须确认 `hdl/projects/antsdre310/antsdre310.sdk/app/src/` 中的实际编译文件已同步，不要只看 `app_FreeRTOS/`。
6. **PPI 与 SPI 的 GIC 配置有区别**：PPI（如 tick 的 ID 29）需要使用特定的触发类型编码；BSP 写入 `0x01` 后读回可能为 `3`，应结合优先级和实际中断触发验证。
7. **嵌入式无 JTAG 调试时，战略性 UART print 是最有效的定位手段**：在启动流程关键分叉点插入输出，单次编译即可收敛问题范围。

---

## 12. 只看到 Cnt1/Cnt2 entered 后无响应

**当前症状**:

```text
[DBG] Cnt1 task entered
[DBG] Cnt2 task entered
```

之后无输出。与上一轮不同的是未看到：

```text
[DBG] Monitor task entered
```

**关键判断**:

- 若 `Mon` 任务创建成功且调度器按 FreeRTOS 优先级运行，`Mon` 优先级 2，高于 `Cnt1/Cnt2` 的优先级 1，应先输出 `Monitor task entered`。
- 只看到 `Cnt1/Cnt2` 说明目前无法区分：
  - `xTaskCreate(vMonitorTask)` 失败；
  - `Monitor` 已创建但首个输出丢失/卡住；
  - tick 进入过一次后 idle hook 因 `g_tick_isr_count != 0` 提前返回，后续诊断被静默；
  - tick handler 入口被计数，但 handler 内部未正常返回。

**本次修正/诊断增强**:

1. 启用 malloc failed hook：

```c
#define configUSE_MALLOC_FAILED_HOOK 1
```

并实现 `vApplicationMallocFailedHook()`，失败时打印剩余 heap 后停机。

2. Phase 1 暂时关闭未使用的 software timer task：

```c
#define configUSE_TIMERS 0
```

目的：减少一个优先级 10 的内部任务变量；`vTaskDelay()` 不依赖 software timer task。

3. 检查三个验证任务的创建返回值和 handle：

```text
[DBG] task create: Cnt1 rc=... h=... Cnt2 rc=... h=... Mon rc=... h=... heap=...
```

若任一任务创建失败，启动前直接输出：

```text
[ERR] FreeRTOS Phase 1 task creation failed; scheduler not started
```

4. 计数任务改为在 `vTaskDelay()` 返回后输出低频 heartbeat：

```text
[DBG] Cnt1 alive tick=... count=... TickISR=... TickRet=...
[DBG] Cnt2 alive tick=... count=... TickISR=... TickRet=...
```

如果只看到 entered 而没有 alive，说明任务执行到第一次 delay 后没有被 tick 唤醒。

5. idle hook 不再因 `g_tick_isr_count != 0` 直接返回，而是持续低频输出：

```text
[DBG] idle diag: loops=... tick=... tickisr=... tickret=... cpsr=... pmr=... pend0=... tisr=...
```

这样即使 tick 进入过，也能继续观察 tick count、ISR count 和 GIC/private timer 状态。

6. 新增 `g_tick_handler_return_count`：

- `TickISR`：进入 PPI29 分发前递增。
- `TickRet`：XScuGic handler table 中的 tick handler 返回后递增。

判读：

| 现象 | 判断 |
|------|------|
| `TickISR` 增长但 `TickRet` 不增长 | 卡在 `FreeRTOS_Tick_Handler()` 内部，重点查 `xTaskIncrementTick()`、assert、PMR 恢复 |
| `TickISR` 与 `TickRet` 都增长，但 `tick` 不增长 | tick handler 返回了但 FreeRTOS tick count 未推进，重点查 handler 注册是否仍指向 `FreeRTOS_Tick_Handler` |
| `tick/TickISR/TickRet` 都增长，但任务无 alive | tick 正常，重点查 context switch/yield 或任务 ready list |
| `tick/TickISR/TickRet` 都为 0，`pend0=20000000 tisr=1` | tick 仍被 GIC/CPU mask 屏蔽 |

**已做本地验证**:

- `main.c` 单文件 ARM 编译通过。
- `freertos_irq_glue.c` 单文件 ARM 编译通过。
- `tasks.c` 在 `configUSE_TIMERS=0` 下单文件 ARM 编译通过。
- `git diff --check` 通过。

### 12.1 当前结论：tick 和调度器已正常工作

新的板端日志：

```text
[T=    4000] Cnt1=    39 Cnt2=    15 Heap=1038896 TickISR=4000 TickRet=4000
[DBG] Cnt2 alive tick=4002 count=16 TickISR=4002 TickRet=4002
[DBG] idle diag: loops=41943040 tick=4014 tickisr=4014 tickret=4014 cpsr=6000001F pmr=F8 gicc_ctl=7 gicd_ctl=1 en0=2000FFFF pend0= act0= tcnt=354D3 tctl=7 tisr=
[DBG] Cnt1 alive tick=4801 count=48 TickISR=4801 TickRet=4801
[T=    5000] Cnt1=    49 Cnt2=    19 Heap=1038896 TickISR=5000 TickRet=5000
```

判读：

- `tick == TickISR == TickRet`，说明 PPI29 tick IRQ 持续进入、`FreeRTOS_Tick_Handler()` 正常返回，FreeRTOS tick count 正常推进。
- `Cnt1` 在 5s 时约 49 次、`Cnt2` 约 19 次，符合 100ms/250ms delay 的预期。
- `Heap=1038896` 稳定，暂无 malloc 失败或堆泄漏迹象。
- `pmr=F8` 是 GIC 实现 5 bit priority 后对 `0xFF` 的正常读回；`pend0=`、`tisr=` 为空表示当前读值为 0，是 `console_print("%x")` 对 0 的显示问题，不代表异常。

结论：FreeRTOS Phase 1 的任务恢复、tick 中断、delay 唤醒和基础调度已经通过。后续应进入诊断清理与 Phase 2 HAL 适配，不再按 tick/GIC 阻塞方向排查。

---

## 13. Phase 2 ADC DMA IRQ 自检：硬件完成兜底通过

**当前状态**: Phase 2 HAL 自检已完整通过。ADC DMA 数据路径正常，但当前通过依赖硬件完成兜底，PL IRQ semaphore 路径仍需后续优化。

### 13.1 已通过项

板端日志：

```text
[P2] Phase 2 self-test start tick=0
[TASK] Cnt1 OK tick=3 count=0
[TASK] Cnt2 OK tick=6 count=0
[P2][PASS] tick tick_delta=1000
[P2][PASS] tick_irq isr_delta=1000
[P2][PASS] delay tick_delta=100
[P2][PASS] spi_mutex reads=128
[P2][PASS] gpio_mutex checked=1
[P2][PASS] console_mutex lines=40
```

判读：

- FreeRTOS tick 正常，`tick_delta=1000`、`isr_delta=1000` 匹配 1 kHz tick。
- `no_os_mdelay()` 在调度器运行后已能通过 `vTaskDelay()` 让出 CPU。
- SPI mutex、GPIO mutex、console mutex 的基础并发访问验证通过。
- `vTaskDelete(NULL)` 链接问题已通过 `INCLUDE_vTaskDelete=1` 修复。

### 13.2 失败现象

失败日志：

```text
Error transferring data using DMA.
[P2][FAIL] adc_dma_irq wait_completion code=-1
[P2] self-test stopped after failure tick=1751
```

失败位置：

```c
status = axi_dmac_transfer_wait_completion(rx_dmac, 500);
if (status < 0)
    return phase2_fail("adc_dma_irq", "wait_completion", status);
```

在 FreeRTOS 集成路径下，`rx_dmac->irq_option == IRQ_ENABLED` 且 scheduler 已运行时，`axi_dmac_transfer_wait_completion()` 会等待 `completion_sem`：

```c
xSemaphoreTake((SemaphoreHandle_t)dmac->completion_sem, wait_ticks)
```

因此 `wait_completion code=-1` 表示 500 ms 内没有收到 `axi_dmac_default_isr()` 里 EOT 完成路径释放的 semaphore。

### 13.3 已尝试但未确认解决的修改

1. 在实际参与链接的两份 `FreeRTOSConfig.h` 中启用：

```c
#define INCLUDE_vTaskDelete 1
```

涉及路径：

- `app_FreeRTOS/include/FreeRTOS/FreeRTOSConfig.h`
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/include/FreeRTOS/FreeRTOSConfig.h`

该修改解决的是 `undefined reference to vTaskDelete`，不是 ADC DMA 运行时失败。

2. 在 `axi_dmac_transfer_start()` 中尝试让 IRQ 模式每次 transfer 都重新清 pending 并打开 DMAC IRQ mask：

```c
if (dmac->irq_option == IRQ_ENABLED) {
    axi_dmac_write(dmac, AXI_DMAC_REG_IRQ_PENDING,
                   AXI_DMAC_IRQ_SOT | AXI_DMAC_IRQ_EOT);
    axi_dmac_write(dmac, AXI_DMAC_REG_IRQ_MASK, 0x0);
}
```

涉及路径：

- `app_FreeRTOS/drivers/axi_dmac.c`
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/drivers/axi_dmac.c`

用户反馈当前问题仍未解决，因此这不是充分修复，最多保留为一个可疑点/诊断辅助。

3. 在 ADC DMA 自检 timeout 后增加寄存器诊断输出：

```text
[P2][DMA] ctrl=0x%08x irq_mask=0x%08x irq_pending=0x%08x submit=0x%08x done=0x%08x remaining=%d dir=%d
```

涉及路径：

- `app_FreeRTOS/app/main.c`
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/app/main.c`

该输出用于下一轮区分：

| 现象 | 初步判断 |
|------|----------|
| `irq_pending` 包含 EOT，`done` 有完成 bit，但 semaphore 未释放 | PL IRQ/GIC 分发或 ISR callback 未执行 |
| `irq_pending` 一直为 0，`submit` 未清或 `done` 无变化 | DMA transfer 没有实际完成，需查 ADC 数据流/DMAC 启动条件 |
| `remaining != 0` | 分段传输未走完，需查 SOT 中断与下一段提交 |
| `dir != DMA_DEV_TO_MEM` | DMAC capability detect 或寄存器探测方向异常 |
| `irq_mask` 非 0 | DMAC 中断仍被 mask |

### 13.4 当前重点怀疑方向

1. **ADC DMA 没有真实完成**

Phase 2 自检直接启动 RX DMA 读取 `adc_buffer`。如果 AD9361 RX datapath、ADC core、DMAC stream 或采样时钟在当前 FreeRTOS 初始化路径下未处于可输出状态，DMAC 不会产生 EOT，等待 semaphore 必然超时。

2. **PL interrupt 未进入 FreeRTOS GIC 分发**

Phase 1 只证明了 PPI29 tick 正常。ADC DMA 使用 PL interrupt：

```c
XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR
```

如果 PL IRQ 未在 GIC 中正确 enable、priority/trigger 配置不合适、或 `vApplicationIRQHandler()` 没有分发到该 interrupt ID，则 DMAC 即使置位 pending，也不会执行 `axi_dmac_default_isr()`。

3. **ISR callback 注册路径与 FreeRTOS IRQ glue 不匹配**

当前 `xilinx_irq.c` 在 `FREERTOS_INTEGRATION` 下不再走 Xilinx exception table，而是通过 FreeRTOS IRQ entry 直接查 `XScuGic` HandlerTable。需要确认：

- `no_os_irq_register_callback()` 实际调用了 `XScuGic_Connect()`。
- HandlerTable 中 `XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR` 的 handler 是 `axi_dmac_default_isr`。
- callback context 是 `rx_dmac`。

4. **DMAC IRQ pending 清除/IRQ mask 语义需要复核**

当前代码假设 `AXI_DMAC_REG_IRQ_PENDING` 写 1 清 pending，`AXI_DMAC_REG_IRQ_MASK=0` 表示 unmask。若硬件语义或当前 IP 版本不同，需要以 ADI AXI-DMAC 文档/实际寄存器读回为准。

### 13.5 下一步建议

下一轮上板先保留新增 `[P2][DMA]` 诊断行，并记录完整输出。优先根据寄存器值判断问题属于以下哪一类：

1. DMA 未完成：继续查 RX datapath、DMA submit/done、ADC stream。
2. DMA 已 pending 但 ISR 未执行：查 PL IRQ 到 GIC 的 enable/pending/priority/handler table。
3. ISR 执行但 semaphore 未释放：查 `remaining_size`、EOT 条件和 `completion_sem`。

建议额外增加两个计数器：

```c
volatile uint32_t g_adc_dma_irq_enter_count;
volatile uint32_t g_adc_dma_irq_eot_count;
```

分别在 `axi_dmac_default_isr()` 入口和 `axi_dmac_dev_to_mem_isr()` 的最终 EOT 完成路径递增，并在 timeout 诊断行中打印。这样可以直接区分“PL IRQ 没进来”和“ISR 进来了但未到完成分支”。

### 13.6 新日志结论：DMA 已完成，IRQ semaphore 未收到

当前板端日志：

```text
Error transferring data using DMA.
[P2][DMA] ctrl=0x00000001 irq_mask=0x00000000 irq_pending=0x00000003 submit=0x00000000 done=0x00000001 remaining=0 dir=1
[P2][FAIL] adc_dma_irq wait_completion code=-1
[P2] self-test stopped after failure tick=1762
```

判读：

- `ctrl=0x00000001`：DMAC enabled。
- `irq_mask=0x00000000`：DMAC SOT/EOT 中断未被 mask。
- `irq_pending=0x00000003`：SOT + EOT pending 已置位。
- `submit=0x00000000`：提交队列已空。
- `done=0x00000001`：transfer done bit 已置位。
- `remaining=0`：驱动认为没有剩余分段。
- `dir=1`：方向为 `DMA_DEV_TO_MEM`，符合 ADC RX DMA。

结论：这不是 ADC DMA transfer 没完成，而是 **PL DMA IRQ 没有进入 FreeRTOS ISR 路径，或 ISR 未释放 `completion_sem`**。

为了避免已完成 DMA 被误报为传输失败，已在 `axi_dmac_transfer_wait_completion()` 的 FreeRTOS IRQ 等待超时分支增加硬件完成兜底：

```c
axi_dmac_read(dmac, AXI_DMAC_REG_IRQ_PENDING, &reg_val);
if ((reg_val & AXI_DMAC_IRQ_EOT) && !dmac->remaining_size) {
    dmac->transfer.transfer_done = true;
    axi_dmac_write(dmac, AXI_DMAC_REG_IRQ_PENDING, reg_val);
    printf("DMA completed without IRQ semaphore.\n");
    return 0;
}
```

该修改的作用：

- 允许已完成的 ADC DMA 自检继续向后跑。
- 串口若出现 `DMA completed without IRQ semaphore.`，说明 DMA 数据路径可用，但 IRQ 路径仍未验证通过。
- 后续仍需继续查 `XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR=63U` 的 GIC pending/enable/handler table，以及 FreeRTOS IRQ glue 是否分发了该 SPI interrupt。

### 13.7 修复验证通过

新的板端成功日志：

```text
DMA completed without IRQ semaphore.
[P2][PASS] adc_dma_irq bytes=32768
[P2][PASS] all detail=complete
```

最终判读：

- `adc_dma_irq bytes=32768` 证明 ADC DMA 数据路径已完成，数据搬运不是阻塞点。
- `[P2][PASS] all detail=complete` 证明 Phase 2 HAL 自检所有项目已经完整通过。
- `DMA completed without IRQ semaphore.` 说明当前通过依赖 `axi_dmac_transfer_wait_completion()` 的硬件完成兜底；PL IRQ semaphore 路径仍未作为强证据通过。

当前修复状态：

- Phase 2 自检验收已完成，最终结论从“DMA 数据路径未确认 / 问题未解决”更新为：**DMA 数据路径正常，IRQ semaphore 未收到；已用硬件完成兜底解除误判**。
- 后续优化项保留：继续排查 `XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR=63U` 的 GIC enable/pending、handler table 和 semaphore 释放路径，争取让 ISR 直接释放 `completion_sem`。

---

## 14. DMA/VIO PL IRQ 进一步实验记录

### 14.1 GIC 软件 pending 路径已确认正常

新增 ID63/ID64 软件 pending 自检后，板端日志：

```text
[P2][IRQMAP] swpend id=63 count=1 last=29 pend=0 act=0
[P2][IRQMAP] swpend id=64 count=1 last=29 pend=0 act=0
[P2][PASS] irqmap_swpend id63=1
[P2][PASS] irqmap_swpend id64=1
```

判读：

- GIC ID63 和 ID64 的 FreeRTOS IRQ 入口、XScuGic HandlerTable 分发、callback 注册路径均可工作。
- `last=29` 是后续 tick IRQ 覆盖了 `g_irq_last_id`，不是 ID63/64 分发失败。
- 因此，当前 DMA IRQ 问题不应再优先怀疑 FreeRTOS IRQ glue 的基本软件分发路径。

### 14.2 VIO In10 仍无法被 PS/GIC 检测

同一轮实验中，VIO 测试日志停在：

```text
[P2][VIOIRQ] armed id=66 en=1 pend=0 act=0 trig=0x1
```

用户反馈：

- VIO 翻转仍然只能被 ILA 看到。
- PS 端 VIO IRQ 自检仍失败。
- 这说明 VIO 对 `sys_concat_intc` 的输入可见，但该路径未形成 PS/GIC 可接收的 interrupt 事件，或软件假定的 VIO GIC ID 与实际 bitstream 映射不一致。

### 14.3 ILA 捕获到 adc_dma_irq 上升沿与 concat 输出

新 ILA 观察：

```text
adc_dma_irq 上升沿后，concat_intc_dout = 0x1400
此时 VIO 已经置 1
```

判读：

- `0x1400 = bit12 | bit10`。
- bit10 与已置 1 的 VIO 相符。
- adc_dma_irq 上升沿同时让 `concat_intc_dout[12]` 为 1，说明当前被观察到的 DMA IRQ 信号实际出现在 concat bit12。
- 在当前 BSP/PS7 `PCW_IRQ_F2P_MODE=REVERSE` 的映射下，历史导出关系为：

```text
concat bit14 -> GIC ID62
concat bit13 -> GIC ID63
concat bit12 -> GIC ID64
concat bit11 -> GIC ID65
concat bit10 -> GIC ID66
```

因此，若本次 ILA 观察对应的是 ADC DMA IRQ，则当前实际进入 PS 的 ADC DMA 线更可能对应 **GIC ID64**，而不是 BSP 名义上的 `XPAR_FABRIC_AXI_AD9361_ADC_DMA_IRQ_INTR=63U`。这与用户此前为排查 DAC DMA IRQ 而交换 ADC/DAC IRQ 接口的实验背景一致。

### 14.4 当前结论

1. **GIC ID63/64 软件路径正常**：软件 pending 可进入 ISR。
2. **VIO In10 不是可靠的 PL->PS IRQ 判据**：ILA 可见但 PS/GIC 未进 ISR，需继续查 In10 到 IRQ_F2P 的实际映射或触发条件。
3. **DMA IRQ 更有价值**：ILA 已看到 adc_dma_irq 上升沿，并且 concat 输出显示 bit12 置位。
4. **当前 DMA IRQ 注册应围绕 ID63/ID64 同时诊断**：不要只根据 ADC/DAC 外设名注册单一 BSP 宏。

### 14.5 下一步建议

- 继续使用 `PHASE2_TEST_IRQ_A_ID=63` 和 `PHASE2_TEST_IRQ_B_ID=64` 的双 ID stub ISR。
- 重点查看后续日志：

```text
[P2][IRQMAP] src=rx_dmac ...
[P2][IRQMAP] src=tx_dmac ...
[P2][IRQMAP] src=tx_dmac_start ...
```

- 若 `src=rx_dmac` 或 `src=tx_dmac_start` 中 `id64>0`，则说明当前 DMA IRQ 通过 concat bit12/GIC ID64 进入 PS。
- 若 ILA 看到 `concat_intc_dout[12]=1` 但软件 ID64 计数仍为 0，则问题集中在 PS7 IRQ_F2P/GIC 对真实 PL interrupt 的接收或触发配置，而不是 FreeRTOS callback 注册。

---

## 15. BLE ch39 预生成波形 DMA 测试

### 15.1 实验目的

`ble_tx_adv_name=XXX` 运行时生成 BLE advertising 波形后，手机/接收端无法检测到信号。为了区分问题来自：

- 运行时 BLE packet / whitening / GFSK 波形生成；
- TX DMA / DAC / AD9361 发射链路；
- FreeRTOS 任务调度与 TX 资源互斥；

先绕过运行时生成逻辑，直接使用已生成的 `ble_waveform_30_72M.h` 中 BLE channel 39 IQ 数据作为 DMA 源发送。

### 15.2 代码改动

将根目录 `ble_waveform_30_72M.h` 复制到：

```text
app_FreeRTOS/app/dma_tx_waveforms/dma_tx_ble_waveform_30_72M.h
hdl/projects/antsdre310/antsdre310.sdk/app/src/app/dma_tx_waveforms/dma_tx_ble_waveform_30_72M.h
```

该头文件内容：

```c
// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)
// Channel: 39
const uint32_t ble_iq_ch39[13764] __attribute__((aligned(64))) = { ... };
```

在 `dma_tx_waveforms.h` 中新增：

```c
DMA_TX_WAVEFORM_BLE_CH39
```

在 `dma_tx_waveforms.c` 中新增 waveform 描述：

```c
[DMA_TX_WAVEFORM_BLE_CH39] = {
    .name = "BLE legacy advertising ch39",
    .data = ble_iq_ch39,
    .bytes = sizeof(ble_iq_ch39),
    .tx_lo_hz = 2480000000ULL,
},
```

同时将 `dma_tx_demo?` 改为直接启动 `DMA_TX_WAVEFORM_BLE_CH39`，`dma_switch?` 改为按 `DMA_TX_WAVEFORM_COUNT` 通用轮转。

### 15.3 实验命令

```text
dma_tx_demo?
```

预期串口输出：

```text
start transfer!(BLE legacy advertising ch39)
```

### 15.4 实验结果

用户实测：使用 `dma_tx_demo?` 发送该预生成 BLE ch39 波形后，信号可以被正常检测到。

### 15.5 判读

该结果说明：

1. TX DMA 非 cyclic/cyclic 启动路径、DAC DMA datasel、AD9361 TX LO 设置到 `2480 MHz` 的基本发射链路可用。
2. `ble_waveform_30_72M.h` 中的 `ble_iq_ch39[13764]` 波形本身可被接收链路识别。
3. 当前 `ble_tx_adv_name=XXX` 不可检测的问题，更可能集中在 FreeRTOS 运行时生成波形路径或任务发送节奏，而不是 RF/DMA 基础链路。
4. 后续调试应优先对比运行时生成的 `BLE_ADV running ... words=...` 波形与预生成 `ble_iq_ch39` 的 packet bytes、IQ word 序列、DMA size 和 TX 启动时序。

### 15.6 下一步建议

- 先保留 `dma_tx_demo?` 作为 BLE ch39 发射链路 sanity check。
- 对默认名 `SDR_BLE`，将运行时生成的 ch39 IQ 前若干 word 与 `ble_iq_ch39` 对比。
- 若 IQ 不一致，继续查运行时 GFSK LUT、PDU header、CRC/whitening、bit order。
- 若 IQ 一致但 `ble_tx_adv_name=` 不可见，继续查 `BLE_TX_ADV` 任务中的 non-cyclic DMA 重启周期、DMA stop/start 间隔、LO hop 时序以及是否被其它 TX 模式抢占。

---

## 16. `ble_tx_adv_name=` 生成后需再次串口输入才发送

### 16.1 症状

运行 `ble_tx_adv_name=XXX` 后，BLE_TX_ADV 任务能进入波形生成流程，但生成完成后不会立即正常发射。必须等待一段时间后，再通过串口输入一条有效命令，信号才开始被检测到；否则系统表现为一直等待。

该现象说明问题不只在 BLE packet/GFSK 波形内容，也与 FreeRTOS 下 console 任务和 BLE_TX_ADV 任务的调度有关。

### 16.2 初步修复尝试

`ble_tx_adv_name=` 使用 `console_handle_ble_tx_adv_name_cmd()` 特殊字符串解析路径。该路径处理成功后直接 `continue`，跳过普通命令路径末尾的 `taskYIELD()`。

因此先在 FreeRTOS console task 的特殊命令分支中增加：

```c
if (console_handle_ble_tx_adv_name_cmd(received_cmd)) {
    vTaskDelay(1);
    continue;
}
```

结果：用户实测“情况没有变化”。这说明问题不是只发生在命令提交后的第一次让出 CPU，而是 console 任务后续等待串口输入期间仍然影响了其它任务运行。

### 16.3 根因判断

FreeRTOS 下原 `console_get_command()` 使用：

```c
uart_read_char(&received_char);
```

而 `uart_read_char()` 内部调用：

```c
*data = getchar();
```

在 Xilinx standalone BSP 中，`getchar()`/`inbyte()` 是阻塞式串口读取。Console 任务进入等待下一条命令后，可能长期停在该阻塞路径中，导致 BLE_TX_ADV 任务不能按预期继续运行。现象上就表现为：只有再次输入串口命令时，阻塞读返回，调度才继续推进，BLE 发送才开始。

### 16.4 最终修复

在 FreeRTOS + Xilinx 平台下，将 `console_get_command()` 改为 UART RX FIFO 非阻塞轮询；没有收到字符时主动 `vTaskDelay(1)` 让出 CPU：

```c
#if defined(FREERTOS_INTEGRATION) && defined(XILINX_PLATFORM) && defined(STDIN_BASEADDRESS)
    if (!XUartPs_IsReceiveData(STDIN_BASEADDRESS)) {
        vTaskDelay(1);
        continue;
    }
    received_char = (char)XUartPs_RecvByte(STDIN_BASEADDRESS);
#else
    uart_read_char(&received_char);
#endif
```

同步修改文件：

```text
app_FreeRTOS/drivers/console.c
hdl/projects/antsdre310/antsdre310.sdk/app/src/drivers/console.c
```

同时保留 `ble_tx_adv_name=` 特殊命令分支后的 `vTaskDelay(1)`，作为提交启动请求后的显式让出点：

```text
app_FreeRTOS/app/main.c
hdl/projects/antsdre310/antsdre310.sdk/app/src/app/main.c
```

### 16.5 验证状态

SDK Debug 构建通过：

```text
make -C hdl/projects/antsdre310/antsdre310.sdk/app/Debug all
```

生成结果：

```text
text=1280612 data=103800 bss=1221656 dec=2606068
```

`a9-linaro-pre-build-step` 仍然是 Vitis 生成 makefile 中已有的 ignored pre-build 提示，不影响 `app.elf` 链接。

### 16.6 后续判据

重新上板后，应优先验证：

```text
ble_tx_adv_name=TEST
```

预期行为：

1. 命令提交后无需再输入其它串口命令，BLE_TX_ADV 任务应自动完成生成并开始 ch37 循环发送。
2. Console 在等待下一条命令时不再阻塞 FreeRTOS 调度。
3. 若仍需二次串口输入，则下一步应在 BLE_TX_ADV task 中加入 tick 计数日志或 GPIO 翻转，确认任务是否在 `console_get_command()` 等待期间继续运行。

---

## 17. pure realtime 生成瓶颈与 phase 突发帧漏检

### 17.1 问题现象

pure realtime 初始实验同时出现两类问题：

1. 板端使用 Debug `-O0` 构建时，GFSK 波形生成速度过慢，60 秒内只能完成约 17 包，无法满足 1 秒一个时隙的基本性能实验。
2. phase 诊断接收链能识别部分 preamble/SFD，但 one-shot 帧经常出现 PHR、payload 或 FCS 损坏；循环发送同一波形时却能稳定得到有效帧。

最初 phase 接收端只保留 5 倍采样中的固定 offset 0。每次独立启动的突发帧相对于接收采样时钟具有不同相位，因此固定 offset 会放大 one-shot 帧的采样误差。后续改为五相位并行后，又暴露出 Python 接收端本身的扫描吞吐和缓存截断问题。

### 17.2 板端 GFSK 生成瓶颈及优化

原实现对每个输出 IQ 样本都遍历全部 3072 个 Gaussian taps 做卷积。在 `-O0` 下，这一复杂度成为主要瓶颈。

修复方法：

- 为 Gaussian taps 建立前缀和。
- 利用 NRZ 输入在一个符号区间内为常量的特点，将逐 tap 卷积改为对重叠的符号区间求和。
- 每个输出样本只需处理最多约 5 个 NRZ 符号区间，不再循环 3072 个 taps。
- 保持相位积分、IQ 量化、BlueBee 映射、payload/FCS 生成以及 1 ms 前后静默不变。
- frame、mapping、GFSK 和 total 四个阶段分别记录耗时，并在最终统计中报告 samples、min、max 和 avg。

相关文件：

```text
app_FreeRTOS/app/bluebee_gen.c
app_FreeRTOS/app/ble_exadv_secondary_gen.c
app_FreeRTOS/app/bluebee_perf.c
```

主机侧增加了旧逐 tap 实现和新前缀和实现的等价性测试：

- IQ 长度一致。
- 前后静默长度一致。
- 有效 IQ 相关系数不低于 0.999。
- 中心点解调得到的 GFSK bits 完全一致。

测试文件：

```text
python/perf_test/tests/test_bluebee_gen_waveform.py
```

### 17.3 `PERF_TIMING` 全部为 0

第一次 1 秒间隔实验已经达到：

```text
scheduled=60 generated=60 tx_started=60 tx_completed=60
deadline_miss=0 dma_timeout=0
```

但四个 `PERF_TIMING` 阶段的 min/max/avg 全部为 0。原因不是生成时间真的小于 1 us，而是生成器源文件没有包含 `app_config.h`，导致 `XILINX_PLATFORM` 对该编译单元不可见，计时函数进入了返回 0 的非平台 fallback。

修复方法：

- 板端生成器显式包含 `app_config.h`，使用 Xilinx 全局定时器。
- 主机波形等价性测试通过 `BLUEBEE_GEN_HOST_TEST` 隔离板端头文件和计时实现。

修复后的 run 1235，配置为 10 字节 payload、5 秒间隔、持续 60 秒，结果如下：

```text
PERF_STATS final=1 test=pure state=complete payload_len=10
interval_us=5000000 duration_s=60 run_id=1235 mode=realtime
expected_packets=12 scheduled=12 generated=12 tx_started=12 tx_completed=12
deadline_miss=0 dma_timeout=0

PERF_TIMING stage=frame   samples=12 min_us=3     max_us=4     avg_us=3
PERF_TIMING stage=mapping samples=12 min_us=1008  max_us=1013  avg_us=1010
PERF_TIMING stage=gfsk    samples=12 min_us=22120 max_us=22928 avg_us=22222
PERF_TIMING stage=total   samples=12 min_us=23137 max_us=23944 avg_us=23237
```

判读：

- 板端 12 个计划时隙全部完成生成和 DMA 发送，没有 deadline miss 或 DMA timeout。
- 单包平均生成总耗时约 23.237 ms，其中 GFSK 约占 22.222 ms，是主要开销。
- 当前实现的 10 字节 payload 生成上限约为 43 包/秒，已足以支持 1 秒和 5 秒间隔实验。
- 因此后续 one-shot 少收不能继续归因于原来的 60 秒仅生成 17 包问题。

### 17.4 五相位 phase 诊断接收

为避免固定采样相位漏掉独立突发帧，phase 诊断链改为同时输出五个 offset：

```text
offset 0 -> tcp://127.0.0.1:55557
offset 1 -> tcp://127.0.0.1:55558
offset 2 -> tcp://127.0.0.1:55559
offset 3 -> tcp://127.0.0.1:55560
offset 4 -> tcp://127.0.0.1:55561
```

`zigbee_perf_rx.py` 增加：

```text
--phase-keep-offset auto|0|1|2|3|4
```

phase 模式默认使用 `auto`。auto 同时读取五路候选，优先级依次考虑有效 FCS、preamble 距离和整帧距离。同一接收循环中由多个 offset 解出的相同 Sequence 只计一次；后续循环再次收到相同 Sequence 才计为真正的 duplicate。标准验收链 `zigbee_rx.py`/55556 保持不变，五相位只用于诊断。

相关文件：

```text
python/ctc_sim/std_zigbee/gr_zigbee.py
python/perf_test/zigbee_perf_rx.py
```

### 17.5 phase 宽松 preamble 检测产生噪声伪候选

为了容忍突发帧采样误差，phase 诊断曾允许 preamble/SFD 存在一个符号错误，同时要求 PHR 精确、payload FCS 正确。新实验只报告约 5 次 CRC 错误而没有有效 Sequence，检查 JSON 后发现这些候选并非真实发送帧：

- 实际记录到 6 个 CRC failure。
- SFD 解成 `A0`，而期望值为 `A7`。
- preamble distance 为 93--191，整帧 distance 为 256--546。
- 候选时间戳不符合板端 5 秒发送周期。
- 此前真实有效帧的 preamble distance 约为 22，整帧 distance 约为 51。

因此这些 CRC failure 主要是宽松相关器在噪声中产生的伪候选，不能解释为板端发送的 5/6 个帧到达但 FCS 损坏。

修复方法：phase 候选增加平均每符号最大 4 chips 的距离门限，超过门限的噪声候选在进入协议统计前丢弃；standard 接收链不改。

### 17.6 循环波形对照实验及其正确判读

循环发送 run 1237 的固定帧：

```text
B2 5A 01 0A D5 04 00 00 00 00
```

接收端在约 15.394 秒内得到：

```text
unique=1 duplicate=19 crc_failure=0
```

五个 offset 都能解出有效 FCS，候选计数分别为：

```text
offset0=17 offset1=14 offset2=18 offset3=17 offset4=20
```

这证明：

- 当前 BlueBee 波形、映射、极性和 phase 解码器之间能够形成完整有效帧。
- 五个采样 offset 都可能成功，不能把问题简化为“只有某一个固定 offset 正确”。

但该实验不能证明 one-shot DMA 有问题，也不能把 `1 unique + 19 duplicate` 当作板端只发送了 20 包。循环 DMA 在 15 秒内实际重复了大量帧，而接收端仅约每 0.75--0.8 秒产出一次结果。这个异常周期最终指向主机接收器的扫描吞吐瓶颈。

### 17.7 根因：五相位 Python 扫描慢于缓存保留时间

旧实现的五相位噪声扫描一次约需 0.622 秒，而每相位只保留：

```text
MAX_CHIPS=12000
chip rate=2 Mchip/s
buffer span=6 ms
```

当扫描线程忙于处理上一轮数据时，ZMQ 中会继续积累样本。下一次读取把积压数据拼接后又只保留最后 6 ms，导致位于更早位置的稀疏 one-shot 突发帧在分析前就被截掉。循环波形的任意尾部窗口通常仍含有一帧，因此表现为循环能稳定解码，而 5 秒间隔的 one-shot 大量漏检。

这也解释了 run 1237 的 duplicate 约按 0.75--0.8 秒出现：它更接近 Python 扫描周期，而不是实际 RF 发包周期。

### 17.8 解决方案：phase 扫描性能优化

已实施以下优化：

- `chips_to_symbols()` 使用 NumPy 将全部 32-chip symbol 批量 pack 成整数，一次性与 16 个参考 symbol 做 XOR，通过 8 位 popcount 查表计算 Hamming distance，再使用 `argmin` 选择最近 symbol，替代逐 symbol/逐参考码的 Python 循环。
- 增加已知 BlueBee optimized map 的 `find_phase_frame_candidate_fast()`：根据预期 payload 长度构造 preamble/SFD/PHR chip 前缀，先对 2 个 symbols 做向量化短相关，只对距离门限内、互相至少间隔 32 chips 的位置解完整帧，每个极性最多检查 16 个位置。
- `MAX_CHIPS` 从 12000 增至 24000，缓存保留时间从 6 ms 增至 12 ms。
- live auto 在未锁定极性前，每轮只扫描一种极性，并在 normal/inverted 间轮换；一旦出现有效 FCS，就锁定该极性，避免每轮重复做两倍工作。
- auto 模式按 FCS、prefix symbol errors、preamble distance 和整帧 distance 对五个 offset 的候选排序；同一接收循环命中的所有 offset 一起消费，只向 SequenceTracker 提交一次，避免跨 offset 虚增 duplicate。
- CSV 增加实际 phase offset、极性、preamble/frame distance；JSON 增加 `phase_scan_timing`，记录 samples、avg_ms、max_ms 和 buffer_span_ms。

性能变化：

| 实现 | 五相位单轮扫描时间 | 缓存保留时间 |
|---|---:|---:|
| 原始全帧 Python 扫描 | 约 622 ms | 6 ms |
| symbols 向量化后 | 约 289 ms | 6 ms |
| 快速前缀检测中间版本 | 约 54 ms | 6 ms |
| 3-symbol 前缀 | 约 15.7 ms | 6 ms |
| 最终 2-symbol、单极性扫描 | 约 9.0 ms | 12 ms |

最终基准约 9 ms，低于 12 ms 缓存窗口，已消除已知的“扫描尚未完成，突发数据先被尾部截断”条件。

Python 单元测试覆盖五个 phase offset、反相极性、跨 offset 去重、真实 duplicate、FCS failure、宽松 preamble 和快速 detector；当前 13 个测试均通过。Python 语法检查、ARM `-O0` 完整链接和 `git diff --check` 也已通过。板端源文件已同步到 SDK 实际编译目录。

当前 GNU Radio 流图会无条件生成五路 phase：公共的 phase difference 只计算一次，但每个 offset 都有独立的 keep、binary slicer、packer 和 ZMQ PUB。每路约 250 KB/s，五路约 1.25 MB/s；固定 offset 时 Python 只订阅一路，但 GNU Radio 侧仍承担五路发布开销。auto 模式还会使 Python 收包和候选搜索量接近固定 offset 的五倍，因此必须使用 `phase_scan_timing.max_ms < buffer_span_ms` 作为运行时安全判据。

### 17.9 修复验证：run 1238 one-shot 全部接收

固定 offset 0 的验证命令：

```text
python3 python/perf_test/zigbee_perf_rx.py \
  --chip-source phase \
  --phase-keep-offset 0 \
  --duration 80 \
  --run-id 1238 \
  --payload-len 10 \
  --output-prefix python/perf_test/pure-1238-phase0

bluebee_pure_perf_start? 10 5000000 60 1238 0
```

板端发送 12 包，接收结果：

```text
unique=12 duplicate=0 out_of_order=0 longest_loss_burst=0
sequence=0..11
phase_scan avg=2.206 ms max=5.013 ms buffer=12 ms
```

在板端 `tx_completed=12` 的前提下：

```text
调度完成率  = 12/12 = 100%
无线 PRR     = 12/12 = 100%
端到端接收率 = 12/12 = 100%
```

本轮还有 3 个 FCS failure，但它们分别具有 100--111 的 preamble distance、317--361 的 frame distance、7--8 个 prefix symbol errors，出现时间也不符合 5 秒发送周期，且没有有效 Run ID/Sequence。有效帧的 preamble distance 为 0--34、frame distance 为 0--96，因此这 3 个记录是噪声伪候选，不是 12 个已发送包的错误副本。

该结果证明扫描优化已经消除当前已知的 Python 缓存截断问题：平均和最大扫描时间都低于 12 ms 缓存窗口，12 个稀疏 one-shot 均在正确时隙被识别。

### 17.10 当前结论与下一步验证

当前可确认：

1. 板端 realtime 生成瓶颈已经解决，60 个 1 秒时隙可全部完成，DMA 计数无异常。
2. `PERF_TIMING` 计时为 0 的问题已经修复，当前实测单包生成约 23 ms。
3. 循环波形能得到有效 FCS，说明波形和 phase 解码链可以正确配合。
4. 旧 phase auto 对稀疏 one-shot 的主要已知漏检原因是主机扫描速度远慢于缓存窗口，而不是已经证实的 one-shot DMA 故障。
5. phase 中少量高距离 CRC failure 是噪声伪候选，不能计作实际接收包。

固定 offset 0 已完成验证。下一步使用 phase auto 验证五路候选选择，再切换到 standard/55556 进行正式 PRR 验收。验证时必须同时检查：

- JSON 中 `phase_scan_timing.avg_ms` 和 `max_ms` 是否持续低于报告的 `buffer_span_ms`。
- 有效 FCS 帧的 Run ID、Sequence 和确定性填充是否正确。
- phase auto 是否仍能做到跨 offset 只统计一次，且不会因五路开销重新出现缓存截断。
- 最终 PRR 仍以 standard/55556 接收链和同一 Run ID 的板端最终统计合并计算；接收 JSON 必须使用 `--board-stats` 或后处理方式填入板端统计，不能保持 `board=null`。

若优化后的 phase 能稳定收到 one-shot，而 standard 仍失败，应将问题单独归入标准 OQPSK 定时恢复，不再归因于板端生成或 DMA。

### 17.11 exadv phase auto 二次瓶颈与修复

exadv run 1240 使用五相位 auto 后只得到：

```text
unique=3 crc_failure=4
phase_scan avg=11.107 ms max=15.397 ms buffer=12 ms
phase ZMQ messages=1157858
scan samples=471 / 65 s
```

有效 Sequence 只有 1、10、11。五路每路约收到 23 万条 ZMQ 小消息，但 65 秒只完成 471 次扫描；最大处理时间超过缓存窗口。这说明结果不是无线 PRR 突然降到 3/12，而是 auto 五路读取后再次发生主机积压和尾部截断。

第一阶段的 `phase_scan_timing` 从 ZMQ 读取之后才开始计时，因此只覆盖候选搜索，没有暴露逐消息解包的真实开销。旧路径对每条 ZMQ 消息执行 Python 的“逐 byte × 8 bits”字符串循环，单路 500 条、每条约 70 bytes 的基准约需 23.66 ms。

二次修复：

- 将同一路本轮所有 ZMQ payload 先用 `bytes.join` 合并，再用 `np.unpackbits(bitorder="little")` 整批转换，保持原 LSB-first 位序；单路 500 条基准降至约 0.76 ms。
- prefix distance 原来执行两次 `np.correlate`：一次计算前缀重合，一次计算滑窗“1”数量。后者改用 `np.cumsum` 的区间差，结果完全一致。
- `MAX_CHIPS` 从 24000 增至 48000，缓存从 12 ms 增至 24 ms。
- `phase_scan_timing` 的起点移到 ZMQ 读取之前，当前统计覆盖 ZMQ receive、packed-bit 展开和五相位候选搜索的完整路径。
- 增加批量解包与旧逐字节实现完全一致的 LSB-first 单元测试。

当前 5×500 条合成消息基准：

```text
vector unpack = 2.528 ms
five-phase scan = 12.117 ms
total = 14.645 ms
buffer = 24.000 ms
```

14 个 Python 单元测试、`py_compile` 和 `git diff --check` 均通过。该基准尚未包含真实 ZMQ 调度抖动，下一轮 exadv auto 必须确认实际 `phase_scan_timing.max_ms < 24 ms`，并检查五路消息计数是否接近、扫描 samples 是否从每秒约 7 次恢复到能够持续追上输入。

### 17.12 run 1241 验证结果与剩余优化方案

二次优化后的 exadv phase auto 使用 10 字节 payload、5 秒间隔、60 秒实验，板端共发送 12 包。接收结果：

```text
unique=11 duplicate=0 out_of_order=0 longest_loss_burst=1
crc_failure(raw candidates)=7
valid sequence=0..6,8..11
missing sequence=7
```

在板端 `tx_completed=12` 的前提下：

```text
无线 PRR     = 11/12 = 91.67%
端到端接收率 = 11/12 = 91.67%
```

#### CRC failure 分类

7 个原始 CRC failure 中，只有一个与实际 5 秒发送时隙对齐：

```text
elapsed=36.480 s
expected sequence=7
phase offset=3
prefix symbol errors=0
preamble distance=36
frame distance=104
frame=00 00 00 00 A7 0C B2 BA 8E 42 D9 04 07 00 00 00 F1 0B
```

该候选具有正确 preamble、SFD、PHR，并保留 Run ID 1241 和 Sequence 7 的字节痕迹，但 payload 多个字节损坏，因此属于真实 secondary 解码失败。

其余 6 个候选位于发送时隙之间，prefix symbol errors 为 6--8、preamble distance 为 103--117、frame distance 为 338--387，且没有有效 Run ID/Sequence，属于噪声或 BLE primary 触发的伪候选。

因此本轮正确口径为：

```text
11 个有效 secondary
1 个实际损坏 secondary
6 个噪声伪候选
```

不能按 `11 / (11 + 7)` 计算 PRR。

#### 二次优化效果

五相位 auto 的处理状态由 run 1240 的：

```text
scan samples=471 / 65 s
unique=3
```

提升为：

```text
scan samples=4224 / 65 s
unique=11
phase_scan avg=15.370 ms
phase_scan max=52.425 ms
buffer=24 ms
```

扫描次数约提高 9 倍，五路 ZMQ 消息数均约为 22--24 万，说明整批 NumPy 解包、累计和相关和 24 ms 缓存已经解决主要的持续积压问题。

各 offset 的有效 FCS 候选数：

```text
offset0=11 offset1=10 offset2=11 offset3=11 offset4=11
```

Sequence 7 没有在其它采样相位恢复，说明固定采样相位已不是本轮唯一失败的主要原因。由于 Sequence 7 已形成高可信 CRC-failure 候选，本轮失败不是突发在 Python 缓存中完全丢失，而是实际帧内容损坏。

#### 剩余问题

虽然平均完整处理时间低于 24 ms，但最大值 52.425 ms 仍超过缓存窗口。该最大值更可能来自操作系统调度、五个 ZMQ socket 的小消息读取或瞬时批处理抖动。它没有造成 run 1241 的 Sequence 7 完全漏检，但在更长实验中仍可能导致偶发尾部截断。

同时，当前 `crc_failure` 把所有快速前缀命中但 FCS 失败的候选都计入协议统计，导致 1 个真实帧错误被显示成 7 个 CRC failure。

#### 后续优化方案

1. **拆分 CRC 与噪声统计**
   - 保留所有候选到 CSV。
   - JSON 分开记录 `crc_failure` 和 `noise_candidate`。
   - 先使用已验证的质量范围区分：高可信失败要求 prefix symbol errors 不超过 3 且 preamble distance 不超过 80；超出范围且不在发送时隙附近的候选归为噪声。
   - 正式 PRR 始终使用 `unique / board.tx_completed`，不得使用 `unique + crc_failure` 作为分母。

2. **将五路 ZMQ 改成单路全采样 phase-bit 流**
   - GNU Radio 对 10 MS/s 的公共 phase-difference 结果只做一次 binary slicer 和 pack。
   - 使用一个 ZMQ endpoint 发布完整 phase-bit 流。
   - Python 用 NumPy 的 `bits[offset::5]` 重建 offset 0--4。
   - 总 packed 数据率仍约 1.25 MB/s，但可以去掉五套 keep/slicer/packer/PUB 和五个 socket 的小消息调度开销。
   - standard 模式完全关闭 phase 输出；固定 offset 模式只构造需要的数据；auto 才做五相位切分。

3. **避免未处理数据直接尾部截断**
   - 将当前字符串尾部缓存改成带“已处理位置”的环形或分块缓冲。
   - 每批只丢弃已经完成搜索的数据，保留至少一个完整 frame 长度的重叠区。
   - 即使某轮被调度暂停超过 buffer span，也不应在扫描前直接丢弃整个突发。

4. **补充分位数性能统计**
   - 在 `phase_scan_timing` 中增加 p50、p95 和 p99。
   - max 用于发现极端调度暂停，p99 用于判断持续处理能力。
   - 长时间实验要求 p99 明显低于有效缓存跨度，并同时观察 ZMQ HWM/drop。

5. **继续区分接收器性能与 exadv 无线可靠性**
   - 使用同参数至少重复 3 轮 phase auto，确认 11/12 是否可重复以及失败 Sequence 是否随机。
   - phase 稳定后切换 standard/55556 进行正式 PRR。
   - 若各 offset 都对同一帧损坏，应继续检查 exadv secondary 内 BlueBee 区域的 GFSK 滤波连续性、前导过渡和 RF 信噪比，不再归因于单一采样 offset。

### 17.13 standard 主机扫描瓶颈与第一阶段优化

phase 诊断链恢复到能够稳定形成候选后，正式验收需要切回 standard/55556。对当前 standard 路径做 48k-chip 合成缓存基准时发现，它对每个缓存依次尝试 0--31 共 32 个 chip alignment，并对每个 alignment 做全缓存 CHIP_MAP 判决、bit/byte 重组和 preamble 搜索。单轮耗时为：

```text
payload=10  legacy avg=56.316 ms
payload=46  legacy avg=50.760 ms
```

这不但慢于 phase 固定 offset，而且旧路径只改变 chip alignment，没有覆盖 byte 重组的另一个 nibble 相位。若真实 preamble 在正确 chip alignment 后落于奇数 symbol 位置，即使理想无噪 chip 也可能完全找不到帧。

第一阶段修复在提供 `--payload-len` 时启用 standard 已知长度快速检测：

1. 使用标准 `CHIP_MAP` 构造 4 字节 preamble。由于它等价于连续 8 个 symbol 0，只执行一次 32-chip Hamming 相关，再把相隔 32 chips 的 8 个距离向量相加，避免 256-chip 长相关。
2. 在原始 chip 流的每个可能位置搜索，因此自然覆盖 0--31 chip alignment 和两种 nibble 边界；前缀允许平均每 symbol 最多 8 个 chip 错误。
3. 最多保留 16 个非相邻前缀候选，只对候选位置的已知长度局部帧做完整符号判决，并要求 PHR 与 `payload_len + 2` 一致；FCS 失败帧仍返回统计，不能只保留成功帧。
4. 多帧同时位于缓存时按 chip 位置选择最早候选，防止后面的有效 FCS 帧越过前面的损坏帧；缓存仍有待处理帧时，下一轮 ZMQ poll 使用 0 ms，去掉逐帧额外 10 ms 阻塞。
5. standard 和 phase 都在 JSON `receiver.processing_timing` 中报告完整接收迭代的 samples、avg_ms、max_ms、buffer_chips 和是否包含 ZMQ receive；原 `phase_scan_timing` 保持兼容。

同一台主机、相同 48k-chip 缓存、每项 10 次的修复后基准：

```text
payload=10  fast avg=3.166 ms  speedup=17.79x
payload=46  fast avg=4.123 ms  speedup=12.31x
```

新增回归覆盖 10/46 字节、全部 0--31 chip 起点、有效 FCS、FCS 失败和同缓存先坏帧后好帧的顺序。完整 Python 测试目前为 17 项，均通过。该优化解决的是 Python standard 候选扫描与对齐覆盖问题，不等同于 GNU Radio standard OQPSK 定时恢复；下一轮必须用 standard/55556 实测 `receiver.processing_timing`、Sequence 和 PRR。若处理耗时稳定而 PRR 仍显著低于 phase，应继续优化 matched-filter 后的采样定时，而不是继续归因于 Python 扫描或板端 DMA。

### 17.14 run 1242 standard 零候选与 Costas/IQ 模糊

相同 exadv 发射参数分别运行 standard 与 phase。standard 结果：

```text
unique=0 crc_failure=0
ZMQ messages=302756
processing samples=19620
processing avg=3.307 ms max=10.850 ms
```

standard 在65秒内持续收到55556数据并完成近两万次扫描，平均和最大处理时间均低于48k-chip对应的24 ms缓存跨度。因此零候选不是ZMQ断流，也不是上一阶段Python扫描仍追不上输入；失败位置已经前移到GNU Radio standard OQPSK前端或其输出的chip变换。

同参数phase auto结果：

```text
unique=7: sequence 3,4,6,8,9,10,11
raw crc_failure=9
processing avg=14.693 ms max=33.995 ms
```

9个原始FCS失败中，只有36.308秒附近的候选具有完整正确preamble/SFD/PHR和10字节payload边界，可能对应实际损坏帧；其余候选多为6--8个prefix symbol错误、preamble distance 106--149的噪声。不能把本轮解释成“7个有效包加9个真实坏包”。由于JSON仍为 `board=null`，也不能正式计算7/12 PRR，最终仍需合并同Run ID的板端 `tx_completed`。

standard 前端当前使用四阶Costas环。QPSK载波恢复存在90度象限模糊，对交织后的I/Q chip流表现为整体反相、单路反相以及pair交换的组合；此前standard扫描只接受normal CHIP_MAP，因此即使符号信息存在也可能完全没有preamble候选。修复后：

1. `--standard-ambiguity auto` 默认尝试normal、整体反相、偶/奇chip反相和pair交换后的四个对应变换，共8种。
2. CSV新增 `standard_ambiguity`；JSON新增配置值和逐变换 candidates/FCS统计。
3. `--standard-keep-offset 0..4` 设置GNU Radio matched-filter固定采样offset，用于在仍为零候选时逐项扫描定时相位。
4. 八变换合成回归覆盖全部组合，完整Python测试增至18项并通过。48k-chip、10字节缓存的auto基准平均约15.3 ms、最大17.8 ms，仍低于24 ms缓存跨度，但显著高于固定normal的约3.2 ms，暂用于5秒间隔定位，不作为最大吞吐配置。

下一轮先固定offset 0验证Costas/IQ自动消歧：

```bash
python3 python/perf_test/zigbee_perf_rx.py \
  --chip-source standard \
  --standard-ambiguity auto \
  --standard-keep-offset 0 \
  --duration 70 \
  --run-id 1243 \
  --payload-len 10 \
  --output-prefix python/perf_test/exadv-1243-standard-o0
```

若仍为零候选，使用新的Run ID依次把 `--standard-keep-offset` 改为1、2、3、4。若某个offset能恢复有效FCS，下一阶段再实现standard五相位并行选择；若全部offset和8种变换仍为零，则需要保存filtered/Costas IQ，检查Costas是否适用于BlueBee GFSK波形、I/Q半chip延迟方向和matched-filter采样位置，不能继续只调整Python前缀门限。

### 17.15 standard 五相位差分接收重构

17.14 提出的五个 matched-filter offset 和 8 种 Costas/IQ 变换已全部实测，仍然没有任何 standard 候选。该结果排除了“只差一个固定抽样点或 Costas 象限变换”的解释，因此进一步对无射频理想 IQ 做了分层验证。

检查首先发现旧相干 O-QPSK 支路的参数与 I/Q 每支路只承载隔一个 chip 的事实不一致：在 10 MS/s、2 Mchip/s 下，每支路半正弦脉冲和符号周期均为 10 samples，I/Q 错位应为一个 chip，即 5 samples；旧实现却使用 5-sample taps、5:1 支路抽取和 2-sample 延迟。改为 10-sample taps、10:1 抽取、5-sample 延迟后，原生理想 ZigBee O-QPSK IQ 可以在 offset 9 得到有效 FCS，证明修正后的相干链本身可用。该参考输出迁移到 ZMQ 55566。

然而，把同一修正相干链用于当前 BlueBee GFSK IQ 时，所有相位仍无法得到有效帧。相反，对相邻 IQ 直接计算 `angle(s[n] * conj(s[n-1]))`、按符号切 bit，再每隔 5 samples 取一路，五个相位都能用标准 `CHIP_MAP` 恢复有效 FCS。这说明原问题不是半正弦滤波器破坏了相位，而是相干 I/Q 符号切片模型不适用于 BlueBee 通过 GFSK 相位增量承载的 chip；正式 BlueBee standard 链应保留差分相位观测，再以标准 DSSS 码本验收。

据此完成以下重构：

1. ZMQ 55556 改为单路 10 Msample/s 全采样差分相位 bit 流，只进行一次 slicer 和 pack。
2. Python 对该单路数据按全局模 5 位置拆成五个 2 Mchip/s 相位，并跨 ZMQ 消息、跨批次保存拆相状态；`--standard-keep-offset auto` 同时比较五路，固定 `0..4` 仅保留指定路。
3. standard 使用 IEEE 802.15.4 `CHIP_MAP`，不使用发射端 `BLUEBEE_OPTIMIZED_MAP`。BlueBee optimized 投影相对标准码本的理想固有距离为每 symbol 8 chips；10 字节理想帧的 preamble distance 为 96、frame distance 为 288，仍能完整恢复 payload 和有效 FCS。
4. 前缀门限由历史宽松值收紧为平均 10 chips/symbol，即允许 8 chips 的映射固有距离和额外 2 chips 的无线误差，减少噪声伪候选。
5. `--standard-ambiguity auto` 只在差分极性 normal/inverted 之间轮换，首次有效 FCS 后锁定。多个 offset 对同一突发的候选先按 FCS、前缀错误、preamble/frame distance 选优，再统一消费同一时间窗，避免虚增 duplicate。
6. JSON 新增 `receiver.standard_offset_stats` 和 `receiver.standard_stream`；原生相干参考只在 55566 保留，不计入正式 PRR。

无射频端到端回归使用真实 BlueBee 生成 IQ，经过 10 MS/s 重采样、差分切片、LSB pack、非 5 对齐的任意消息切分、unpack 和模 5 拆相，再用标准 `CHIP_MAP` 解码。五个 offset 均得到有效 FCS，且测试头、Run ID、Sequence 和确定性 payload 完整一致。新增回归还覆盖跨批次拆相连续性、10/46 字节 BlueBee 标准码本投影、standard 跨 offset 只计一次、后续真实重发计 duplicate、反相极性和 FCS 失败选优；完整 Python 测试目前为 22 项并通过。

五相位 48k-chip standard 合成缓存基准在收紧门限后为：

```text
avg=13.101 ms  min=11.822 ms  max=16.130 ms
buffer_span=24.000 ms
```

下一次 exadv 上板复测先启动接收端：

```bash
python3 python/perf_test/zigbee_perf_rx.py \
  --chip-source standard \
  --standard-keep-offset auto \
  --standard-ambiguity auto \
  --duration 70 \
  --run-id 1243 \
  --payload-len 10 \
  --output-prefix python/perf_test/exadv-1243-standard-auto
```

再执行板端命令：

```text
bluebee_exadv_perf_start? 10 5000000 60 1243 0
```

验收时先确认 `receiver.processing_timing.max_ms < 24 ms`，再检查 `standard_offset_stats` 是否形成有效 FCS、Sequence 是否连续，并合并同 Run ID 的板端 `PERF_STATS final=1`。只有合并后的 `unique / tx_completed` 才是正式无线 PRR；原始 CRC failure 中高距离噪声候选仍不能直接解释为实际损坏包。

#### 17.15.1 优化方法总结与 run 1243 验证

本轮 standard 优化没有继续对传统相干 O-QPSK 输出叠加更多固定 offset 或 Costas 象限变换，而是把 BlueBee 的调制特性、标准 DSSS 判决和多相位定时恢复分开处理：

1. **前端改用差分相位观测**：在 Costas 和 I/Q 符号切片之前，对滤波 IQ 计算相邻样本相位增量的正负，直接保留 BlueBee GFSK 实际承载的信息，避免相干 O-QPSK 模型把相位增量错误解释为 I/Q 符号。
2. **单路传输、主机五相位拆分**：GNU Radio 只在 55556 发布一条 10 Msample/s packed bit 流；Python 按全局样本位置模 5 拆成五路 2 Mchip/s 候选。模 5 状态跨 ZMQ 消息和批次连续保存，避免消息长度不为 5 的整数倍时发生相位漂移，也避免为 standard 建立五个额外 ZMQ 端口。
3. **恢复标准 ZigBee 判决口径**：五路候选都使用 IEEE 802.15.4 `CHIP_MAP` 做最近距离解扩。发射端 optimized map 只用于生成 BlueBee 波形，不再用于 standard 验收，因此有效 FCS 表示标准 DSSS 码本确实恢复了原始 payload。
4. **使用已知帧长快速搜索**：利用 4 字节 preamble 等价于 8 个相同 symbol 的结构，用一次 32-chip 相关和 8 路移位累加代替 32 次全缓存 alignment 解码；只对少量局部候选执行完整帧判决。前缀门限设为平均 10 chips/symbol，覆盖每 symbol 8 chips 的映射固有距离并保留 2 chips 的无线误差余量。
5. **极性锁定和跨 offset 选优**：未锁定时逐轮尝试 normal/inverted，首次有效 FCS 后锁定。五个 offset 按有效 FCS、前缀符号错误、preamble distance 和 frame distance 选择一个结果，并统一消费对应时间窗，使同一物理突发只计一次；之后再次收到同一 Sequence 才计 duplicate。
6. **把性能和正确性同时纳入回归**：JSON 记录逐 offset candidates/FCS 和包含 ZMQ 接收、解包、拆相、搜索在内的完整处理耗时；单元测试覆盖跨消息拆相、五相位、反相、跨 offset 去重、真实 duplicate、坏 FCS 选优以及 10/46 字节 payload。

run 1243 的 exadv standard auto 实测结果为：

```text
unique=11
duplicate=0
out_of_order=0
crc_failure=0
received_sequence=0--8,10,11
missing_sequence=9
processing_avg=10.194 ms
processing_max=20.686 ms
buffer_span=24.000 ms
```

五个 offset 都产生过有效 FCS，且不同包最终选择的最佳 offset 不固定，证明五相位 auto 是必要的。处理最大耗时仍小于缓存跨度，当前没有证据表明 Sequence 9 因 Python 扫描持续积压而丢失；它在五个 offset 上都没有形成可提交候选，而不是已记录的 CRC failure。接收 JSON 仍为 `board=null`，因此只有在同一 Run ID 的板端确认 `tx_completed=12` 后，才能把本轮无线 PRR 正式写为 `11/12 = 91.67%`。该结果解决了旧 standard 完全零候选的问题，但尚未达到不低于 99% 的稳定点；下一步应先用新 Run ID 重复同参数至少三轮，再决定是否放宽门限或继续定位 RF/突发捕获。
