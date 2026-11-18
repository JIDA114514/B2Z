# N5 下一步：单侧失更与基准的独立重复实验方案

> 整理标注（2026-11-18）：本文件保留实验设计、执行命令与预登记约束；阶段状态见[文档导航](../README.md)，已使用的 Run ID 不应直接复用。 已有结果见[N5 独立重复结果](../results/n5_independent_repeat_results.md)。

制定于 2026-11-16。依据 [N5 原方案](n5_mechanism_experiment_plan.md)、[2504/2507/2508 首轮现场结果](../results/n5_task_rule_ablation_results.md)和[下一阶段总计划](../archive/next_stage_plan.md)。本方案只安排当前设备和现有板端命令即可完成的下一组物理实验；以下为**预定采集**，不是已取得的结果。

## 1. 问题、范围和先后顺序

首轮已经观察到 BLE 与 IEEE 两个方向的独立解码缺失、在线 `holdover → stale → reacquiring → tracking` 路径及保守拒绝。2504 是无干预基准；2507 第二次操作不在预登记窗口内；2508 第三次恢复距发送结束太近，未能重新满足八包建模条件。三轮各只是一条物理轨迹，同轨迹消融不能替代独立重复。

本轮回答：在统一的 300 槽/500 ms 任务表和单次 150–200 槽接收条件改变下，基准、BLE 单侧缺失、IEEE 单侧缺失的解析、探测覆盖、状态转换和恢复是否能跨轮复现？每种条件各做 **3 个全新的独立 Run**，旧 2504/2507/2508 作为先导证据单列，不与本矩阵混作重复。板端只使用既有 `b2z_plan_*` 命令，不修改 v1 负载、旧性能协议或 Sequence 规则。

若九轮之后要定量声称 K 的物理可靠性收益，再另开均一 K 的板端对照。当前混合 K 任务表和已完成的反事实输入筛选不能给出该收益；N4 同空口预算重发、N3 缺失的同期 IEEE 证据及可选 C1 时间语义桥接仍是独立工作包，见第 8 节。

## 2. 预登记矩阵

Run ID 2509–2517 仅为预留，生成配置前检查是否已被占用。按表中顺序交替条件；每轮板端、BLE 和 IEEE 使用同一新 Run ID，重新启动接收进程，重新加载并执行一次完整板端计划。三组保持发送参数、任务表、接线、设备、增益、录制时长和接收软件版本一致。无干预组全程不人为改变链路。

| 顺序 | Run ID | 条件 | 计划操作窗口 | 保存全量双侧 IQ |
| ---: | ---: | --- | --- | --- |
| 1 | 2509 | 无干预基准 A | 无 | 否；已有 2504 基准 IQ |
| 2 | 2510 | BLE 单侧失更 B | 150–200 槽 | 是 |
| 3 | 2511 | IEEE 单侧失更 C | 150–200 槽 | 是 |
| 4 | 2512 | IEEE 单侧失更 C | 150–200 槽 | 否 |
| 5 | 2513 | 无干预基准 A | 无 | 否 |
| 6 | 2514 | BLE 单侧失更 B | 150–200 槽 | 否 |
| 7 | 2515 | BLE 单侧失更 B | 150–200 槽 | 否 |
| 8 | 2516 | IEEE 单侧失更 C | 150–200 槽 | 否 |
| 9 | 2517 | 无干预基准 A | 无 | 否 |

受影响侧沿用已实际执行的**断开该侧馈线连接并恢复**方法；另一侧接线、增益和位置保持不变。在未受影响侧的有效解码流到达约槽 150 时断开、约槽 200 时恢复。目标窗口按端点包含的板端槽号预登记，实际操作会有误差；现场笔记记录触发依据、未受影响侧看到的槽号、操作时刻、接线状态、实际恢复和偏离窗口。不能把预登记窗口当作实际缺包区间，也不能在其他时间再增加人为干扰。观察时间轴持续运行，不通过停止接收进程制造失更。

150–200 槽对应约 25 s，足以跨过 2 s holdover 和 10 s stale 阈值；恢复后距第 300 槽还有约 50 s，供八个候选训练包建模及后续独立探测。**这是覆盖机会设计，不保证成功解码或重获。** 若操作误差导致未覆盖某状态，照实保留本轮，再用新的 Run ID 补采，不能更改本轮配置或丢弃失败轮。

## 3. 硬件、版本和空间前提

