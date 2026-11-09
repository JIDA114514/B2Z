# B2Z v1 控制包匹配

`analyze.py` 离线读取现有 BLE / ZigBee 接收器保存的逐包 JSONL。它对每侧独立解析 `B2 43` v1 的 35 B 控制记录、校验应用 CRC16 和时间/命令字段；同一时隙的重复包只计一次。既有 `B2 5A` 性能测试协议仍由原接收器统计，本脚本不修改旧 `unique` 口径。

若需要在采集期间立即看到 ZigBee 侧的控制字段和去重状态，使用 [`zigbee_rx/control_receive.py`](../zigbee_rx/README.md#b2-43-控制包实时分析)；本脚本用于接收结束后的单侧复核与双侧匹配。

只分析 ZigBee 的 run 1006：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261103_run1006 \
  --run-id 1006 --command-id 43
```

只分析 BLE 的 run 1004：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261102_run1004 \
  --run-id 1004 --command-id 43
```

脚本自动选取实验目录中唯一的正常结束接收记录；若同侧存在多份正常结束录制，使用 `--ble-packets`、`--zigbee-packets` 明确指定。若实验目录下有 `board.board.log`，自动合并同一 Run ID、Command ID 的一条最终 `CONTROL_STATS`；单任务计划也可合并 `CONTROL_PLAN_STATS`，缺少 `CONTROL_PLAN_TASK` 时会标记板端命令号未经逐任务日志核对。多任务计划使用下述 `plan_analyze.py`。

两块 HackRF **同时录制同一轮发送**时，将两个接收结果放在同一个实验目录，并显式使用 `--same-transmission`：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261103_run1100 \
  --run-id 1100 --command-id 43 --same-transmission
```

该选项要求两份接收摘要的录制墙钟区间有交集。脚本按 `(run_id, command_id, slot_index)` 计算同一物理尝试的两侧有效解码，同时报告同一命令是否分别被两侧至少恢复一次；后者允许来自不同的重发时隙。若未声明同次录制，脚本只报告标识重合，不报告联合有效解码。不能将不同 Run ID 的历史单侧实验合并。

结果写入实验目录下新建的 `analyses/control_match_<UTC 时间>/`，包含 `control.report.md`、`control.summary.json` 和 `control.slots.metrics.csv`。`sample_start` 只作为各接收机自己的 IQ 索引保存，不直接相减测同步精度。完整恢复和匹配表示软件解码成功，不表示命令已被执行，也不表示规范 AuxPtr 跟随或商用 ZigBee 协议栈兼容。

## 单轮离线同步回放

`sync_replay.py` 对两侧已独立解码的控制包按时间切分。每侧只用切分点以前最近的 K 个有效包拟合 `ref_tick_ms → 本机 IQ 时间`；切分点以后两侧共同收到的包只用于检验，绝不回填训练。`natural` 使用各侧原本收到的包；`disjoint` 将 BLE 训练时隙从 ZigBee 训练候选中移除，以回放两侧收包完全不重合的情形。1 包只估计偏移，采用标称采样率；2 包及以上估计偏移和速率。

```bash
python3 python/control_match/sync_replay.py \
  --experiment-dir python/experiments/20261104_run1101 \
  --run-id 1101 --command-id 43 --cut-slot 60 \
  --analysis-id sync_replay_packet_count_v1
```

结果写入 `sync.report.md`、`sync.summary.json`、`sync.sweep.csv` 和 `sync.validation.csv`，列出实际训练时隙、训练跨度、最近更新时隙、验证样本数及误差。所有配置使用同一批更晚的共同验证包。该误差是两个独立模型对共同 RF 事件的时间估计差，固定的包内标记和接收路径偏差尚未独立校准；不表示绝对同步精度或执行时差。单轮离线屏蔽包是回放实验，不能充当新的物理独立重复。

1703/1704 的 300 槽固定验证集、不同包训练和周期更新由 `holdover_analyze.py` 处理。它接受两侧显式逐包路径、Run ID 和新输出目录，生成 32 种策略的汇总、逐验证槽 CSV 与采样间隔质量表；命令示例与解释见[时间保持实验方案](../../doc/independent_sync_holdover_experiment_plan.md)。验证包只用于打分，不参与模型拟合。

## 多任务板端计划匹配

`plan_analyze.py` 读取完整 `CONTROL_PLAN_STATS/TASK/SLOT` 板端日志和两份独立解码的逐包文件，按全轮 `slot_index` 输出四象限、按非零 `command_id` 输出逐任务联合解析，并保留实时软件状态。它要求完整逐槽日志，防止把单一最终计数错配到某个命令。

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261104_run1601 \
  --run-id 1601 --analysis-id plan_match
```

若同侧有多份录制，指定 `--ble-packets` 与 `--zigbee-packets`。两侧可从不同重发槽恢复同一任务；同槽共同有效数与逐任务联合解析数分别报告。该脚本不从两台独立 IQ 的样本索引推算执行时差。下一轮连续时间更新与三任务实验见[方案](../../doc/integrated_sync_control_experiment_plan.md)。

## 单侧时间与软件命令模块

`control_engine.py` 已实现第一阶段的独立接收侧逻辑。BLE 或 IEEE 802.15.4 PHY 解码器各自提供本侧校验有效的 35 B 应用负载、本侧包起始采样索引和**负载可用时**的采集进度；模块完成应用 CRC/语义校验、时间模型更新、目标与有效期判决、去重、定时及 `NOOP`/`SET_STATE`/`TRIGGER` 软件事件。调用接口为 `SideControlEngine(EngineConfig(...))`、`observe(payload, packet_start_sample, available_sample)`、`advance(current_sample)` 和只读报告用的 `snapshot()`。事件均标明本地 IQ 样本时间域和 `software_only=true`。

`EngineConfig.external_reference_bound_ms` 默认是 `None`：此时仍能建立时间模型，但定时命令会以 `time_quality_insufficient` 拒绝。只有提供**明确覆盖板端计划时刻到实际 RF 起点、接收标记和检测偏差**的上界，才能启用定时软件处理。测试中的数值只是模拟输入，不代表当前设备已完成校准。IEEE 802.15.4 侧按 v1 布局补偿设计上的 472 µs 标记位置差；两块 HackRF 的样本零点仍不可直接相减。

两条接收链的新逐包记录已保存 `available_sample`，`replay_engine.py` 可独立回放一侧。旧实验 JSONL 没有该字段时，先用保存的 IQ 重新运行相应接收脚本；回放器会拒绝用包起点代替可用时刻。离线回放按录制块大小推进样本进度，其 `software_processed` 是样本时间域中的模拟软件事件，不代表主机实时处理或物理动作。

两个实时接收入口已接入同一模块。分别给 BLE 侧和 IEEE 802.15.4 侧指定本机目标 ID，即可生成单侧控制事件和逐任务报告：

```bash
python3 python/exadv_rx/receive.py --run-id 1101 --control-target-id 1
python3 python/zigbee_rx/control_receive.py --run-id 1101 --command-id 43 --control-target-id 2
```

每个接收目录增加 `rx.control.events.jsonl`、`rx.control.tasks.csv`、`rx.control.summary.json` 和 `rx.control.report.md`。实时模式的事件另带 `host_monotonic_ns`，它包含解码和软件处理时延，不能作为空口时间戳。默认未提供参考误差上界，定时命令会被拒绝；仅做功能演示时可在**两侧各自的命令**加 `--control-assumed-reference-bound-ms 1`，结果会标记此上界未经校准。`--control-target-id` 可重复指定多个本机目标；`--control-accept-broadcast` 启用广播目标。`--control-sender-id` 只是本侧配置的来源标签，v1 负载并不携带可认证的发送者身份。该功能仍只有软件状态和软件事件，不表示物理控制或独立设备同步精度。板端多任务计划的验证步骤见[实验方案](../../doc/multi_task_control_experiment_plan.md)。

例如在项目根目录回放一份已重新解码的 BLE 逐包记录：

```bash
python3 python/control_match/replay_engine.py \
  --packets /tmp/ble_rx.packets.jsonl --side ble --run-id 1101 \
  --target-id 1 --output-dir /tmp/ble_control_replay
```

输出 `control.events.jsonl` 与 `control.summary.json`。默认无参考误差上界，定时命令会被拒绝；仅作功能演示时可显式加 `--assumed-reference-bound-ms 1`，报告会标记该数值未经实测校准。IEEE 802.15.4 侧改用 `--side zigbee --target-id 2` 和本侧逐包文件，不能复用 BLE 文件。

### 立即处理软件基线

`replay_engine.py --policy immediate` 复用相同的独立解码输入、应用 CRC、Run ID、目标、操作码、任务字段一致性与去重规则。首次有效命令在该包的 `available_sample` 位置产生一次 `software_processed`；纯时间更新只记录为 `time_update_ignored`。此基线不建立时间模型、不等待 `execute_at_ms`，也不使用假设参考误差界；没有共同时间参考时不在线判断 `valid_until_ms`，报告明确标记截止时间未评估。它只用于样本域离线软件功能对照，不是实时主机处理时刻或物理执行。

例如从 1801 的两份原始逐包文件各自回放：

```bash
python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261109_run1801/captures/ble/155243_684234_luouk7f9/rx.packets.jsonl \
  --side ble --run-id 1801 --target-id 1 --policy immediate \
  --output-dir python/experiments/20261109_run1801/analyses/immediate_baseline/ble
python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261109_run1801/captures/zigbee/155241_736656_lrrof3kw/rx.packets.jsonl \
  --side zigbee --run-id 1801 --target-id 2 --policy immediate \
  --output-dir python/experiments/20261109_run1801/analyses/immediate_baseline/zigbee
```

输出目录必须尚不存在；每次分析使用新目录名。1801 的结果见[立即处理基线报告](../experiments/20261109_run1801/analyses/immediate_baseline/report.md)。
该轮还从原始 `rx.ci8` 各重新解调一次，再运行同一基线；新旧逐包流的 300 个槽号、命令号、包起始与可用样本位置完全一致。重新解调是同一物理录制的复核，不算新一轮实验。
