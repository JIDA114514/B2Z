# Run 1703：双接收端时间保持实验

实际板端负载标识为 `run_id=1703`、`command_id=0`、槽号 0–299。BLE 接收器配置为 1703；ZigBee 接收器启动命令误设为 1702，因此其原始文件由自动归档放在 `20261109_run1702/captures/zigbee/110914_154091_btxesy84/`，实时摘要把 300 个有效控制包记为 `foreign_run`。包内标识、FCS、应用校验及逐槽字段均表明这些是 1703 的包。保留原始记录和错误配置，不改写它们。

- [BLE 原始摘要](captures/ble/110916_399121_8lvkyj6j/rx.summary.json)
- [ZigBee 原始摘要](../20261109_run1702/captures/zigbee/110914_154091_btxesy84/rx.summary.json)
- [板端最终统计](board.board.log)：由用户在对话中提供并原样保存；不是从串口终端导出的完整日志，缺少 `CONTROL_PLAN_TASK/SLOT` 行。
- [按包内 1703 匹配并合并板端统计的报告](analyses/control_match_1703_with_board/control.report.md)
- [ZigBee 控制引擎离线重放摘要](analyses/zigbee_control_replay_corrected/control.summary.json)：`decoded=300`、`clock_updated=300`；此轮全是时间更新，`accepted=0` 是预期结果。
- [预登记时间保持分析](analyses/holdover_preregistered_v2/report.md)
- [IQ 校验清单](captures/iq.manifest.json)

板端最终统计为 `planned_slots=reached_slots=generated=primary_completed=tx_completed=300`，`deadline_miss=dma_timeout=0`。两侧各 300/300、联合 300/300 可按板端 DMA 完成的代理口径报告；DMA 完成不直接测得实际空口发射。完整逐槽串口日志、馈线连接细节、实际发射时刻及采样短缺的独立计数仍未保存。