- 发送端沿用当前 Zynq-7020/AD9363 板卡与已验证固件；primary ch39，secondary BLE ch3/IEEE ch12，`rf_mode=standard_secondary_ch3`。两块 HackRF 分别固定 BLE ch3 和 IEEE ch12、4 Msps、LNA 16、VGA 10、AMP 关闭、180 s。具体序列号见下方命令；采集前 `hackrf_info` 核对设备身份，记录板端固件/bitstream 标识及接线。
- 同一矩阵冻结主机代码和板端固件。若必须修复程序，记录变更点和版本，把变更前后拆成不同批次；不能悄悄合并为三轮重复。生成配置后不得编辑任务、探测槽、阈值或窗口。
- 当前磁盘约余 17 GiB。4 Msps、180 s、ci8 双侧全量 IQ 约 2.88 GB/轮；本矩阵仅 2510、2511 保存全量双侧 IQ，预计新增约 5.76 GB，另计逐包/事件/分析。每轮前检查剩余空间和接收处理积压；无 IQ 轮仍保留两侧完整 JSONL、控制事件、摘要及板端日志。异常轮若无 IQ，报告其无法重解码的限制，必要时用新 Run ID 补采带 IQ 的轮次。历史 2504、2507、2508 IQ 作为代表性复查材料，裁剪/备份遵守原 N5 方案的偏移与哈希要求。

完成第 4 节配置生成后、采集前在仓库根目录运行并保存输出；未拿到板端固件/bitstream 的可审计标识时，至少记录人工版本及其局限：

```bash
hackrf_info
df -h .
git rev-parse HEAD
sha256sum python/control_match/configs/n5_2510.json
```

最后一行仅是 2510 示例，每轮换成自己的配置。两台 HackRF 的序列号与实际接收命令逐一核对；不要把设备枚举顺序当成设备身份。

## 4. 采集前配置和板端任务表

从仓库根目录执行；先确认预留 ID 不存在。下列说明写入采集前配置，实际操作偏差另写 `notes.md`，不事后回写预登记文件。

```bash
for run in 2509 2513 2517; do
  PYTHONPATH=python python3 -m control_match.n5_config \
    --run-id "$run" --output "python/control_match/configs/n5_${run}.json"
done
for run in 2510 2514 2515; do
  PYTHONPATH=python python3 -m control_match.n5_config \
    --run-id "$run" --output "python/control_match/configs/n5_${run}.json" \
    --intervention-description 'BLE侧仅在槽150–200附近断开馈线后恢复；IEEE侧保持原接收条件' \
    --intervention-window 150 200
done
for run in 2511 2512 2516; do
  PYTHONPATH=python python3 -m control_match.n5_config \
    --run-id "$run" --output "python/control_match/configs/n5_${run}.json" \
    --intervention-description 'IEEE侧仅在槽150–200附近断开馈线后恢复；BLE侧保持原接收条件' \
    --intervention-window 150 200
done
```

每轮重新加载**完全相同**的 13 条板端任务表；其中 6 个非零任务与 2504 相同，300 槽、500 ms 周期，保留现有任务 K=1/3/5 的混合配置以复核机制，不把它当作均一 K 对照：

```text
b2z_plan_clear?
b2z_plan_add? 0 70 0 0
b2z_plan_add? 51 1 40000 39000 1 1 1 2 1 1
b2z_plan_add? 0 19 0 0
b2z_plan_add? 52 3 50000 49000 1 1 2 2 1 2
b2z_plan_add? 0 57 0 0
b2z_plan_add? 53 3 80000 79000 1 2 3 2 2 3
b2z_plan_add? 0 37 0 0
b2z_plan_add? 54 5 100000 99000 1 1 4 2 1 4
b2z_plan_add? 0 45 0 0
b2z_plan_add? 55 3 125000 124000 1 2 5 2 2 5
b2z_plan_add? 0 27 0 0
b2z_plan_add? 56 3 140000 139000 1 1 6 2 1 6
b2z_plan_add? 0 27 0 0
```

两侧接收进程已运行后约 15 s 内在板端发送 `b2z_plan_start? <run_id> 500 1`，例如 `b2z_plan_start? 2510 500 1`。保留从清空、逐项添加、启动到最终 `CONTROL_PLAN_STATS/TASK/SLOT` 的完整串口原文，保存到对应实验目录 `board.board.log`；不要只保存最终计数。每轮新的 Run ID，不复用失败轮的 ID。

## 5. 两侧接收命令与人工操作

以下以 2510（BLE 受影响、保存 IQ）为**命令示例**。执行前把 `YYYYMMDD` 换成采集当天日期，并在两个终端使用同一个实验目录。BLE 侧改成 IEEE 受影响时只换配置和 `--no-quiet` 所在侧；其余 RF 参数保持相同。2510/2511 使用 `--save-iq`，其余七轮两侧均用 `--no-save-iq`。

终端 A，BLE：

```bash
python3 python/exadv_rx/receive.py \
  --run-id 2510 --experiment-dir python/experiments/YYYYMMDD_run2510 \
  --channels 3 --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 180 \
  --control-target-id 1 --n5-config python/control_match/configs/n5_2510.json \
  --save-iq --quiet
```

终端 B，IEEE（本轮未受影响，用槽号提示人工干预）：

```bash
python3 python/zigbee_rx/control_receive.py \
  --run-id 2510 --experiment-dir python/experiments/YYYYMMDD_run2510 \
  --channel 12 --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 180 \
  --expected-packets 300 --control-target-id 2 \
  --n5-config python/control_match/configs/n5_2510.json \
  --save-iq --no-quiet
```

