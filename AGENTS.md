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

### FreeRTOS 移植方案概览

#### Phase 1: FreeRTOS 内核集成

- **源码**: FreeRTOS-Kernel v10.6.2，ARM Cortex-A9 GCC 移植层
- **移植文件**: `portable/GCC/ARM_CA9/port.c`, `portASM.S`, `portmacro.h`
- **内存管理**: `heap_4.c`，堆大小 1 MB
- **Tick**: Cortex-A9 Private Timer (0xF8F00600)，1 kHz
- **FPU**: 启用 VFP 上下文保存恢复
- **双核**: Core 0 运行 FreeRTOS，Core 1 保持 WFE 休眠
- **启动**: 保持标准 `main()` 入口，不修改 xil-crt0.S。`main()` → `hw_init()` → 创建任务 → `vTaskStartScheduler()`
- **向量表**: FreeRTOS 运行时通过 `vPortInstallFreeRTOSVectorTable()` 替换 VBAR

#### Phase 2: no_OS HAL 适配

修改原则：通过 `#ifdef FREERTOS_INTEGRATION` 条件编译，保持对裸机模式的兼容。

| 文件 | 修改内容 |
|------|----------|
| `xilinx_irq.c` | 移除 `Xil_ExceptionInit/RegisterHandler`，改为暴露 GIC 实例给 FreeRTOS IRQ 入口；`global_enable/disable` 改用 `portENABLE/DISABLE_INTERRUPTS` |
| `no_os_spi.c/h` | `no_os_spi_desc` 新增 `void *mutex`，init 中创建互斥锁，write_and_read/transfer 前后加锁 |
| `no_os_gpio.c/h` | 同上模式添加 GPIO 互斥锁 |
| `delay.c` | 调度器未启动时忙等；启动后 `vTaskDelay()` 让出 CPU |
| `console.c/h` | `console_print()` 添加互斥锁防止输出交错 |
| `axi_dmac.c` | ISR 回调改用 `xSemaphoreGiveFromISR()` + `portYIELD_FROM_ISR()` |
| `lscript.ld` | SYS 栈 8→64 KB，IRQ/SVC/ABT/FIQ/UND 栈 1-2→4 KB，C 库堆 8→64 KB |

**新建文件**:
- `freertos_irq_glue.c`: 实现 `vApplicationIRQHandler()`，桥接 FreeRTOS IRQ 入口 → `XScuGic_InterruptHandler()`
- `FreeRTOSConfig.h`: FreeRTOS 完整配置

#### Phase 3: 应用任务架构

| 任务 | 优先级 | 栈 | 触发方式 | 功能 |
|------|--------|-----|----------|------|
| BLE_EXADV | 9 (最高) | 8 KB | 100us 定时 | BLE extended advertising + BlueBee secondary |
| DAC_DMA_BH | 9 | 4 KB | DMA ISR 通知 | DAC DMA 下半部 |
| BLE_TX | 8 | 8 KB | 100us 定时 | BLE 普通 advertising TX |
| ADC_DMA_BH | 8 | 4 KB | DMA ISR 通知 | ADC DMA 下半部 |
| BLE_RX | 7 | 8 KB | 事件驱动 | BLE 接收处理 |
| CONSOLE | 5 (最低) | 4 KB | UART 轮询 | 串口命令交互 |
| Idle | 0 | 1 KB | — | FreeRTOS 内置 |
| Timer Service | 10 | 2 KB | — | FreeRTOS 内置 |

任务间通信：DMA ISR → Bottom-half 用 Task Notification，Bottom-half → 业务任务用 Binary Semaphore，SPI 用互斥锁串行化。

#### Phase 4: 验证策略

1. **内核验证**: 两任务交替运行、`vTaskList()` 输出、tick 中断正常
2. **HAL 验证**: SPI 互斥、DMA ISR→任务通知、console 互斥、延时让出 CPU
3. **全功能验证**: nRF Connect 检测 primary 广播、`zigbee_rx.py` 检测 ZigBee 帧、连续运行 1 小时无栈溢出

