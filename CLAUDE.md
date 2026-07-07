# 项目概述

## 总目标

本项目以论文 BlueBee 为基础，论文原文位于 `python/ctc_sim/bluebee/`。目标是利用 BLE 的 extended advertising 双包调度外壳，把 BlueBee 负载放入 secondary 包，在尽可能小的系统改动下实现 BLE 到 ZigBee 的跨协议通信，并完成后续性能测量。

## 当前目标：FreeRTOS 移植

在 Zynq-7020 平台上将裸机 no-OS 应用移植到 FreeRTOS，实现多任务并发执行。当前分支 `feat/freertos-dev`，目标目录 `app_FreeRTOS/`。

### 平台信息

| 项目 | 规格 |
|------|------|
| SoC | Xilinx Zynq-7020 (XC7Z020CLG400-2) |
| CPU | 双核 ARM Cortex-A9 @ 666.67 MHz |
| DDR | 1 GB @ 0x00100000 |
| OCM | 192 KB @ 0x00000000 |
| RF | AD9363 (AD9361 系列) |
| BSP | Xilinx standalone v7.5 |
| 工具链 | Vitis 2021.1, GCC (ARM bare-metal) |
| 构建 | Vitis Managed Make (Eclipse-based) |

### FreeRTOS 移植方案（四大阶段）

#### Phase 1: FreeRTOS 内核集成

- **源码**: FreeRTOS-Kernel v10.6.2，ARM Cortex-A9 GCC 移植层
- **移植文件**: `portable/GCC/ARM_CA9/port.c`, `portASM.S`, `portmacro.h`
- **内存管理**: `heap_4.c`，`configTOTAL_HEAP_SIZE = 1 MB`
- **Tick**: Cortex-A9 Private Timer @ 0xF8F00600，1 kHz
- **FPU**: `configENABLE_FPU = 1`，由 FreeRTOS portASM.S 管理 VFP 上下文
- **双核**: Core 0 运行 FreeRTOS，Core 1 保持 `boot.S` 中的 WFE 休眠
- **启动**: 不修改 BSP 的 `xil-crt0.S`。保持标准 `main()` → `hw_init()` → `xTaskCreate()` → `vTaskStartScheduler()`
- **向量表**: `vTaskStartScheduler()` 内部调用 `vPortInstallFreeRTOSVectorTable()` 替换 VBAR，Xilinx `asm_vectors.S` 不再使用但保留在二进制中

#### Phase 2: no_OS HAL 适配（线程安全）

所有修改通过 `#ifdef FREERTOS_INTEGRATION` 保持裸机兼容。

| 文件 | 修改内容 |
|------|----------|
| `xilinx_irq.c` | 移除 `Xil_ExceptionInit()` 和 `Xil_ExceptionRegisterHandler()`，改为启动 XScuGic 并暴露实例给 `vApplicationIRQHandler()`；`global_enable/disable` 改用 `portENABLE/DISABLE_INTERRUPTS()` |
| `no_os_spi.c/h` | `no_os_spi_desc` 新增 `void *mutex` 字段，`init` 创建互斥锁，所有传输操作加锁 |
| `no_os_gpio.c/h` | 同上模式，添加 GPIO 互斥锁 |
| `delay.c` | 调度器未启动时保持 `usleep()` 忙等；启动后改用 `vTaskDelay()` 让出 CPU |
| `console.c/h` | `console_print()` 添加互斥锁，防止多任务输出交错 |
| `axi_dmac.c` | ISR 回调从纯标志位改为 `xSemaphoreGiveFromISR()` + `portYIELD_FROM_ISR()` |
| `lscript.ld` | SYS 栈 8 KB → 64 KB，IRQ/SVC/ABT/UND/FIQ 栈提高至 4 KB，C 库堆 8 KB → 64 KB |

新建文件：
- `FreeRTOSConfig.h`：完整 FreeRTOS 配置（见项目树中的详细记录）
- `freertos_irq_glue.c`：实现 `vApplicationIRQHandler(uint32_t ulICCIAR)`，内部调用 `XScuGic_InterruptHandler(g_gic_instance)`

#### Phase 3: 应用任务架构

