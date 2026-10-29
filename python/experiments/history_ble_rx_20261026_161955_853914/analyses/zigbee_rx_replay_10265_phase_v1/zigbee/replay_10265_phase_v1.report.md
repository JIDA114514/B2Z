# 接收报告

- 接收链：IEEE 802.15.4 / BlueBee
- 实验 Run ID：10265（解码后测试负载过滤条件）
- 模式：离线回放
- 运行状态：正常结束（仅表示程序状态）
- 有效包：97（PHY FCS有效）
- IQ观察时长：40.000000 s（全部已处理采样，含实验前后余量）
- Run ID：10265
- 有效唯一测试包：97；重复：0；乱序：0
- 最长连续缺失：4（explicit planned range）
- 无线 PRR：N/A（分子 97；分母 N/A；matching board final counts and full-run coverage required）
- 端到端接收率：N/A（分子 97；分母 N/A；matching board final counts and full-run coverage required）
- 调度完成率：N/A（分子 0；分母 N/A；matching board final counts and full-run coverage required）
- 总吞吐：72.750 B/s（582.000 bit/s）
- 应用 goodput：48.500 B/s（388.000 bit/s）
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
| cutoff_hz | 1300000 |
| iq_file | python/exadv_rx/results/rx_20261026_161955_853914.ci8 |

## 数据与口径

完整结构化记录：[replay_10265_phase_v1.summary.json](replay_10265_phase_v1.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。

- [replay_10265_phase_v1.hackrf.log](replay_10265_phase_v1.hackrf.log)
- [replay_10265_phase_v1.packets.jsonl](replay_10265_phase_v1.packets.jsonl)
- [replay_10265_phase_v1.summary.txt](replay_10265_phase_v1.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- independent SDR PHY decoder, not commercial ZigBee stack compatibility
- FCS failures are candidate counts, not unique physical packet losses
- relative nominal sample timing; USB gaps and sample clock errors not ruled out
- two HackRF captures have independent time origins; do not subtract their timestamps as synchronization error
- no command execution or common control command schema implemented
