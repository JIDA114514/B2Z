# 独立 ZigBee 接收器初次验证

日期：2026-10-26。实现入口为 `python/zigbee_rx/receive.py`，未修改现有 BLE 接收器或板端程序。

## 自动验证

运行：

```bash
python3 -m unittest discover -s python/zigbee_rx/tests -v
```

10 项测试全部通过。覆盖标准码本和 FCS 与既有生成器交叉校验、BlueBee 10/30/40/46 B、原生半正弦 O-QPSK 两种符号顺序、最大 127 B PSDU、频偏/反相、跨块、真实重复发射保留、噪声和坏 FCS 拒绝、真实 IQ 软重试、CLI/测试头/计划缺口/板端计数合并，以及未指定设备和损坏 IQ 的拒绝行为。

## 完整历史 IQ 独立解调

两份输入均为此前保存的 8 Msps、2480 MHz、40 s 原始 IQ；运行时不读取 BLE 解码输出。命令配置均为 `--channel 26 --demod phase --symbol-order project --expected-packets 150 --duration 0 --quiet`，分别设置对应 Run ID、payload 长度和输入路径。完整命令及源码 SHA-256 保存在各自 summary 中。

| Run ID | 测试 payload | FCS 正确帧 | 有效唯一测试包 | 重复/逆序 | 最长计划序列缺失 | 硬判决/软重试恢复 |
| --- | --- | --- | --- | --- | --- | --- |
| 10265 | 30 B | 97 | 97 | 0/0 | 4 | 96/1 |
| 10266 | 40 B | 64 | 64 | 0/0 | 6 | 64/0 |

所有接收测试负载通过 Run ID、Sequence 和完整确定性填充校验。这里的 97/150、64/150 只能表示相对显式计划序列范围的恢复情况；没有合并板端最终发送计数，不作为无线 PRR。

摘要：`replay_10265_phase_v1.summary.json`、`replay_10266_phase_v1.summary.json`。完整逐包流和原始 IQ 默认不进入 Git。

解码完成后，另行与既有 BLE 结果按 Sequence 比较：30 B 的 BLE 91 包中与 ZigBee 共同恢复 85 包；40 B 的 BLE 61 包中共同恢复 48 包。ZigBee 独有分别 12、16 包，BLE 独有分别 6、13 包。详见 `validation_comparison.summary.json`。这说明两种解码结果不能相互替代，但同一 IQ 的两次解码不构成两块物理设备独立接收实验。

## HackRF 实机采集检查

本次只检测到一块已连接 HackRF，序列号 `000000000000000017c467dc3348a6c3`。使用该设备运行 3 s、8 Msps、2480 MHz、LNA 24/VGA 20、`phase/project` 采集检查：

- 处理 24,000,000 个样本，共 48,000,000 B；`hackrf_transfer` 退出码 0。
- 应用队列最高 2 块，未报告队列溢出；块大小 65,536 样本。
- 处理时延均值约 6.16 ms、P99 约 7.73 ms，单块样本时长 8.192 ms。
- 未安排目标发射实验，接收有效目标帧为 0；此项只验证 USB 采集、数据处理与正常退出。

记录为 `live_transport_smoke_v1_usb.*`。此前沙箱内尝试因无法初始化 USB 失败，保留为 `live_transport_smoke_v1.*`，不能计入成功运行。

## 尚待实验

连接第二块 HackRF，按 README 选用两个不同序列号，先验证同一轮板端实验的双独立接收，再进行更长时长稳定性验证。上述短测不支持长时间实时稳定、商业 ZigBee 芯片互操作、同步执行精度或 SCI 核心机制已经完成的结论。两个独立采集时间原点不同，不能直接相减计算同步误差。
