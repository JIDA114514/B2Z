# Run 2728 现场记录

- **目的**：prepare_uc1 2728 P3 2 B L1。
- **物理拓扑**：固定天线布局 `2`（TX-BLE `0.1 m`，TX-IEEE `0.1 m`，朝向 `统一规格胶棒天线`）。
- **设备绑定**：BLE HackRF `000000000000000017c467dc2926a0c3`，IEEE HackRF `000000000000000017c467dc3348a6c3`。
- **板端发射设置**：标称发射功率 `0 dBm`（无功率计实测），板端衰减参数 `tx_attenuation=10000`（mdB）。
- **人工干预**：无。
- **现场异常**：未观测到异常（无告警不代表已证明 USB 零丢样）。
- **关联记录**：[`uc1_2728.json`](../../control_match/configs/uc1_2728.json)、[board.board.log](board.board.log)、[uc1.report.md](analyses/uc1_lc_core/uc1.report.md)（设备参数、包数与成本以此为准）。
- **记录日期**：2026-11-23。
