# UC1 跨模式对比（点 B，策略 budget）

| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| JC | 2740 | 3 | 72/100 (72.0%) | 99/100 (99.0%) | 556800 | 43200 | 5624.2 | 3 |
| SC | 2741 | 3 | 70/100 (70.0%) | 99/100 (99.0%) | 556800 | 43200 | 5624.2 | 3 |
| LC | 2742 | 2 | 47/100 (47.0%) | 76/100 (76.0%) | 580800 | 19200 | 7642.1 | 39 |

## 配对差值

- **JC_vs_SC**：条件状态=match，信道混杂=False，具备协议归因条件=True，计划内解析率差=0.0，提交波形差=0 µs，差异项=无，缺失证据=无
- **JC_vs_LC**：条件状态=match，信道混杂=True，具备协议归因条件=False，计划内解析率差=0.22999999999999998，提交波形差=-24000 µs，差异项=无，缺失证据=无

- JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.
- Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.
- Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.
