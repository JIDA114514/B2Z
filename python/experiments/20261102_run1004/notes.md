# 接收增益 A–B–A 实验复查（2026-11-02）

对照记录：[run 1003](../20261102_run1003/report.md)、[run 1004](report.md)、[run 1005](../20261102_run1005/report.md)。三轮板端[统计](board.board.log)及相邻实验目录中的 `board.board.log` 均为 `command_id=43`、`period_ms=200`、`attempts=100`，各有 `scheduled=generated=primary_started=primary_completed=tx_started=tx_completed=100`、`deadline_miss=dma_timeout=0`。DMA 完成是发送链代理，不是实际空口发射逐包证明。

| 轮次 | HackRF LNA/VGA | IQ 时长 | 目标 primary CRC 正确 | 完整 secondary BLE CRC 正确 | 同频诊断配对 |
|---|---:|---:|---:|---:|---:|
| A / 1003 | 24/20 dB | 40 s | 13/100 | 0/100 | 0/100 |
| B / 1004 | 32/20 dB | 30 s | 88/100 | 28/100 | 25/100 |
| A / 1005 | 24/20 dB | 30 s | 31/100 | 0/100 | 0/100 |

计数依据为各轮 `rx.packets.jsonl` 中的目标格式 primary、224 B secondary 和 `rx.events.jsonl`；总 BLE 有效包含环境广播，不用作本任务分子。三轮采集窗口均覆盖计划发送期。1003 在有效录制前还有一次 `HackRF not found` 的 0 s 失败启动，该文件未纳入表格。各轮采集正常结束，队列高水位分别为 13、10、7，未见软件队列溢出。

run 1004 的 28 个 secondary 均在 BLE CRC 正确的前提下满足以下校验：厂商数据内控制记录的 `run_id=1004`、`command_id=43`、`slot_index=ADI DID`；35 B 记录自身 CRC16 通过；完整 226 B PDU 与按板端命令参数生成的参考 PDU 逐字节一致。这验证了 **BLE 接收链的完整共包恢复**，不等于 IEEE 802.15.4 接收链已经独立解码。28 个 secondary 中有 25 个找到同一 DID、CRC 正确的 primary；另 3 个（DID 3、4、68）缺少 CRC 正确的目标 primary。

25 个同频诊断对的 secondary 相对宣告 30 ms 的偏差为 924.5–952.0 µs，中位数 943.5 µs。板端仍在 ch39 同频发送，而 primary AuxPtr 宣告 ch3；因此严格 `matched_events=0` 是预期结果，25 个 `diagnostic_pairs` 不能写成规范 exadv 跟随。三轮 `secondary_dma_late_avg_us` 分别为 80149、80157、80181 µs，约 80 ms 计划时刻偏移没有因接收增益而消失。

结论：在这次交替顺序实验中，LNA 从 24 dB 提至 32 dB 与目标 primary、完整 secondary 恢复的明显提升同时出现，恢复率尚未稳定：高增益轮 primary 为 88/100，secondary 为 28/100。两次基线从 13/100 变到 31/100，说明环境或设备状态也有波动。当前证据支持继续做增益和接收链质量扫描，不能据此直接宣称已达到可靠控制，更不能报告 ZigBee 侧或同步执行成功。
