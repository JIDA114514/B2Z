# BLE 共包接收复查（run 1002）

原始资料：[接收报告](captures/ble/181336_200150_m1ds_iz2/rx.report.md)、同前缀的 `rx.summary.json`、`rx.packets.jsonl`、`rx.ci8`，以及用户提供的[板端命令与统计](board.board.log)。接收参数为 ch39 / 2480 MHz、8 Msps、LNA 24 dB、VGA 20 dB、放大器关闭、40 s；录制正常结束，320,000,000 个复采样，采集队列高水位 12/64。`--run-id 1002` 只用于归档，不参与 BLE 包过滤。

## 直接解码与板端计数

- 板端 `scheduled=generated=primary_started=primary_completed=tx_started=tx_completed=100`，`deadline_miss=dma_timeout=0`。这些是 DMA 提交/完成代理计数，未直接测量完整空口发射。
- 接收端 566 个 BLE CRC 正确包全部是 primary。其中 30 个符合本命令的 primary 格式，ADI DID 均不同，范围 1–99，时间约 1.922–21.522 s；其余 536 个不能归为本命令。结合板端 100 个计划时隙，本轮目标 primary 的 CRC 正确恢复为 **30/100**。primary 不含 run_id / command_id，此归属依据特征格式、DID 周期和板端记录，属于本实验的诊断口径。
- **0/100** 个目标 secondary 通过完整 BLE CRC；`matched_events=0`、`diagnostic_pairs=0`。BLE 控制记录没有一次独立完整恢复，因此不能报告 BLE 命令解析成功。
- 对照 run 1001 的 40 s IQ：上一轮只有 1 个目标格式 primary CRC 正确，本轮有 30 个；上一轮三次发送的完整板端统计未保存，不能用 `1/30` 与本轮 `30/100` 作为严格同条件 PRR 比较。两轮均没有完整 secondary。

## 利用已知发送内容辅助诊断 IQ

以下结果使用用户提供的命令参数生成参考波形，并在已解码目标 primary 后约 25–40 ms 寻找对应 secondary；它们用于定位误码，**不计入独立解码成功数**。

- 在 30 个 CRC 正确的目标 primary 后，27 个时隙的 secondary 前缀相关分数不低于 0.8；其中 21 个还能从信号中读到预期头部 `47 e0`（224 B PDU payload）。这些信号峰通常在 primary 后约 30.8–31.0 ms，与板端同频调试发送相符。完整 CRC 仍全部失败。
- 对 27 个高相关候选，按当前接收机的硬判决解调后与该时隙发射端参考 PDU 比较：总误码最少 3 bit、中位数 29 bit、最多 450 bit；BLE AD 前段的误码中位数 4 bit，172 B BlueBee 区域中位数 20 bit。两个区域长度不同，不能仅用错误数量比较其每比特可靠性。有 18 个候选的接收 CRC 字节与发射端预期完全相同，但前面的数据有误码；没有候选通过重算 CRC。
- run 1002 的 `secondary_dma_late_avg_us=80116`、`max_us=80782`（100 个样本），仍是相对计划 secondary 时刻的约 80 ms 延迟，不能当作 primary-to-secondary 间隔或已校准 RF 起点。

## 判断

本轮短 primary 的恢复明显多于上一轮，但只有 30/100；长 secondary 有明确射频波形和可读头部，仍为 0/100 CRC 正确。当前首要障碍仍是实际射频信号的解调/误码，而非板端 DMA 漏提交。单次 IQ 无法区分无线损坏、板端 RF/波形失真与接收算法误码，需以同配置的 RF/增益检查和定向解调对照继续定位。

当前 primary AuxPtr 宣告 ch3 / 30 ms，板端却在 ch39 发送 secondary；即使完整 CRC 恢复，严格 AuxPtr 配对仍不成立。观测包间隔约 31 ms，也超出当前严格容差。完成 CRC 恢复前只可讨论信号定位；之后可用 `diagnostic_pairs` 检验同频模式。同步实验还须处理约 80 ms 的计划时刻偏移。
