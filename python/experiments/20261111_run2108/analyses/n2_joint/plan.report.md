# 多任务双端联合分析

- Run ID：2108；计划控制任务：3；板端 secondary DMA 完成：120/120
- BLE / IEEE 有效解码尝试：120/120 / 120/120
- 同尝试联合有效解码：120/120
- 逐任务联合有效解析：3/3
- 两侧软件处理事件均出现：N/A（零任务或缺少软件处理观测）

| Command ID | 计划发送 | BLE 有效 | IEEE 有效 | 同尝试双方有效 | 双方解析任务 | BLE/IEEE 实时状态 |
|---:|---:|---:|---:|---:|---:|---|
| 43 | 3 | 3 | 3 | 3 | 1 | not_measured / not_measured |
| 44 | 3 | 3 | 3 | 3 | 1 | not_measured / not_measured |
| 45 | 3 | 3 | 3 | 3 | 1 | not_measured / not_measured |

## 按提交波形长度核算的成本（非实测 RF 占用）

- 模式：joint；BLE/IEEE DMA 完成：120/120、120/120
- 突发提交尝试/成功/完成：240/240/240；发送程度不确定：0
- 全轮提交有效波形：240960 µs；零样本 padding：2400 µs；提交尝试预算：240960 µs
- 每成功联合解析任务：80320.0 µs（分母 3）；包含时间更新、失败与重发。
- 逐突发及软件 DMA 调用时刻见 plan.bursts.csv；串口及 DMA 时刻不代表实际空口起点。

逐槽及逐任务数据见 [plan.slots.metrics.csv](plan.slots.metrics.csv)、[plan.tasks.metrics.csv](plan.tasks.metrics.csv) 和 [plan.summary.json](plan.summary.json)。
软件处理事件不等于物理执行；两台 IQ 的独立采样零点未校准，不能由此计算执行时差。
