# Run 1801：收到有效命令后立即处理的软件基线

## 方法

对 BLE 与 IEEE 802.15.4 两条接收链已独立解码的 `rx.packets.jsonl` 分别回放；在各自的 `available_sample`（解码器认为负载可用时的本地 IQ 采样进度）处理首次有效命令。沿用应用校验、Run ID、目标、操作码、任务字段一致性及去重规则。纯时间更新不驱动调度；不建立时间模型、不等待 `execute_at_ms`，也不在线判断 `valid_until_ms`。板端 300/300 完成和同槽双方 300/300 有效的依据见[联合匹配](../plan_match/plan.report.md)。

## 功能结果

| 接收侧 | 有效记录 | 忽略的纯时间更新 | 接受并软件处理任务 | 去重的命令包 | 最终软件状态 |
|---|---:|---:|---:|---:|---|
| BLE | 300 | 291 | 3/3 | 6 | 目标 1 状态 2；记录 `TRIGGER(9)` |
| IEEE 802.15.4 | 300 | 291 | 3/3 | 6 | 目标 2 状态 3；记录 `TRIGGER(7)` |

命令 43、44、45 在两侧均各处理一次，无目标错误、冲突或应用解析失败。每侧 3 个命令各重发 3 次；另外 6 包只产生 `duplicate` 事件。逐事件及结构化摘要见 [BLE 事件](ble/control.events.jsonl)、[BLE 摘要](ble/control.summary.json)、[IEEE 事件](zigbee/control.events.jsonl)、[IEEE 摘要](zigbee/control.summary.json)。

## 原始 IQ 复核

另外从两份保存的 `rx.ci8` 独立重新解调，输出见 [BLE 离线接收报告](../immediate_source_redecode_ble/ble/rx.report.md) 和 [IEEE 离线接收报告](../immediate_source_redecode_zigbee/zigbee/rx.report.md)。新逐包流分别恢复 300 条本侧有效控制记录；逐槽核对 `slot_index`、`command_id`、`sample_start` 和 `available_sample`，均与采集时保存的 300 条记录完全一致。将新逐包流再送入立即处理基线，双方仍各得到 3 次软件处理、6 次去重，见 [BLE 原始 IQ 回放](../immediate_baseline_raw_iq/ble/control.summary.json) 和 [IEEE 原始 IQ 回放](../immediate_baseline_raw_iq/zigbee/control.summary.json)。这些是同一份 IQ 的复核，**不增加物理实验轮数**。

| Command ID | BLE 立即处理采样索引 | IEEE 立即处理采样索引 | 与各侧 1 ms 假设界定时回放的本地样本域间隔 |
|---:|---:|---:|---:|
| 43 | 46,989,312 | 54,788,096 | 两侧各 9,994.24 ms |
| 44 | 126,943,232 | 134,742,016 | 两侧各 9,994.24 ms |
| 45 | 206,962,688 | 214,761,472 | 两侧各 9,994.24 ms |

约 10 s 的间隔来自本实验在命令广播与 `execute_at_ms` 之间安排的提前量，以及 4 Msps 回放中的块进度量化；它**不是**测得的同步改善、真实主机处理延迟或跨机执行时差。两台接收机的采样零点不同，上表两侧采样索引不能互相相减。定时回放中的 1 ms 只是显式输入的软件功能假设，不是实测误差界。

本基线可证明“同包解码后立即软件处理、每任务只处理一次”的功能；对于过期命令、目标时刻偏差和真实实时处理性能，仍需独立参考或另设明确的后验评价规则，不能把本轮 `3/3` 称为同步控制成功率。本轮仍是同频诊断模式，不证明规范跨信道 AuxPtr 跟随。
