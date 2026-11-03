# B2Z v1 控制包匹配

`analyze.py` 离线读取现有 BLE / ZigBee 接收器保存的逐包 JSONL。它对每侧独立解析 `B2 43` v1 的 35 B 控制记录、校验应用 CRC16 和时间/命令字段；同一时隙的重复包只计一次。既有 `B2 5A` 性能测试协议仍由原接收器统计，本脚本不修改旧 `unique` 口径。

若需要在采集期间立即看到 ZigBee 侧的控制字段和去重状态，使用 [`zigbee_rx/control_receive.py`](../zigbee_rx/README.md#b2-43-控制包实时分析)；本脚本用于接收结束后的单侧复核与双侧匹配。

只分析 ZigBee 的 run 1006：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261103_run1006 \
  --run-id 1006 --command-id 43
```

只分析 BLE 的 run 1004：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261102_run1004 \
  --run-id 1004 --command-id 43
```

脚本自动选取实验目录中唯一的正常结束接收记录；若同侧存在多份正常结束录制，使用 `--ble-packets`、`--zigbee-packets` 明确指定。若实验目录下有 `board.board.log`，自动合并同一 Run ID、Command ID 的一条最终 `CONTROL_STATS`，提供计划时隙和 DMA 完成分母。

未来两块 HackRF **同时录制同一轮发送**时，将两个接收结果放在同一个实验目录，并显式使用 `--same-transmission`：

```bash
python3 python/control_match/analyze.py \
  --experiment-dir python/experiments/20261103_run1100 \
  --run-id 1100 --command-id 43 --same-transmission
```

该选项要求两份接收摘要的录制墙钟区间有交集。脚本按 `(run_id, command_id, slot_index)` 计算同一物理尝试的两侧有效解码，同时报告同一命令是否分别被两侧至少恢复一次；后者允许来自不同的重发时隙。若未声明同次录制，脚本只报告标识重合，不报告联合有效解码。不能将不同 Run ID 的历史单侧实验合并。

结果写入实验目录下新建的 `analyses/control_match_<UTC 时间>/`，包含 `control.report.md`、`control.summary.json` 和 `control.slots.metrics.csv`。`sample_start` 只作为各接收机自己的 IQ 索引保存，不直接相减测同步精度。完整恢复和匹配表示软件解码成功，不表示命令已被执行，也不表示规范 AuxPtr 跟随或商用 ZigBee 协议栈兼容。
