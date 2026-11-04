# 一轮多任务共包控制：实验方案

状态：2026-11-04 制定，板端 `b2z_plan_*` 代码已通过 ARM 语法检查并同步 SDK 编译目录，**尚待构建和上板验证**。本方案先验证计划调度、同一 secondary 双侧独立解码及单侧软件控制，再在射频条件可控、时间参考可校准后测可靠性、效率和同步性能。软件事件不等于物理执行器动作。

## 1. 问题、拓扑与实验单位

发送端为一块 Zynq/AD9363 板；BLE 侧与 IEEE 802.15.4 侧各用一块 HackRF 独立接收。主机只在**两侧独立完成 CRC/FCS 和应用记录解析之后**合并统计。当前板端在 ch39/2480 MHz 发送 primary 与共包 secondary，AuxPtr 声明的跨信道位置尚不符合实际发射；本轮只验证同频诊断共包，不称为规范 exadv 跟随。IEEE 802.15.4 侧是 PHY 帧和实验应用负载，不是完整 ZigBee 协议栈。

一个 `run_id` 是一次板端计划和两份同步录制的关联键；一个非零 `command_id` 是一个逻辑任务；`slot_index` 是全轮物理发送尝试，包含纯时间更新和可能漏掉的时隙。一次任务的 K 次重发只计 **1 个计划任务**。同一任务可由两侧在不同重发时隙恢复；同一时隙两侧都收到则另计“同尝试联合有效解码”。三者不互换。

## 2. 首轮固定计划和预期内容

固定 `period_ms=200`，两条命令各重发 3 次，在前后插入纯时间更新。先在板端输入前五行准备计划；**两侧接收器显示启动后**再输入最后一行。再次运行同一配置时换 `run_id`，先 `b2z_plan_clear?`。以下 1601 仅是未使用的示例编号。

```text
b2z_plan_clear?
b2z_plan_add? 0 2 0 0
b2z_plan_add? 43 3 5000 4000 1 1 1 2 1 1
b2z_plan_add? 0 1 0 0
b2z_plan_add? 44 3 7000 6000 1 1 2 2 2 7
b2z_plan_start? 1601 200
```

| 条目 | 时隙 | 计划 `ref_tick_ms` | BLE 侧 | IEEE 802.15.4 侧 | 任务分母 |
| --- | --- | --- | --- | --- | ---: |
| 0 | 0–1 | 0、200 | 纯时间更新 | 纯时间更新 | 0 |
| 1 | 2–4 | 400、600、800 | 命令 43：节点 1 `SET_STATE(1)` | 命令 43：节点 2 `SET_STATE(1)` | 1 |
| 2 | 5 | 1000 | 纯时间更新 | 纯时间更新 | 0 |
| 3 | 6–8 | 1200、1400、1600 | 命令 44：节点 1 `SET_STATE(2)` | 命令 44：节点 2 `TRIGGER(7)` | 1 |

计划共 **9 个时隙、2 个逻辑任务、6 个命令尝试、3 个纯时间更新**。`valid_until_ms` 均晚于该任务最后一次计划时隙，且早于 `execute_at_ms`。板端约 2 s 结束广播；接收软件仍需持续到本轮 7 s 目标时刻之后。两侧 35 B 记录的共同字段应逐时隙一致，BLE ADI/DID 应等于 `slot_index & 0xFFF`，每个事件的 secondary PDU payload 应为 224 B。设计预算为每事件一 primary（136 µs）加一 secondary（1872 µs），9 次约 18.072 ms RF 发射时间；它是格式计算值，须以实际波形/发射配置复核，不含两包间静默，也不是从 DMA 完成推得的实测空口时间。

## 3. 可立即执行的流程

### A. 构建与板端计划检查

由用户在 Vitis 构建、上板，并保存 ELF 标识、源码/SDK 副本哈希、bitstream/BSP 版本及串口原始日志。先执行 `b2z_plan_clear?` 和四条 `b2z_plan_add?`，核对每条 `CONTROL_PLAN_ADD` 的 `entry/first_slot/repeats/command_id/execute_at_ms/valid_until_ms/两侧命令`，再启动接收器。边界检查另用独立准备过程确认重复非零 `command_id`、零重复、过期于最后计划时隙、超过 16 条或 1024 时隙时会拒绝启动；这些失败准备不计入主实验轮次。

