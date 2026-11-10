# N1：跨信道双端多任务执行方案

制定日期：2026-11-10。对应[下一阶段计划 N1](next_stage_plan.md)。目标是在同一轮观察 BLE 按 AuxPtr 跟随 ch39→ch3、IEEE ch12 独立解码，并核对连续时间更新与三项逻辑任务。验收对象为解析与跟随，不以未经校准的定时处理或物理动作作成功判据。

## 1. 软件接口状态（已实现）

`verify_board_exadv.py` 省略 `--command-id` 后支持纯时间更新和多个命令，`--expected-attempts` 对应全轮槽数。新采集在 `flow.events.jsonl` 保存收到的 BLE CRC 字节，并在 `flow.summary.json` 保存 UTC 起止时间；这些主机时间只用于检查录制窗口重叠，不用于同步精度。

`plan_analyze.py --ble-flow` 现可直接导入该记录，与 IEEE 原始逐包流和完整 `CONTROL_PLAN_*` 日志汇总。导入器重新校验 PDU/应用 CRC、字段、DID 和有序的 primary→secondary→follow 证据，保留原始事件行号。报告分别给出逐槽四象限、跟随数/计划数、跟随数/有效 primary 数、同槽双端有效及逐任务联合解析；不同重发槽可以共同恢复同一逻辑任务。

当前 BLE 跟随器没有 IQ、样本时间轴或控制调度事件，软件处理字段输出 `null`/未测。历史 1906 已成功复核 9 个跟随事件和缺失槽 2；其旧格式没有收到的 CRC 字节及 UTC 窗口，只保留旧验证器的 CRC 成功断言，不能作为新联合实验的完整时间窗口证据。多任务不同重发槽、缺失槽、CRC 篡改和无前置包的伪跟随事件均有测试。

本轮无需额外转换文件，必须使用更新后的接收脚本重新采集。

## 2. 固定任务清单

首轮使用新 Run ID **2001**，周期 **500 ms**，**120 槽 / 60 s**，`rf_mode=1`。时间字段以包内 epoch 为准，不是从键入串口命令起算的主机时间。相对 1801 保留三任务语义与约 10 s 执行提前量，减少纯时间更新槽以适应跨信道周期。

| 条目 | 槽号 | 次数 | 命令 | execute_at_ms / valid_until_ms |
| --- | --- | ---: | --- | --- |
| 0 | 0–19 | 20 | 纯时间更新 | 0 / 0 |
| 1 | 20–22 | 3 | 43：BLE SET_STATE(1)，IEEE SET_STATE(1) | 20000 / 15000 |
| 2 | 23–59 | 37 | 纯时间更新 | 0 / 0 |
| 3 | 60–62 | 3 | 44：BLE SET_STATE(2)，IEEE TRIGGER(7) | 40000 / 35000 |
| 4 | 63–99 | 37 | 纯时间更新 | 0 / 0 |
| 5 | 100–102 | 3 | 45：BLE TRIGGER(9)，IEEE SET_STATE(3) | 60000 / 55000 |
| 6 | 103–119 | 17 | 纯时间更新 | 0 / 0 |

合计 111 个纯时间更新槽、9 个命令尝试、3 项逻辑任务。先在串口输入准备命令，并核对各条回显：

```text
b2z_plan_clear?
b2z_plan_add? 0 20 0 0
b2z_plan_add? 43 3 20000 15000 1 1 1 2 1 1
b2z_plan_add? 0 37 0 0
b2z_plan_add? 44 3 40000 35000 1 1 2 2 2 7
b2z_plan_add? 0 37 0 0
b2z_plan_add? 45 3 60000 55000 1 2 9 2 1 3
b2z_plan_add? 0 17 0 0
```

## 3. 双接收启动指令

从仓库根目录运行 `hackrf_info`。本方案预期 BLE 跟随设备序列号末尾为 `2926a0c3`，IEEE 接收设备为 `3348a6c3`。2026-11-10 制订方案时主机未检测到设备；以下 `hackrf=0` 仅在确认索引 0 对应 BLE 设备后使用，否则替换为实际索引。

