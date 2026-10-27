# 真实 IQ 回归片段

`run10265_soft_frame.npz` 从本项目原始录制 `python/exadv_rx/results/rx_20261026_161955_853914.ci8` 裁剪，包含 80,000 个交错 int8 I/Q 样本（8 Msps，10 ms）。压缩后约 43 KB，用于跨块解码与软重试回归。它是单个弱信号片段，不是完整实验数据集。

归档字段：`iq_ci8`、`source_sample_start`（原始文件样本偏移）、`sample_rate_hz`、`expected_frame_hex`。预期帧来自独立 ZigBee 解调并通过 FCS，测试负载为 Run ID 10265、Sequence 98；没有使用 BLE 逐包结果生成预期负载或辅助解调。

这个片段在当前解码配置下硬判决未得到有效帧，软重试恢复一帧。测试仍要求逐字节匹配完整 PHY 帧及 FCS，不能据此宣称软重试对所有信号条件都有收益。
