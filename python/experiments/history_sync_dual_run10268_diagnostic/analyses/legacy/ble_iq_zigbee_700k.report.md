# 接收报告

- 接收链：IEEE 802.15.4 / BlueBee
- 模式：离线回放
- 运行状态：正常结束（仅表示程序状态）
- 有效包：81（PHY FCS有效）
- IQ观察时长：40.000000 s（全部已处理采样，含实验前后余量）
- Run ID：10268
- 有效唯一测试包：81；重复：0；乱序：0
- 最长连续缺失：6（explicit planned range）
- 无线 PRR：N/A（分子 81；分母 N/A；matching board final counts and full-run coverage required）
- 端到端接收率：N/A（分子 81；分母 N/A；matching board final counts and full-run coverage required）
- 调度完成率：N/A（分子 0；分母 N/A；matching board final counts and full-run coverage required）
- 总吞吐：60.750 B/s（486.000 bit/s）
- 应用 goodput：40.500 B/s（324.000 bit/s）
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
| payload_len | 30 |
| expected_packets | 150 |
| demod | phase |
| symbol_order | project |
| cutoff_hz | 700000.000 |
| iq_file | python/exadv_rx/results/rx_20261027_154450_562661.ci8 |

## 数据与口径

完整结构化记录：[ble_iq_zigbee_700k.summary.json](ble_iq_zigbee_700k.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。

- [ble_iq_zigbee_700k.hackrf.log](ble_iq_zigbee_700k.hackrf.log)
- [ble_iq_zigbee_700k.packets.jsonl](ble_iq_zigbee_700k.packets.jsonl)
- [ble_iq_zigbee_700k.summary.txt](ble_iq_zigbee_700k.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- independent SDR PHY decoder, not commercial ZigBee stack compatibility
- FCS failures are candidate counts, not unique physical packet losses
- relative nominal sample timing; USB gaps and sample clock errors not ruled out
- two HackRF captures have independent time origins; do not subtract their timestamps as synchronization error
- no command execution or common control command schema implemented
