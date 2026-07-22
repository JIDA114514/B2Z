# app_FreeRTOS — 裸机到 FreeRTOS 移植说明

本文档对比 [app_B2Z/](../app_B2Z/)（裸机 no-OS 程序），描述 [app_FreeRTOS/](./) 在 Zynq-7020 平台上移植到 FreeRTOS 后的关键变化，以及应用代码如何通过 FreeRTOS 实现多任务调度和功能执行。

## 一、执行模型：从超级循环到抢占式多任务

### 裸机执行模型

裸机程序在 `main()` 中完成硬件初始化（`hw_init()`）后，进入一个单线程超级循环（super-loop），所有功能以函数调用的方式顺序执行：

```c
// app_B2Z/main.c:1008 — 裸机超级循环
while (1) {
    ble_tx_task_tick();       // BLE 发送周期处理
    ble_exadv_task_tick();    // BLE extended advertising 周期处理
    ble_rx_service_poll();    // BLE 接收轮询
    if (XUartPs_IsReceiveData(STDIN_BASEADDR)) {
        console_get_command(received_cmd);
        // ... 命令匹配与执行
    }
}
```

关键特征：

- **单线程**：所有功能跑在同一个 `while(1)` 循环中
- **协作式**：每个函数必须快速返回，否则阻塞整个系统
- **忙等延时**：`usleep()` 在 CPU 上自旋等待，不释放处理器
- **轮询串口**：必须主动检查 `XUartPs_IsReceiveData()` 才能读取命令
- **无优先级**：所有功能平等，无法保证时序关键路径的实时性

### FreeRTOS 执行模型

FreeRTOS 程序在 `main()` 中完成硬件初始化后，创建多个独立任务，然后调用 `vTaskStartScheduler()` 启动抢占式调度器——此函数**永不返回**：

```c
// app/main.c — 任务创建与调度器启动
rc_dmac_poll = xTaskCreate(vDmacPollTask, "DmacPoll", 512, NULL, 8, &h_dmac_poll);
rc_console   = xTaskCreate(vConsoleCommandTask, "Console", 2048, NULL, 1, &h_console);
rc_ble_ctrl  = xTaskCreate(ble_command_service_task, "BLE_CTRL", 2048, NULL, 5, &h_ble_control);
rc_ble_tx    = xTaskCreate(ble_tx_adv_task, "BLE_TX_ADV", 4096, NULL, 8, &h_ble_tx_adv);

// 安装 FreeRTOS 向量表，替换 Xilinx asm_vectors.S
__asm volatile ("MCR p15, 0, %0, c12, c0, 0" :: "r" (&_freertos_vector_table));

vTaskStartScheduler();  // 永不返回
```

关键特征：

- **抢占式**：高优先级任务就绪时立即抢占低优先级任务
- **时间片**：同优先级任务轮转调度（1 ms tick）
- **阻塞式延时**：`vTaskDelay()` 让出 CPU，调度器切换到其他任务
- **事件驱动**：任务可以阻塞等待信号量/通知，不消耗 CPU
- **优先级隔离**：BLE 时隙任务最高优先级，调试任务最低优先级

## 二、中断处理体系的变化

这是移植中**最底层、最关键**的变化。

### 裸机中断路径

```
硬件 IRQ → Xilinx asm_vectors.S → Xil_ExceptionHandler()
         → XScuGic_InterruptHandler() → 查表调用用户 ISR
```

- `Xil_ExceptionInit()` 注册 Xilinx 异常处理到 VBAR
- `Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT, XScuGic_InterruptHandler, ...)` 挂 IRQ 入口
- ISR 完成后直接返回到被中断的代码，不存在上下文切换

### FreeRTOS 中断路径

```
硬件 IRQ → _freertos_vector_table (VBAR替换)
         → FreeRTOS_IRQ_Handler (portASM.S)
           → 读 ICCIAR → 获取中断ID
           → 调用 vApplicationIRQHandler(irq_id)
             → 查 XScuGic HandlerTable → 调用用户 ISR
           → 写 ICCEOIR
           → 检查 ulPortYieldRequired → 如有更高优先级任务就绪则上下文切换
```

核心变化：

