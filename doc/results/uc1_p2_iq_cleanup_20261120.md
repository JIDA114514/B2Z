# UC1 P2 IQ 清理记录（2026-11-20）

清理前先完成当前 UC1 轮次联合分析。以下 20 个完整 IQ 在删除前均核对有板端日志、接收逐包 JSON/summary 和对应分析报告。旧 N4 为历史成本/容量对照，UC1 四轮为已完成 H2 中非同 IQ 布局、非 C3 关键留样的分支。只删除列出的 `rx.ci8`；接收原始逐包、日志、配置及报告保留。

## 已删除文件

- `python/experiments/20261113_run2411/captures/zigbee/113909_980568_vc2o7nv7/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2411/captures/ble/113908_416091__u90updm/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2412/captures/zigbee/114231_046844_5bybxie3/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2412/captures/ble/114229_589143_xihavn95/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2413/captures/zigbee/114502_795469_f28g8f2f/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2413/captures/ble/114500_961255_xd_9r0ph/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2414/captures/zigbee/114805_255269_mr3e66s1/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2414/captures/ble/114803_313700_1znoma7s/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2415/captures/zigbee/115031_787384_uhk0l36u/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2415/captures/ble/115029_930457_w6x9g70s/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2416/captures/zigbee/115300_703415_0qre402u/rx.ci8` — 560,000,000 B
- `python/experiments/20261113_run2416/captures/ble/115258_732857_bag2h045/rx.ci8` — 560,000,000 B
- `python/experiments/20261119_run2702/captures/zigbee/155500_625391_af4v7v67/rx.ci8` — 480,000,000 B
- `python/experiments/20261119_run2702/captures/ble/155502_411584_nrn66s3y/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2703/captures/zigbee/102650_148222_yqgydluc/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2703/captures/ble/102651_840497_d9s6549l/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2705/captures/zigbee/103201_619803_05uh9grw/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2705/captures/ble/103203_040356_qva99q2g/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2708/captures/zigbee/103752_528736_mje2iwil/rx.ci8` — 480,000,000 B
- `python/experiments/20261120_run2708/captures/ble/103753_867790_605l_lb2/rx.ci8` — 480,000,000 B

合计释放：10,560,000,000 B（10.56 GB）。

保留 UC1 2704/2707/2718 用于 A/C/B 同 IQ 布局复核；2706/2709 用于 C3，2710 用于直接 legacy 边界，2701 与 2711–2714 用于预算/重发核查，2715–2717 用于时间更新、失更和回放。2701–2718 的其他录制也未在本次清理。

注意：2411–2416 已不能从全长 IQ 重新解调；仍可使用已保存的逐包记录及分析审计历史结论。清理后的文件缺失是有意操作，不应计为采集失败。