### B. 两块 HackRF 独立录制

为防两进程跨午夜落入不同默认日期目录，给两端指定同一个实验目录；把 `20261104` 和 1601 换成实际日期和新 Run ID。先在两个终端运行，确认都进入采集，再立刻输入板端最后一行 `b2z_plan_start? 1601 200`。30 s 录制留出人工启动和软件目标时刻余量；若未覆盖板端整轮或 7 s 目标时刻，这轮标为不完整并换新 ID 重做。

```bash
EXP_DIR=python/experiments/20261104_run1601
python3 python/exadv_rx/receive.py \
  --run-id 1601 --experiment-dir "$EXP_DIR" --channels 39 \
  --control-target-id 1 --duration 30 --quiet
```

```bash
EXP_DIR=python/experiments/20261104_run1601
python3 python/zigbee_rx/control_receive.py \
  --run-id 1601 --experiment-dir "$EXP_DIR" --channel 26 \
  --expected-packets 9 --control-target-id 2 --duration 30 --quiet
```

首轮保留两份 IQ；后续独立重复可加 `--no-save-iq`，但异常配置和关键结果至少保留可复查 IQ。ZigBee 端**省略** `--command-id`，使一轮内 43、44 和纯时间更新均参与统计。多任务板端日志保存为该目录下的 `board.board.log`；当前接收器的 `--board-log` 和 `control_match/analyze.py` 只理解旧单任务 `CONTROL_STATS`，不能把新日志喂给它们计算多任务 PRR。两侧采集应保存 `rx.summary.json`、`rx.packets.jsonl`、`rx.control.events.jsonl`、`rx.control.tasks.csv`、`rx.control.summary.json`、`rx.hackrf.log` 及配置。

### C. 当轮核对

1. 板端出现一条 `CONTROL_PLAN_START`、四条 `CONTROL_PLAN_ENTRY`、一条 `final=1` 的 `CONTROL_PLAN_STATS`、四条 `CONTROL_PLAN_TASK` 和 9 条 `CONTROL_PLAN_SLOT`；检查时隙 0–8 无缺号、条目归属与上表一致。完整健康轮预期 `reached_slots=generated=primary_started=primary_completed=tx_started=tx_completed=9`，`deadline_miss=dma_timeout=0`。任一项不符时保留原始日志，分别报告漏调度、生成失败、primary 或 secondary DMA 问题，不把它归入无线丢包。
2. 两侧独立从各自 IQ 恢复外层 CRC/FCS 和应用 CRC16；逐侧核对 Run ID、时隙、命令、目标、操作码、参数、`ref_tick_ms=200×slot_index`。同一时隙两侧都解码到时，再核对共同字段；一侧缺包时不使用另一侧的字段补齐。9 时隙全部解码是理想结果，射频环境不稳定时只对**实际恢复的包**判定字段正确性；缺包导致的功能项标记“未能观测”，可靠性分母仍保留全部计划任务/时隙。
3. 默认未提供已校准的发送参考误差界，`time_quality_insufficient` 拒绝定时任务是**预期行为**；本轮 `software_processed=0` 不表示解析失败。纯时间更新应更新本侧模型，但不得产生任务动作。每侧同一 `command_id` 最多一次 `accepted` 和一次 `software_processed`，重发不能重复改状态或触发。
4. 若首轮保存 IQ，可把 BLE 的一份 IQ 再交给 ZigBee 接收脚本离线解码，独立检验“同一 IQ、同一 secondary 波形”两种解码路径；该分析目录明确标记 `same_iq`，不与两块 HackRF 的独立双端结果合并，也不算新增物理重复。`BLE_IQ` 取 BLE 捕获目录内实际生成的 `rx.ci8`：

```bash
EXP_DIR=python/experiments/20261104_run1601
BLE_IQ="$EXP_DIR/captures/ble/<实际接收子目录>/rx.ci8"
python3 python/zigbee_rx/control_receive.py \
  --iq-file "$BLE_IQ" --run-id 1601 --channel 26 \
  --experiment-dir "$EXP_DIR" --analysis-id same_iq \
  --expected-packets 9 --control-target-id 2 --quiet
```

