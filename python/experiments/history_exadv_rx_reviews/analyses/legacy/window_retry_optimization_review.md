# 已存 IQ 接收优化与诊断配对（2026-10-26）

## 实现与接受规则

保留原完整符号窗口的首次解码路径。只有该候选组未得到有效包且出现硬 CRC 失败时，才对最多两个采样位置、每个三个时钟偏差假设（0、-80、+80 ppm）执行固定 0.75 符号中心窗口重判。完整 BLE CRC24 与扩展头合法性仍是接受条件，既不使用测试 payload 先验，也不翻转错误位来凑 CRC。已成功的原始路径不进入重试。

新增 `--timing-retry`（默认开启）与 `--no-timing-retry`，逐包记录 `decode_method` / `decision_window_fraction`；分别统计硬 CRC 失败、重试尝试、恢复和最终失败候选。默认通道截止频率保持 850 kHz，`--channel-cutoff-hz` 允许显式试验。降低截止频率的收益跨记录不一致，未作为默认优化。

## 连续 IQ 回放结果

| Run ID | 原始目标 secondary | 优化后 | 新恢复 Sequence | 丢失原有 Sequence | 严格 pairs | diagnostic_pairs |
|---|---:|---:|---|---|---:|---:|
| 10262 | 104 | 104 | 无 | 无 | 0 | 100 |
| 10263 | 106 | 107 | 42 | 无 | 0 | 101 |
| 10264 | 115 | 117 | 69、96 | 无 | 0 | 106 |

全部优化后目标负载均独立复核了 Run ID、30 B 长度、10 B 测试头、确定性填充和 IEEE 802.15.4 FCS。复核仅发生在 BLE 解码完成之后，不能作为独立 ZigBee 接收成功率。10262 的通道统计另有一个非目标包经窄窗口恢复，不计入目标收益。

10264 覆盖 0–149，序列范围覆盖率由 115/150=76.67% 到 117/150=78.00%；仍不是板端 tx_completed 分母的无线 PRR，且远未达到 99%。所有结果为相同硬件录制的离线对照，不是新版本实时长测。

短片段探针中 10264 曾恢复 3 个新增包；完整连续回放只新增 2 个。片段重置 DC 状态、滤波上下文、抽取起点及结束处理，可能改变解码结果，因此以完整 IQ 回放为正式证据，不将短片段探针计数直接用作最终收益。真实短片段仍作为特定失败模式的回归测试。

## 剩余损失诊断

对 10264 完整优化回放后剩余 33 个缺失序列，在预测时隙附近作短片段诊断：26 个窗口找到与目标固定包头兼容但 CRC 失败的候选，7 个未找到此类候选。固定包头比较用于识别诊断对象；期望测试负载只用于离线误差统计，没有输入正式解码器。除少量 1–2 bit 错误外，多数兼容候选与期望码流相差几十到上百 bit，说明仅微调同步门限/判决窗口不能解决主要剩余损失。

这不是已完成的无线/板端损失归因：缺候选不等于板端漏发，短片段初始化也可能改变结果；较多错误仍需区分干扰、信噪比、采样定时与解调失真。具体逐时隙记录见 `window_retry_loss_diagnosis.summary.json`。

## 配对显示

`pairs` 保持严格 AuxPtr 口径；新 `diagnostic_pairs` 默认启用，只对同 RF、相同 ADI、必要时相同 AdvA 的同频诊断包，在声明偏移的 ±2000 us 范围内做一对一关联。配置为 `--diagnostic-pair-window-us`，最高 10000 us，`--no-diagnostic-pairs` 可关闭。没有使用周期折叠或主机到达时间。

事件 JSONL 用 `match_type=aux_ptr` 与 `match_type=same_channel_diagnostic` 区分。诊断事件显式记录 `standards_compliant=false`、实际时差、对 AuxPtr 的误差和信道/PHY 不符信息。当前板端 AuxPtr 与实际 RF、PHY、偏移均不一致，所以严格 pairs 仍应为 0，不能用诊断数替代规范符合性结论。

## 开销及验证

单进程、同一 IQ 前 25 s、相同配置的顺序对照：

- hard：处理墙钟 20.459 s，块处理平均/P99/最大 5.763/8.727/10.517 ms。
- retry：处理墙钟 21.625 s，块处理平均/P99/最大 6.117/9.930/11.758 ms。

重试组回放总墙钟增加约 5.7%，处理 25 s IQ 仍快于实时时长。块跨度 8.192 ms，P99 可以超出，实时运行仍需观察队列高水位；不能从此单次离线基准保证任意主机实时稳定性。

17 项测试通过，包括强直流下弱包、长包、跨块、CRC 错误拒绝、真实 IQ 窄窗口回归、诊断配对与严格配对隔离、身份不符、窗口超限和重复提交。代码语法检查与 git diff --check 通过。未修改发送端或历史原始结果。

## 复现

在项目根目录运行：

```bash
python3 python/exadv_rx/receive.py --iq-file python/exadv_rx/results/rx_20261026_155043_397830.ci8 --channels 39 --duration 0 --quiet --no-timing-retry --output /tmp/exadv_hard_baseline
python3 python/exadv_rx/receive.py --iq-file python/exadv_rx/results/rx_20261026_155043_397830.ci8 --channels 39 --duration 0 --quiet --output /tmp/exadv_window_retry
python3 -m unittest discover -s python/exadv_rx/tests -v
```

输出前缀须不存在，避免覆盖记录。完整三轮优化回放为 `replay_10262_window_retry1.*`、`replay_10263_window_retry1.*`、`replay_10264_window_retry1.*`；摘要比较见 `window_retry_comparison.summary.json`。原 IQ 和完整逐包流按仓库归档约定另存。