### 关键风险

- **FPU 上下文**: FreeRTOS 替换 VBAR 后 Xilinx 向量表不再使用，FPU 由 FreeRTOS portASM.S 管理
- **BLE 时序**: BLE_EXADV 最高优先级，不被其他任务抢占
- **SPI 优先级反转**: CONSOLE 最低优先级，即使持有 SPI 锁也不会饿死 BLE 任务
- **malloc 线程安全**: 所有 C 库堆分配在 `hw_init()`（调度器启动前）完成

## 阶段结论（BLE/CTC 部分）

- 旧阶段的"手机显示完整 BLE extended advertising secondary 数据"路线已暂停，不再作为当前主线目标。
- 当前主线改为利用 BLE exadv 的双包调度外壳，在 `ch39 / 2480 MHz` 上发 primary，并在同频发 BlueBee secondary。
- 裸机 `ble_exadv_tx?` 现阶段只保留 `aux_delay_us interval_us` 两个参数，默认推荐命令形态为 `ble_exadv_tx? 600 10000`。
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
  - `bluebee_zigbee_frame_iq_30_72M.py`：生成纯 bluebee 构造的完整 zigbee 帧
  - `bluebee_phase_analyze.py`、`bluebee_phase_zigbee_rx.py`：BlueBee/ZigBee 分析辅助工具
- `python/ctc_sim/std_zigbee/`
  - `bluebee_rx.py`：当前主接收验证脚本，用于解调 bluebee 构造的 zigbee 帧
  - `zigbee_rx.py`：标准 zigbee 解调脚本
- `python/std_ble/`
  - `generate_ble_exadv_iq_30_72M.py`：将 bluebee 负载嵌入到 BLE 广播包中，调试参数 `--timing-debug-same-channel --channel 39 --append-bluebee-zigbee --aux-offset-us 600 --post-pad-us 10`

### 裸机端
- `app_B2Z/`：当前主应用（含 BLE/CTC 代码），57 个源文件
- `app_FreeRTOS/`：FreeRTOS 移植目标目录（当前是 `app_e310/` 副本，缺 BLE 文件）
- `app_e310/`、`app_e200/`、`app_e310v2/`：参考裸机应用（无 BLE 代码）
- `hdl/projects/antsdre310/antsdre310.sdk/`：Vitis SDK 工作区
  - `app/src/`：SDK 中编译的源文件
  - `system_top/ps7_cortexa9_0/standalone_ps7_cortexa9_0/bsp/`：BSP

### HDL 端
- `hdl/projects/antsdre310/`：Vivado 工程（2021.1）
  - `system_top.v`：顶层 Verilog
  - `system_bd.tcl`：Block Design 脚本（含地址映射和中断连接）
  - `system.xdc`：约束文件

## 注意事项

1. 工作区裸机程序代码未被 git 追踪。
2. 裸机代码修改后，只检查代码逻辑和语法，由用户自行编译和上板。
3. 以实际规范为准，历史注释和旧实验记录可能已过时。
4. `python/ctc_sim/stc_zigbee` 是笔误，实际路径是 `python/ctc_sim/std_zigbee`。
5. `doc/BLE_Core_v5.1.pdf` 可作为 BLE 规范参考，但当前阶段不再以"规范手机跟随 AuxPtr"作为主要成功判据。
6. FreeRTOS 移植使用 `FREERTOS_INTEGRATION` 条件编译宏，所有 HAL 修改通过 `#ifdef` 保持裸机兼容。
7. `app_FreeRTOS/` 缺少 BLE/CTC 文件，实现时需从 `app_B2Z/` 复制。
8. 当前DMA实现中无法正常触发IRQ信号，在之后的处理中要主动检查相关寄存器确定传输状态。

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
