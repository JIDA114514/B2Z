# run 1006 ZigBee 接收诊断

原始记录：[接收报告](captures/zigbee/143027_116609_obv3m07c/rx.report.md)、同前缀的 `rx.summary.json`、`rx.packets.jsonl`、`rx.ci8`，以及[板端最终统计](board.board.log)。录制为独立 HackRF 的 ch26 / 2480 MHz、8 Msps、LNA 32 dB、VGA 20 dB、放大器关闭、30 s。采集正常结束，队列高水位 6/64；采集状态不能排除设备未报告的丢样。

## 统计结果

- 板端 `scheduled=generated=primary_started=primary_completed=tx_started=tx_completed=100`，`deadline_miss=dma_timeout=0`。这些为 DMA 提交/完成代理，未直接测量完整空口发射。
- ZigBee 软件 PHY 接收机输出 35 个 **FCS 正确**的 35 B payload。逐条解析均为新控制格式 `B2 43`、版本 1、`run_id=1006`、`command_id=43`、目标设备 2、`SET_STATE(1)`、`execute_at_ms=30000`、`valid_until_ms=25000`；内部 CRC16 **35/35 通过**，`ref_tick_ms=slot_index×200` **35/35 成立**。
- 时隙号 1–99，共 35 个不同值，无重复；计划 0–99 中未恢复 65 个，最长连续缺失为 61–72（12 个时隙）。录制范围覆盖了从首个计划时隙到最后时隙的 20 s 发送期。以板端 `tx_completed` 为代理分母，独立 ZigBee 控制记录有效恢复率为 **35/100**；这不是执行成功率，亦不能仅凭本轮归因全部 65 个缺失为无线损坏。
- 接收脚本原有 `unique=0`、`non_test=35` 是格式分类结果：`python/zigbee_rx/receive.py` 调用的 `parse_test_payload` 只接受旧性能测试 magic `B2 5A`，而本轮新控制记录以 `B2 43` 开头。故此处 `valid=0` **不表示 35 个 FCS 正确帧无效**；现有汇总中的 `wireless_prr` / goodput 不适用于新控制协议。

本轮只有 ZigBee 接收链录制；不能与其他 Run ID 的 BLE 结果合并计算联合成功率，也未测实际命令执行或跨设备同步。IEEE 802.15.4 标准 DSSS 码本与 FCS 的软件解码不等于完整商用 ZigBee 协议栈兼容。新的[控制包离线匹配报告](analyses/control_match_verified/control.report.md)已独立统计 `B2 43` 有效数，并保留旧 `B2 5A` 性能测试接收器原有的 `unique` 语义。

新增的[实时控制接收入口完整 IQ 回放](analyses/control_live_replay_v1/zigbee/rx.report.md)再次独立解出 35 个 `B2 43` 控制记录，应用 CRC16 全部通过，结合板端完整统计给出 35/100；回放用于验证新入口代码路径，不是第二轮独立无线实验。
