# BLE 共包接收诊断（2026-11-02）

原始记录：[`captures/ble/170327_237258_xoj2szen/rx.report.md`](captures/ble/170327_237258_xoj2szen/rx.report.md)、同前缀的 `rx.summary.json`、`rx.packets.jsonl` 和 `rx.ci8`。本次只录制了 BLE 接收链；`--run-id 1001` 是归档标签，不会过滤 BLE 负载。

## 直接解码结果

- ch39，2480 MHz，8 Msps，40 s；采集到 320,000,000 个复采样，HackRF 进程正常结束，采集队列高水位 14/64。采集状态不能排除未被设备报告的 USB 丢样。
- 555 个 BLE CRC 正确包全部是 primary。其中只有 1 个能明确识别为本次新命令的 primary：采样时间 4.948257 s，ADI DID=9，`pdu_hex=07070618090003e803`，AuxPtr 宣告数据 ch3、30 ms、LE 1M。
- 没有任何 BLE CRC 正确的 secondary；严格匹配和同频诊断匹配均为 0。其余 554 个 CRC 正确 primary 不能算作本实验的命令包。

## 对原始 IQ 的定向复查

以下为利用预期波形/时隙辅助定位的诊断，不计入独立解码成功数。

- 与已知 primary 空口比特模板比较，发现三段不同的命令形状发送活动，估计起点约为采样时间 3.148 s、25.263 s、34.347 s。能够识别出第一段的 DID 8、9，第二段的 DID 1、2、9，第三段的 DID 0、5（完整 primary 模板最多 8 bit 错误）。这支持三次发送确实落入录制窗口，但不能据此认定 30 个包均已完整空口发射。
- 第一段第 9 时隙，约 4.979201 s 有 secondary 前导码峰，比其 CRC 正确的 primary 晚约 30.944 ms。解调头部为 `47 e0`，对应 224 B 的 extended PDU payload；扩展头中的 ADI DID=9。按照 `b2z_control_start? 1001 42` 的默认参数生成的参考 PDU，观测 CRC 字节 `1f42bf` 与发射端预期相同，但前面的数据有约 16–20 bit 解调错误，重算 CRC 不相等。错误数随符号定时搜索而变化；不能将参考数据替代独立恢复结果。
- 使用已知 secondary 前缀作相关检测，三段起点后均有接近 30–31 ms 的峰；能独立从解调头部读到 `47 e0` 的至少有第一段第 8、9 时隙及第三段第 0、1、4、5、9 时隙。它们均未通过完整 BLE CRC。
- 将 3.0–5.3 s 片段以同步阈值 0.72（原为 0.84）回放，仍无完整 secondary；分别以 600 kHz 和 950 kHz 信道滤波截止频率回放，也仍无完整 secondary。单纯放宽同步阈值或这两档滤波未解决问题。

## 解释与后续验证

这轮未配对的直接原因是**没有 CRC 正确的目标 secondary**。IQ 中有长 secondary 的证据，因此至少已定位的一组不能解释为板端完全未发送。短 primary 也只有 1 个通过 CRC，说明问题不只发生在长包末尾；需继续检查射频链路质量、干扰及接收解调。现有资料不能判定主因是无线损坏、波形/射频失真还是接收处理误码。

另有独立的结构限制：板端当前把 primary 和 secondary 都发在 ch39，但 AuxPtr 宣告 ch3。因此即使未来同频 secondary 通过 CRC，**严格 AuxPtr 匹配仍应为 0**；同频调试只能看 `diagnostic_pairs`，不能报告为规范 exadv 跟随。已定位的那一对波形起点相隔约 30.944 ms，比宣告的 30 ms 晚约 944 µs；也超出接收脚本当前严格匹配的 30 µs AuxPtr 单位加 20 µs 容差。该时间差是单个包对的 IQ 测量，尚不能代表所有时隙。

用户随后提供了[其中一轮的串口原文](board_round_unattributed.board.log)：`run_id=1001`、`command_id=42`、`period_ms=200`、`attempts=10`；最终 `state=complete`，`scheduled=generated=primary_started=primary_completed=tx_started=tx_completed=10`，`deadline_miss=dma_timeout=0`。这证明该轮的 10 次 primary 与 secondary 均完成 DMA 提交和轮询完成，不能再将未配对解释为这一轮板端未调度或 DMA 超时。DMA 完成仍不是逐包完整空口发射的硬件证明。

同一板端统计给出 `secondary_dma_late_avg_us=80171`、`max_us=80337`（10 个样本），相对的是 **计划 secondary 起点**，不是相对 primary 的延迟。[发送路径](../../../app_FreeRTOS/app/bluebee_perf.c)在每个时隙先生成整包波形，再开始 primary DMA，随后等待约 30 ms 才提交 secondary DMA。因此录制中约 30.944 ms 的 primary-to-secondary 间隔可以与约 80 ms 的计划时刻迟到同时成立。`ref_tick_ms` 仍由计划时隙计算，尚未绑定实际 RF 起点；这约 80 ms 的系统偏移必须在同步实验前测量和处理。当前统计只有均值和最大值，不足以给出逐包时间误差或抖动分布。

提供的串口日志没有与录制中的三段发送活动一一对应的时间标识。三次调用重复使用相同 `run_id`、`command_id` 和时隙 DID，故不能将这一份 10 次发送计数硬套到某一段 IQ，也不能据此报告三轮合计 PRR。下一次应分别保存三轮 `CONTROL_START`、`CONTROL_STATS` 及启动时间或使用不同 Run ID；同时对照短 primary 和长 secondary 的逐时隙恢复情况，并记录收发增益、距离和环境。只有在完整 secondary 通过 CRC 后，才使用同频诊断配对评估当前模式。
