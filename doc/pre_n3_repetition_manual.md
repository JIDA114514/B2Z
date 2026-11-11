# N3 前已完成实验的必要重复：实验操作手册

版本：2026-11-11  
适用范围：`doc/next_stage_plan.md` 中 **N3 之前**的 N1、N2 已完成实验的必要重复。  
不包含：N3-A/N3-B（2201/2203）、N4、N5、绝对同步/硬件校准、商用设备、多节点、执行器。

> 本手册只回答一件事：**哪些已完成的 N3 前实验必须补重复，以及每一轮怎么用现有串口命令和脚本再跑一遍。**  
> 不在本手册内的实验，不要顺手加进来；尤其不要执行 `2201`、`2203`，也不要把 N3 的取时/同步评价混入本轮。

---

## 0. 结论：需要重复的实验

### 0.1 重复矩阵

| 组别 | 已完成 | 现有轮数 | 需补 | 新增 Run ID | 目的 |
| --- | --- | ---: | ---: | --- | --- |
| N1 跨信道双端多任务 | 2001 | 1 | 2 | **2002、2003** | 主配置凑满 3 轮；交替 BLE/IEEE 启动顺序 |
| N2 共包固定频点 | 2101 | 1 | 2 | **2104、2108** | 共包基线凑满 3 轮 |
| N2 分别发送固定频点 | 2102 | 1 | 2 | **2105、2107** | 分别发送基线凑满 3 轮；与共包配对 |
| N2 BLE-only 实际跟随 | 2103 | 1 | 2 | **2106、2109** | 跟随配置凑满 3 轮 |

**配对关系：**

| 轮次 | 共包 | 分别发送 | BLE-only 跟随 | 启动顺序 |
| --- | --- | --- | --- | --- |
| 第 1 轮（已完成） | 2101 | 2102 | 2103 | 共包 → 分别 → 跟随 |
| 第 2 轮 | 2104 | 2105 | 2106 | 共包 → 分别 → 跟随 |
| 第 3 轮 | 2108 | 2107 | 2109 | **分别 → 共包** → 跟随 |

第 3 轮把“分别发送”放在“共包”之前，用于交替 A/B 顺序，避免顺序偏置。

### 0.2 为什么是这些，不是全部

- **N1 2001**：已完成 3/3 任务、93/120 BLE 跟随；只有一轮，按计划 §4“主要配置至少三轮”补 2 轮。
- **N2 2101/2102/2103**：N2 首轮功能与成本初验已完成；按 N2 方案 §6“最终主要配置至少三轮独立重复，交替 A/B 顺序”补 2 轮。
- **1703–1705**：已有 3 轮同频时间保持，**本轮不重复**。
- **1801、1901–1906、1201–1203、1601/1701**：属于前期功能/诊断轮，已被 2001/2101–2103 取代，**本轮不重复**。
- **2001、2101、2102、2103**：保留为第 1 轮，**不要用同一 Run ID 重跑**；新轮必须用 2002/2003、2104–2109。
- **N3 及以后**：不在本手册范围。

---

## 1. 共同前置条件

### 1.1 硬件与接线

- 发送端：Zynq-7020 / AD9363（现有板端），已上板。
- BLE 接收：HackRF One，序列号末尾 **`2926a0c3`**。
- IEEE 接收：HackRF One，序列号末尾 **`3348a6c3`**。
- 馈线/衰减/分路：保持 1703–1705、2001、2101–2103 的接线与衰减不变；本轮不要换线、换口、换增益。
- 主机：两块 HackRF 尽量分属不同 USB 控制器；至少不要经过多级 hub。

先核对设备：

```bash
hackrf_info
```

BLE 跟随用 `--osmosdr-args hackrf=000000000000000017c467dc2926a0c3` **按序列号选设备，不要用 `hackrf=0`**。osmosdr 的 hackrf source 在 `hackrf=<serial>` 长度大于 1 时按序列号后缀匹配，因此 BLE 跟随和 IEEE 的 `--serial 000000000000000017c467dc3348a6c3` 会锁定两台不同设备，不会同时打开同一台。不要省略 `--osmosdr-args`：`verify_board_exadv.py` 的默认值是 `hackrf=0`，省略就会退回索引选择。先运行 `hackrf_info` 核对两个序列号都在；如果序列号不同，不要开跑。