终端 A，BLE 跟随：

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2001 --expected-attempts 120 --period-ms 500 \
  --osmosdr-args hackrf=0 --sample-rate 8000000 \
  --if-gain 16 --bb-gain 10 --duration 90
```

终端 B，IEEE ch12 固定接收：

```bash
python3 python/zigbee_rx/control_receive.py \
  --run-id 2001 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --control-target-id 2 \
  --duration 90 --save-iq --quiet
```

两侧均省略 `--command-id`。BLE 使用 1906 验证过的 8 Msps；IEEE 采用已有时间轴实验使用的 4 Msps，以控制总 USB 数据量。本轮 16/10 是明确的起始增益配置，需要记录实际布线及接收质量，不预设最优。不要填写假设参考误差界来获取“通过”结果。

两接收器尽量在 10 s 内先后启动，确认均在接收后于 5 s 内从串口启动：

```text
b2z_plan_start? 2001 500 1
```

两终端均等到自然结束。日期和 Run ID 自动决定归档目录，不需要额外设置 EXP_DIR；两侧应在同一本地日期启动。示例日期为 `20261110_run2001`，实际执行日不同时替换路径。

## 4. 保存和分析

将完整串口输出保存为 `python/experiments/20261110_run2001/board.board.log`，包括 START/ENTRY、最终 STATS、7 条 TASK 及 120 条 SLOT。跟随脚本的 `--board-log` 当前只支持单任务 CONTROL_STATS，本轮不传此参数；完整计划日志交给联合分析环节。保存 BLE flow 文件、IEEE 全部 rx 文件和 IQ。若同一 Run ID 启动多次，明确每次采集与板端日志的对应关系，不混合统计。

接收结束后直接指定本轮 BLE flow 和 IEEE 包文件（尖括号替换为实际路径）：

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261110_run2001 --run-id 2001 \
  --board-log python/experiments/20261110_run2001/board.board.log \
  --ble-flow <本轮BLE分析目录下的flow.events.jsonl> \
  --zigbee-packets <本轮IEEE的rx.packets.jsonl> \
  --analysis-id n1_joint
```

不使用其他轮次或固定频点 BLE 结果代替本轮跟随记录。分析器保存输入哈希；旧 flow 缺少 UTC 录制窗口时会明确拒绝联合验收。

## 5. 首轮判定与后续动作

先核对板端 120 槽及全部 DMA 计数、两接收器正常结束、队列和 USB 告警；未完成的槽保留为失败或原因未定。DMA 完成仍只是发送代理口径。

- 逐槽分别报告 BLE 跟随和 IEEE 解码，四象限总和应为 120；命令尝试分母为 9，逻辑任务分母为 3。
- 每项任务两侧至少各有一次独立有效解析即可计入联合解析成功，允许来自不同重发槽；若另报同槽联合成功，必须按同一个 slot_index 匹配。
- 首轮功能目标是 3/3 项任务完整解析且有对应的 BLE 实际跟随证据，字段与任务清单一致；全部 120 槽的失败照常报告。跟随脚本只有 120/120 才返回完整验收通过，部分槽丢失不抹去已观察的功能证据。
- IEEE 定时任务可能因参考界缺失被拒绝，BLE 跟随侧尚无调度事件。这轮不报告同步执行成功率；两侧主机回调或独立采样索引不作执行时差。
- `auxptr_dma_window_miss` 单列为取时诊断，不能直接判为空口失败或忽略。严格 AuxPtr 空口时序仍交由 N3 评价。

若首轮三任务均解析，整理报告后进入 N2 基线实现；将主要配置的至少三轮独立重复列入后续确认。若缺失任务，先根据 primary、跟随、IEEE 和板端逐槽证据定位，再决定是否调整 RF 或接收接口。
