# 接收报告

- 接收链：BLE exadv
- 实验 Run ID：2412（控制记录独立校验并统计匹配 Run ID；总 PHY 包数仍包含其他包）
- 模式：实时采集
- 运行状态：正常结束（仅表示程序状态）
- 有效包：100（BLE CRC及广播结构有效）
- IQ观察时长：70.000000 s（全部已处理采样，含实验前后余量）
- 严格 AuxPtr 匹配：0
- 同频诊断配对：0（不代表规范跟随）
- 无线 PRR：N/A（未合并发送计数及一致观察窗口）
- 有效控制记录：100；匹配 Run ID：100；无效控制记录：0（未按槽去重）
- C1分片重组（本地IQ时间，非跨端同步）：compact_pending=0, compact_incomplete_at_end=0
- 采集队列：溢出 0；高水位 2
- 时间基准：相对 IQ 标称采样时间；独立采集未经校准不能直接相减。

## 关键配置

| 参数 | 值 |
|---|---|
| serial | 000000000000000017c467dc2926a0c3 |
| channels | [39] |
| whitening_channels | [39] |
| center_hz | 2480000000.000 |
| sample_rate | 4000000 |
| format | ci8 |
| channel_cutoff_hz | 850000 |
| iq_file | N/A |

## 数据与口径

完整结构化记录：[rx.summary.json](rx.summary.json)。

候选 CRC/FCS 失败计数不等于唯一物理坏包数；队列未溢出不证明 USB 无丢样。
当前报告描述解码与测试负载校验，不表示命令执行或执行器同步。

- [rx.ci8](rx.ci8)
- [rx.events.jsonl](rx.events.jsonl)
- [rx.hackrf.log](rx.hackrf.log)
- [rx.packets.jsonl](rx.packets.jsonl)
- [rx.summary.txt](rx.summary.txt)

历史记录中保存的旧路径可通过 python/experiments/migration.manifest.json 或 manage.py locate 查询。

- LE 1M only; fixed RF capture, no host-timed frequency hopping
- DC blocker/filter and demodulation timing require calibration before synchronization claims
- sample timestamps are relative to capture, not hardware/UTC timestamps
- HackRF/USB sample losses may be unobservable in raw IQ; no guaranteed gap-free timeline
- CRC-failure counts refer to sync candidates, not uniquely identified transmitted packets
- no PRR without independently supplied TX counts and matched observation window