### 1.2 磁盘与采样率

| 轮次 | BLE | IEEE | 90 s IQ 约占用 |
| --- | --- | --- | ---: |
| N1 2002/2003 | 跟随，8 Msps，不存 IQ | 固定 ch12，4 Msps，存 IQ | 约 0.72 GB |
| N2 2104/2108 | 固定 ch3，4 Msps，存 IQ | 固定 ch12，4 Msps，存 IQ | 约 1.44 GB |
| N2 2105/2107 | 固定 ch3，4 Msps，存 IQ | 固定 ch12，4 Msps，存 IQ | 约 1.44 GB |
| N2 2106/2109 | 跟随，8 Msps，不存 IQ | 固定 ch12，4 Msps，存 IQ | 约 0.72 GB |

开跑前至少留 5 GB 空闲；不要把 IQ 写进 Git。

### 1.3 固件与脚本

- N1 2002/2003、N2 2104/2108 使用 `rf_mode=1`（共包）。
- N2 2105/2107/2106/2109 使用 `rf_mode=2`（分别发送）。
- `rf_mode=2` 需要 N2 已实现并上板的固件；如果当前板端不是这版固件，先构建/上板，**不要在本轮改源码**。
- 记录本轮实际 ELF/源码版本或哈希；不要在论文里用主机 Git HEAD 代替固件版本。
- 所有命令从仓库根目录执行（即包含 `python/`、`app_FreeRTOS/` 的那一层）。
- 以下命令按 bash（Git Bash/WSL）书写；PowerShell 下把 `$(date +%Y%m%d)` 换成实际日期，把 `python3` 换成你的 Python 入口（`python`/`py`）。

### 1.4 串口日志

打开现有板端串口终端（端口和波特率沿用当前上板调试配置）。每轮必须保存**完整**串口输出：

```text
CONTROL_PLAN_START / ENTRY
CONTROL_PLAN_STATS
7 条 CONTROL_PLAN_TASK
120 条 CONTROL_PLAN_SLOT
模式 1 的 240 条 / 模式 2 的 360 条 CONTROL_BURST
CONTROL_COST_STATS
```

保存为：

```text
python/experiments/YYYYMMDD_run<run_id>/board.board.log
```

不要在 `CONTROL_PLAN_STATS` 出现时就停止保存；`CONTROL_BURST`/`CONTROL_COST_STATS` 可能在 RF 调度结束后才输出。

---

## 2. 通用板端任务清单（N1/N2 共用）

每一轮开始前，在串口依次输入：

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

核对每条 `CONTROL_PLAN_ADD` 回显的：

- `entry`、`first_slot`、`repeats`
- `command_id`（43/44/45）
- `execute_at_ms` / `valid_until_ms`
- 两侧 `target` / `opcode` / `arg`

任务语义：

| 槽 | 内容 |
| ---: | --- |
| 0–19 | 20 个纯时间更新 |
| 20–22 | 命令 43，3 次重发 |
| 23–59 | 37 个纯时间更新 |
| 60–62 | 命令 44，3 次重发 |
| 63–99 | 37 个纯时间更新 |
| 100–102 | 命令 45，3 次重发 |
| 103–119 | 17 个纯时间更新 |

合计 120 槽、111 个时间更新、9 个命令尝试、3 个逻辑任务。

启动命令：

```text
b2z_plan_start? <run_id> 500 <rf_mode>
```

- N1：`rf_mode=1`
- N2 共包（2104/2108）：`rf_mode=1`
- N2 分别发送/跟随（2105/2107/2106/2109）：`rf_mode=2`

---

## 3. N1 重复：2002、2003

### 3.1 2002（BLE 先启动）

