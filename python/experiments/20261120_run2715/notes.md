# Run 2715 现场记录

- **目的**：P2-H5 时间参考支撑初验（B 点 `b=26, z=0`，JC，`time` profile，`K=3`，300 slots 无干预基线；另含 H6 离线故障注入回放）。
- **物理拓扑**：馈线稳定直连（`R0`）。
- **板端发射设置**：标称发射功率 `0 dBm`（无功率计实测），板端衰减参数 `tx_attenuation=10000`（mdB）。
- **人工干预**：无。
- **现场异常**：未观测到异常（无告警不代表已证明 USB 零丢样）。
- **关联记录**：[`uc1_2715.json`](../../control_match/configs/uc1_2715.json)、[board.board.log](board.board.log)、[uc1.report.md](analyses/uc1_p2_review/uc1.report.md)、[uc1.report.md (tail audit)](analyses/uc1_time_tail_audit/uc1.report.md)、[h6.report.md (v2)](analyses/h6_fault_injection_replay_v2/h6.report.md)（设备参数、包数与成本以此为准）。
- **记录日期**：2026-11-20。
