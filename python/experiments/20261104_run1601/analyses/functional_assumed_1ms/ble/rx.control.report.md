# 单侧控制处理

- 接收侧：ble；Run ID：1601
- 模式：离线样本进度回放；接收程序状态：complete
- 参考误差界：1.0 ms（user supplied; calibration not verified by software）
- 有效控制记录：9；接受任务：2；软件处理：2；取消：0

| Command ID | 已解码包 | 唯一时隙 | 状态 | 处理样本 | 原因 |
| ---: | ---: | ---: | --- | ---: | --- |
| 43 | 3 | 3 | software_processed | 62259200 |  |
| 44 | 3 | 3 | software_processed | 78249984 |  |

仅记录本侧软件事件；离线回放不表示实时处理。独立接收机的 IQ 样本零点不能直接相减，未校准时不报告执行同步误差。

逐事件：[control.events.jsonl](rx.control.events.jsonl)；逐任务：[control.tasks.csv](rx.control.tasks.csv)；结构化结果：[control.summary.json](rx.control.summary.json)。
