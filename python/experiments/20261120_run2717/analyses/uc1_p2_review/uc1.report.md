# UC1 联合分析报告（Run 2717）

- 配置：`mode=JC`、`profile=time`、`point=B`（`b=26, z=0`）、`policy=k`、`K=3`、`tasks=6`、`slots=300`
- 采集证据：`overlapping_live_capture_intervals`；时间轴异常：`{"ble": [], "zigbee": []}`

## 三层联合解析结果（分母为计划任务数，保留全部失败与缺失）

1. **首次尝试 (`first_attempt`)**：5/6 (83.3%)；四类 `{'both': 5, 'ble_only': 1, 'zigbee_only': 0, 'neither': 0}`
2. **计划尝试内 (`within_planned_attempts`)**：5/6 (83.3%)；四类 `{'both': 5, 'ble_only': 1, 'zigbee_only': 0, 'neither': 0}`；异槽互补成功任务 `0`
3. **截止期分类 (`deadline_class`)**：on_time=0/6 (0.0%)，late=0/6 (0.0%)，unknown=5/6 (83.3%)，not_decoded=1/6 (16.7%)
   - 审计说明：Uncalibrated independent HackRF IQ timelines cannot certify RF deadline compliance; decoded tasks without calibrated external reference bounds remain classified as unknown.

## 波形成本代理与预算（非实测 RF 时长）

- 计划波形预算：`556800 µs`；提交有效波形：`556800 µs`；DMA 完成波形：`556800 µs`；零样本 padding：`6000 µs`
- 命令尝试提交波形：`33408 µs`；纯时间更新提交波形：`523392 µs`；未用预算总计：`0 µs`（每任务 `0 µs`）
- 单位联合解析任务成本（提交 / 计划 / 完成代理）：`111360.0` / `111360.0` / `111360.0` µs（分母 `5`）
- BLE 分片重组统计（C3）：`{"pending_peak": 0, "closed_peak": 0, "closed_count": 0, "pending_count": 0, "closed_exhausted": false}`

## 时间参考支撑（固定 secondary JC）

- 布局标记位置差：`608 µs`（配置布局值，非 RF 测量校准）
- `ble`：探测覆盖 24/24 (100.0%)；恢复 0/1 (0.0%)；残差绝对值中位/P95/P99/最大 = 0.22199851189926267/0.3173376488100737/0.35022330356940623/0.35942261904478073 ms（n=24）
- `zigbee`：探测覆盖 19/24 (79.2%)；恢复 1/2 (50.0%)；残差绝对值中位/P95/P99/最大 = 0.13438541666418313/0.33570729167461394/0.34109979166030885/0.3424479166567326 ms（n=19）

## 限制与口径

- Waveform budgets and DMA completions are transmit proxies, not measured RF airtime or energy.
- Independent BLE/IEEE HackRF IQ origins are uncalibrated; decoded tasks without a calibrated reference bound are marked deadline=unknown.
- Software processing events are not physical actuator execution.
- LC BLE ch39 (2480 MHz) differs in RF frequency from JC/SC BLE ch3 (2410 MHz); reliability differences cannot be attributed solely to packet format.