### D. 仅验证软件路径的假设回放

在首轮 IQ 上分别重跑两侧接收脚本，指定同一个新的 `--analysis-id functional_assumed_1ms` 和 `--control-assumed-reference-bound-ms 1`。将下述两个 IQ 变量换为各自真实文件路径：

```bash
EXP_DIR=python/experiments/20261104_run1601
BLE_IQ="$EXP_DIR/captures/ble/<实际接收子目录>/rx.ci8"
ZIGBEE_IQ="$EXP_DIR/captures/zigbee/<实际接收子目录>/rx.ci8"
python3 python/exadv_rx/receive.py \
  --iq-file "$BLE_IQ" --run-id 1601 --channels 39 \
  --experiment-dir "$EXP_DIR" --analysis-id functional_assumed_1ms \
  --control-target-id 1 --control-assumed-reference-bound-ms 1 --quiet
python3 python/zigbee_rx/control_receive.py \
  --iq-file "$ZIGBEE_IQ" --run-id 1601 --channel 26 \
  --experiment-dir "$EXP_DIR" --analysis-id functional_assumed_1ms \
  --expected-packets 9 --control-target-id 2 \
  --control-assumed-reference-bound-ms 1 --quiet
```

该 1 ms **只是故意输入的功能假设，不是板端计划时刻到 RF 起点的实测上界**；结果只用来检查命令 43、44 的接受、冻结、软件处理、去重和状态：BLE 最终节点 1 状态为 2；IEEE 802.15.4 侧节点 2 状态为 1，另有 `TRIGGER(7)` 软件事件。记录每侧 `accepted/scheduled/software_processed/cancelled` 和原因。若一侧没有收到某任务，不能将另一侧记录复制过去；该任务的软件路径验收标为未能观测。要研究迟到、过期、错误目标、冲突字段或连续漏收，可从保存 IQ 的**独立解码结果**做注明变换规则和随机种子的离线注入/回放，单列为仿真，不算物理实验轮次。

## 4. 预先固定的统计表

| 层次 | 分母 | 分子或字段 | 解释 |
| --- | --- | --- | --- |
| 板端时隙 | 9 个计划时隙 | `reached/generated/primary_completed/tx_completed`，逐时隙标志 | DMA 完成是发射代理，不是 RF 起点或完整空口证据。 |
| 单侧有效解码 | 9 个计划时隙；另报对应 `tx_completed` | 各侧不同有效 `slot_index` 数 | 未确认覆盖完整发送期时，对 DMA 完成的比率为 N/A。 |
| 同尝试联合解码 | 9 个计划时隙 | 同一时隙两侧共同字段均有效的数量 | 逐时隙四象限：两侧、仅 BLE、仅 IEEE 802.15.4、两侧均无。 |
| 逐任务联合解析 | 2 个计划任务 | 两侧对同一 `(run_id,command_id)` 各至少恢复一次的任务数 | 允许两侧来自不同重发；不要求相邻包。 |
| 单侧软件处理 | 每侧各 2 个计划任务 | 该侧 `accepted`、`scheduled`、`software_processed`、`cancelled` 的任务数 | 默认无参考界时处理率预期为 0；假设回放结果另列。 |
| 联合软件处理 | 2 个计划任务 | 两侧均有独立软件处理事件的任务数 | 只能称软件原型结果，不能称物理执行成功。 |
| 同步/时差 | 有独立参考与校准后的任务 | 误差中位数、P95、P99、最大值、CDF、失更年龄 | 本轮没有共享采集零点与实测 RF 起点时填 N/A，不能相减两侧 `sample_start` 或主机时钟。 |

每个比率同时保存整数分子和分母；分母为 0 记 N/A。逐任务主键为 `(run_id, command_id)`，纯时间更新按 `slot_index` 单列。每任务的计划 K、已到达时隙、板端各阶段计数、两侧首次/全部有效时隙、接受/拒绝原因和软件事件要能回溯到 `CONTROL_PLAN_ENTRY/TASK/SLOT` 及两份 JSONL。任何 `tx_completed < decoded`、字段冲突、超出计划范围、接收队列溢出或采集异常均单独审计，不能强行计算成功率。

