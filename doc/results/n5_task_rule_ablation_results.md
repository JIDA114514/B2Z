# N5 任务规则消融首轮回放结果

执行依据：[N5 任务规则消融执行方案](../plans/n5_task_rule_ablation_execution_plan.md)。本报告使用 2504 无干预、2507 BLE 单侧缺失、2508 IEEE 单侧缺失的原始逐包轨迹；每个物理条件只有一轮。三轮均为双 HackRF 独立录制后的**软件回放**。合成提前量、处理延迟、1 ms 参考界和异常规则案例均不算新空口实验或真实执行器结果。

## 输入与验收

两侧录制均完整，每轮有 300 个计划槽和 6 个控制任务。执行前 N5 专项测试 19 项通过；完整 `control_match` 测试 97 项通过。每轮产生 21 个条件、126 条逐任务记录及 20/20 通过的合成规则案例。输出清单、代码及输入 SHA256 见各轮 [2504](../../python/experiments/20261116_run2504/analyses/n5_task_rules_v1/manifest.json)、[2507](../../python/experiments/20261116_run2507/analyses/n5_task_rules_v1/manifest.json)、[2508](../../python/experiments/20261116_run2508/analyses/n5_task_rules_v1/manifest.json)。归档后已复核来源哈希；原始逐包记录、板端日志和既有分析未覆盖。

| Run | 实际原始联合解析 | 仅前 1 次 | 仅前 3 次 | 全部计划尝试 | 原轮提交波形预算 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| [2504](../../python/experiments/20261116_run2504/analyses/n5_task_rules_v1/report.md) | 6/6 | 6/6 | 6/6 | 6/6 | 602400 µs |
| [2507](../../python/experiments/20261116_run2507/analyses/n5_task_rules_v1/report.md) | 4/6 | 3/6 | 4/6 | 4/6 | 602400 µs |
| [2508](../../python/experiments/20261116_run2508/analyses/n5_task_rules_v1/report.md) | 2/6 | 2/6 | 2/6 | 2/6 | 602400 µs |

2507 中的差异只来自命令 53：BLE 未解码首发，但在前三次计划尝试中解码到该命令；IEEE 已解码。2504 和 2508 轨迹内没有新增的联合解析任务。K 筛选依据是**计划尝试槽**，自然缺包未被后面的有效包补位。六任务处于不同时间段，三条轨迹也只有各一轮，因此本表不估计 K 的一般可靠性收益。602400 µs 是原轮全部已提交波形的预算代理值，包含同步槽与实际重发；筛选列没有重新测得的 RF 成本。

合成提前量 0.5/2/5 s 只保留任务首发机会，三档联合解析分别保持 2504 的 6/6、2507 的 3/6、2508 的 2/6；按固定的“首发后 400 ms 有效期”重建应用字段和 CRC，所以合成 5 s 与原始发送的 5 s/原始有效期是不同协议条件。0/10/100 ms 延迟注入使用原始 5 s 字节，三档联合解析均分别保持 6/6、4/6、2/6；本批轨迹未产生新的定时边界差异。详细条件与逐任务行见各轮 `conditions.csv`、`tasks.csv`、`events.jsonl`。

在真实未校准参考界下，所有定时回放条件的联合**软件处理**均为 0/6，原因是保守的 `time_quality_insufficient` 拒绝。显式合成 1 ms 参考界时，软件处理数与对应条件的联合解析数相同；该数字只验证状态机分支，不代表已校准同步精度。2504 的无同步立即处理基线两侧各在本侧可用样本处处理 6/6 个任务，但未评估截止时间。[BLE 基线](../../python/experiments/20261116_run2504/analyses/n5_task_rules_v1/immediate_ble/control.summary.json) · [IEEE 基线](../../python/experiments/20261116_run2504/analyses/n5_task_rules_v1/immediate_ieee/control.summary.json)

异常规则表覆盖目标错误、合法但不支持的 opcode、未知 opcode、应用 CRC、冲突、重复、乱序、过期、迟到、未知参考、冻结、过晚取消、时间轴中断/重启、跨 Run ID、全任务缺失及零分母；这是合成输入功能证据。2507 的第二次现场干预超出预登记窗口，仍单列探索性证据。当前结果不提供物理 K 对照、三轮独立重复、实际 RF 时长、真实动作或两设备绝对同步精度。
