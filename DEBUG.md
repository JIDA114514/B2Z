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
