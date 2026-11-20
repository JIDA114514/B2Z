# UC1 联合分析报告（Run 2714）

- 配置：`mode=LC`、`profile=core`、`point=B`（`b=26, z=0`）、`policy=k`、`K=2`、`tasks=10`、`slots=70`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：10/10 (100.0%)；四类 `{'both': 10, 'ble_only': 0, 'zigbee_only': 0, 'neither': 0}`
2. **计划尝试内 (`within_planned_attempts`)**：10/10 (100.0%)；四类 `{'both': 10, 'ble_only': 0, 'zigbee_only': 0, 'neither': 0}`；异槽互补成功任务 `0`
3. **截止期分类 (`deadline_class`)**：on_time=0/10 (0.0%)，late=0/10 (0.0%)，unknown=10/10 (100.0%)，not_decoded=0/10 (0.0%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`58080 µs`；提交有效波形：`58080 µs`；DMA 完成波形：`58080 µs`；零样本 padding：`1200 µs`
- 命令尝试提交波形：`58080 µs`；纯时间更新提交波形：`0 µs`；未用预算总计：`1920 µs`（每任务 `192 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`5808.0` / `5808.0` / `5808.0` µs（分母 `10`）
- BLE 分片重组统计（C3）：`{"fragments": 100, "c3_fragments": 100, "pending_peak": 1, "closed_peak": 20, "complete": 20, "closed_count": 20, "pending_count": 0, "closed_exhausted": false}`

## 配置校正审计

- 接收端原 manifest SHA256：`af98914faa2b1f5c132b985279b76c879a76db3806f7646ebbbba1d750a4df23`；原策略显式 K，原预算 `5808 µs`。
- 板端记录预算 `6000 µs`，每任务未用 `192 µs`；解析与成本使用原始逐包及板端日志，不改写捕获元数据。
- 原始板端命令未独立保存，预算策略本身不能追溯为已证明。此报告标记 board_budget_reconciled，不作严格同预算确认性比较。

## 限制与口径

- Board budget reconstructed from serial log; capture manifest remains explicit-K and the original policy command is unproven. Do not treat this as a strictly matched confirmatory budget run.
- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
