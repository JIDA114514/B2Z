# Run 1601 归档说明

- 目录名沿用了实验时指定的 `20261104_run1601`；两条实时采集的摘要显示实际开始于 2026-11-05 02:18 UTC（上海时间 10:18）。以接收摘要内的 UTC 时刻为准，不据目录日期推断采集时间。
- 两条**实时独立接收**均正常结束并录制 30 s。实验索引的 `interrupted` 来自早期 `analyses/same_iq/zigbee/` 的一次手动中止回放；随后 `same_iq_assumed_1ms` 已完整回放 30 s。这不表示实时采集被中断。
- [板端记录](board.board.log)由用户在对话中提供的最终 `CONTROL_PLAN_STATS/TASK/SLOT` 行整理；缺少串口终端直接保存的完整原始日志和启动时 `CONTROL_PLAN_START/ENTRY` 行。报告明确按此证据范围解释板端发送。
- 两份 `captures/*/rx.ci8` 各 480 MB，本机保留，按实验目录规则不提交 Git；大小和 SHA-256 记录在 [IQ 清单](captures/iq.manifest.json)。完整 `.packets.jsonl` 亦留在本机；提交的 `*.packets.sample.jsonl` 为从独立解码记录逐行摘出的本轮目标包，不借用另一侧负载重构。
- 结论、逐时隙和逐任务统计见[评估报告](analyses/multi_task_review_1601/report.md)与[结构化摘要](analyses/multi_task_review_1601/plan.summary.json)。报告中的同 IQ 双解码与两块 HackRF 独立接收分别标注，不将未经校准的 1 ms 假设当作测得的同步精度。
