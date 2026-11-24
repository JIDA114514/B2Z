# UC1 跨模式对比（点 B，策略 k）

| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| JC | 2765 | 1 | 80/100 (80.0%) | 80/100 (80.0%) | 185600 | 0 | 2320.0 | 3 |
| SC | 2766 | 1 | 63/100 (63.0%) | 63/100 (63.0%) | 185600 | 0 | 2946.0 | 3 |
| LC | 2761 | 1 | 7/100 (7.0%) | 7/100 (7.0%) | 290400 | 0 | 41485.7 | 39 |

## 配对差值

- **JC_vs_SC**：条件状态=match，信道混杂=False，具备协议归因条件=True，计划内解析率差=0.17000000000000004，提交波形差=0 µs，差异项=无，缺失证据=无
- **JC_vs_LC**：条件状态=match，信道混杂=True，具备协议归因条件=False，计划内解析率差=0.73，提交波形差=-104800 µs，差异项=无，缺失证据=无

- JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.
- Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.
- Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.
