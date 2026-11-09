# 连续时间更新与三任务共包控制：下一轮实验方案

状态：2026-11-09 制定，尚未执行。1703 与 1704 两轮 4 Msps 独立双接收均恢复了 300 个时间更新包，且预登记离线回放显示不同包训练时，短训练跨度与长期冻结的相对估计差会增大。本实验接着验证**同一连续 secondary 序列**能否穿插控制任务，两侧分别解码、去重并维持时间模型。功能验收对象为 SDR 软件原型，不是物理执行器同步；1704 尚缺板端最终统计，不能把该轮当作第三个板端已核对的可靠性重复。

## 固定计划与预期

使用现有 `b2z_plan_*` 固件，不改负载格式。新 Run ID 示例为 **1801**，周期 200 ms、共 300 个计划时隙，板端时长 60 s。每个时隙仍是一 primary 加同一共包 secondary；`command_id=0` 为纯时间更新，非零命令也携带相同 `ref_tick_ms`。任务数按 **3** 个非零 `command_id` 计，3 次重发仍是一个逻辑任务。

| 条目 | 槽号 | 包数 | 命令及计划目标 | 最晚接受时间 |
|---:|---:|---:|---|---:|
| 0 | 0–49 | 50 | 时间更新 | — |
| 1 | 50–52 | 3 | 43：两侧分别 `SET_STATE(1)`，目标 20 s | 15 s |
| 2 | 53–149 | 97 | 时间更新 | — |
| 3 | 150–152 | 3 | 44：BLE `SET_STATE(2)`、IEEE `TRIGGER(7)`，目标 40 s | 35 s |
| 4 | 153–249 | 97 | 时间更新 | — |
| 5 | 250–252 | 3 | 45：BLE `TRIGGER(9)`、IEEE `SET_STATE(3)`，目标 60 s | 55 s |
| 6 | 253–299 | 47 | 时间更新 | — |

合计 291 个纯时间更新包、9 个命令发送尝试、3 个逻辑任务。每项最晚接受时间均在本任务最后一个重发时隙之后、目标时刻之前。板端准备命令如下；先准备，再启动两个接收器，最后执行 `b2z_plan_start?`。输入每条 `b2z_plan_add?` 后核对板端回显的 `first_slot/repeats/command_id`。

```text
b2z_plan_clear?
b2z_plan_add? 0 50 0 0
b2z_plan_add? 43 3 20000 15000 1 1 1 2 1 1
b2z_plan_add? 0 97 0 0
b2z_plan_add? 44 3 40000 35000 1 1 2 2 2 7
b2z_plan_add? 0 97 0 0
b2z_plan_add? 45 3 60000 55000 1 2 9 2 1 3
b2z_plan_add? 0 47 0 0
```

## 双端采集

保持 1704 的馈线、频率、增益和设备分工。当前两台设备共用 USB 2.0 路径，暂用已观察到连续时间轴的 4 Msps；记录这项条件，不能将它视为 HackRF 通用推荐采样率。两侧先采集 80 s，确认终端显示相同的新 Run ID 后，在较晚一侧开始采集的 5 s 内启动板端。自动归档使用本地日期与 Run ID，通常不需要 `--experiment-dir`；两侧启动若跨午夜才同时显式指定同一目录。

```bash
python3 python/exadv_rx/receive.py \
  --run-id 1801 --channels 39 --sample-rate 4000000 \
  --control-target-id 1 --duration 80 --quiet
```

```bash
python3 python/zigbee_rx/control_receive.py \
  --run-id 1801 --channel 26 --sample-rate 4000000 \
  --expected-packets 300 --control-target-id 2 --duration 80 --quiet
```

```text
b2z_plan_start? 1801 200
```

将**完整**串口输出保存为本轮 `board.board.log`，包括 1 条最终 `CONTROL_PLAN_STATS`、7 条 `CONTROL_PLAN_TASK` 和 300 条 `CONTROL_PLAN_SLOT`；只提供最终一行不足以逐任务核对。保留两份 IQ 和逐包记录。接收期间不填写未经校准的 `--control-assumed-reference-bound-ms`；实时状态机拒绝定时任务是预期行为，不能把它写成解码失败。两条接收链均独立校验包内 ID、槽号、时间字段、命令和本侧参数。

## 分析顺序与成功口径

1. 检查两份摘要 `status=complete`、各处理 320,000,000 个样本，板端 `planned_slots=reached_slots=generated=primary_completed=tx_completed=300` 且无 deadline miss/DMA timeout。核对 299 个相邻包间隔、USB shortfall（设备支持时）和接收队列；时间线跳变轮只作解码功能分析，不报告时间保持误差。BLE 记录中的 300 个短 primary 不能增加控制尝试分母。
2. 从两份独立 `rx.packets.jsonl` 和完整板端日志生成逐槽、逐任务匹配：

   ```bash
   python3 python/control_match/plan_analyze.py \
     --experiment-dir python/experiments/<实际日期>_run1801 \
     --run-id 1801 --analysis-id plan_match
   ```

   检查 300 槽四象限、9 个命令尝试的同槽联合有效数、3/3 个逻辑任务是否两侧各至少独立恢复一次。同一命令的两侧可以来自**不同重发槽**。任何一侧漏收仍计入全部 3 个任务分母，不用两侧边际接收率相乘。`plan_analyze.py` 还列出实时软件状态；由于没有外部时间参考误差界，`rejected/time_quality_insufficient` 不等于共包解析失败。
3. 在保存的**各自逐包流**上分别做假设参考界的功能回放，检查命令状态机的接受、目标调度、去重和软件处理：

   ```bash
   python3 python/control_match/replay_engine.py \
     --packets python/experiments/<实际日期>_run1801/captures/ble/<采集目录>/rx.packets.jsonl \
     --side ble --run-id 1801 --target-id 1 --assumed-reference-bound-ms 1 \
     --output-dir python/experiments/<实际日期>_run1801/analyses/assumed_1ms/ble
   python3 python/control_match/replay_engine.py \
     --packets python/experiments/<实际日期>_run1801/captures/zigbee/<采集目录>/rx.packets.jsonl \
     --side zigbee --run-id 1801 --target-id 2 --assumed-reference-bound-ms 1 \
     --output-dir python/experiments/<实际日期>_run1801/analyses/assumed_1ms/zigbee
   ```

   **1 ms 是故意输入的软件功能假设，不是 1703/1704 测得的板端 RF 参考界。** 每侧最多各处理一次命令 43、44、45；预期 BLE 软件状态最终为 2，另记一次 `TRIGGER(9)`；IEEE 侧状态最终为 3，另记一次 `TRIGGER(7)`。回放输出必须标为模拟软件处理，不能把两台本地样本索引或进程墙钟相减成执行时差。

本轮建立“连续时间更新＋多命令共包”的功能证据。随后应在相同任务、截止时间和重复次数下实现并测量分别发送基线与同包立即处理基线，再做完整 exadv AuxPtr 时频跟随验证。板端实际 RF 起点、两端时钟/采集起点和执行事件未校准之前，只报告相对时间估计和软件状态，不报告物理同步执行精度。
