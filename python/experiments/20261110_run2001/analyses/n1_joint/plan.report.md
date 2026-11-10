# 多任务共包联合分析

- Run ID：2001；计划控制任务：3；板端 secondary DMA 完成：120/120
- BLE / IEEE 有效解码尝试：93/120 / 120/120
- 同尝试联合有效解码：93/120
- 逐任务联合有效解析：3/3
- 两侧软件处理事件均出现：N/A（零任务或缺少软件处理观测）

| Command ID | 计划发送 | BLE 有效 | IEEE 有效 | 同尝试双方有效 | 双方解析任务 | BLE/IEEE 实时状态 |
|---:|---:|---:|---:|---:|---:|---|
| 43 | 3 | 2 | 3 | 2 | 1 | not_measured / rejected |
| 44 | 3 | 3 | 3 | 3 | 1 | not_measured / rejected |
| 45 | 3 | 3 | 3 | 3 | 1 | not_measured / rejected |

## BLE 跟随证据

- per_planned_slot：93/120
- per_valid_primary：93/102
- joint_same_slot：93/120
- joint_tasks_with_follow：3/3

逐槽及逐任务数据见 [plan.slots.metrics.csv](plan.slots.metrics.csv)、[plan.tasks.metrics.csv](plan.tasks.metrics.csv) 和 [plan.summary.json](plan.summary.json)。
软件处理事件不等于物理执行；两台 IQ 的独立采样零点未校准，不能由此计算执行时差。
