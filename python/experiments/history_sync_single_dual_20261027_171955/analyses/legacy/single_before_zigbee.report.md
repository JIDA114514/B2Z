# 接收报告

- 接收链：IEEE 802.15.4 / BlueBee
- 实验 Run ID：10271（解码后测试负载过滤条件）
- 模式：实时采集
- 运行状态：正常结束（仅表示程序状态）
- 有效包：2（PHY FCS有效）
- IQ观察时长：30.000000 s（全部已处理采样，含实验前后余量）
- Run ID：10271
- 有效唯一测试包：2；重复：0；乱序：0
- 最长连续缺失：7（min..max valid received Sequence）
- 无线 PRR：N/A（分子 2；分母 N/A；matching board final counts and full-run coverage required）
- 端到端接收率：N/A（分子 2；分母 N/A；matching board final counts and full-run coverage required）
- 调度完成率：N/A（分子 0；分母 N/A；matching board final counts and full-run coverage required）
- 总吞吐：2.000 B/s（16.000 bit/s）
- 应用 goodput：1.333 B/s（10.667 bit/s）
- 采集队列：溢出 0；高水位 3
- 时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。

## 关键配置

| 参数 | 值 |
|---|---|
| serial | 000000000000000017c467dc3348a6c3 |
| channel | 26 |
| center_hz | 2480000000 |
| sample_rate | 8000000 |
| format | ci8 |
| payload_len | 30 |
| expected_packets | N/A |
| demod | phase |
| symbol_order | project |
| cutoff_hz | 700000.000 |
| iq_file | N/A |

## 数据与口径

完整结构化记录：[single_before_zigbee.summary.json](single_before_zigbee.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。

- [single_before_zigbee.ci8](single_before_zigbee.ci8)
- [single_before_zigbee.console.log](single_before_zigbee.console.log)
- [single_before_zigbee.hackrf.log](single_before_zigbee.hackrf.log)
- [single_before_zigbee.packets.jsonl](single_before_zigbee.packets.jsonl)
- [single_before_zigbee.summary.txt](single_before_zigbee.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- independent SDR PHY decoder, not commercial ZigBee stack compatibility
- FCS failures are candidate counts, not unique physical packet losses
- relative nominal sample timing; USB gaps and sample clock errors not ruled out
- two HackRF captures have independent time origins; do not subtract their timestamps as synchronization error
- no command execution or common control command schema implemented
