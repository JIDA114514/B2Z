# 旧 BlueBee 性能协议与可选支撑实验

迁移：2026-11-19，保留原 AGENTS.md 的协议、参数和统计规则。修改 pure/exadv 性能命令、测试头、生成模式或开展性能支撑实验时必须阅读。以下实验阶段仅在明确开展对应性能研究时适用，不是当前 UC1 论文的前置要求。FreeRTOS/裸机对照仅在开展该项对照时验收。文中的 99% 是旧性能稳定点条件，不是新论文预设结果。

## 支撑目标：BlueBee 性能测量与优化

在 Zynq-7020 平台上建立可重复的 BlueBee 性能测试链路，准确区分板端生成或 DMA 漏发与无线链路丢包，并寻找满足稳定性要求的最大有效吞吐量。测试分为两级：

1. **纯 BlueBee（pure）**：测量波形生成、DMA 提交和 PHY 的性能上限。
2. **exadv 外壳（exadv）**：测量 BLE extended advertising 双包调度下的最终端到端有效吞吐量。

手机 nRF Connect 不再是当前阶段的主要验收手段。标准接收链路使用 `python/ctc_sim/std_zigbee/zigbee_rx.py`，`bluebee_rx.py` 仅作为诊断链路。

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

## 既有 BlueBee 性能测试协议（保持兼容）

以下协议用于 pure/exadv 性能基线，不直接规定新联合控制包格式。不得因研究主线调整而静默改变已有命令、测试头、填充或 Sequence 规则。

### Payload 格式

每个测试 payload 使用固定的 10 字节测试头：

| 偏移 | 长度 | 字段 | 编码 |
|------|------|------|------|
| 0 | 2 B | Magic | 固定为 `B2 5A` |
| 2 | 1 B | Version | 当前为 `1` |
| 3 | 1 B | Header length | 固定为 `10` |
| 4 | 2 B | Run ID | 小端 |
| 6 | 4 B | Sequence | 小端 |

测试头之后的剩余空间使用由 Run ID 和 Sequence 决定的确定性数据填充。发送端和接收端必须使用相同的填充算法，使接收端能够校验整个 payload，而不只检查测试头。填充算法固定为 32 位无符号 LCG：初始状态为 `0xB25A5A2D ^ (run_id << 16) ^ sequence`，每生成一个填充字节先执行 `state = state * 1664525 + 1013904223`（按 32 位回绕），再取 `state` 的最高 8 位。

Sequence 按计划发送时隙递增；即使该时隙发生生成失败、DMA 提交失败或 DMA 超时，也不得复用或回退序列号。由此可通过板端统计与接收端序列缺口区分板端漏发和无线链路丢包。

### 板端命令

```text
bluebee_pure_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]
bluebee_exadv_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]
bluebee_perf_stop?
bluebee_perf_status?
```

参数规则：

- `bluebee_pure_perf_start?`：只启动纯 BlueBee 性能实验。
- `bluebee_exadv_perf_start?`：只启动 exadv primary/secondary 嵌套性能实验。
- 两个启动命令沿用下列相同参数规则；同一时间只允许一个性能实验，已有实验运行时，任一启动命令均返回 `busy`。
- `payload_len`：10–46 字节，包含 10 字节测试头。
- `interval_us`：计划发送时隙间隔，必须为正数。
- `duration_s=0`：持续发送，由接收端控制观察时长，使用 `bluebee_perf_stop?` 停止。
- `duration_s=1..600`：板端有界实验，到时自动停止。
- `run_id`：可选的 16 位实验标识；未提供时由板端生成并在启动输出中报告。
- 所有参数均为十进制整数；不接受模式名称、键值参数、小数、科学计数法或十六进制形式。
- `mode`：`0=realtime`、`1=batch`、`2=double`；省略时默认为 `0`。
- 可选参数必须严格按位置提供：指定 `mode` 时必须先提供 `run_id`，指定 `batch_size` 时必须提供前面的全部参数。
- `batch_size` 必须为正整数且仅允许在 `mode=1` 时提供；其他模式必须省略。
- 完整启动命令最多包含 6 个数字参数；后续板端实现不得受当前通用解析器 5 参数上限影响。
- 启动输出和 `bluebee_perf_status?` 必须报告实际采用的生成模式和 batch size，便于人工确认和脚本解析。
- 有界实验的预计包数固定为 `floor(duration_s * 1000000 / interval_us)`。
- `bluebee_perf_status?` 必须报告运行配置（含 `test=pure` 或 `test=exadv`）、当前状态、已用时间和全部板端计数器。
- `bluebee_perf_stop?` 和有界实验自动停止时必须输出同一格式的最终统计，方便脚本解析。

