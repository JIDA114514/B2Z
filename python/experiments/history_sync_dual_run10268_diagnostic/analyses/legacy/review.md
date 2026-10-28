# Run 10268：双 HackRF 下 ZigBee 零有效包诊断

日期：2026-10-27。用户确认板端命令为 `bluebee_exadv_perf_start?30 200000 30 10268`，其他条件维持不变。

后续更新：Run 10269 已使用 700 kHz 实时重测，但 ZigBee 设备仍为 0 包；同一程序回放本轮旧 IQ 仍可复现 68 包。以下离线改善结果保留，但不能作为已稳定解决的证据。后续诊断见 `../dual_run10269_diagnostic/review.md`。

## 结论

已找到可通过现有参数修正的直接因素：当前 ZigBee 差分相位接收器的 1.3 MHz 低通截止频率不适合本轮 IQ。在相同完整 IQ、相同标准 DSSS/FCS 解码算法下，只将截止频率改为 700 kHz，ZigBee 设备的录制由 0 个有效包恢复到 **68 个**；BLE 设备的录制由 0 个恢复到 **81 个**。两者均通过 Run ID、Sequence 和完整确定性填充校验。

本次未改解调代码、码本、FCS 或测试填充，也没有把 BLE 内容提供给 ZigBee 解调器。通用默认值 1.3 MHz 保留；下一轮建议显式加入 `--cutoff-hz 700000 --dc-block-hz 1000`，以便配置可审计。这个参数是在当前数据上选择的，需新一轮实时实验确认，不能直接宣称适用于所有 RF 条件或所有原生 O-QPSK 输入。

## 原始采集状态

| 项目 | BLE 设备 | ZigBee 设备 |
| --- | --- | --- |
| 序列号末尾 | 2926a0c3 | 3348a6c3 |
| 文件前缀 | `rx_20261027_154450_562661` | `rx_20261027_154453_216417` |
| IQ 目录 | `python/exadv_rx/results` | `python/zigbee_rx/results` |
| 采集 | 40 s、8 Msps、640 MB | 40 s、8 Msps、640 MB |
| 完成状态 / 设备退出码 | complete / 0 | complete / 0 |
| 实时队列最高 | 8/64 | 11/64 |
| 报告应用队列溢出 | 无 | 无 |

设备选择冲突已解决；本次没有 `Resource busy` 或采集退出错误。无应用溢出不保证 USB/硬件完全无丢样，当前没有合并硬件 shortfall 计数，不能排除所有底层问题。

原 BLE 终端的 808 包由 790 个 primary 和 18 个同频 secondary 诊断包构成。18 个 secondary 均能解析出 Run 10268、30 B 的有效测试负载；不能将 808 当作本轮 808 个有效控制/测试包，primary 中还存在其他广播源。

原 ZigBee 端确实没有 FCS 有效包：61 个前导码候选中 19 个进入 FCS 失败分支、42 个被拒；不是 `--quiet`、Run ID 或 payload 长度过滤把成功包隐藏了。

## 完整交叉回放

以下数字均来自完整 40 s 输入。ZigBee 700 kHz 结果为不使用 BLE 时间定位的独立全流解码，不是后述窗口诊断的结果。

| IQ 所属物理设备 | BLE 解码有效测试包 | ZigBee 原 1.3 MHz | ZigBee 700 kHz |
| --- | --- | --- | --- |
| BLE 设备 2926a0c3 | 18 | 0 | **81** |
| ZigBee 设备 3348a6c3 | 13 | 0 | **68** |

ZigBee 设备自己的 IQ 能解出 13 个 BLE 目标包，也能在收窄带宽后解出 68 个 ZigBee 目标包。原默认配置完整离线回放仍为 0，因此没有证据将零接收主要归因于实时 CPU 积压或终端打印。

低通带宽改变会影响解调前的噪声、带外分量和波形平滑，当前结果说明它对该差分相位/DSSS 路径至关重要。但本次没有测得目标 SNR、模拟前端状态或可控干扰，不能据此断定某个外部干扰源、硬件故障或“两台接收器互相干扰”为根本物理原因。

全流验证命令如下，对另一份 IQ 使用相同参数并更换输入和输出路径：

```bash
python3 python/zigbee_rx/receive.py \
  --iq-file python/zigbee_rx/results/rx_20261027_154453_216417.ci8 \
  --duration 0 --channel 26 --demod phase --symbol-order project \
  --cutoff-hz 700000 --dc-block-hz 1000 \
  --run-id 10268 --payload-len 30 --expected-packets 150 \
  --quiet --output python/sync_validation/results/new_replay_10268_700k
```

## 窗口参数诊断

`python/sync_validation/probe_dual_rx.py` 对 BLE 已解码后定位的 10 ms 原始 IQ 片段扫描参数，仅用于诊断。片段独立初始化 DC/FIR 状态，且定位使用 BLE 结果，因此这些数量不作为独立接收器的正式恢复率。

- BLE 设备的 18 个目标片段：700/850 kHz + 1 kHz DC 抑制均恢复 18 个；1.0 MHz 恢复 14 个；1.3 MHz 恢复 0 个。
- ZigBee 设备的 13 个目标片段：700 kHz 恢复 13 个，850 kHz 恢复 11 个，1.0 MHz 恢复 8 个，1.3 MHz 恢复 0 个。
- 两份输入关闭 DC 抑制的全部带宽配置均恢复 0 个，下一轮应保留 DC 抑制。
- 仅将前导码距离阈值从 80 放宽到 88，保留 1.3 MHz，仍均为 0；本次没有靠降低完整校验要求获得结果。
- 补充在 700 kHz 下验证 10/30/40/46 B、60 kHz 频偏的合成 BlueBee 测试帧，均通过。这不是对应长度的真实无线性能实验。

完整窗口变体见 `window_parameter_probe.summary.json`。频谱诊断只记录固定时刻的未校准功率及 Welch PSD，见 `iq_spectrum.summary.json`，不将其作为目标 SNR 或故障根因证据。

## 两块设备记录的联合结果

使用原 BLE 设备的 18 个有效测试包，与 ZigBee 设备经 700 kHz 完整离线回放的 68 个有效测试包按 Run ID+Sequence 匹配：

| 结果 | 数量 |
| --- | --- |
| 两侧共同有效 | 15 |
| 仅 BLE 有效 | 3 |
| 仅 ZigBee 有效 | 53 |
| 两侧均未恢复 | 79 |

共同恢复为 **15/150 = 10%**，分母是配置的计划序列数，不是核实后的空口发送数。该结果包含一侧离线重处理，不能称为两侧原始实时配置都成功；也不能用这两个文件的相对时间直接计算同步误差。当前主要限制仍包括目标包联合恢复比例，尚不能据此开展真实同步执行结论。

## 下一步

保持 BLE 启动参数不变，在 ZigBee 命令中加入 `--cutoff-hz 700000 --dc-block-hz 1000`，下一轮使用新 Run ID。继续保存两侧 IQ 和设备日志，确认 700 kHz 在实时双设备条件下的有效包数及队列状态。新滤波配置下的时间参考偏差还需校准，旧同 IQ 的残差结果不能直接替代新配置的测量。

原始数据和历史基线未覆盖。`diagnostic_review.summary.json` 保存输入 SHA-256、全流配置、源码散列、联合序列和限制；`per_sequence.metrics.csv` 保留全部 150 个计划序列的两侧恢复状态。原始 1.3 MHz 与新增 700 kHz 的独立摘要分别保留。
