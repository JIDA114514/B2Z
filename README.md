# B2Z

主要开发基于 BLE 的跨技术通信（cross technology communication, CTC），具体原理基于 [BlueBee](https://doi.org/10.1145/3131672.3131678)。

当前研究主线是基于 BLE extended advertising 的双协议共包控制与同步：在同一个 secondary `AUX_ADV_IND` 中承载 BLE 与 BlueBee/IEEE 802.15.4 信息。v1 共包、多任务发送、两侧独立命令解析和时间模型原型已实现，已有 BLE 跨信道跟随观察；公平对照收益、独立同步精度及严格 AuxPtr 空口时序仍待验证。板端现有工作主要位于 `app_FreeRTOS/`。

新代码按功能迭代提交，消息格式见[提交约定](CONTRIBUTING.md)。

当前进度与后续优先级以 2026-11-10 更新的[下一阶段计划](doc/next_stage_plan.md)为准。协议字段见[v1 负载草案](doc/control_sync_packet_v1_draft.md)，已有步骤见[多任务实验方案](doc/multi_task_control_experiment_plan.md)和[功能完成路线](doc/control_sync_function_plan.md)，相关先例见[设计研究笔记](doc/sync_control_payload_research.md)。较早文档中的待办状态需结合最新计划与实测报告阅读。

常用工作流有两类：

- Python 端离线生成 IQ/C 头文件，用于分析、SDK 集成或 HackRF/接收链路验证。
- FreeRTOS 串口命令在板端启动 legacy BLE、切换共享 TX DMA 波形，或运行时生成 BlueBee / BLE exadv secondary 波形。

使用的硬件为 MicroPhase 的 e310，上面搭载 Zynq-7020 和 AD9363。

代码来自于 [MicroPhase 官方](https://github.com/MicroPhase/antsdr_standalone)的裸机代码程序，需要注意 hdl 中用于 e310 开发板的 Vivado 项目为 `antsdre310` 而非 `e310v2`。`e310v2` 的代码生成后在下板执行时可能会报错。

## 当前证据与下一阶段

[1703–1705](doc/holdover_1703_1705_review.md)已有三轮独立录制上的离线相对时间保持复核；[1801](python/experiments/20261109_run1801/notes.md)在同频诊断模式下实现同槽双端有效 300/300、三任务联合解析 3/3，并完成[立即处理软件基线](python/experiments/20261109_run1801/analyses/immediate_baseline/report.md)。1801 的实时定时软件处理仍为 0/3，假设 1 ms 参考界的回放结果不能当作实测同步精度。[1906](python/experiments/20261109_run1906/analyses/std_ble_flow_20261109_182005_0f42d1/flow.summary.json)完成 9/10 个实际 BLE 跨信道跟随事件，缺失 DID 2 的 primary；该轮没有同时验证 IEEE 接收，也未校准空口 AuxPtr 时间。

下一阶段先补齐下面的证据，再对选定主要配置增加独立重复。详细交付物与统计规则见[完整计划](doc/next_stage_plan.md)。

Run 2001 已完成 N1 首轮功能验证：同槽双端有效 93/120、带 BLE 跟随证据的联合任务解析 3/3；这不表示可靠性或同步精度验收完成。[N2](doc/n2_separate_transmission_experiment_plan.md) 的 2101–2103 首轮已完成：固定接收两组均 120/120、任务 3/3；共包突发数减少 1/3，有效波形预算相等；2103 跟随 75/120、任务 3/3。功率配置仍未知，严格空口时序与同步精度未测。N3 的2203已完成缓存前移后300槽固定频点双端初验（联合300/300），2204完成跟随能力审计（91/120、BLE三命令恢复），其同轮IEEE数据缺项移至后续补采与重复阶段。当前按 [N4详细方案](doc/n4_capacity_experiment_plan.md)推进变长共包格式、容量扫描和legacy对照设计；尚未实现变长扫描接口。各阶段先完成有效初验，主要配置的独立重复后续集中开展。已有 [N1 执行方案](doc/n1_cross_channel_experiment_plan.md)继续作为复测入口。

| 顺序 | 工作包 | 要回答的问题 |
| --- | --- | --- |
| N1 | 同轮跨信道双端多任务：一块 HackRF 做 BLE 跟随，另一块固定 IEEE ch12 | 跟随、独立双协议解码、时间更新和多任务解析能否在最终配置下同时成立？ |
| N2 | 实现分别发送基线，并与共包立即处理、共包时间模型处理对照 | 在相同任务、截止时间及明确重发策略下，共包的联合解析率、RF 成本和完成时延有何收益或代价？ |
| N3 | 拆分板端 DMA 准备/提交/返回取时，建立独立时间参考与误差预算 | 记录偏差与实际发送偏差如何区分，能支持哪一层同步精度结论？取时诊断可与 N1/N2 并行 |
| N4/N5 | 容量与 legacy 对照、有效包数/更新间隔/失更/提前量/K 次重复等消融 | exadv 容量具体解决什么约束，效果来自哪些机制，哪些条件会失败？ |

计划进一步要求四项证据：最终跨信道发送与实际跟随接收条件下的相对时间保持、真实单侧漏收后的在线恢复、逐槽发送延迟与保持残差的归因、N1 跟随失败的阶段分解。2001 的 27 个 IEEE-only 槽是真实解码缺失，但尚无 BLE 在线保持/恢复精度；1703–1705 的同频离线掩码结果不能替代这些交付。跨信道固定接收 IQ 的相对预测为当前必测项；实际跟随时间精度取决于采样连续性是否可核验，无法核验时保留为未测。计划不要求新增硬件测量设备，具体观测范围、实验分层与未知原因处理见[下一阶段计划](doc/next_stage_plan.md)。

没有可审计的共同参考误差界时，论文结论限定为共包时间信息分发、相对时间保持及软件调度原型。主机回调时差、拟合残差及 `auxptr_dma_window_miss` 软件代理计数不能直接代替实际空口或跨设备同步精度。成本计入全部 primary、secondary、时间更新和重发，任务失败保留在分母内。商用芯片、执行器和更多独立节点作为扩展，创新性与性能收益仍需查新和对照支撑。

## 接收结果与实验归档

实验统一存放在 [`python/experiments/`](python/experiments/)。先看[实验索引](python/experiments/index.md)，进入某一轮的 `report.md`，再按需查看两侧接收报告、结构化数据和人工记录。

```text
python/experiments/
├── index.md / index.csv / runs.csv
├── history_*/                       # 原有实验归档
└── YYYYMMDD_run<run_id>/            # 主机本地日期 + 指定 Run ID
    ├── experiment.config.json
    ├── report.md
    ├── captures/
    │   ├── ble/<时间_唯一后缀>/rx.*
    │   └── zigbee/<时间_唯一后缀>/rx.*
    └── analyses/<回放标识>/<ble|zigbee>/rx.*
```

每个 `rx.*` 前缀包含 `.summary.json`（完整配置、原始计数及统计）、`.summary.txt`（简短文本）、`.report.md`（可读报告）、`.packets.jsonl`（完整逐包流）及 `.hackrf.log`；BLE 另有 `.events.jsonl`。实时采集默认保存 IQ，可用 `--no-save-iq` 关闭；离线回放默认不复制 IQ。终端显示运行状态、主要结果、数据质量和报告路径，完整计数保留在 JSON 中。

两条接收链使用同一个日期和 Run ID 自动进入同一归档目录；每次启动都保留独立的采集子目录。日期取主机本地时区，`run_id` 是实验标识；BLE 接收器仅用它标记归档，不用它推断包内已解码的命令。两台 HackRF 序列号、RF 信道和长期使用的解调参数集中在 [`receiver_defaults.py`](python/experiment_tools/receiver_defaults.py)，需要时仍可用命令行覆盖。

当前板端同频性能实验的两终端命令：

```bash
python3 python/exadv_rx/receive.py --run-id 10270
python3 python/zigbee_rx/receive.py --run-id 10270 \
  --payload-len 30 --expected-packets 150
```

先启动接收，再启动匹配的板端实验。上例 `150` 是显式计划范围，不由 40 秒接收时长推断；板端任务应为对应的 30 秒、200000 us 间隔。接收参数只是示例，不表示已经满足稳定性要求。

### 板端标准 BLE 跨信道流程核验

[`python/std_ble/verify_board_exadv.py`](python/std_ble/verify_board_exadv.py) 基于标准 BLE GNU Radio/HackRF 接收链，针对当前板端 v1 共包格式检查 ch39 `ADV_EXT_IND`、AuxPtr、切频后的 ch3 `AUX_ADV_IND`、两包 BLE CRC、扩展头/AD 结构、35 B BLE 控制记录校验及 ADI DID 对应关系。运行前连接 BLE 接收用 HackRF，先启动脚本，再从板端串口发送下面的命令；`rf_mode=1` 指定真正的 ch3 secondary，默认同频诊断模式不适用于这个验证：

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 1904 --command-id 43 --expected-attempts 10 \
  --osmosdr-args hackrf=0 --sample-rate 8000000 --duration 15
```

```text
b2z_control_start? 1904 43 500 10 5000 4500 1
```

脚本默认以板端当前设置检查 primary ch39、AuxPtr 指向 ch3、LE 1M、300 ms，secondary ch3；增益默认 `--gain 0 --if-gain 16 --bb-gain 10`，可按接收条件调整。确认板端 `CONTROL_STATS` 后，可用 `--board-log <path>` 将其纳入分析。每轮自动写入 `python/experiments/YYYYMMDD_run<run_id>/analyses/std_ble_flow_*/`，包含 `flow.md`、`flow.summary.json` 和 `flow.events.jsonl`，并更新实验索引。实时模式退出码 0 表示预期 DID 均在同一 HackRF 的 AuxPtr 驱动切频过程中通过 BLE 与应用校验并配对；离线模式退出码 0 只表示同轮双文件的内容与 DID 关联完整。退出码 2 表示观察不完整或校验失败。命令行 `FOLLOW` 是单接收机的流程证据。

1905 的固定 ch3 IQ 表明，GNU Radio 旧接收链对前导码要求逐位完全相同会漏掉 CRC 正确的 secondary，且 4 Msps 解调在该 IQ 上不稳定。当前解析器允许前导码至多 2 位错误和任意 bit 对齐，仍要求完整 BLE CRC；跟随脚本默认改为 8 Msps。后续 1906 实时观察到 9/10 个配对事件；脚本仍按预设全部 10 个 DID 判断验收，因此该轮 `verification_passed=false`，不表示 9 个实际跟随事件无效。

已有的两频点固定接收逐包文件可用 `--primary-packets <ch39 rx.packets.jsonl> --secondary-packets <ch3 rx.packets.jsonl>` 离线复核 BLE 内容；仅同轮且采集时间重叠才进行 DID 关联。不同轮只能加 `--allow-cross-run-structure-only` 检查结构，不能视作跟随成功。Host 回调时刻和独立 IQ 的采样起点尚未校准；以上两种模式都不判定实际空口 AuxPtr 时间误差，也不宣称完整 BLE 规范兼容性。报告中的 `aux_air_timing_verified` 与 `full_standard_exadv_verified` 因此始终为 `false`。

离线回放默认读取完整 IQ，另存于当天相同 Run ID 的 `analyses/`，不复制输入 IQ。`--analysis-id` 可命名一轮对照；已有分析标识拒绝覆盖：

```bash
python3 python/zigbee_rx/receive.py \
  --iq-file /path/to/capture.ci8 --run-id 10270 \
  --payload-len 30 --expected-packets 150 --analysis-id replay_001
```

两接收器的 `--output <prefix>` 仍保持旧的前缀语义，与 `--experiment-dir` 互斥；已有结果拒绝覆盖。显式输出到归档树内时自动更新本轮报告和总索引；树外的旧前缀输出不会自动加入中央索引。`capture_single_dual.py` 与 `validate_saved_iq.py` 的默认输出也进入该归档树；前者按 `captures/<stage>/<receiver>/` 分阶段保存。

### 历史结果与可复查性

原 `exadv_rx/results`、`zigbee_rx/results` 及 `sync_validation/results` 中的 375 个实验文件已归档到 29 个 `history_*` 目录。实时采集按原前缀分组；有明确输入 IQ 路径的回放放入该采集的 `analyses/`；跨轮分析集中在 `history_*_reviews`。既有组合实验保留原分组及文件名，位于 `history_sync_*/analyses/legacy/`，其中每条接收记录仍按自身配置区分 live/replay。归档目录数不能当作独立实验重复次数。

历史 JSON、文本、人工报告和 IQ 内容均保持原样，因此其中可能仍写着旧路径。迁移清单保存所有旧/新路径及原始 SHA-256；接收器的 `--iq-file` 可解析清单中的旧路径，也可手动查询。历史目录中的 `.report.md` 和顶层 `report.md` 是新生成的阅读层，不覆盖原有报告。

```bash
# 重建报告与索引；不会重新解码 IQ 或更改历史统计
python3 python/experiment_tools/manage.py index

# 查找旧记录的新位置
python3 python/experiment_tools/manage.py locate \
  python/exadv_rx/results/rx_20261026_161955_853914.ci8

# 逐文件复核本机迁移结果（需要原始大文件仍在本机）
python3 python/experiment_tools/manage.py verify
```

正常结束只代表程序完成；没有匹配板端计数及完整观察窗口时无线 PRR 为 `N/A`，不将它显示为 0%。同目录分组不自动产生联合成功率，也不能将独立设备时间戳直接相减。现有联合分析必须依据逐 Run ID/Sequence 匹配结果；未来控制命令另按正式定义的 command_id 关联。指标单位、分子分母和观测边界见各报告。

### Git 与大文件

[`python/experiments/.gitignore`](python/experiments/.gitignore) 递归放行小型摘要、配置、清单、指标 CSV、Markdown、设备/板端日志及已有分析图；完整 IQ、完整 `.packets.jsonl`、控制台日志、锁和临时文件默认忽略。`artifacts.csv` 描述本机扫描到的文件，不是 Git 收录清单，也不是外部备份证明；新文件尚未计算哈希时显示 `N/A`。`.events.jsonl` 可提交，但需检查大小。

Git clone 不会恢复忽略的大文件。关键 IQ 和完整逐包流需另外备份；移动到外部存储时保存对应 `*.manifest.json`，记录位置、字节数、哈希及采样率/中心频率/格式。原 results 目录保留说明和兼容规则，后续实验优先使用统一归档。

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
| `b2z_control_start? <run_id> <command_id> [...]` | 启动有限次数的 v1 双协议控制与时间广播；默认 `rf_mode=0` 为同频诊断，末尾 `rf_mode=1` 为 ch39 primary / ch3 secondary，参数见 [FreeRTOS 命令说明](app_FreeRTOS/README.md#十六v1-双协议控制与时间广播命令待上板验证)。 |
| `b2z_plan_clear?`、`b2z_plan_add? ...`、`b2z_plan_start? <run_id> <period_ms> [rf_mode]` | 建立并启动一轮多任务计划；模式 1 需按跨信道周期重算有效期。逐任务与逐时隙日志见 [FreeRTOS 多任务说明](app_FreeRTOS/README.md#一轮多任务计划待上板验证)。 |
| `bluebee_perf_status?` | 输出当前配置、运行状态、板端计数器和分阶段生成耗时。 |
| `bluebee_perf_stop?` | 停止当前性能实验或控制广播；分别输出 `PERF_STATS`、`CONTROL_STATS` 或 `CONTROL_PLAN_STATS`。 |

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
b2z_control_start? 1001 42
bluebee_perf_status?
bluebee_perf_stop?
```

`ble_exadv_secondary_gen?` 默认负载是当前手机可检测阈值内的 46 字节 ZigBee payload；nRF Connect 主要用于确认 ch39 primary 可见，HackRF 或其他接收链路用于确认 secondary/BlueBee 波形在 2480 MHz，`python/ctc_sim/std_zigbee/zigbee_rx.py` 或 BlueBee 接收脚本用于检查 ZigBee frame bytes/FCS。

新命令的 ZigBee 侧 `B2 43` 控制记录可用 [实时接收脚本](python/zigbee_rx/README.md#b2-43-控制包实时分析)逐包校验；两侧保存的记录再用 [control_match 离线脚本](python/control_match/README.md)逐时隙匹配。它们与旧性能测试的 `B2 5A` 有效计数分开。只有两条接收链同时录制同一轮发送，才计算联合有效解码。

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