1. **VBAR 替换**（[main.c:1865](app/main.c#L1865)）：`vTaskStartScheduler()` 内部调用 `vPortInstallFreeRTOSVectorTable()`，将 VBAR 指向 `freertos_vector_table.S` 定义的向量表。Xilinx 的 `asm_vectors.S` 不再被硬件使用（但保留在二进制中）。

2. **ICCIAR 由汇编读取**（[freertos_irq_glue.c:126](port/freertos_irq_glue.c#L126)）：`portASM.S` 中的 `FreeRTOS_IRQ_Handler` 从 GIC CPU Interface 读取 ICCIAR 获取中断 ID，传入 `vApplicationIRQHandler()`。这意味着不能再调用 Xilinx BSP 的 `XScuGic_InterruptHandler()`（它也会读 ICCIAR，导致中断 ID 丢失），而是直接从 `HandlerTable` 分发。

3. **ISR 可触发上下文切换**（[axi_dmac.c:106-115](drivers/axi_dmac.c#L106-L115)）：当 ISR 中调用 `xSemaphoreGiveFromISR()` 唤醒更高优先级的任务时，`portYIELD_FROM_ISR()` 标记 `ulPortYieldRequired`，汇编出口路径在写 ICCEOIR 后执行 SVC 指令切换到新任务。这是从"IRQ 返回到被中断线程"到"IRQ 可能切换到等待该事件的最高优先级任务"的本质跃迁。

4. **不调用 `Xil_ExceptionInit()`**（[xilinx_irq.c:93-95](drivers/xilinx_irq.c#L93-L95)）：FreeRTOS 路径跳过 Xilinx 异常初始化，仅初始化 `XScuGic` 实例并通过 `freertos_irq_set_gic_instance()` 暴露给 `vApplicationIRQHandler`。

5. **`global_enable/disable` 改用 FreeRTOS API**（[xilinx_irq.c:170-176](drivers/xilinx_irq.c#L170-L176)）：`xil_irq_global_enable()` 改为 `portENABLE_INTERRUPTS()`，`xil_irq_global_disable()` 改为 `portDISABLE_INTERRUPTS()`。这两个宏操作 CPSR 的 IRQ mask bit，保证与 FreeRTOS 临界区机制一致。

## 三、HAL 层线程安全适配

裸机程序不需要考虑并发访问，所有全局状态和硬件访问都是安全的。FreeRTOS 下多任务并发，需要对共享资源加锁。所有修改通过 `#ifdef FREERTOS_INTEGRATION` 条件编译，**裸机编译路径不受影响**。

### 3.1 SPI 总线互斥

**文件**：[no_os_spi.c](drivers/no_os_spi.c), [no_os_spi.h](drivers/no_os_spi.h)

| 修改点 | 裸机 | FreeRTOS |
|--------|------|----------|
| 描述符字段 | 无 | `no_os_spi_desc.mutex`（`void *` 指向 `SemaphoreHandle_t`） |
| `init` | 仅初始化硬件 | 额外调用 `xSemaphoreCreateMutex()` 创建互斥锁 |
| `write` / `read` / `transfer` | 直接操作 SPI | 操作前后调用 `no_os_spi_lock()` / `no_os_spi_unlock()` |
| `remove` | 仅释放硬件 | 额外调用 `vSemaphoreDelete()` |

锁的实现：

```c
// drivers/no_os_spi.c:49
static void no_os_spi_lock(struct no_os_spi_desc *desc) {
    if (desc && desc->mutex &&
        (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING))
        xSemaphoreTake((SemaphoreHandle_t)desc->mutex, portMAX_DELAY);
}
```

注意 `xTaskGetSchedulerState() == taskSCHEDULER_RUNNING` 检查：在 `hw_init()` 阶段（调度器尚未启动），不会尝试获取互斥锁，避免了死锁。

### 3.2 GPIO 互斥

**文件**：[no_os_gpio.c](drivers/no_os_gpio.c), [no_os_gpio.h](drivers/no_os_gpio.h)

与 SPI 完全对称的模式：`no_os_gpio_desc` 新增 `mutex` 字段，`init` 创建互斥锁，`set_value` / `get_value` 操作前后加锁。

### 3.3 Console 互斥

**文件**：[console.c](drivers/console.c)

`console_print()` 被多个任务调用时，如果不加锁，UART 输出会交错。解决方案：在 `console_print()` 进入时调用 `console_lock()`，离开时 `console_unlock()`。

```c
// drivers/console.c:304
void console_print(char* str, ...) {
    console_lock();
    va_start(argp, str);
    console_vprint(str, argp);  // 完整格式化输出
    va_end(argp);
    console_unlock();
}
```

同时额外提供 `console_print_unlocked()` 供异常处理函数使用（`vApplicationStackOverflowHook` 等可能在临界上下文中被调用）。

### 3.4 延时函数

**文件**：[delay.c](drivers/delay.c)

这是最直接影响任务调度的 HAL 修改：

```c
// drivers/delay.c:75
void no_os_mdelay(uint32_t msecs) {
#ifdef FREERTOS_INTEGRATION
    if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) {
        TickType_t ticks = pdMS_TO_TICKS(msecs);
        if (ticks > 0) {
            vTaskDelay(ticks);   // 让出 CPU，调度器切换到其他任务
            return;
        }
    }
#endif
    usleep(msecs * 1000);        // 调度器未启动时回退到忙等
}
```

裸机的 `no_os_mdelay()` 就是 `usleep()` 的忙等循环。FreeRTOS 下改为 `vTaskDelay()`，调用任务进入 Blocked 状态，调度器在此期间可以运行其他任务，显著提升 CPU 利用率。

`no_os_udelay()` 保持忙等不变——微秒级延时太短，不值得上下文切换的开销。

## 四、DMA 完成通知：从轮询到信号量

这是应用架构变化最大的部分。裸机通过忙等轮询 DMA 寄存器来确认传输完成，FreeRTOS 则改为基于信号量的阻塞等待。

### 结构体变化

**文件**：[axi_dmac.h](drivers/axi_dmac.h)

```c
struct axi_dmac {
    // ... 原有字段 ...
#ifdef FREERTOS_INTEGRATION
    void *completion_sem;   // SemaphoreHandle_t，DMA 完成信号量
#endif
};
```

### 初始化

[axi_dmac.c:516-523](drivers/axi_dmac.c#L516-L523)：如果 DMA 通道配置为 `IRQ_ENABLED`，`axi_dmac_init()` 创建 Binary Semaphore（初始为空）。

### ISR 中释放信号量

[axi_dmac.c:98-115](drivers/axi_dmac.c#L98-L115)：DMA 传输完成的 ISR 回调中，`axi_dmac_signal_completion()` 调用 `xSemaphoreGiveFromISR()` 释放信号量，并用 `portYIELD_FROM_ISR()` 标记是否需要立即切换：

```c
static void axi_dmac_signal_completion(struct axi_dmac *dmac, bool from_isr) {
    BaseType_t higher_priority_task_woken = pdFALSE;
    if (from_isr) {
        xSemaphoreGiveFromISR(dmac->completion_sem, &higher_priority_task_woken);
        portYIELD_FROM_ISR(higher_priority_task_woken);
    } else {
        xSemaphoreGive(dmac->completion_sem);   // 轮询路径
    }
}
```

### 任务中等待信号量

[axi_dmac.c:709-735](drivers/axi_dmac.c#L709-L735)：`axi_dmac_transfer_wait_completion()` 不再忙等，而是调用 `xSemaphoreTake()` 阻塞等待：

```c
if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING && dmac->completion_sem) {
    TickType_t wait_ticks = timeout_ms ? pdMS_TO_TICKS(timeout_ms) : portMAX_DELAY;
    if (xSemaphoreTake(dmac->completion_sem, wait_ticks) != pdTRUE) {
        // 超时处理：fallback 检查 IRQ 是否已到来但信号量丢失
    }
}
```

这种设计的优势：

- **零 CPU 消耗**：等待 DMA 期间，调度器运行其他任务
- **确定性唤醒**：DMA ISR 到来后，等待任务被精确唤醒
- **优先级正确**：如果等待任务是最高优先级，ISR 返回时立即切换

### DMA 轮询补充任务

[main.c:1240-1252](app/main.c#L1240-L1252)：`vDmacPollTask` 以 1 ms 周期轮询 DMA 中断状态寄存器，对尚未触发 ISR 但已完成传输的边缘情况做补偿：

```c
static void vDmacPollTask(void *pvParameters) {
    for (;;) {
        if (rx_dmac && (rx_dmac->irq_option == IRQ_ENABLED))
            axi_dmac_poll_pending(rx_dmac);
        if (tx_dmac && (tx_dmac->irq_option == IRQ_ENABLED))
            axi_dmac_poll_pending(tx_dmac);
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
```

## 五、串口命令读取与异步执行

串口命令路径分为“读取与解析”和“业务执行”两个阶段。这样设计的原因是 BlueBee 与 BLE extended advertising 的波形生成包含大量浮点运算；如果直接在 Console 任务中执行，Console 在计算完成前无法继续读取 `ble_tx_stop?` 等命令，而且低优先级 Console 持有共享资源时也会增加任务耦合。

当前 FreeRTOS 路径为：

```text
UART FIFO
  → Console：逐字符读取并组成完整命令行
  → command_dispatch_line()：统一匹配、解析和校验
  → BLE 请求队列：复制名称或 payload
  → BLE_CTRL
      ├─ BlueBee/exadv：波形生成、模式切换和 DMA 启动
      └─ 普通 BLE advertising：更新发送状态
           → BLE_TX_ADV：波形构建与周期发送
```

### 5.1 UART 读取不再忙等

裸机的 `console_get_command()` 调用 Xilinx BSP 的阻塞式 `uart_read_char()`（内部忙等 FIFO）。FreeRTOS 下改为先检查 FIFO 状态再决定行为：

```c
// drivers/console.c:346
void console_get_command(char* command) {
    while ((received_char != '\n') && (received_char != '\r')) {
#if defined(FREERTOS_INTEGRATION) && defined(XILINX_PLATFORM) && defined(STDIN_BASEADDRESS)
        if (!XUartPs_IsReceiveData(STDIN_BASEADDR)) {
            vTaskDelay(1);        // FIFO 为空 → 阻塞 1ms，让出 CPU
            continue;
        }
        received_char = XUartPs_RecvByte(STDIN_BASEADDR);
#else
        uart_read_char(&received_char);  // 裸机：阻塞等待
#endif
        // ... 行缓冲处理
    }
}
```

`vTaskDelay(1)` 让调用任务睡眠 1ms（1 tick），在此期间调度器运行其他任务。用户无感知（按键操作时间远大于 1ms），但避免了 CPU 空转。

命令行缓冲区 `CONSOLE_MAX_COMMAND_LEN` 为 192 字节。`console_get_command()` 为行结束符和结尾 `\0` 预留空间，最多接收 190 个命令字符；超出的字符会被丢弃直到收到换行符，防止 UART 输入覆盖内存。192 字节可以容纳最长的 46 字节 ZigBee payload 命令；例如使用空格分隔的完整 `ble_exadv_secondary_gen?` 命令约为 163 字节。

### 5.2 所有命令使用统一分发表

旧实现先在 `main.c` 中调用多个 `console_handle_ble_*()` 特殊处理函数，未匹配时才遍历 `cmd_list[]`。这使 BLE 命令存在两套入口，帮助信息、参数解析和实际执行函数容易不一致。

当前 `vConsoleCommandTask()` 对所有输入只调用 [command_dispatch_line()](app/command.c#L148)：

```c
console_get_command(received_cmd);
if (!command_dispatch_line(received_cmd))
    console_print("Invalid command!\n");
```

`cmd_list[]` 的每个表项可以选择两种处理接口：

- `cmd_function(double *param, char param_no)`：保留给原有数值命令。解析器最多接收 5 个参数，每个参数文本最多 9 个字符，超限时返回 `UNKNOWN_CMD`，避免 `param[]` 和 `param_string[]` 越界。
- `cmd_text_function(const char *args)`：用于 BLE 名称和十六进制 payload 等不能安全转换为 `double` 的参数。命令名称仍由同一张 `cmd_list[]` 匹配，handler 只接收名称之后的原始参数文本。

当前文本命令包括 `ble_tx_adv_name=`、`ble_tx_stop?`、`bluebee_gen_demo?` 和 `ble_exadv_secondary_gen?`。BLE 名称限制为 1–26 个可打印 ASCII 字符；payload 最大 46 字节，支持空格、Tab、逗号、冒号或分号分隔，并支持可选的 `0x` 前缀。

### 5.3 BLE 请求队列与参数所有权

FreeRTOS 启动调度器前，`ble_command_service_init()` 创建长度为 4 的队列。每个队列元素都是固定大小的 `ble_command_request`：

```c
struct ble_command_request {
    enum ble_command_request_type type;
    uint32_t payload_len;
    union {
        char name[BLE_TX_ADV_NAME_MAX_LEN + 1];
        uint8_t payload[BLE_EXADV_SECONDARY_GEN_MAX_PAYLOAD_BYTES];
    } data;
};
```

Console handler 在入队前完成校验，并把名称或 payload **复制**到请求结构中，绝不把 `received_cmd` 内部指针传给其他任务。这样下一条串口命令覆盖接收缓冲区时，不会破坏尚未执行的请求；运行期间也不需要为每条命令调用 `malloc()`。

普通请求使用 `xQueueSend()`，`ble_tx_stop?` 使用 `xQueueSendToFront()`，因此停止请求会优先于尚未开始的启动请求。队列已满时输出 `BLE command queue busy`，命令不会悄悄丢失。队首发送只能调整等待中请求的顺序，不能中断已经开始的波形计算。

### 5.4 提示信息输出时机

入队后不输出通用的 `BLE command accepted`。原因是 `BLE_CTRL` 优先级高于 Console：`xQueueSend()` 唤醒 `BLE_CTRL` 后可能立即发生抢占，如果提示由 Console 在入队返回后打印，反而可能等到整段波形计算完成才出现。

现在提示由实际执行计算的任务在计算开始前输出：

```text
bluebee_gen: generating waveform...
ble_exadv_secondary_gen: generating waveform...
BLE ADV: generating waveform, name=<name>
```

前两条由 `BLE_CTRL` 输出；普通 BLE advertising 的波形实际在 `BLE_TX_ADV` 中构建，因此第三条由 `BLE_TX_ADV` 在调用 `ble_adv_build_all_channels()` 前输出。这样串口日志顺序能够真实反映任务执行进度。

未定义 `FREERTOS_INTEGRATION` 时不创建请求队列，文本 handler 保持同步调用，兼容裸机执行路径。

## 六、任务架构与优先级设计

### 当前任务清单

| 优先级 | 任务名 | 栈空间 | 触发方式 | 功能 |
|--------|--------|--------|----------|------|
| 8 | BLE_TX_ADV | 4096 words (16 KB) | 状态驱动，空闲 10 ms/发送循环 1 ms 延时 | 普通 BLE advertising 波形构建与 TX |
| 8 | DmacPoll | 512 words (2 KB) | 1 ms 周期 `vTaskDelay` | DMA 中断状态轮询补偿 |
| 5 | BLE_CTRL | 2048 words (8 KB) | 阻塞等待 BLE 请求队列 | BlueBee/exadv 波形生成、BLE 模式控制和 DMA 启动 |
| 1 | Console | 2048 words (8 KB) | `vTaskDelay(1)` 等待串口输入 | CLI 命令读取、匹配、校验和请求入队 |

### 优先级设计理由

- **BLE_TX_ADV（优先级 8）**：负责普通 BLE advertising 的波形构建和发送，必须能抢占波形生成及 Console 处理。与 DmacPoll 同优先级，DMA 状态检查不会长期落后；任务每轮发送后按当前实现延时 1 ms，空闲时延时 10 ms。
- **DmacPoll（优先级 8）**：DMA 状态轮询需要及时处理（避免丢失传输完成信号），与 BLE 同优先级确保不落后。该任务每次只做一次寄存器检查然后 `vTaskDelay`，不长时间占用 CPU。
- **BLE_CTRL（优先级 5）**：高于 Console，确保命令入队后及时开始计算；低于 BLE_TX_ADV 和 DmacPoll，使耗时的浮点波形生成不会阻塞时序关键任务。任务没有请求时阻塞在 `xQueueReceive(..., portMAX_DELAY)`，不消耗 CPU。
- **Console（优先级 1）**：最低优先级。只完成轻量的输入、解析和入队，用户交互不会直接执行耗时波形计算，也不会打断 BLE 传输或 DMA 处理。

### 为什么没有创建 ISR 专用的 Bottom-Half 任务？

原始设计规划了 ADC_DMA_BH 和 DAC_DMA_BH 任务（优先级 8/9），由 DMA ISR 通过 Task Notification 唤醒。当前实现中，DMA ISR 直接通过 `xSemaphoreGiveFromISR()` 通知等待在 `xSemaphoreTake()` 上的任务（即调用 `axi_dmac_transfer_wait_completion()` 的业务任务）。这避免了 BH 任务链条的额外延迟和开销，更适合当前 ADC/DAC DMA IRQ 的简单场景。

## 七、FreeRTOS Tick 配置

Zynq-7020 不使用 SysTick 而是使用 **Cortex-A9 Private Timer**：

| 参数 | 值 |
|------|-----|
| 基地址 | `0xF8F00600` |
| 时钟源 | `CPU_CLK / 2 ≈ 333.33 MHz`（configCPU_CLOCK_HZ = 666666687） |
| Tick 频率 | 1000 Hz |
| Load 值 | 333333 |
| PPI ID | 29（Private Peripheral Interrupt） |
| 优先级 | 30（最低可用优先级，configKERNEL_INTERRUPT_PRIORITY） |

[freertos_irq_glue.c:205-273](port/freertos_irq_glue.c#L205-L273) 中的 `vConfigureTickInterrupt()` 完成：
1. 停止定时器，设置 Load 值
2. 通过 `XScuGic_Connect()` 注册 `FreeRTOS_Tick_Handler` 到 PPI 29
3. 配置优先级和触发类型（level-sensitive）
4. 使能 PPI 并在 GIC Distributor 中启用
5. 启动定时器（AutoReload + IRQ Enable + Timer Enable）

## 八、中断/异常向量表

FreeRTOS V11 的 ARM_CA9 移植层 `port.c` 在 `xPortStartScheduler()` 中调用 `vPortInstallFreeRTOSVectorTable()` 安装自定义向量表 `_freertos_vector_table`（定义在 `port/freertos_vector_table.S`）：

| 异常类型 | 偏移 | 向量 |
|----------|------|------|
| Reset | 0x00 | `_boot`（BSP `boot.S` 入口） |
| Undefined | 0x04 | `FreeRTOS_Undefined_Handler` |
| SVC | 0x08 | `FreeRTOS_SWI_Handler`（用于 `portYIELD` / 任务切换） |
| Prefetch Abort | 0x0C | `FreeRTOS_Prefetch_Abort_Handler` |
| Data Abort | 0x10 | `FreeRTOS_Data_Abort_Handler` |
| Unused | 0x14 | 保留 |
| IRQ | 0x18 | `FreeRTOS_IRQ_Handler`（核心中断入口） |
| FIQ | 0x1C | `FreeRTOS_FIQ_Handler` |

异常处理函数内部调用 [vFreeRTOSExceptionHandler()](port/freertos_irq_glue.c#L45-L84) 打印异常信息后 halt，便于 JTAG 调试。

## 九、FreeRTOS 配置要点

完整配置见 [include/FreeRTOS/FreeRTOSConfig.h](include/FreeRTOS/FreeRTOSConfig.h)，关键决策如下：

| 配置项 | 值 | 理由 |
|--------|-----|------|
| `configTOTAL_HEAP_SIZE` | 1 MB | 足够容纳所有任务的栈和运行时分配 |
| `configTICK_RATE_HZ` | 1000 | 1 ms tick，平衡响应性与开销 |
| `configMAX_PRIORITIES` | 16 | 足够当前 8→1 的优先级范围 |
| `configUSE_PREEMPTION` | 1 | 抢占式调度是核心需求 |
| `configUSE_MUTEXES` | 1 | SPI/GPIO/Console 互斥锁 |
| `configUSE_TASK_NOTIFICATIONS` | 1 | 规划中的 BH 通知路径 |
| `configCHECK_FOR_STACK_OVERFLOW` | 2 | 开发阶段严格检测栈溢出（canary） |
| `configUSE_TASK_FPU_SUPPORT` | 2 | 所有任务默认启用 FPU 上下文 |
| `configUSE_TICKLESS_IDLE` | 0 | BLE 需要确定性 tick，不能进入 tickless |
| `configKERNEL_INTERRUPT_PRIORITY` | 30 | Tick 中断最低优先级 |
| `configMAX_API_CALL_INTERRUPT_PRIORITY` | 18 | 优先级 18–31 的中断可调用 ISR API |
| `configUNIQUE_INTERRUPT_PRIORITIES` | 32 | GIC PL390 实现 5 bit 优先级 |

## 十、堆内存管理

- **`heap_4.c`**：支持相邻空闲块合并，减少碎片。适合长时间运行的应用。
- **`configTOTAL_HEAP_SIZE = 1 MB`**：所有 FreeRTOS 内核对象（任务栈、TCB、队列、信号量、互斥锁）从此堆分配。
- **裸机 C 库堆**：`lscript.ld` 中扩大至 64 KB，仅在 `hw_init()` 阶段的 `calloc()` 使用（如 `axi_dmac_init` 中的 `dmac` 结构体分配）。调度器启动后，运行时分配使用 `pvPortMalloc()`。
- **启动前分配**：所有硬件描述符（AD9361 PHY、DMA 描述符、SPI 描述符等）在 `hw_init()` 中通过 `calloc()` 从 C 库堆分配，调度器启动后不再调用 `malloc/calloc`，避免线程安全问题。

## 十一、链接脚本变化

`lscript.ld` 相比裸机版本的主要调整：

| 区域 | 裸机 | FreeRTOS |
|------|------|----------|
| Supervisor 栈 (SYS) | 8 KB | 64 KB（FreeRTOS 在 SVC 模式下运行，所有任务共享此栈） |
| IRQ 栈 | 1 KB | 4 KB |
| SVC/ABT/UND/FIQ 栈 | 各 1 KB | 各 4 KB |
| C 库堆 (Heap) | 8 KB | 64 KB（`hw_init()` 中的 `calloc` 需要更多空间） |

## 十二、移植兼容性保证

所有 HAL 修改通过 `#ifdef FREERTOS_INTEGRATION` 条件编译，确保：

1. **裸机 `app_B2Z/` 不受影响**：相同的 `drivers/` 源码在裸机项目中不定义 `FREERTOS_INTEGRATION`，编译器选择原有路径。
2. **驱动源码共享**：`app_FreeRTOS/drivers/` 中的驱动源码与 `app_B2Z/` 中的对应文件功能完全一致，仅在 FreeRTOS 宏启用时插入线程安全代码。
3. **IV：业务代码可移植**：`app/` 中的 BLE/BlueBee 业务逻辑（`ble_tx_adv.c`、`bluebee_gen.c` 等）与裸机版本功能一致，仅调用路径从函数直接调用变为任务入口调用。

## 十三、验证与诊断

FreeRTOS 移植内建了多级验证机制：

### FreeRTOS 内置诊断

- **栈溢出检测**：`configCHECK_FOR_STACK_OVERFLOW = 2`，在任务栈顶设置 canary，切换任务时检查。
- **堆不足 Hook**：`vApplicationMallocFailedHook()` 打印剩余堆大小后 halt。
- **Idle Hook**：`vApplicationIdleHook()` 检测 GIC PMR 异常并自动恢复（防止 tick 被误屏蔽导致系统 hang 死）。
- **异常捕获**：`vFreeRTOSExceptionHandler()` 打印异常类型和寄存器后 halt。

### Phase 2 自检任务

`PHASE2_SELFTEST` 宏启用 `vPhase2SelfTestTask`：

1. Tick 验证：`vTaskDelay(100)` 实际延迟是否在 99–101 ms 内
2. SPI Mutex 验证：多线程并发 SPI 传输不出错
3. GPIO Mutex 验证：并发 GPIO 操作
4. Console Mutex 验证：多线程 `console_print()` 不交错
5. IRQ 分发验证：`swpend` 命令触发软件 pending 确认 GIC 分发路径

### IRQ 诊断计数器

[freertos_irq_glue.h](port/freertos_irq_glue.h) 暴露的全局诊断变量：

| 变量 | 意义 |
|------|------|
| `g_tick_isr_count` | tick ISR 进入次数 |
| `g_irq_last_id` | 最后一次 IRQ 的 GIC ID |
| `g_irq_dispatch_count[id]` | 各 GIC ID 的分发计数 |
| `g_irq_unhandled_count[id]` | 无 handler 的中断数 |
| `g_adc_dma_gic_dispatch_count` | ADC DMA IRQ 在 GIC 层分发的次数 |
| `g_adc_dma_irq_enter_count` | ADC DMA ISR 进入次数 |
| `g_adc_dma_irq_eot_count` | EOT 事件计数 |
| `g_adc_dma_irq_sem_give_count` | ISR 中 `xSemaphoreGiveFromISR` 成功次数 |
| `g_adc_dma_irq_sem_woken_count` | 触发任务唤醒的次数 |

这些计数器通过串口命令可读，用于诊断 "IRQ 是否到达 GIC → 是否被 FreeRTOS 分发 → ISR 是否被调用 → 信号量是否释放" 的完整链路。

## 十四、BlueBee 性能测试与 realtime 生成优化

当前板端性能测试集成在 FreeRTOS 应用中；公共 payload 构造逻辑位于 `FREERTOS_INTEGRATION` 条件块之外，驱动修改继续保留裸机编译路径，但 `app_B2Z/` 尚未创建对应的性能任务和命令入口。

### 14.1 测试协议和命令

每包前 10 字节为固定测试头：

| 偏移 | 字段 | 编码 |
|---:|---|---|
| 0--1 | Magic | `B2 5A` |
| 2 | Version | `1` |
| 3 | Header length | `10` |
| 4--5 | Run ID | 小端 16 位 |
| 6--9 | Sequence | 小端 32 位 |

10 字节之后使用 32 位 LCG 确定性填充，初始值为 `0xB25A5A2D ^ (run_id << 16) ^ sequence`。接收端会重建并比较整个 payload，而不是只检查测试头。

命令格式：

```text
bluebee_pure_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]
bluebee_exadv_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]
bluebee_perf_status?
bluebee_perf_stop?
```

`payload_len` 为 10--46，`duration_s` 为 0--600，参数只接受十进制整数。三种模式均已实现：`mode=0` realtime 逐包生成；`mode=2` double 使用两个独立 IQ 缓冲，在 DMA 读取当前包时生成下一 Sequence；`mode=1` batch 在实验计时前预生成首批，后续批次继续生成新的 Sequence 波形，绝不循环复用旧波形。

batch 未提供 `batch_size` 时默认为 4，最大为 8。arena 为 64 字节对齐的静态 DDR BSS，最大约 7.4 MB，不占用 1 MB FreeRTOS heap；double 只使用 slot 0/1。

### 14.2 时隙、DMA 和统计

- Sequence 取计划时隙编号；生成或 DMA 失败时不回退、不补发、不复用。
- IRQ 关闭时主动读取 DMAC `TRANSFER_SUBMIT`、`TRANSFER_DONE` 和 `IRQ_PENDING`，不能依赖 IRQ 回调确认完成。
- `PERF_STATS` 输出 `scheduled`、`generated`、`tx_started`、`tx_completed`、`deadline_miss`、`dma_timeout`。
- `PERF_TIMING` 输出 frame、mapping、GFSK、total 四阶段的 samples/min/max/avg。
- pure 发送保留 1 ms 前置和后置静默，one-shot DMA 每个计划时隙独立提交。
- pure 和 exadv 共用相同测试头、Sequence 和填充规则；exadv 先发 primary，再按 AuxOffset 发送包含 BlueBee 负载的 secondary。

### 14.3 Gaussian 卷积优化

Debug `-O0` 下，旧生成器对每个 IQ 样本遍历全部 3072 个 Gaussian taps，60 秒只能生成约 17 包。当前实现为 taps 建立前缀和，利用 NRZ 在符号区间内恒定的特性，将逐 tap 乘加改成最多约 5 个符号区间求和。

该优化保持以下行为不变：

- ZigBee frame、FCS 和 optimized BlueBee chip map。
- GFSK 相位积分和 IQ 量化。
- 有效 IQ 长度以及 1 ms 前后静默。
- TX LO、DMA word 格式和 one-shot 提交流程。

主机等价性测试比较新旧实现，要求 IQ 相关系数不低于 0.999，且中心点解调出的 GFSK bits 完全一致。

### 14.4 实测结果

10 字节 pure realtime 的 run 1235：

```text
scheduled=12 generated=12 tx_started=12 tx_completed=12
deadline_miss=0 dma_timeout=0
frame avg=3 us mapping avg=1010 us gfsk avg=22222 us total avg=23237 us
```

1 秒间隔的 60 秒实验也达到 `scheduled=generated=tx_started=tx_completed=60`，且 `deadline_miss=0`、`dma_timeout=0`。这表明原来的板端生成瓶颈已经解决；后续无线少收必须与接收端 Run ID/Sequence 和板端最终计数合并判断。

`PERF_TIMING` 曾全部为 0，原因是生成器编译单元没有包含 `app_config.h`，导致 `XILINX_PLATFORM` 不可见并进入计时 fallback。当前生成器已显式包含平台配置；主机测试使用 `BLUEBEE_GEN_HOST_TEST` 隔离板端计时头文件。

板端源码修改后还必须同步到 SDK 实际编译目录：

```text
hdl/projects/antsdre310/antsdre310.sdk/app/src/app/
```

## 十五、关键文件索引

| 文件 | 内容 |
|------|------|
| [app/main.c](app/main.c) | `main()` 入口、`hw_init()`、任务创建、FreeRTOS Hook 函数 |
| [port/freertos_irq_glue.c](port/freertos_irq_glue.c) | `vApplicationIRQHandler()`、`vConfigureTickInterrupt()`、异常处理、诊断计数器 |
| [port/freertos_vector_table.S](port/freertos_vector_table.S) | FreeRTOS 专用异常向量表 |
| [port/port.c](port/port.c) | FreeRTOS ARM_CA9 移植层：任务上下文初始化、`xPortStartScheduler()` |
| [port/portASM.S](port/portASM.S) | 汇编级上下文保存/恢复、`FreeRTOS_IRQ_Handler`、`FreeRTOS_SWI_Handler` |
| [include/FreeRTOS/FreeRTOSConfig.h](include/FreeRTOS/FreeRTOSConfig.h) | FreeRTOS 完整配置（GIC 基地址、tick 频率、堆大小、FPU 等） |
| [drivers/axi_dmac.c](drivers/axi_dmac.c) | DMA 驱动：信号量通知、ISR 上下文切换 |
| [drivers/no_os_spi.c](drivers/no_os_spi.c) | SPI 互斥锁实现 |
| [drivers/no_os_gpio.c](drivers/no_os_gpio.c) | GPIO 互斥锁实现 |
| [drivers/console.c](drivers/console.c) | Console 互斥锁、非阻塞 UART 读取 |
| [app/command.c](app/command.c) | 统一命令分发、文本参数解析、BLE 请求队列和 `BLE_CTRL` 任务 |
| [app/ble_tx_adv.c](app/ble_tx_adv.c) | BLE advertising 波形生成与 `BLE_TX_ADV` 发送任务 |
| [app/bluebee_perf.c](app/bluebee_perf.c) | 测试 payload、时隙调度、pure/exadv realtime/double/batch、DMA 轮询和性能统计 |
| [app/bluebee_gen.c](app/bluebee_gen.c) | pure BlueBee frame/mapping/GFSK 生成和 Gaussian 前缀和优化 |
| [app/ble_exadv_secondary_gen.c](app/ble_exadv_secondary_gen.c) | exadv secondary/BlueBee 波形生成和分阶段耗时元数据 |
| [drivers/delay.c](drivers/delay.c) | 调度感知的 `no_os_mdelay()` |
| [drivers/xilinx_irq.c](drivers/xilinx_irq.c) | IRQ 初始化（跳过 `Xil_ExceptionInit`、暴露 GIC 实例） |