当前 `control_match/analyze.py` 按**单个** `command_id` 分析，且不解析 `CONTROL_PLAN_*`。在下一阶段逐任务联合分析器完成前，可人工按上述主键复核并保存可审计附表；不能直接引用旧脚本对多任务整轮的“联合成功率”。

## 5. 重复、边界与后续对照

- **功能重复**：固定上表计划，用 1601、1602、1603 等三个互异 Run ID 做至少 3 轮独立双端录制。每轮都重新清空/加入计划；记录各轮板端和接收异常。没有收到两侧任务包时，这一轮仍计入可靠性分母，但相应字段/软件功能验收记“未能观测”，不能只挑收包成功轮报告。
- **K 值扫描（射频稳定后）**：固定任务字段、RF 条件、200 ms 周期及 5 s/7 s 目标时刻，把两个任务的重复数同设 K=1、3、5。布局均为前 2 个纯时间时隙、任务 43 的 K 次、1 个纯时间时隙、任务 44 的 K 次，计划总时隙为 `3+2K`，即 5/9/13；`valid_until_ms` 仍为 4000/6000。每配置至少 3 轮，交替 K 顺序，记录每轮与跨轮置信区间；按**任务**算联合解析率，按全部 primary+secondary 尝试算空口成本，连续丢失按轮保留，不把所有包当作独立样本。
- **异常与边界**：分别做错误目标、`NOOP`、纯时间更新、重复包、缺失前若干时隙、间隔较远的有效包、提前 `bluebee_perf_stop?`。提前停止的轮次与正常完整轮分开；计划未到达的任务不从正式分母中悄悄删除。版本/CRC 错误和不支持命令可先用独立测试向量或注明变换的回放验证，不把人为改写数据称为空口故障。
- **同步验证**：在同一 IQ 上先独立双解码，补偿设计上的 472 µs 标记位置差，并把训练包与更晚的验证包分开；随后用两块 HackRF 的独立 IQ 研究时间模型在漏收和失更后的预测一致性。没有外部校准时，这只支持相对一致性与软件定时功能，不支持独立设备绝对同步精度。校准采集起点、采样率、固定链路延迟及板端 RF 起点后，才报告真实误差和预设容差内成功率；不得逐个验证包强制对齐后再算残差。
- **论文对照（需补齐实现后执行）**：相同两任务、截止时间、RF 条件和总空口预算下，分别测“BLE 与 IEEE 802.15.4 分别发送”、同包立即软件处理、同包时间模型处理；计入 primary、secondary、失败尝试与重发。当前分别发送路径、立即处理对照和多任务联合分析器尚未实现，故这一组不能用现有 `b2z_plan_*` 数据冒充。

三个独立轮次是功能重复的最低要求；射频可靠性结论需要条件稳定且更多轮次。按轮报告样本数、异常和分子/分母；跨轮区间以整轮为重采样单位，只有 3 轮时标注区间探索性，不把相关时隙当独立伯努利样本。

## 6. 归档清单与停用条件

每轮在 `python/experiments/YYYYMMDD_run<id>/` 保存：板端完整原始串口日志 `board.board.log`、实际执行的命令清单、RF/接收增益与距离、板端 ELF/源码及 SDK 副本哈希、两侧 `rx.summary.json`、逐包 JSONL、控制事件/任务报告、设备 stderr，以及关键轮的原始 IQ 与校验和。另存分析脚本版本、分析参数、逐任务 CSV、逐时隙 CSV、总览 JSON/Markdown；后两种联合表在下一阶段分析器实现后自动生成。录制日期、时区、Run ID 和两侧是否确属**同一次发送**需写明。

若板端计划未完成、任一接收器异常退出、队列溢出、USB/主机可能丢样、RF 明显饱和、两份录制没有共同覆盖发送窗口，停止把该轮用于可靠性或同步精度结论，保留作诊断数据。环境无法保证射频质量时，先完成板端计划与软件解析的条件性验收，不据此设定 PRR 门槛、宣称物理执行或论文性能收益。