**终端 A：BLE 实际跟随**

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2002 --expected-attempts 120 --period-ms 500 \
  --osmosdr-args hackrf=000000000000000017c467dc2926a0c3 --sample-rate 8000000 \
  --if-gain 16 --bb-gain 10 --duration 90
```

**终端 B：IEEE 固定 ch12**

```bash
python3 python/zigbee_rx/control_receive.py \
  --run-id 2002 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --control-target-id 2 \
  --duration 90 --save-iq --quiet
```

**串口启动**

```text
b2z_plan_start? 2002 500 1
```

顺序：先 BLE 终端 A，约 5–10 s 内起 IEEE 终端 B；确认两侧都在采集后，5 s 内输入板端启动命令。

### 3.2 2003（IEEE 先启动，交替顺序）

命令与 2002 相同，只把 `--run-id 2002` 改为 `--run-id 2003`，串口改为：

```text
b2z_plan_start? 2003 500 1
```

顺序：先 IEEE 终端 B，再 BLE 终端 A；用于交替启动顺序，检查是否影响跟随/解码。

### 3.3 N1 分析

先确认 2003 的 flow 确实是 2003、完整、未中断：

```bash
RUN=2003
EXP=python/experiments/$(date +%Y%m%d)_run${RUN}

python3 - "$EXP" <<'PY'
import glob, json, os, sys
exp = sys.argv[1]
for p in sorted(glob.glob(f"{exp}/analyses/*/flow.summary.json")):
    s = json.load(open(p))
    print(os.path.dirname(p))
    print({k: s.get(k) for k in ("run_id", "status", "mode", "interrupted", "verification_passed")})
