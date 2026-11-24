# UC1 跨模式对比（点 B，策略 k）

| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| JC | 2748 | 1 | 86/100 (86.0%) | 86/100 (86.0%) | 185600 | 0 | 2158.1 | 3 |
| SC | 2747 | 1 | 78/100 (78.0%) | 78/100 (78.0%) | 185600 | 0 | 2379.5 | 3 |
| LC | 2746 | 1 | 36/100 (36.0%) | 36/100 (36.0%) | 290400 | 0 | 8066.7 | 39 |

## 配对差值

- **JC_vs_SC**：条件状态=match，信道混杂=False，具备协议归因条件=True，计划内解析率差=0.07999999999999996，提交波形差=0 µs，差异项=无，缺失证据=无
- **JC_vs_LC**：条件状态=match，信道混杂=True，具备协议归因条件=False，计划内解析率差=0.5，提交波形差=-104800 µs，差异项=无，缺失证据=无

- JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.
- Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.
- Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.
