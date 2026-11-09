# Run 1701 归档说明

- 用户说明本轮将原先的无线连接改为馈线连接；未提供馈线、分路或衰减器的详细配置。本轮不能用于独立空口传播可靠性结论。
- 目录沿用 `20261104_run1701`；两条实时接收摘要的实际开始时间为 2026-11-09 02:33 UTC（上海时间 10:33）。以摘要时间为准。
- BLE 实时接收按 `run_id=1701` 启动；ZigBee 实时接收误用 `--run-id 1601`，因此其报告中的 `unique=0`、`foreign_control=9` 是轮次筛选结果，不是 PHY 失败。原始 ZigBee 包记录均带 `run_id=1701`，PHY FCS 与控制记录校验均通过。保留原实时输出，不改写原始记录。
- 使用同一份 ZigBee 原始 IQ 以 `run_id=1701` 完整离线回放，结果在 [`analyses/corrected_run_id/zigbee/`](analyses/corrected_run_id/zigbee/)。此回放仅修正软件筛选口径，不增加一个独立接收端或一次新无线实验。
- 对比结论和证据边界见[馈线试验评估](analyses/feedline_review/report.md)。本轮未保存板端最终 `CONTROL_PLAN_STATS`，不能从接收数量推定板端 DMA 完成率或 RF 发射率。