```
优先级  任务             栈      触发           功能
───────────────────────────────────────────────────────────
 10     Timer Service     2 KB    FreeRTOS 内置   软件定时器回调
  9     BLE_EXADV         8 KB    100us 定时      BLE exadv + BlueBee secondary TX
  9     DAC_DMA_BH        4 KB    DMA ISR 通知    DAC DMA 下半部处理
  8     BLE_TX            8 KB    100us 定时      BLE 普通 advertising TX
  8     ADC_DMA_BH        4 KB    DMA ISR 通知    ADC DMA 下半部处理
  7     BLE_RX            8 KB    事件驱动        BLE 接收/解调处理
  5     CONSOLE           4 KB    UART 10ms 轮询  串口命令交互
  0     Idle              1 KB    FreeRTOS 内置   空闲任务
```

任务间通信：
- DMA ISR → Bottom-half 任务：**Task Notification**（`vTaskNotifyGiveFromISR`，最快路径）
- Bottom-half → 业务任务：**Binary Semaphore**
- 所有 SPI 访问：**Mutex** 串行化（`no_os_spi` 层透明处理）
- 控制台输出：**Console Mutex**（`console_print` 内部透明处理）

优先级理由：BLE_EXADV 最高（时序关键），DMA BH 与对应业务任务同优先级（及时处理），CONSOLE 最低（用户输入不能干扰 BLE 时序）。

#### Phase 4: 验证策略

1. **内核验证**: 两 LED 任务交替闪烁、`vTaskList()` 输出任务列表、tick GPIO 翻转用示波器确认
2. **HAL 验证**: 两任务并发 SPI 访问不出错、DMA ISR 触发后 BH 任务被正确唤醒、多任务 `console_print()` 不交错
3. **全功能**: nRF Connect 检测 primary 广播、`zigbee_rx.py` 检测 ZigBee 帧、连续运行 1 小时 `vTaskGetRunTimeStats()` 正常、`xPortGetFreeHeapSize()` 无泄漏

### 关键风险与缓解

| 风险 | 缓解 |
|------|------|
| FPU 上下文保存冲突（Xilinx vs FreeRTOS 向量表） | FreeRTOS 替换 VBAR，portASM.S 统一管理 VFP |
| BLE 时隙抖动 | BLE_EXADV 最高优先级，不受其他任务抢占 |
| SPI 优先级反转（低优先级 CONSOLE 持有锁阻塞 BLE） | CONSOLE 最低优先级，SPI 事务短，即使阻塞也不影响 BLE 窗口 |
| C 库 `malloc/calloc` 线程安全 | 所有堆分配在 `hw_init()` 中完成（调度器启动前），运行时用 `pvPortMalloc()` |
| Vitis 不自动发现子目录源文件 | 所有 .c 放 `app_FreeRTOS/` 根目录，仅头文件用 `include/` 子目录 |

## 阶段结论（BLE/CTC 部分）

- 旧阶段的"手机显示完整 BLE extended advertising secondary 数据"路线已暂停，不再作为当前主线目标。
- 当前主线改为利用 BLE exadv 的双包调度外壳，在 `ch39 / 2480 MHz` 上发 primary，并在同频发 BlueBee secondary。
- 裸机 `ble_exadv_tx?` 现阶段只保留 `aux_delay_us interval_us` 两个参数，默认推荐命令形态为 `ble_exadv_tx? 6990 100000`。
- 裸机调度以生成头文件中的 primary/secondary IQ、频点和 AuxOffset 元数据为准；不再保留 lead sweep、secondary test、timing debug 路径。

## 验收标准

- 手机 nRF Connect 能看到 `ch39` 上的 primary 广播
- HackRF 或其他接收链路能够确认 secondary/BlueBee 波形确实在 `2480 MHz`
- `python/ctc_sim/std_zigbee/zigbee_rx.py` 能检测到完整 ZigBee frame
- 优先接受标准：
  - 能输出完整 frame bytes 供比对
  - 若同时 FCS OK，则视为更强证据

## 相关路径

