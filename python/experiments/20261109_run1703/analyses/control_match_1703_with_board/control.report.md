# B2Z v1 控制包匹配

- Run ID：1703；Command ID：0
- 计划时隙：300
- 同次同步录制声明：是

| 接收侧 | 控制候选 | 记录有效 | 唯一时隙 | 重复 |
|---|---:|---:|---:|---:|
| ble | 300 | 300 | 300 | 0 |
| zigbee | 300 | 300 | 300 | 0 |

- 板端只有单任务计划的最终统计，缺少 `CONTROL_PLAN_TASK`；任务命令号由两侧逐包记录交叉核对。
- ble 有效解码 / 板端 secondary DMA 完成：300/300
- zigbee 有效解码 / 板端 secondary DMA 完成：300/300

- 跨文件标识重合时隙：300
- 联合有效解码：300/300
- 同一轮纯时间更新两侧至少各恢复一次：是（可来自不同发送时隙；不代表控制任务）
- 仅 BLE / 仅 ZigBee / 两侧均缺：0 / 0 / 0

`control.slots.metrics.csv` 逐时隙列出两侧独立结果；没有同次录制声明时，标识重合不作为联合成功。

- Receiver records prove decoding, not command execution.
- Board tx_completed is a DMA-completion proxy, not measured RF airtime.
- Independent HackRF sample times have separate origins and are not subtracted.
- Same-channel diagnostic packets do not prove standards-compliant AuxPtr following.
