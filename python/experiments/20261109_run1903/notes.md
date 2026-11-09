# Run 1901–1903：跨信道 secondary 初验

三轮均使用板端 `rf_mode=standard_secondary_ch3`、500 ms 周期、10 个时隙；板端日志各记录 `generated=primary_completed=tx_completed=10`，`deadline_miss=dma_timeout=retune_failure=0`。完整记录分别见 [1901](../20261109_run1901/report.md)、[1902](../20261109_run1902/report.md) 和本轮 [1903](report.md)。

| 轮次 | 固定接收配置 | 有效结果 | 解释 |
|---|---|---|---|
| 1901 | BLE ch3，LNA/VGA 24/20；IEEE 802.15.4 ch12 | BLE 6/10，IEEE 10/10，同槽双方 6/10 | BLE IQ 有 198757 个满量程分量；一次低截止频率离线回放只解出 5 包。 |
| 1902 | BLE ch3，LNA/VGA 16/10 | BLE 10/10，DID 0–9；满量程分量 0 | 降增益后本轮 BLE 完整解码；无同轮 IEEE 录制，不能计算联合率。 |
| 1903 | BLE ch39，LNA/VGA 16/10 | primary 10/10，DID 0–9；满量程分量 0 | AuxPtr 均为 ch3、LE 1M、300 ms（300 µs 单位）；primary 不含控制记录。 |

三轮板端均报告 `auxptr_dma_window_miss=10`。1902 的板端 primary 前 DMA 时间标记至 secondary DMA 函数返回的差值为 300961–300983 µs；1903 为 300966–300992 µs。该软件代理值超过 AuxPtr 声明的 300000–300300 µs 窗口，但 primary 标记在 DMA 调用前、secondary 标记在调用后，**不能直接等同于空口起点差**。该计数发生于 secondary DMA 已提交之后，因此与 `tx_completed=10` 不冲突。现有实现仍在目标时刻之后执行 secondary 的缓存刷新与 DMA 设置；需先把准备工作移到等待之前，并在两次提交的相同代码位置记录时间，再做空口校准。

1902 与 1903 是不同轮的固定频点录制，不能将它们的 IQ 时刻相减，也不能据此宣称严格 AuxPtr 跟随。1901 的联合值只表示两条独立软件接收链对同一时隙有效解码，不表示物理执行。当前证据支持跨信道两种 PDU 各自的正确内容与接收，尚不支持规范时间窗、商用设备跟随或同步精度结论。