### Python 端
- `python/ctc_sim/bluebee/`
  - `generate_bluebee_iq_30_72M.py`：当前主生成脚本
  - `bluebee_phase_analyze.py`、`bluebee_phase_zigbee_rx.py`：BlueBee/ZigBee 分析辅助工具
- `python/ctc_sim/std_zigbee/`
  - `zigbee_rx.py`：当前主接收验证脚本
- `python/std_ble/`
  - `ble_exadv_hackrf_sniffer.py`：仍可用于观察 primary/secondary 存在性
  - `generate_ble_exadv_iq_30_72M.py`：保留旧 BLE exadv 生成逻辑，但不再是当前主线

### 裸机端
- `app_B2Z/`：当前主应用（含 BLE/CTC 代码），57 个源文件
- `app_FreeRTOS/`：FreeRTOS 移植目标目录（当前是 `app_e310/` 副本，缺 BLE 文件）
- `app_e310/`、`app_e200/`、`app_e310v2/`：参考裸机应用（无 BLE 代码）
- `hdl/projects/antsdre310/antsdre310.sdk/`：Vitis SDK 工作区
  - `app/src/lscript.ld`：链接脚本（需为 FreeRTOS 调整栈大小）
  - `system_top/ps7_cortexa9_0/standalone_ps7_cortexa9_0/bsp/`：BSP 源码和库

### HDL 端
- `hdl/projects/antsdre310/`：Vivado 工程（2021.1）
  - `system_top.v`：顶层 Verilog
  - `system_bd.tcl`：Block Design（PL 外设地址、中断号全量定义）
  - `system.xdc`：约束文件（125 MHz rx_clk，引脚分配）

### BSP 关键文件（只读参考，不修改）
- `asm_vectors.S`：Xilinx 异常向量表（FreeRTOS 运行时被替换）
- `boot.S`：CPU 初始化、MMU、Cache、模式栈（保持不变）
- `xil-crt0.S`：C 运行时初始化（保持调用 `main()`，不修改）
- `translation_table.S`：MMU 1:1 映射表（DDR 可缓存，PL 强序，外设设备内存）
- `xil_exception.h`：`XIL_EXCEPTION_ID_INT = XIL_EXCEPTION_ID_IRQ_INT = 5`

## 注意事项

1. 工作区裸机程序代码未被 git 追踪。
2. 裸机代码修改后，只检查代码逻辑和语法，由用户自行编译和上板。
3. 以实际规范为准，历史注释和旧实验记录可能已过时。
4. `python/ctc_sim/stc_zigbee` 是笔误，实际路径是 `python/ctc_sim/std_zigbee`。
5. `doc/BLE_Core_v5.1.pdf` 可作为 BLE 规范参考，但当前阶段不再以"规范手机跟随 AuxPtr"作为主要成功判据。
6. FreeRTOS 移植使用 `FREERTOS_INTEGRATION` 条件编译宏，所有 HAL 修改均通过 `#ifdef` 保持裸机兼容路径。
7. `app_FreeRTOS/` 当前缺少 BLE/CTC 文件（`ble*.c`、`zigbee_tx.c`、`bluebee_waveform.h` 等），实现时需从 `app_B2Z/` 复制。

## 手机 BLE 检测的负载上限

经实验测定，手机（nRF Connect）能检测到 BLE extended advertising 的 secondary 包存在一个**严格的 PDU payload 阈值**：

| ZigBee payload | BlueBee bytes | PDU payload | 手机检测 |
|------|------|------|------|
| 46 B | 216 | ~238 | ✅ 正常 |
| 47 B | 220 | ~242 | ❌ 检测不到 |
| 48 B | 224 | ~246 | ❌ 检测不到 |
| 49 B | 228 | ~250 | ❌ 检测不到 |

- **阈值**：PDU payload **~238 字节**（216 BlueBee 字节 / 46 字节 ZigBee payload）是手机能检测到的上限。
- **默认配置**：`generate_ble_exadv_iq_30_72M.py` 的 `DEFAULT_ZIGBEE_PAYLOAD` 已设置为 46 字节最大值，`--include-flags` + `--name S` 已启用。
- **理论吞吐**：46 字节 / 100ms = **460 B/s**（3680 bps）。
