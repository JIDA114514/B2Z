# 接收报告

- 接收链：IEEE 802.15.4 / B2Z 控制
- 实验 Run ID：1006（解码后控制记录过滤条件）
- 模式：离线回放
- 运行状态：正常结束（仅表示程序状态）
- 有效包：35（PHY FCS有效）
- IQ观察时长：30.000000 s（全部已处理采样，含实验前后余量）
- Command ID：43
- 控制记录候选：35；记录有效：35
- 有效唯一时隙：35；重复：0；乱序：0
- 最长连续缺失：12（explicit planned range）
- 有效解码 / DMA 完成：35/100 = 35.00%
- 采集队列：溢出 0；高水位 64
- 时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。

## 关键配置

| 参数 | 值 |
|---|---|
| serial | N/A |
| channel | 26 |
| center_hz | 2480000000 |
| sample_rate | 8000000 |
| format | ci8 |
| command_id | 43 |
| payload_len | N/A |
| expected_packets | 100 |
| demod | phase |
| symbol_order | project |
| cutoff_hz | 700000 |
| iq_file | python/experiments/20261103_run1006/captures/zigbee/143027_116609_obv3m07c/rx.ci8 |

## 数据与口径

完整结构化记录：[rx.summary.json](rx.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与负载校验，不表示命令执行或执行器同步。

- [rx.hackrf.log](rx.hackrf.log)
- [rx.packets.jsonl](rx.packets.jsonl)
- [rx.summary.txt](rx.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- independent SDR PHY and application decode; no command execution
- FCS-failure candidate counts are not uniquely identified transmitted packets
- sample times are relative to this HackRF IQ and not UTC or another receiver clock
- DMA completion is a proxy for TX; no calibrated RF-start timestamp
