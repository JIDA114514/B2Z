# UC1 联合分析报告（Run 2762）

- 配置：`mode=JC`、`profile=core`、`point=B`（`b=26, z=0`）、`policy=budget`、`K=3`、`tasks=100`、`slots=610`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：44/100 (44.0%)；四类 `{'both': 44, 'ble_only': 12, 'zigbee_only': 31, 'neither': 13}`
2. **计划尝试内 (`within_planned_attempts`)**：92/100 (92.0%)；四类 `{'both': 92, 'ble_only': 1, 'zigbee_only': 7, 'neither': 0}`；异槽互补成功任务 `2`
3. **截止期分类 (`deadline_class`)**：on_time=0/100 (0.0%)，late=0/100 (0.0%)，unknown=92/100 (92.0%)，not_decoded=8/100 (8.0%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`556800 µs`；提交有效波形：`556800 µs`；DMA 完成波形：`556800 µs`；零样本 padding：`6000 µs`
- 命令尝试提交波形：`556800 µs`；纯时间更新提交波形：`0 µs`；未用预算总计：`43200 µs`（每任务 `432 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`6052.2` / `6052.2` / `6052.2` µs（分母 `92`）
- BLE 分片重组统计（C3）：`{"pending_peak": 0, "closed_peak": 0, "closed_count": 0, "pending_count": 0, "closed_exhausted": false}`

## 限制与口径

- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
