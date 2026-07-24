# B2Z

主要开发基于 BLE 的跨技术通信（cross technology communication, CTC），具体原理基于 [BlueBee](https://doi.org/10.1145/3131672.3131678)。

当前主线是 FreeRTOS 分支：在 Zynq-7020 / AD9363 上运行 `app_FreeRTOS/`下的代码，使用 BLE extended advertising 的 primary/secondary 双包调度外壳，将 BlueBee 构造的 ZigBee frame 放入 secondary 包。常用工作流有两类：

- Python 端离线生成 IQ/C 头文件，用于分析、SDK 集成或 HackRF/接收链路验证。
- FreeRTOS 串口命令在板端启动 legacy BLE、切换共享 TX DMA 波形，或运行时生成 BlueBee / BLE exadv secondary 波形。

使用的硬件为 MicroPhase 的 e310，上面搭载 Zynq-7020 和 AD9363。

代码来自于 [MicroPhase 官方](https://github.com/MicroPhase/antsdr_standalone)的裸机代码程序，需要注意 hdl 中用于 e310 开发板的 Vivado 项目为 `antsdre310` 而非 `e310v2`。`e310v2` 的代码生成后在下板执行时可能会报错。

## 当前 Python 波形脚本

### BLE extended advertising + BlueBee secondary

`python/std_ble/generate_ble_exadv_iq_30_72M.py` 生成标准 BLE extended advertising 的 primary `ADV_EXT_IND` 和 secondary `AUX_ADV_IND` IQ 波形，并可把 BlueBee/ZigBee 负载追加到 secondary AdvData 中。

常用参数：

| 参数 | 说明 |
|------|------|
| `--channel` | legacy 单 primary 通道参数；默认 37。未设置 `--primary-channels` 时可用它指定 primary。 |
| `--primary-channels` | 一个 advertising event 中的 primary 通道列表，逗号分隔；默认 `39`。 |
| `--primary-spacing-us` | 多 primary PDU 的 start-to-start 间隔；默认 `9000`，需为 30 us 的整数倍。 |
| `--secondary-channel` | AuxPtr 编码的 secondary BLE data channel；默认 `3`。 |
| `--aux-offset-us` | primary 中 AuxPtr 编码的 secondary 偏移；默认 `30000` us。 |
| `--timing-debug-same-channel` | 调试模式：secondary 实际发在 primary 通道上，但 AuxPtr 仍编码为 `--secondary-channel`。当前同频验证常用该模式。 |
| `--diagnostic-profile` | 手机显示诊断 profile：`baseline-nonconn-nonscan`、`connectable-advdata`、`no-flags-name-only`；默认 `connectable-advdata`。 |
| `--include-flags` / `--no-include-flags` | 覆盖 profile 中是否加入 BLE Flags AD structure。 |
| `--no-name` | 省略 Complete Local Name，给 BlueBee 负载留出更多 AdvData 空间。 |
| `--append-bluebee-zigbee` | 在 secondary AdvData 后追加 BlueBee 构造的 ZigBee 内容。 |
| `--zigbee-payload` | BlueBee 模式下的 ZigBee payload，例如 `"0x11 0x22 0x33 0x44"`；默认是 46 字节 `0x00` 到 `0x2D`。 |
| `--bluebee-embed-mode` | `payload` 只映射 payload；`preamble` 映射 `00 00 00 00 A7 00`；`phy-frame` 映射完整 ZigBee PHY frame。默认 `phy-frame`。 |
| `--bluebee-ad-mode` | BlueBee bytes 在 AdvData 中的封装：`manufacturer` 或 `raw`；默认 `manufacturer`。 |
| `--company-id` | manufacturer AD structure 使用的 company ID；默认 `0xFFFF`。 |
| `--map-mode` | BlueBee chip-map：`legacy` 或 `optimized`；默认 `optimized`。 |
| `--phase-polarity` | 相位符号测试：`normal` 或 `inverted`；默认 `normal`。 |
| `--bt` | BLE Gaussian BT；默认 `0.5`。 |
| `--post-pad-us` | 每个 packet 后追加的零 IQ 静默；默认 `10` us。 |
| `--secondary-pre-pad-us` | AUX_ADV_IND 前追加的零 IQ 静默；默认 `0` us。 |
| `--output` | 输出 C 头文件路径；默认 `python/std_ble/ble_exadv_waveform_30_72M.h`。 |
| `--primary-symbol-name` / `--secondary-symbol-name` | 输出 C 数组符号名。 |

当前同频 BlueBee/secondary 验证示例：

```bash
python3 python/std_ble/generate_ble_exadv_iq_30_72M.py \
  --channel 39 \
  --timing-debug-same-channel \
  --append-bluebee-zigbee \
  --bluebee-embed-mode phy-frame \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --aux-offset-us 600 \
  --post-pad-us 10 \
  --output /tmp/ble_exadv_waveform_30_72M.h
```

### 纯 BlueBee ZigBee frame

`python/ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py` 生成纯 BlueBee PHY emulation 的 ZigBee PHY frame IQ，不包 BLE advertising PDU，适合单独验证 BlueBee 到 ZigBee 的投影关系和接收脚本。

常用参数：

| 参数 | 说明 |
|------|------|
| `--zigbee-payload` | ZigBee payload；默认 `"0x11 0x22 0x33 0x44"`。 |
| `--bt` | Gaussian filter BT；默认 `0.5`。 |
| `--post-pad-us` | frame 后静默；默认 `1000` us。 |
| `--map-mode` | `legacy` 或 `optimized`；默认 `optimized`。 |
| `--phase-polarity` | `normal` 或 `inverted`；默认 `normal`。 |
| `--output` | 输出 C 头文件路径；默认 `python/ctc_sim/bluebee/bluebee_zigbee_frame_30_72M.h`。 |
| `--output-iq` | 可选 complex64 IQ 文件，供 HackRF/offline analysis 使用。 |
| `--symbol-name` | 输出 C 数组名；默认 `bluebee_zigbee_frame_iq`。 |
| `--sdk-output` | 同时写出 `zigbee_tx.c/.h` 到 SDK source 目录。 |

示例：

```bash
python3 python/ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --map-mode optimized \
  --phase-polarity normal \
  --post-pad-us 1000 \
  --output /tmp/bluebee_zigbee_frame_30_72M.h \
  --output-iq /tmp/bluebee_zigbee_frame_30_72M.iq
```

### BlueBee BLE 组合脚本

`python/ctc_sim/bluebee/generate_bluebee_iq_30_72M.py` 是 BlueBee 调试用的组合生成器，支持三种 profile：

| `--profile` | 用途 |
|-------------|------|
| `extended` | 生成 primary `ADV_EXT_IND` + secondary `AUX_ADV_IND`；默认模式。 |
| `ble-visible` | 生成 BLE 可见的单包 advertising 形态，用于手机可见性调试。 |
| `zigbee-frame` | 生成 BlueBee 构造的 ZigBee frame 波形。 |

常用参数包括 `--embed-mode`、`--zigbee-payload`、`--channel`、`--secondary-channel`、`--aux-offset-us`、`--ext-adv-mode`、`--post-pad-us`、`--map-mode`、`--phase-polarity`、`--preamble-repeats`、`--ad-mode`、`--include-flags` / `--no-include-flags`、`--company-id` 和输出符号名参数。默认 `--profile extended`、primary channel `39`、secondary channel `3`、AuxOffset `6990` us、`--post-pad-us 10`、`--map-mode optimized`。

示例：

```bash
python3 python/ctc_sim/bluebee/generate_bluebee_iq_30_72M.py \
  --profile extended \
  --embed-mode phy-frame \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --channel 39 \
  --secondary-channel 3 \
  --aux-offset-us 6990 \
  --post-pad-us 10 \
  --output /tmp/bluebee_waveform_30_72M.h
```

## 当前 FreeRTOS 串口命令

FreeRTOS 运行时入口在 `app_FreeRTOS/`。串口 console task 会先处理带原始字符串参数的 BLE/BlueBee 命令，再回落到 AD9361/no-OS 原有命令表。

| 命令 | 作用 |
|------|------|
| `ble_tx_adv_name=<name>` | 设置 Complete Local Name，并启动 legacy advertising，在 ch37/ch38/ch39 轮发。 |
| `ble_tx_stop?` | 停止当前共享 TX DMA advertising 发送并恢复 DDS。 |
| `dma_tx_demo?` | 使用共享 TX DMA 发送内置 BLE ch39 legacy advertising 波形。 |
| `dma_switch?` | 在 `dma_tx_waveforms` 注册的 cyclic DMA 波形之间切换。 |
| `bluebee_gen_demo? [hex payload]` | 运行时构造纯 BlueBee ZigBee frame 并启动 cyclic TX DMA。无 payload 时使用默认 `11 22 33 44`。 |
| `ble_exadv_secondary_gen? [hex ZigBee payload]` | 运行时构造 BLE exadv secondary + BlueBee/ZigBee 波形并启动 cyclic TX DMA。无 payload 时使用默认 46 字节负载。执行时会先输出 `ble_exadv_secondary_gen: generating waveform...`。 |
| `bluebee_pure_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]` | 启动 pure BlueBee 性能实验；当前已实现 `mode=0` realtime。 |
| `bluebee_exadv_perf_start? <payload_len> <interval_us> <duration_s> [run_id] [mode] [batch_size]` | 启动 exadv primary/secondary 性能实验；当前已实现 `mode=0` realtime。 |
| `bluebee_perf_status?` | 输出当前配置、运行状态、板端计数器和分阶段生成耗时。 |
| `bluebee_perf_stop?` | 停止当前实验并输出最终 `PERF_STATS` 和 `PERF_TIMING`。 |

十六进制 payload 每个 token 最多 1 字节，可使用空格、逗号、冒号或分号分隔，`0x` 前缀可选。当前运行时 BlueBee payload 上限为 46 字节。

串口示例：

```text
ble_tx_adv_name=B2Z
ble_tx_stop?
dma_tx_demo?
dma_switch?
bluebee_gen_demo?
bluebee_gen_demo? 11 22 33 44
bluebee_gen_demo? 0x11,0x22,0x33,0x44
ble_exadv_secondary_gen?
ble_exadv_secondary_gen? 00 01 02 03 04
bluebee_pure_perf_start? 10 1000000 60 1234 0
bluebee_exadv_perf_start? 46 100000 60 1235 0
bluebee_perf_status?
bluebee_perf_stop?
```

`ble_exadv_secondary_gen?` 默认负载是当前手机可检测阈值内的 46 字节 ZigBee payload；nRF Connect 主要用于确认 ch39 primary 可见，HackRF 或其他接收链路用于确认 secondary/BlueBee 波形在 2480 MHz，`python/ctc_sim/std_zigbee/zigbee_rx.py` 或 BlueBee 接收脚本用于检查 ZigBee frame bytes/FCS。

## BlueBee 性能测量链

当前性能实现位于 `app_FreeRTOS/app/`，使用 Xilinx standalone BSP 驱动，并通过 `FREERTOS_INTEGRATION` 保持公共 HAL 的裸机兼容。`app_B2Z/` 尚未加入同名性能任务，不能把当前状态理解为 FreeRTOS 和裸机两个工程都已完成实现。

### 板端更新

- 每个 payload 使用 10 字节测试头：`B2 5A | version | header_len | run_id_le | sequence_le`；剩余字节使用由 Run ID 和 Sequence 决定的 32 位 LCG 填充。
- Sequence 按计划时隙推进，错过时隙不得补发或复用，用于区分板端漏发和无线丢包。
- `PERF_STATS` 报告 `scheduled`、`generated`、`tx_started`、`tx_completed`、`deadline_miss` 和 `dma_timeout`。
- `PERF_TIMING` 分别报告 frame、mapping、GFSK 和 total 的样本数、最小值、最大值和平均值。
- TX DMAC 在 IRQ 不可靠时主动轮询 `TRANSFER_DONE`/提交状态，并设置明确超时。
- pure 和 exadv GFSK 生成器将每个样本遍历 3072 个 Gaussian taps 的卷积改成“Gaussian taps 前缀和 + NRZ 符号区间求和”。相位积分、IQ 量化和 BlueBee 映射保持不变；pure 波形继续保留 1 ms 前后静默。

当前 realtime 只实现 `mode=0`；`mode=1` batch 和 `mode=2` double 的参数位置已经保留，但启动时会明确返回尚未实现。

10 字节 pure realtime 的实测平均耗时为：frame 约 3 us、mapping 约 1010 us、GFSK 约 22222 us、total 约 23237 us。1 秒间隔、60 秒实验已达到：

```text
scheduled=60 generated=60 tx_started=60 tx_completed=60
deadline_miss=0 dma_timeout=0
```

### Python 接收与统计

性能接收入口为 `python/perf_test/zigbee_perf_rx.py`：

- `--chip-source standard` 使用正式验收链 ZMQ 55556；该端口输出单路 10 Msample/s 差分相位 bit 流，Python 按模 5 拆成五个 2 Mchip/s 采样相位。
- standard 默认使用“硬判决成功直通、FCS失败才软重试”的 retry-only 模式，从并行 ZMQ 55562 的量化 `int8` 相位差窗口执行软 `CHIP_MAP` 重解码；只有完整软解码和FCS校验成功后才更新相位提示。`--no-standard-soft-retry`关闭整个软分支。
- `--chip-source phase` 使用 BlueBee 相位差诊断链；offset 0--4 对应 55557--55561。
- `--phase-keep-offset auto` 同时比较五相位，固定值 `0`--`4` 只订阅指定相位。
- 有效帧必须通过 ZigBee FCS、测试头、Run ID、Sequence 和确定性填充校验。
- CSV 保存每个最终提交的候选及所选 offset、极性和距离；JSON 保存接收计数、逐 offset candidates/FCS、完整处理耗时和板端合并后的比率。
- 当前默认接收校准参数为 RF=0、IF=32、BB=40、CFO correction=0；命令行仍可逐项覆盖。
- 使用 `--board-stats <serial.log>` 合并同一 Run ID 的最终 `PERF_STATS`，才能正式计算无线 PRR 和端到端接收率。
- standard 模式提供 `--payload-len` 时启用已知长度快速检测：使用一次 32-chip 相关与 8 路移位累加定位 preamble，只对少量局部候选解完整帧。五相位 48k-chip 合成缓存平均约 13.10 ms、最大约 16.13 ms，低于 24 ms 缓存跨度；JSON 的 `receiver.processing_timing` 记录包含 ZMQ 接收、解包、模 5 拆相和搜索的完整迭代耗时。
- standard 默认使用 `--standard-keep-offset auto` 同时比较五个采样相位，并使用标准 IEEE 802.15.4 `CHIP_MAP` 解扩；`--standard-ambiguity auto` 在未锁定前轮换差分极性，首次有效 FCS 后锁定。逐 offset 候选/FCS 统计写入 JSON `standard_offset_stats`。
- 模 5 拆相状态跨 ZMQ 消息和接收批次连续保存；同一突发被多个 offset 解出时只提交一次，之后再次收到相同 Sequence 才计为 duplicate。
- 修正后的原生相干 O-QPSK 链保留在 ZMQ 55566，仅用于接收机正向校验；它不再作为 BlueBee PRR 的正式输入。

one-shot phase 漏检的根因曾是 Python 五相位扫描约需 622 ms，而缓存只保留 6 ms。接收器已使用 NumPy 批量 Hamming distance、两 symbol 短前缀相关、局部完整帧解码和极性轮换/锁定；固定 offset 0 的 run 1238 在 12 ms 缓存下实测扫描平均 2.21 ms、最大 5.01 ms，板端发送 12 包并收到连续 Sequence 0--11。

run 1240 的五相位 auto 又暴露出逐消息 Python bit 解包和第二次滑窗相关开销：完整扫描最大 15.40 ms，超过当时的 12 ms 缓存。当前进一步改为整批 NumPy LSB-first 解包、用累计和替代第二次相关，并把 `MAX_CHIPS` 增至 48000（24 ms）。5×500 条合成消息的完整处理基准约 14.65 ms，下一轮仍须以 JSON 中包含 ZMQ 读取/解包的实际 `phase_scan_timing.max_ms < 24 ms` 为准。

固定相位诊断示例：

```bash
python3 python/perf_test/zigbee_perf_rx.py \
  --chip-source phase \
  --phase-keep-offset 0 \
  --duration 80 \
  --run-id 1238 \
  --payload-len 10 \
  --output-prefix python/perf_test/pure-1238-phase0
```

正式 standard 五相位验收示例：

```bash
python3 python/perf_test/zigbee_perf_rx.py \
  --chip-source standard \
  --standard-keep-offset auto \
  --standard-ambiguity auto \
  --duration 70 \
  --run-id 1248 \
  --payload-len 10 \
  --output-prefix python/perf_test/exadv-1248-standard-auto
```

### 部分实验数据

使用bluebee_exadv_perf_start?命令，将bluebee负载嵌入BLE拓展广播包的情况下有如下实验数据：

- 在单包负载10字节，发射间隔500ms,持续时间65秒的设置下，包接受率为93.846%，总吞吐量300.308bit/s,应用负载吞吐量150.154bit/s
- 在单包负载20字节，发射间隔250ms,持续时间65秒的设置下，包接受率为86.923%，总吞吐量834.462bit/s,应用负载吞吐量556.308bit/s
- 在单包负载40字节，发射间隔250ms,持续时间65秒的设置下，包接受率为78.077%，总吞吐量999.385bit/s,应用负载吞吐量749.538bit/s

五相位 phase auto 会增加 GNU Radio 分支、ZMQ 和 Python 扫描开销；当前流图即使固定 phase offset 也仍会发布全部五路。standard 的五相位则由 55556 单路全采样数据在 Python 中拆分，不需要五个 standard ZMQ 端口。phase 只作为诊断结果，最终 PRR 以 55556 和板端最终统计为准。

## Windows下复原vivado工程

### 所需软件

- git (用于从github上下载源码)
- vivado2021.1（用于复原工程）
- vitis 2021.1（用于搭建no-OS测试程序）

### 下载源码

首先需要从github上下载对应的源码。打开**git bash**，然后在mingwin中使用如下命令下载源码。

```bash
git clone --recursive https://github.com/MicroPhase/antsdr_standalone.git
```

![image-20210924190649784](README.assets/image-20210924190649784.png)

注意：在下载源码的时候，使用--recursive会递归的下载子模块当中的文件，只有这样才能保证所需要的版本是一致的。

![image-20221107172649783](README.assets/image-20221107172649783.png)

下载完源码之后，你将会看到有一个**hdl**文件夹。接下来就介绍如何在windows下使用vivado2021.1来复原工程。

### 使用vivado tcl命令行复原工程

关于使用vivado复原工程，可以参考adi官方说明：[ADI HDL Building](https://wiki.analog.com/resources/fpga/docs/build)

打开vivado2019.1，在tcl命令窗口中进入到antsdr工程所在的目录：具体的路径你自己的情况而定。主要是定位到hdl/project/antsdre310或者hdl/project/antsdre200目录下。

![image-20221107172535645](README.assets/image-20221107172535645.png)

然后依次执行如下命令：

```tcl
source ../scripts/adi_make.tcl
adi_make::lib all
source ./system_project.tcl
```

执行上述命令后，vivado将会依次检查所需要的IP，创建所需要的IP，生成Vivado工程并完成bit文件的生成。

![image-20210924191721108](README.assets/image-20210924191721108.png)

Vivado在构建IP和工程的时候，需要等待较长的时间，请耐心等待。

![image-20210924193419017](README.assets/image-20210924193419017.png)

![image-20210924193351690](README.assets/image-20210924193351690.png)

等到整个工程综合完成之后，可以在该工程的 **antsdre310.sdk**或者**antsdre200.sdk**文件夹下找到硬件描述文件，使用这个硬件描述文件，可以用来搭建no-OS工程。

### 搭建no-OS工程

对于Windows用户，为了简单构建no-OS的过程，请直接使用已经提供好的no-OS源码，也就是在git下载下来的源文件下的app_e310或者app_e200文件夹下的代码。

打开vitis软件，定位到**antsdrxxx.sdk**目录下

![image-20230207130507006](README.assets/image-20230207130507006.png)

创建新的工程

![image-20230207130611520](README.assets/image-20230207130611520.png)

首先需要根据导出的.xsa文件,创建一个硬件平台。

![image-20230207130651797](README.assets/image-20230207130651797.png)

![image-20230207130938975](README.assets/image-20230207130938975.png)

![image-20230207131005309](README.assets/image-20230207131005309.png)

创建好硬件平台之后，就可以创建一个新的软件工程了。

![image-20230207131059350](README.assets/image-20230207131059350.png)

在选择模板的时候，选择一个空的工程就可以了。

![image-20230207131141754](README.assets/image-20230207131141754.png)

然后将仓库当中的app_e200或者app_e310拷贝到当前的src文件夹下，然后点击编译，就可以生成可执行程序了。

![image-20230207131326326](README.assets/image-20230207131326326.png)

### 功能测试

接下来就可以连接串口jtag到到电脑上，然后在SDK中生成调试用的elf文件进行调试了。

![image-20210924232424492](README.assets/image-20210924232424492.png)

### NOTE

工程基于ADRV9361,可以支持2R2T,可以通过串口修改本振，采样率，增益，基带信号的频率，幅度等。
