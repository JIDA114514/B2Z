# Run 1704：时间更新复测

两条独立 HackRF 接收链均以 4 Msps 采集 80 s，实时程序配置与包内标识均为 `run_id=1704`。各自完成 PHY 与应用校验，恢复 `command_id=0` 的 0–299 槽，每侧 `decoded=clock_updated=300`。该轮没有非零控制命令，软件动作计数为零符合设计。

- [双侧逐槽匹配](analyses/control_match_1704/control.report.md)：共同有效 300 槽；暂缺板端最终统计，发送分母为 N/A。
- [1704 时间保持回放](analyses/holdover_preregistered_v1/report.md)：固定 168 个验证槽，比较训练包数与更新策略。
- [两份 IQ 哈希](captures/iq.manifest.json)：大文件留本机。

目前目录中没有 `CONTROL_PLAN_STATS` 或完整板端串口日志，也没有本轮配对的 USB shortfall 计数；不能据此计算相对于板端 DMA 完成的 PRR 或校准绝对空口时间。
