# UC1 跨模式对比（点 A，策略 k）

| 模式 | Run | K | 首次联合解析 | 计划内联合解析 | 提交有效波形 µs | 未用预算 µs | µs/成功任务 | BLE 信道 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| JC | 2731 | 1 | 63/100 (63.0%) | 63/100 (63.0%) | 164800 | 0 | 2615.9 | 3 |
| SC | 2732 | 1 | 66/100 (66.0%) | 66/100 (66.0%) | 164800 | 0 | 2497.0 | 3 |
| LC | 2733 | 1 | 51/100 (51.0%) | 51/100 (51.0%) | 145600 | 0 | 2854.9 | 39 |

## 配对差值

- **JC_vs_SC**：条件状态=match，信道混杂=False，具备协议归因条件=True，计划内解析率差=-0.030000000000000027，提交波形差=0 µs，差异项=无，缺失证据=无
- **JC_vs_LC**：条件状态=match，信道混杂=True，具备协议归因条件=False，计划内解析率差=0.12，提交波形差=19200 µs，差异项=无，缺失证据=无

- JC/SC BLE runs on ch3 (2410 MHz) while LC BLE runs on ch39 (2480 MHz); JC vs LC reliability differences include RF channel effects.
- Submitted waveform length is a design/DMA proxy, not measured RF occupancy or energy.
- Single rounds do not establish statistical significance; use >=3 alternating blocks for confirmatory claims.