## 性能支撑实验阶段

### Phase 1：序列号、统计与 PRR

板端至少记录以下计数器：

- `scheduled`：已经到达的计划发送时隙数。
- `generated`：成功完成 payload、BlueBee 映射和波形生成的时隙数。
- `tx_started`：成功提交到 DMA/RF 发送链路的时隙数。
- `tx_completed`：主动轮询确认 DMA 发送完成的时隙数。
- `deadline_miss`：未能在下一个计划时隙前完成本时隙工作的次数。
- `dma_timeout`：DMA 完成轮询超时次数。

接收端至少记录以下指标：

- `unique`：Run ID 匹配且首次出现的有效 Sequence 数。
- `duplicate`：同一 Sequence 的重复接收次数。
- `out_of_order`：Sequence 逆序到达次数。
- `crc_failure`：CRC/FCS 校验失败数。
- `longest_loss_burst`：观察范围内最长的连续 Sequence 丢失长度。

统一统计口径：

- 调度完成率：`tx_completed / scheduled`。
- 无线 PRR：`unique / tx_completed`。
- 端到端接收率：`unique / scheduled`。

计算比率时必须同时输出分子和分母；分母为 0 时输出 `N/A`。接收报告需与同一 Run ID 的板端最终统计合并后再计算无线 PRR，不能只根据接收端推测板端发送数。

已有实验允许人工统计收发有效包数；JSON 中 `board=null` 仅表示该文件未合并板端统计，不等于实验没有发送计数。人工记录须保留同一轮 Run ID、配置、观察边界、计数来源和原始记录，再导入报告或形成可审计的附表。仅有汇总数量不足以计算逐命令联合成功和同步误差，新实验需保存两侧逐事件结果。`tx_completed` 代表 DMA 完成，不自动保证完整空口发射；未校准时注明无线 PRR 使用的 DMA 完成代理口径，且可能包含接收处理损失。

标准 `zigbee_rx.py` 作为验收链路，`bluebee_rx.py` 作为波形、映射或解码异常时的诊断链路。测试工具必须同时输出便于人工阅读的文本报告，以及可供后续分析的 CSV 或 JSON 原始数据。

### Phase 2：灵活板上生成

实现三种生成模式：

- `realtime`：逐包实时构建 payload 并生成波形，用于测量 CPU 生成上限。
- `batch`：实验开始前预生成一批递增 Sequence 的波形，用于隔离并测量 RF/DMA 上限。
- `double`：使用双缓冲并行执行下一包生成和当前包发送，用于寻找最佳实际吞吐量。

分阶段记录并报告 frame 构建、BlueBee 映射、GFSK 调制和 DMA 提交的耗时，至少提供样本数、最小值、最大值和平均值。若目标平台资源允许，优先补充高分位数。

当前 DMA IRQ 无法可靠触发。所有模式都必须主动轮询相关 DMA 状态寄存器确认传输完成，不得把 IRQ 到达作为正确性或完成条件；轮询必须有明确超时，并累计到 `dma_timeout`。

### Phase 3：吞吐量扫描

固定扫描 payload 长度：10、16、24、32、40、46 字节。对 pure 和 exadv 分别扫描 `interval_us`，确定各自的性能上限和稳定工作点。

扫描流程：

1. 初步搜索使用 `duration_s=0` 持续发送，每个配置由接收端观察 30–60 秒。
2. 对候选最佳点使用板端有界模式确认，单次运行 300–600 秒。
3. 每次实验保存完整命令、Run ID、板端统计、接收端统计、RF/系统配置和原始 CSV/JSON 数据。
4. 分别输出 pure 上限、exadv 端到端最佳点，以及完整的 PRR–goodput 曲线。

