# 接收报告

- 接收链：IEEE 802.15.4 / B2Z 控制
- 实验 Run ID：2303（解码后控制记录过滤条件）
- 模式：实时采集
- 运行状态：正常结束（仅表示程序状态）
- 有效包：100（PHY FCS有效）
- IQ观察时长：80.000000 s（全部已处理采样，含实验前后余量）
- Command ID：N/A
- B2 43 候选：100；记录有效：100
- 有效唯一时隙：100；重复：0；乱序：0
- 最长连续缺失：0（explicit planned range）
- 有效解码 / DMA 完成：N/A（分子 100；分母 N/A；matching final CONTROL_STATS and full-run coverage required）
- 采集队列：溢出 0；高水位 2
- 时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。

## 关键配置

| 参数 | 值 |
|---|---|
| serial | 000000000000000017c467dc3348a6c3 |
| channel | 12 |
| center_hz | 2410000000 |
| sample_rate | 4000000 |
| format | ci8 |
| command_id | N/A |
| payload_len | N/A |
| expected_packets | 100 |
| demod | phase |
| symbol_order | project |
| cutoff_hz | 700000 |
| iq_file | N/A |

## 数据与口径

完整结构化记录：[rx.summary.json](rx.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与负载校验，不表示命令执行或执行器同步。

- [rx.ci8](rx.ci8)
- [rx.hackrf.log](rx.hackrf.log)
- [rx.packets.jsonl](rx.packets.jsonl)
- [rx.summary.txt](rx.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- independent SDR PHY and application decode; no physical actuator execution
- FCS-failure candidate counts are not uniquely identified transmitted packets
- sample times are relative to this HackRF IQ and not UTC or another receiver clock
- DMA completion is a proxy for TX; no calibrated RF-start timestamp
