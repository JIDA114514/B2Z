# UC1 跨模式对比（点 B，策略 budget）

| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| JC | 2762 | 3 | 44/100 (44.0%) | 92/100 (92.0%) | 556800 | 43200 | 6052.2 | 3 |
| SC | 2763 | 3 | 70/100 (70.0%) | 99/100 (99.0%) | 556800 | 43200 | 5624.2 | 3 |
| LC | 2764 | 2 | 9/100 (9.0%) | 17/100 (17.0%) | 580800 | 19200 | 34164.7 | 39 |

## 配对差值

- **JC_vs_SC**：条件状态=match，信道混杂=False，具备协议归因条件=True，计划内解析率差=-0.06999999999999995，提交波形差=0 µs，差异项=无，缺失证据=无
- **JC_vs_LC**：条件状态=match，信道混杂=True，具备协议归因条件=False，计划内解析率差=0.75，提交波形差=-24000 µs，差异项=无，缺失证据=无

- JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.
- Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.
- Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.