吞吐量统一报告：

- Gross throughput：`unique * payload_len * 8 / observation_time`，包含 10 字节测试头。
- Application goodput：`unique * (payload_len - 10) * 8 / observation_time`，扣除测试头。

报告必须明确 observation time 的起止口径，并同时给出 bit/s 和 byte/s。`payload_len=10` 时 application goodput 为 0。

### Phase 4：FreeRTOS 与裸机对比

本节作为可选系统支撑实验，不再是双协议共包论文主线的前置验收条件；若开展该对照或声称系统收益，遵守以下规则。

FreeRTOS 与裸机实现必须使用相同的命令、测试头、Sequence 规则、确定性填充、BlueBee 波形映射和统计口径。

对照实验必须满足：

- 使用相同 bitstream、BSP、RF 参数、收发距离、接收链和实验配置。
- 每种系统对每个确认配置至少运行 3 轮，并交替安排两种系统的实验顺序。
- 单轮默认 300 秒，可调范围 30–600 秒，且不得超过 10 分钟。
- 比较 PRR、application goodput、deadline miss、DMA timeout、最长连续丢包、串口响应、栈余量、剩余堆和异常退出。
- 两种系统均需保持串口命令可响应，不得崩溃或永久失去响应。
- 不预设 FreeRTOS 一定更稳定；若差异不能重复，结论写为“未观察到稳定性提升”。

FreeRTOS 侧仍通过 `FREERTOS_INTEGRATION` 条件编译保持 HAL 对裸机模式的兼容。`app_FreeRTOS/` 中的全部源码修改必须同步到 SDK 实际编译目录后再进行构建和上板验证。

### 性能基线验收（开展对应支撑实验时）

- 能根据 Run ID 和 Sequence 准确识别丢包、重复和乱序。
- 46 字节 payload 完成不少于 1,000 包的序列验证。
- 能结合板端计数器区分板端漏发和无线链路丢包。
- 完成 pure/exadv、指定 payload 长度和 interval 的扫描，并保存可复查的原始数据。
- 最佳稳定点要求 PRR 不低于 99%，且 `deadline_miss=0`、`dma_timeout=0`。
- 若没有配置满足最佳稳定点要求，必须输出完整的 PRR–goodput 曲线，不得只报告单一最佳值。
- FreeRTOS 和裸机完成至少 3 轮同参数对照，每轮不超过 10 分钟。
- 两种系统均不得崩溃或永久失去串口响应。
- 所有 `app_FreeRTOS/` 源码修改均已同步到 SDK 实际编译目录。

## 历史 exadv 负载实验与当前容量约束

历史手机 nRF Connect 实验在当时配置下观察到 secondary 检测阈值，以下仅为该设备/配置的结果，不是 BLE 标准的通用上限。既有性能命令仍沿用 46 字节 ZigBee payload 上限，保持 pure/exadv 基线口径一致；新共包设计需重新核算和测量 BLE 命令、BlueBee 区域及同步信息共享容量。

| ZigBee payload | BlueBee bytes | PDU payload | 手机检测 |
|------|------|------|------|
| 46 B | 216 | ~238 | ✅ 正常 |
| 47 B | 220 | ~242 | ❌ 检测不到 |
| 48 B | 224 | ~246 | ❌ 检测不到 |
| 49 B | 228 | ~250 | ❌ 检测不到 |

- **旧性能协议测试上限**：当前性能命令仅接受 10–46 字节 payload，不代表新共包结构已验证同样容量。
- **实验阈值**：PDU payload 约 238 字节（216 BlueBee 字节 / 46 字节 ZigBee payload）是已有手机实验中的检测上限。
- **历史生成配置**：曾使用 46 字节 `DEFAULT_ZIGBEE_PAYLOAD`、`--include-flags` 和 `--name S`，实际默认值以脚本为准；共包空间核算必须计入这些字段。
- **历史理论吞吐**：46 字节 / 100 ms = 460 B/s（3680 bit/s）；本阶段以带序列统计的实测结果为准。
