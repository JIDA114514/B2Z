# 单侧控制处理

- 接收侧：ble；Run ID：1703
- 模式：实时软件处理；接收程序状态：complete
- 参考误差界：N/A ms（not supplied; timed commands denied）
- 有效控制记录：300；接受任务：0；软件处理：0；取消：0

| Command ID | 已解码包 | 唯一时隙 | 状态 | 处理样本 | 原因 |
| ---: | ---: | ---: | --- | ---: | --- |

仅记录本侧软件事件；离线回放不表示实时处理。独立接收机的 IQ 样本零点不能直接相减，未校准时不报告执行同步误差。

逐事件：[control.events.jsonl](rx.control.events.jsonl)；逐任务：[control.tasks.csv](rx.control.tasks.csv)；结构化结果：[control.summary.json](rx.control.summary.json)。
