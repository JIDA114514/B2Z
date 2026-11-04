# B2Z v1 控制包匹配

- Run ID：1101；Command ID：43
- 计划时隙：100
- 同次同步录制声明：是

| 接收侧 | 控制候选 | 记录有效 | 唯一时隙 | 重复 |
|---|---:|---:|---:|---:|
| ble | 52 | 52 | 52 | 0 |
| zigbee | 74 | 74 | 74 | 0 |

- ble 有效解码 / 板端 secondary DMA 完成：52/100
- zigbee 有效解码 / 板端 secondary DMA 完成：74/100

- 跨文件标识重合时隙：52
- 联合有效解码：52/100
- 同一命令两侧至少各恢复一次：是（可来自不同重发时隙；仅表示解析）
- 仅 BLE / 仅 ZigBee / 两侧均缺：0 / 22 / 26

`control.slots.metrics.csv` 逐时隙列出两侧独立结果；没有同次录制声明时，标识重合不作为联合成功。

- Receiver records prove decoding, not command execution.
- Board tx_completed is a DMA-completion proxy, not measured RF airtime.
- Independent HackRF sample times have separate origins and are not subtracted.
- Same-channel diagnostic packets do not prove standards-compliant AuxPtr following.
