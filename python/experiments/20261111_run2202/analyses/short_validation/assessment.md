# 2202：30 槽缓存前移短验证

本轮是修改后的短轮验证，不按原 N3 矩阵中 2202 的预定用途解释。

板端 planned/generated/primary_completed/tx_completed 均为 30，deadline_miss=0、dma_timeout=0、retune_failure=0。auxptr_dma_window_miss=0/30（2201 为 300/300）。CONTROL_TIME_META 标记 secondary_cache=before_aux_wait；30 槽取时完整、overflow=0，缓存先于 secondary call 的顺序检查通过。

|软件取时，µs|中位数|P95|最大|
|---|---:|---:|---:|
|secondary cache_flush|977.992|983.294|985.023|
|secondary call 耗时|6.288|6.425|6.432|
|pre_submit 相对软件目标|8.410|8.682|8.877|
|post_return 相对软件目标|9.186|9.502|9.648|

刷新成本仍约 1 ms，但已移出目标附近的提交调用。2201 的 pre_submit 中位数约 983.871 µs，本轮降至 8.410 µs。软件窗口修正的短轮验证通过；这些值不等于 RF 发射误差。primary 与 secondary 同位置 submit 间隔中位数约 299909.277 µs：当前目标仍绑定 primary 调用前锚点，不能据此宣称实际 AuxPtr 空口间隔合规。

BLE 有效 30/30，IEEE 有效 29/30；逐槽联合记录 29/30。IEEE 唯一缺失 slot=29。IEEE 只录制 20 s，slot=0 在本地 IQ 的 5.838886 s，slot=28 在 19.837868 s；按 500 ms 周期推算 slot=29 约在 20.337868 s，已超出记录末尾。故此缺失符合观察窗截断，不应计为已证明的无线丢包。BLE 完整观测到了 slot=29。两侧设备序列号不同，4 Msps、增益 16/10、无削顶和已报告队列溢出。

可以进入新 run_id 的 300 槽复测，无需因为本轮末包截断继续修改板端。沿用预登记 n3_2201.json、500 ms 周期和两侧各 180 s 的录制，确保发送在较早启动的接收机开始后 20 s 内开始，给 150 s 发包及结束阶段留余量。保留本轮 29/30 的原始计数及观察窗限制，不修改为 30/30。正式复测后仍需实际跟随诊断；本轮未测绝对同步精度与物理执行。

结构化取时与逐槽数据见 timing.json、plan.slots.metrics.csv 和 plan.summary.json。
