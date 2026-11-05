# 单侧控制处理

- 接收侧：zigbee；Run ID：1601
- 模式：离线样本进度回放；接收程序状态：complete
- 参考误差界：1.0 ms（user supplied; calibration not verified by software）
- 有效控制记录：2；接受任务：1；软件处理：1；取消：0

| Command ID | 已解码包 | 唯一时隙 | 状态 | 处理样本 | 原因 |
| ---: | ---: | ---: | --- | ---: | --- |
| 43 | 1 | 1 | software_processed | 86310912 |  |

仅记录本侧软件事件；离线回放不表示实时处理。独立接收机的 IQ 样本零点不能直接相减，未校准时不报告执行同步误差。

逐事件：[control.events.jsonl](rx.control.events.jsonl)；逐任务：[control.tasks.csv](rx.control.tasks.csv)；结构化结果：[control.summary.json](rx.control.summary.json)。
