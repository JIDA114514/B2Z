# UC1 联合分析报告（Run 2711）

- 配置：`mode=LC`、`profile=core`、`point=A`（`b=0, z=0`）、`policy=k`、`K=4`、`tasks=10`、`slots=70`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：10/10 (100.0%)；四类 `{'both': 10, 'ble_only': 0, 'zigbee_only': 0, 'neither': 0}`
2. **计划尝试内 (`within_planned_attempts`)**：10/10 (100.0%)；四类 `{'both': 10, 'ble_only': 0, 'zigbee_only': 0, 'neither': 0}`；异槽互补成功任务 `0`
3. **截止期分类 (`deadline_class`)**：on_time=0/10 (0.0%)，late=0/10 (0.0%)，unknown=10/10 (100.0%)，not_decoded=0/10 (0.0%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`58240 µs`；提交有效波形：`58240 µs`；DMA 完成波形：`58240 µs`；零样本 padding：`800 µs`
- 命令尝试提交波形：`58240 µs`；纯时间更新提交波形：`0 µs`；未用预算总计：`1760 µs`（每任务 `176 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`5824.0` / `5824.0` / `5824.0` µs（分母 `10`）
- BLE 分片重组统计（C3）：`{"pending_peak": 0, "closed_peak": 0, "closed_count": 0, "pending_count": 0, "closed_exhausted": false}`

## 配置校正审计

- 接收端原 manifest SHA256：`f8f8fb7cf2a4a7f5c0bd1e2a30ace7a6fb98d0fabbc762e31c09a00b903c8cf9`；原策略显式 K，原预算 `5824 µs`。
- 板端记录预算 `6000 µs`，每任务未用 `176 µs`；解析与成本使用原始逐包及板端日志，不改写捕获元数据。
- 原始板端命令未独立保存，预算策略本身不能追溯为已证明。此报告标记 board_budget_reconciled，不作严格同预算确认性比较。

## 限制与口径

- Board budget reconstructed from serial log; capture manifest remains explicit-K and the original policy command is unproven. Do not treat this as a strictly matched confirmatory budget run.
- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
