# 实验：history_sync_single_dual_20261027_171955

本页自动生成；人工观察请写入 notes.md。运行正常结束不代表达到实验目标。

## 接收结果

| 记录 | 接收链 | 模式 | 程序状态 | 实验Run ID | 解码Run ID | 有效包 | 唯一测试包 | IQ时长(s) |
|---|---|---|---|---|---|---|---|---|
| [analyses/legacy/dual_ble](analyses/legacy/dual_ble.report.md) | ble | live | error | N/A | N/A | 243 | N/A | 14.974976 |
| [analyses/legacy/dual_zigbee](analyses/legacy/dual_zigbee.report.md) | zigbee | live | interrupted | 10271 | 10271 | 5 | 5 | 16.285696 |
| [analyses/legacy/single_before_zigbee](analyses/legacy/single_before_zigbee.report.md) | zigbee | live | complete | 10271 | 10271 | 2 | 2 | 30.000000 |

同目录不自动计算联合成功率；联合结果须依据已保存的逐标识匹配分析。独立设备的相对时间不能直接相减。

## 分析与原始记录

- [analyses/legacy/single_dual.summary.json](analyses/legacy/single_dual.summary.json)（error）
- [analyses/legacy/usb_disconnect.summary.json](analyses/legacy/usb_disconnect.summary.json)（历史分析；状态未记录）
- [analyses/legacy/failure_review.md](analyses/legacy/failure_review.md)

配置：[experiment.config.json](experiment.config.json)。完整参数、分母依据和异常见各接收报告及原始 JSON。
