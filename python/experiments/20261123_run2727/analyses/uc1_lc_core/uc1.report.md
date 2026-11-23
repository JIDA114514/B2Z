# UC1 联合分析报告（Run 2727）

- 配置：`mode=LC`、`profile=core`、`point=B`（`b=26, z=0`）、`policy=k`、`K=1`、`tasks=30`、`slots=190`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：4/30 (13.3%)；四类 `{'both': 4, 'ble_only': 8, 'zigbee_only': 9, 'neither': 9}`
2. **计划尝试内 (`within_planned_attempts`)**：4/30 (13.3%)；四类 `{'both': 4, 'ble_only': 8, 'zigbee_only': 9, 'neither': 9}`；异槽互补成功任务 `0`
3. **截止期分类 (`deadline_class`)**：on_time=0/30 (0.0%)，late=0/30 (0.0%)，unknown=4/30 (13.3%)，not_decoded=26/30 (86.7%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`87120 µs`；提交有效波形：`87120 µs`；DMA 完成波形：`87120 µs`；零样本 padding：`1800 µs`
- 命令尝试提交波形：`87120 µs`；纯时间更新提交波形：`0 µs`；未用预算总计：`0 µs`（每任务 `0 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`21780.0` / `21780.0` / `21780.0` µs（分母 `4`）
- BLE 分片重组统计（C3）：`{"fragments": 121, "c3_fragments": 121, "pending_peak": 1, "closed_peak": 30, "complete": 12, "timeout": 18, "closed_count": 30, "pending_count": 0, "closed_exhausted": false}`

## 限制与口径

- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
