# Run 2717 现场记录

- **目的**：P2-H5 时间参考支撑初验（B 点 `b=26, z=0`，JC，`time` profile，`K=3`，300 slots，IEEE 单侧断开失更与恢复）。
- **物理拓扑**：馈线直连（`R0`）。
- **板端发射设置**：标称发射功率 `0 dBm`（无功率计实测），板端衰减参数 `tx_attenuation=10000`（mdB）。
- **人工干预**：110包至160包之间断开Zigbee侧馈线连接。
- **现场异常**：未观测到异常（无告警不代表已证明 USB 零丢样）。
- **关联记录**：[`uc1_2717.json`](../../control_match/configs/uc1_2717.json)、[board.board.log](board.board.log)、[uc1.report.md](analyses/uc1_p2_review/uc1.report.md)、[uc1.report.md (tail audit)](analyses/uc1_time_tail_audit/uc1.report.md)（设备参数、包数与成本以此为准）。
- **记录日期**：2026-11-20。