PY
```

`plan_analyze.py` 的 `load_flow` 要求：`schema=board_std_ble_flow_v1`、`mode=live_hop`、`run_id=2003`、`status=complete`、`interrupted=false`。任何一项不满足都会报：

```text
ValueError: flow must be a complete same-run live hop capture
```

最常见的两个原因：

1. **`run_id` 仍是 2002**：BLE 跟随命令只改了板端 `b2z_plan_start? 2003`，忘了改 `--run-id 2003`。这不是分析脚本能修的；2003 的板端/IEEE 记录没有对应的 BLE flow。归档为无效，换新 Run ID 重跑两侧 + 板端（例如 2010），不要把 2002 的 flow 指给 2003。
2. **`interrupted=true`**：BLE 跟随被 Ctrl-C 或提前结束。重跑并让 `duration 90` 自然结束；不要手改 summary。

确认 flow 后，用**显式路径**，不要用 `analyses/*` 通配（目录里可能同时有旧 flow）：

```bash
FLOW="$EXP/analyses/<正确flow目录>/flow.events.jsonl"
ZIGBEE_PACKETS="$EXP/captures/zigbee/<正确采集目录>/rx.packets.jsonl"

python3 python/control_match/plan_analyze.py \
  --experiment-dir "$EXP" --run-id "$RUN" \
  --board-log "$EXP/board.board.log" \
  --ble-flow "$FLOW" \
  --zigbee-packets "$ZIGBEE_PACKETS" \
  --analysis-id n1_joint
```

2002 同样先检查；`EXP` 的日期必须是**实验当天**，不是分析当天；跨午夜、隔天分析或手动指定了 `EXP_DIR` 时，按实际目录替换 `EXP`。

输出检查：

- BLE 跟随数 / 120、跟随数 / 有效 primary 数
- IEEE 有效 / 120
- 同槽联合 / 120
- 3/3 任务、9/9 命令尝试
- 四象限：双方、仅 BLE、仅 IEEE、双方均缺
- `auxptr_dma_window_miss` 单列，不当作 follow 失败的根因

---

## 4. N2 重复：2104–2109

### 4.1 第 2 轮：2104 共包 → 2105 分别发送 → 2106 跟随

#### 2104：共包，两侧固定频点

**BLE（固定 ch3）**

```bash
python3 python/exadv_rx/receive.py --run-id 2104 --channels 3 \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --duration 90 --save-iq --quiet
```

**IEEE（固定 ch12）**

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2104 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

**串口**

```text
b2z_plan_start? 2104 500 1
```

#### 2105：分别发送，两侧固定频点

**BLE（固定 ch3，separate 布局）**

```bash
python3 python/exadv_rx/receive.py --run-id 2105 --channels 3 --control-layout separate \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --duration 90 --save-iq --quiet
```

**IEEE（固定 ch12，separate 布局）**

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2105 --channel 12 --control-layout separate \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

**串口**

```text
b2z_plan_start? 2105 500 2
```

#### 2106：BLE-only 实际跟随

**BLE 跟随（8 Msps，不存 IQ）**

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2106 --expected-attempts 120 --period-ms 500 --payload-mode ble-only \
  --osmosdr-args hackrf=000000000000000017c467dc2926a0c3 --sample-rate 8000000 \
  --if-gain 16 --bb-gain 10 --duration 90
```

**IEEE（固定 ch12，separate 布局）**

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2106 --channel 12 --control-layout separate \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

**串口**

```text
b2z_plan_start? 2106 500 2
```

### 4.2 第 3 轮：2107 分别发送 → 2108 共包 → 2109 跟随

这一轮把“分别发送”放在“共包”之前，用于交替 A/B 顺序。

#### 2107：分别发送（同 2105，换 Run ID）

BLE：

```bash
python3 python/exadv_rx/receive.py --run-id 2107 --channels 3 --control-layout separate \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --duration 90 --save-iq --quiet
```

IEEE：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2107 --channel 12 --control-layout separate \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

串口：

```text
b2z_plan_start? 2107 500 2
```

#### 2108：共包（同 2104，换 Run ID）

BLE：

```bash
python3 python/exadv_rx/receive.py --run-id 2108 --channels 3 \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --duration 90 --save-iq --quiet
```

IEEE：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2108 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

串口：

```text
b2z_plan_start? 2108 500 1
```

#### 2109：BLE-only 跟随（同 2106，换 Run ID）

BLE：

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2109 --expected-attempts 120 --period-ms 500 --payload-mode ble-only \
  --osmosdr-args hackrf=000000000000000017c467dc2926a0c3 --sample-rate 8000000 \
  --if-gain 16 --bb-gain 10 --duration 90
```

IEEE：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2109 --channel 12 --control-layout separate \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --expected-packets 120 --duration 90 --save-iq --quiet
```

串口：

```text
b2z_plan_start? 2109 500 2
```

---

## 5. N2 分析与跨轮比较

### 5.1 固定频点共包（2104/2108）

```bash
RUN=2104
EXP=python/experiments/$(date +%Y%m%d)_run${RUN}

python3 python/control_match/plan_analyze.py \
  --experiment-dir "$EXP" --run-id "$RUN" --analysis-id n2_joint
```

### 5.2 固定频点分别发送（2105/2107）

```bash
RUN=2105
EXP=python/experiments/$(date +%Y%m%d)_run${RUN}

python3 python/control_match/plan_analyze.py \
  --experiment-dir "$EXP" --run-id "$RUN" --analysis-id n2_separate
```

### 5.3 BLE-only 跟随（2106/2109）

`--ble-flow` 同样必须是 `mode=live_hop`、`run_id` 匹配、`status=complete`、`interrupted=false` 的 flow；先按 §3.3 的方法列出 `flow.summary.json`，再用显式路径：

```bash
RUN=2106
EXP=python/experiments/$(date +%Y%m%d)_run${RUN}
FLOW="$EXP/analyses/<正确flow目录>/flow.events.jsonl"
ZIGBEE_PACKETS="$EXP/captures/zigbee/<正确采集目录>/rx.packets.jsonl"

python3 python/control_match/plan_analyze.py \
  --experiment-dir "$EXP" --run-id "$RUN" \
  --ble-flow "$FLOW" \
  --zigbee-packets "$ZIGBEE_PACKETS" \
  --analysis-id n2_separate_follow
```

`EXP` 同样用**实验当天**日期；隔天分析请手动写死目录，不要用 `date +%Y%m%d` 当天日期去猜。

### 5.4 跨轮比较

先建立条件文件（按实际填写，不能把 TODO 当实测）：

```json
{
  "joint": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"},
  "separate": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"}
}
```

保存为 `python/experiments/n2.conditions.json`，然后：

```bash
# 第 2 轮
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/<日期>_run2104/analyses/n2_joint/plan.summary.json \
  --separate-summary python/experiments/<日期>_run2105/analyses/n2_separate/plan.summary.json \
  --conditions python/experiments/n2.conditions.json \
  --output-dir python/experiments/n2_comparison_2104_2105

# 第 3 轮
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/<日期>_run2108/analyses/n2_joint/plan.summary.json \
  --separate-summary python/experiments/<日期>_run2107/analyses/n2_separate/plan.summary.json \
  --conditions python/experiments/n2.conditions.json \
  --output-dir python/experiments/n2_comparison_2107_2108

# 第 1 轮（已有，补进三轮回看）
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/<日期>_run2101/analyses/n2_joint/plan.summary.json \
  --separate-summary python/experiments/<日期>_run2102/analyses/n2_separate/plan.summary.json \
  --conditions python/experiments/n2.conditions.json \
  --output-dir python/experiments/n2_comparison_2101_2102
```

### 5.5 同输入 B/C 回放（可选）

只对同一份 2104 的接收记录回放，不增加物理轮次：

```bash
RUN=2104
EXP=python/experiments/$(date +%Y%m%d)_run${RUN}

python3 python/control_match/replay_engine.py \
  --packets "$EXP"/captures/ble/*/rx.packets.jsonl \
  --side ble --run-id "$RUN" --target-id 1 --policy immediate \
  --output-dir "$EXP/analyses/n2_immediate_ble"

