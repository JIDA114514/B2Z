# 接收报告

- 接收链：BLE exadv
- 模式：离线回放
- 运行状态：正常结束（仅表示程序状态）
- 有效包：781（BLE CRC及扩展头有效）
- IQ观察时长：40.000000 s（全部已处理采样，含实验前后余量）
- 严格 AuxPtr 匹配：0
- 同频诊断配对：9（不代表规范跟随）
- 无线 PRR：N/A（未合并发送计数及一致观察窗口）
- 采集队列：溢出 0；高水位 64
- 时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。

## 关键配置

| 参数 | 值 |
|---|---|
| serial | N/A |
| channels | [39] |
| whitening_channels | [39] |
| center_hz | 2480000000.000 |
| sample_rate | 8000000 |
| format | ci8 |
| channel_cutoff_hz | 850000 |
| iq_file | python/zigbee_rx/results/rx_20261027_154453_216417.ci8 |

## 数据与口径

完整结构化记录：[zigbee_iq_ble.summary.json](zigbee_iq_ble.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。

- [zigbee_iq_ble.events.jsonl](zigbee_iq_ble.events.jsonl)
- [zigbee_iq_ble.hackrf.log](zigbee_iq_ble.hackrf.log)
- [zigbee_iq_ble.packets.jsonl](zigbee_iq_ble.packets.jsonl)
- [zigbee_iq_ble.summary.txt](zigbee_iq_ble.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- LE 1M only; fixed RF capture, no host-timed frequency hopping
- DC blocker/filter and demodulation timing require calibration before synchronization claims
- sample timestamps are relative to capture, not hardware/UTC timestamps
- HackRF/USB sample losses may be unobservable in raw IQ; no guaranteed gap-free timeline
- CRC-failure counts refer to sync candidates, not uniquely identified transmitted packets
- no PRR without independently supplied TX counts and matched observation window