IEEE 受影响的 2511/2512/2516 轮，BLE 端改用 `--no-quiet` 查看打印的 `ADI.did`（本计划槽号小于 300，故等于槽号），IEEE 端改用 `--quiet`。BLE 受影响轮使用 IEEE 端打印的 `slot=`。以**实际解码到的槽号**作为人工参考，不用 Python 墙钟或报文编号冒充 RF 时刻；如正常侧也漏收，按最近可靠槽及现场时间记录不确定度。手工断开/恢复是操作目标，结果以受影响侧独立解码记录与板端逐槽清单核对。

## 6. 每轮分析、验收与失败保留

接收结束后，先确认 `board.board.log` 完整、两侧 `rx.summary.json` 均 `status=complete`，记录 `samples_processed`、队列/USB 告警、IQ 文件大小（若保存）、设备增益、接线状态和现场操作。每侧 IQ 自己的样本零点独立，不相减估计同步。逐轮分析示例（替换 Run ID 与目录日期，`analysis-id` 不得覆盖已有目录）：

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/YYYYMMDD_run2510 \
  --run-id 2510 --analysis-id n5_repeat_integrity
python3 python/control_match/n5_analyze.py \
  --experiment-dir python/experiments/YYYYMMDD_run2510 \
  --config python/control_match/configs/n5_2510.json \
  --analysis-id n5_repeat_mechanism
```

逐轮至少归档：板端 300 槽生成/提交/完成、`deadline_miss`、`dma_timeout`；两侧有效槽/300、24 个固定探测的有效评分/24；逐槽四象限；全 6 任务的两侧解析、联合解析及拒绝原因；在线状态转换、实际缺失区间、首个恢复包、八候选建模恢复时刻、恢复后探测；`notes.md` 中的操作/接线/异常及配置和源码哈希。`tx_completed` 是 DMA 完成代理，不自动证明完整 RF 发射，也不能唯一归因缺包原因。没有无告警证明硬件从未丢样的结论。

预期功能路径是受影响侧在发送期间进入 holdover、stale、reacquiring，并在足够恢复包到来后回到 tracking；另一侧正常接收。若任何环节缺失、恢复未完成、板端未达 300 槽或采集异常，原轮仍进入结果表，注明现场与时间轴限制，必要时另用新 Run ID 补充。**发送结束后录制尾段触发的 stale 不计为干预恢复事件**；完整恢复表仍保留尾部删失行，并另外按板端发送边界解释。未知参考界下拒绝定时处理为预期，不能把解析或假设 1 ms 回放写成实际同步执行。

## 7. 跨轮统计与停止条件

- 每个条件先逐轮报告六任务联合解析 `n/6`、双方/单侧有效槽、固定探测覆盖、一次失更是否到达各状态、恢复所需有效包数和时间；失更持续时间由实际缺失槽确定，计划窗口和人工时间分列。未到达 tracking 的轮次保留在恢复分母中，但发送后尾部 stale 单列为停止发送造成的删失。
- 汇总每条件 3 条**独立物理轮次**的逐轮值、均值/范围及按轮重采样的描述性 95% 区间；样本仅 3 轮，区间分辨率很低，不据此宣称高可靠性或算法优越。六任务同一轮相关，连续漏收相关，不将 18 个任务或 24 个探测直接当作独立同分布样本。
- 若三轮中有条件未得到发送期间的 stale/重获，结论写明覆盖不足；仅对该状态新增预登记轮，不调整既有阈值、不删除差轮。三类条件各有三轮、配置/输入/异常均可审计后，完成 N5 主要配置的重复证据。没有校准共同参考仍只报告相对时间保持、解析和软件状态，不报告跨设备同步精度或执行成功率。

## 8. 后续工作包与接口门槛

1. **物理 K 对照及 N4 同预算重发**：当前 N5 配置生成器固定混合 K 任务表，必须先设计并实现均一 K=1/3/5 的预登记生成与板端计划核对。比较时固定任务首槽、目标、截止、周期、300 槽总预算和 RF 条件，调整同步填充使总槽数不变；命令任务本身也携带时间参考。逐突发仍须核对实际波形长度与提交预算，不能只因槽数相同就假定空口成本相同。短时人工断连若覆盖整段重发，不能识别 K 收益；先确定能产生部分丢失且条件稳定的接收场景，再做交替的物理轮次。没有可控、可重复的部分丢失时，只报告同轨迹筛选与功能结果，不定量宣称 K 提升。此工作包另行预登记，不能把本矩阵混合 K 的任务间差异当作对照。
2. **N3 同期 IEEE 补采**：2204 缺的同期双端证据需新的一次发送与两侧同时采集；新的 IEEE 录制不能与旧 BLE IQ 拼成同轮。按 [N3 方案](n3_time_reference_experiment_plan.md)另列新 Run ID、配置和误差边界。
3. **C1 桥接**：仅在论文主张把 C1 紧凑包与在线调度作为同一方案时，先适配两侧时间语义与接收调度，再进行板端物理桥接。现有 C1 解析与 N5 v1 调度不能直接合称已验证。