python3 python/control_match/replay_engine.py \
  --packets "$EXP"/captures/ble/*/rx.packets.jsonl \
  --side ble --run-id "$RUN" --target-id 1 --policy scheduled \
  --output-dir "$EXP/analyses/n2_scheduled_ble"
```

IEEE 用 `--side zigbee --target-id 2`，输出目录改为 `n2_immediate_ieee` / `n2_scheduled_ieee`。不要填写假设参考误差界来“制造通过”；`scheduled` 被拒绝是当前能力边界，不是同步收益结论。

---

## 6. 每轮记录清单

每轮结束后，确认以下文件存在并归档：

| 文件 | 内容 |
|---|---|
| `board.board.log` | START/ENTRY、STATS、7 TASK、120 SLOT、240/360 BURST、COST_STATS |
| `captures/ble/.../rx.summary.json` | BLE 摘要（固定频点轮） |
| `captures/ble/.../rx.packets.jsonl` | BLE 逐包记录 |
| `captures/ble/.../*.ci8` | 固定频点轮的 IQ（N1/跟随轮不存） |
| `captures/zigbee/.../rx.summary.json` | IEEE 摘要 |
| `captures/zigbee/.../rx.packets.jsonl` | IEEE 逐包记录 |
| `captures/zigbee/.../*.ci8` | IEEE IQ |
| `analyses/.../flow.events.jsonl` | 跟随轮的 flow 事件（N1/2106/2109） |
| `analyses/.../plan.report.md` | 联合报告 |
| `analyses/.../plan.summary.json` | 机器摘要 |
| `analyses/.../plan.slots.metrics.csv` | 逐槽四象限 |
| `analyses/.../plan.tasks.metrics.csv` | 逐任务 |
| `analyses/.../plan.bursts.csv` | N2 成本/突发清单（若脚本生成） |
| `notes.md` | 日期、Run ID、设备序列号、增益、接线/衰减、启动顺序、异常 |

同时在 `notes.md` 记录：

- 实际串口启动行；
- 实际 BLE `--osmosdr-args`（应为 `hackrf=000000000000000017c467dc2926a0c3`，不是索引）；
- 是否更换馈线/衰减/增益；
- 两侧接收进程的起止时间；
- 任何 USB shortfall、队列溢出、时间轴跳变。

---

## 7. 验收口径

### 7.1 板端

每轮必须满足或如实记录：

```text
planned_slots = reached_slots = generated =
primary_completed = tx_completed = 120
deadline_miss = 0
dma_timeout = 0
```

- **mode 1（2002/2003、2104/2108）**：`tx_completed` 是共包 secondary 的 DMA 完成代理。
- **mode 2（2105/2107/2106/2109）**：`tx_completed` 只代表 BLE secondary 的 DMA 完成；IEEE 独立 BlueBee 突发的完成数看 `CONTROL_BURST` 与 `CONTROL_COST_STATS`，不能把 `tx_completed` 当成两次发射的总数。
- `auxptr_dma_window_miss` 单列记录，不用它直接判 follow 失败；mode 1 与 mode 2 的窗口/延迟不可直接跨模式比较（2102 mode 2 曾为 0，2001 mode 1 为 120/120）。
- `tx_completed` 是 DMA 完成代理，不是实测 RF 发射。

### 7.2 N1

- 3/3 任务两侧独立解析；
- BLE 跟随数 / 120、跟随数 / 有效 primary 数；
- IEEE 有效 / 120；
- 同槽联合 / 120；
- 四象限完整（双方、仅 BLE、仅 IEEE、均缺）；
- 9/9 命令尝试、去重正确；
- 失败槽保留在分母，不只报成功子集。

### 7.3 N2

- 共包/分别发送各 3/3 任务、两侧 120/120（或如实记录缺失）；
- `CONTROL_BURST`/`CONTROL_COST_STATS` 完整；成本按成功提交的整段波形核算，失败提交另计；
- 共包与分别发送的有效波形总时长按预算相等时，只能写“减少突发/提交次数”，不能写“空口时长减少三分之一”或“能耗下降”；
- 跟随轮 3/3 任务，跟随数/120、跟随数/有效 primary 数，与固定频点轮分开报，不平均。

### 7.4 统计

- 所有比率给分子/分母，零分母写 `N/A`；
- 逐轮报告，不把 3 轮直接混成一个独立样本；
- 置信区间用按时间/槽分块的 bootstrap，不把 120 个连续槽当独立样本；
- 失败、缺失、原因未定分开。

---

## 8. 失败处理

| 情况 | 处理 |
|---|---|
| BLE 跟随仍用 `hackrf=0` | 改为 `--osmosdr-args hackrf=000000000000000017c467dc2926a0c3`；不要用索引，避免和 IEEE 的 `--serial` 抢同一台设备 |
| 一侧接收为 0 | 检查天线/馈线/衰减/序列号/增益；不要用同一 Run ID 重跑 |
| Run ID 填错 | 保留原始记录，标为无效；换新 Run ID 重跑，不覆盖 |
| 时间轴跳变 >1 ms | 标为采集异常；N1/N2 功能结果可保留，时间相关结论剔除该轮 |
| 缺 `CONTROL_BURST`/`COST_STATS` | N2 成本记为未测；不要用 `tx_completed` 推算 |
| 模式 2 未上板 | 停止；先构建/上板，再重跑 |
| 跨午夜/目录不一致 | 在 `notes.md` 写明实际目录；分析时用实际 `EXP`，不要按日期猜 |

---

## 9. 明确不做

- **不执行 N3-A/N3-B**（2201/2203），不做板端取时、跨信道时间保持、holdover 残差归因；
- **不执行 N4/N5**（容量扫描、legacy 对照、机制消融、真实漏收）；
- **不做绝对同步/硬件校准**：无示波器、共享时钟、硬件触发、GPIO 标定；
- **不测商用设备、执行器、多节点**；
- **不重复 1703–1705**（已有 3 轮）、**不重复 1801/1901–1906/1201–1203**（前期诊断）；
- **不把离线回放当新增物理轮次**，不把同一 IQ 的多次分析算作重复实验。

---

## 10. 一页执行顺序

```text
[ ] 1. hackrf_info 核对两个序列号；BLE 跟随用 `hackrf=<BLE serial>`，IEEE 用 `--serial`
[ ] 2. 确认接线/衰减/增益与上一轮一致；记录
[ ] 3. 确认板端固件含 rf_mode=1/2；记录版本
[ ] 4. 2002：任务清单 → BLE 先起 → IEEE → b2z_plan_start? 2002 500 1
[ ] 5. 2003：任务清单 → IEEE 先起 → BLE → b2z_plan_start? 2003 500 1
[ ] 6. 2104：任务清单 → BLE ch3 + IEEE ch12 → b2z_plan_start? 2104 500 1
[ ] 7. 2105：任务清单 → BLE ch3 + IEEE ch12（separate）→ b2z_plan_start? 2105 500 2
[ ] 8. 2106：任务清单 → BLE 跟随 + IEEE ch12（separate）→ b2z_plan_start? 2106 500 2
[ ] 9. 2107：分别发送（同 2105）→ b2z_plan_start? 2107 500 2
[ ]10. 2108：共包（同 2104）→ b2z_plan_start? 2108 500 1
[ ]11. 2109：跟随（同 2106）→ b2z_plan_start? 2109 500 2
[ ]12. 每轮保存完整 board.board.log、IQ、逐包、分析 CSV/JSON
[ ]13. 跑 plan_analyze.py；N2 跑 compare_n2.py
[ ]14. 在 notes.md 记录异常与条件；确认没有把 N3 实验混入
```

---

## 附录 A：Run ID 速查

| Run ID | 组别 | 模式 | 接收配置 | 状态 |
|---:|---|---|---|---|
| 2001 | N1 第 1 轮 | 1 | BLE 跟随 + IEEE ch12 | 已完成，保留 |
| **2002** | N1 第 2 轮 | 1 | BLE 跟随 + IEEE ch12 | **本手册** |
| **2003** | N1 第 3 轮 | 1 | BLE 跟随 + IEEE ch12（IEEE 先启） | **本手册** |
| 2101 | N2 共包第 1 轮 | 1 | BLE ch3 + IEEE ch12 | 已完成，保留 |
| 2102 | N2 分别第 1 轮 | 2 | BLE ch3 + IEEE ch12 | 已完成，保留 |
| 2103 | N2 跟随第 1 轮 | 2 | BLE 跟随 + IEEE ch12 | 已完成，保留 |
| **2104** | N2 共包第 2 轮 | 1 | BLE ch3 + IEEE ch12 | **本手册** |
| **2105** | N2 分别第 2 轮 | 2 | BLE ch3 + IEEE ch12 | **本手册** |
| **2106** | N2 跟随第 2 轮 | 2 | BLE 跟随 + IEEE ch12 | **本手册** |
| **2107** | N2 分别第 3 轮 | 2 | BLE ch3 + IEEE ch12 | **本手册** |
| **2108** | N2 共包第 3 轮 | 1 | BLE ch3 + IEEE ch12 | **本手册** |
| **2109** | N2 跟随第 3 轮 | 2 | BLE 跟随 + IEEE ch12 | **本手册** |

## 附录 B：关键命令来源

- N1 任务清单与接收命令：`doc/n1_cross_channel_experiment_plan.md`
- N2 任务清单、2101/2102/2103 命令、分析与比较：`doc/n2_separate_transmission_experiment_plan.md`
- 任务格式与字节预算：`doc/control_sync_packet_v1_draft.md`
- 当前阶段边界：`doc/next_stage_plan.md`

---

**最后提醒**：本手册只补齐 N1/N2 的重复轮次；完成后应得到 N1 3 轮、N2 共包/分别/跟随各 3 轮。N3 的 2201/2203、N4 的容量、N5 的漏收消融都不在本手册内，不要在同一轮里混做。
