# UC1 联合分析报告（Run 2743）

- 配置：`mode=LC`、`profile=core`、`point=B`（`b=26, z=0`）、`policy=budget`、`K=2`、`tasks=100`、`slots=610`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：0/100 (0.0%)；四类 `{'both': 0, 'ble_only': 0, 'zigbee_only': 89, 'neither': 11}`
2. **计划尝试内 (`within_planned_attempts`)**：0/100 (0.0%)；四类 `{'both': 0, 'ble_only': 0, 'zigbee_only': 98, 'neither': 2}`；异槽互补成功任务 `0`
3. **截止期分类 (`deadline_class`)**：on_time=0/100 (0.0%)，late=0/100 (0.0%)，unknown=0/100 (0.0%)，not_decoded=100/100 (100.0%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`580800 µs`；提交有效波形：`580800 µs`；DMA 完成波形：`580800 µs`；零样本 padding：`12000 µs`
- 命令尝试提交波形：`580800 µs`；纯时间更新提交波形：`0 µs`；未用预算总计：`19200 µs`（每任务 `192 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`N/A` / `N/A` / `N/A` µs（分母 `0`）
- BLE 分片重组统计（C3）：`{"fragments": 210, "c3_fragments": 210, "pending_peak": 2, "closed_peak": 115, "timeout": 115, "closed_count": 115, "pending_count": 0, "closed_exhausted": false}`

## 限制与口径

- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
