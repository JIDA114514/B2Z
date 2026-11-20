# UC1 实机采集与分析操作手册（SOP）

日期：2026-11-19。配套文档：[UC1 论文主线实验执行计划](uc1_paper_experiment_plan.md)、[UC1 板端接口](../reference/uc1_board_interface.md)、[UC1 协议规范](../reference/unified_compact_protocol_proposal.md)。

本手册给出当前已实现 CLI（`uc1_config.py`、`exadv_rx/receive.py`、`zigbee_rx/control_receive.py`、`uc1_analyze.py`）与板端命令（`b2z_uc1_start?`）的完整实机执行流程。表内编号仅用于说明参数组合；2701、2702 已用于 B 点 JC 和 A 点 SC，不能按表重跑或把它们合成 A 点配对比较。每个待做组合分配新的 run_id，先核对生成器的占用检查、任务语义和 RF 条件，记录“组合→实际 run_id→分析路径”映射。

---

## 1. 采集前准备（只需确认一次）

1. **板端固件构建与上板**：
   - 使用已同步到 `hdl/projects/antsdre310/antsdre310.sdk/app/src/app/` 的源码完成编译、烧录与上电。
   - 记录本次**实际烧录固件**的构建标识、源码版本与板端发射衰减设置（馈线直连此前使用 `tx_attenuation = 10000 mdB`，本轮须核对实际值），写入每轮 manifest 与 `notes.md`。构建标签本身不能证明板上二进制与源码一致。
   - **推荐接收增益基线**（基于历史 2401–2416、2509–2520、2601–2602 实测结果）：
     - 馈线直连（`R0`）：`--sample-rate 4000000 --lna 16 --vga 10`（关闭 `--amp`；历史 21 轮均 `clipped_components=0` 且满收）
     - 无线天线（`R1`）：起步 `--sample-rate 4000000 --lna 16 --vga 16`（关闭 `--amp`）
2. **核对双 HackRF 在线状态**（在仓库根目录 `/home/jida/Desktop/antsdr/B2Z` 执行）：
   ```bash
   hackrf_info
   ```
   核对两块默认序列号均已识别：
   - BLE 默认：`000000000000000017c467dc2926a0c3`
   - IEEE 802.15.4 默认：`000000000000000017c467dc3348a6c3`
3. **核对 UC1 设计波形成本表（dry-run）**：
   ```bash
   python3 python/control_match/uc1_config.py --dry-run-table
   ```

---

## 2. 单轮实验标准操作流程（6 步 SOP，所有轮次通用）

下面直接以 **H2 的 A 点 JC（`b=0, z=0`、10 任务、`K=1`，以下以当前未占用的 `run_id=2718` 为示例）** 为例；其他轮次按第 3 节表格替换参数，每轮先查占用并使用新的 `run_id`；开始前核对生成器导出的板端与两个接收端命令。

### 步骤 1：生成本轮冻结 manifest（可选导出命令文件）

```bash
python3 python/control_match/uc1_config.py \
  --run-id 2718 --mode JC --profile core \
  --ble-extra 26 --ieee-extra 0 --tasks 10 \
  --policy k --value 1 \
  --phase P2 --stage verification --rf-condition R0 \
  --sample-rate 4000000 --lna 16 --vga 10 --save-iq \
  --firmware-build "<本次实际烧录固件标识>" \
  --output python/control_match/configs/uc1_2718.json
```

> 建议同时导出 `--board-commands python/control_match/configs/uc1_2718.board.txt` 和 `--host-commands python/control_match/configs/uc1_2718.host.sh`，逐项核对该轮的模式、信道、布局、K、时长与保存 IQ 策略。2718 也只在生成器确认为未占用时使用。

### 步骤 2：开启板端串口日志录制

- 开启串口终端的文本记录功能（或事后完整复制本轮输出）。
- 日志必须完整包含：发送的 `b2z_uc1_start?` 命令回显、`CONTROL_PLAN_START`、`UC1_CONFIG`、`CONTROL_PLAN_ENTRY`、`CONTROL_PLAN_STATS final=1`、`UC1_STATS`、`CONTROL_PLAN_TASK`、`COMPACT_SLOT`、`CONTROL_PLAN_SLOT`、`UC1_BURST`、`UC1_COST_STATS` 及结束行（`CONTROL_TIME_END` 或 `COMPACT_TIME_END`）。

### 步骤 3：先在两个终端同时启动 BLE 与 IEEE 802.15.4 接收端

> **强制顺序**：必须**先启动两个接收端**，确认两终端均打印启动横幅并开始收流后，再向板端串口发命令。

- **终端 1（BLE 接收端；JC/SC 用 `--channels 3`，LC 用 `--channels 39`）**：
  ```bash
  python3 python/exadv_rx/receive.py --run-id 2718 \
    --uc1-config python/control_match/configs/uc1_2718.json \
    --channels 3 --control-layout joint \
    --sample-rate 4000000 --lna 16 --vga 10 \
    --duration 60 --save-iq
  ```
- **终端 2（IEEE 802.15.4 接收端；三模式均固定 `--channel 12`）**：
  ```bash
  python3 python/zigbee_rx/control_receive.py --run-id 2718 \
    --uc1-config python/control_match/configs/uc1_2718.json \
    --channel 12 --control-layout joint \
    --sample-rate 4000000 --lna 16 --vga 10 \
    --duration 60 --save-iq
  ```

两个接收端会自动按主机本地日期归档至：
- `python/experiments/<YYYYMMDD>_run2718/captures/ble/<timestamp>/rx.*`
- `python/experiments/<YYYYMMDD>_run2718/captures/zigbee/<timestamp>/rx.*`

### 步骤 4：在板端串口发送发射命令

在串口终端发送**单条**命令（切勿连续粘贴多条命令抢占忙状态）：

```text
b2z_uc1_start? 2718 500 10 0 0 1 0 1 0
```

- 运行中如需查看进度，可发送 `bluebee_perf_status?`；如需中止，发送 `bluebee_perf_stop?`。
- 10 任务（70 槽）约 **35 s** 后板端自动结束并输出全部 `final=1` 统计；两个接收端在 **60 s** 后自动正常结束（`status=complete`）。

### 步骤 5：保存板端日志并填写 `notes.md`

1. 将本轮完整串口日志保存至：
   ```text
   python/experiments/<YYYYMMDD>_run2718/board.board.log
   ```
2. 在同一目录创建 `notes.md`，**只记日志里无法自动获取的现场信息**（配置参数、接收增益、包数与成本均以 JSON/日志为准，不必手抄）：
   ```markdown
   # Run <RUN_ID> 现场记录

   - **目的**：<阶段-项，如 P2-H2 A点 JC K=1>
   - **物理拓扑**：<馈线直连（R0） / 固定天线（R1：距离、朝向、环境）>
   - **板端发射衰减**：<如 10000 mdB（无功率计实测）>
   - **人工干预**：<无 / time profile 单侧遮挡方式与大致起止时间>
   - **现场异常**：<未观测到异常（无告警不代表已证明 USB 零丢样） / 如实记录异常>
   - **关联记录**：[`uc1_<RUN_ID>.json`](../../control_match/configs/uc1_<RUN_ID>.json)、[board.board.log](board.board.log)、[uc1.report.md](analyses/<ANALYSIS_ID>/uc1.report.md)。
   - **记录日期**：<YYYY-MM-DD>。
   ```

### 步骤 6：运行单轮联合分析与跨模式对比

- **单轮联合分析**（输出至新目录 `analyses/uc1_jc_core`，不覆盖既有分析）：
  ```bash
  python3 python/control_match/uc1_analyze.py \
    --experiment-dir python/experiments/<YYYYMMDD>_run2718 \
    --config python/control_match/configs/uc1_2718.json \
    --analysis-id uc1_jc_core
  ```
  查看 `python/experiments/<YYYYMMDD>_run2718/analyses/uc1_jc_core/uc1.report.md`，核对：
  - `first_attempt`、`within_planned_attempts`、`deadline_class`（无校准参考界应为 `unknown`）
  - `submitted_waveform_us`、`unused_budget_total_us`、`per_joint_decoded_task`（零成功应为 `N/A`）
  - `ble_fragment_reassembly`（含 `pending_peak`、`closed_peak`、`pending_overflow`、`closed_capacity_exhausted`）
- **同点三模式（JC / SC / LC）完成后运行跨模式对比**：以下占位符须替换为实际 run 与日期；不可将 2701(B/预算) 和 2702(A/K=1) 配对。先核对三轮的任务内容、b/z、策略、预算、接收增益和物理条件；用 `--conditions` 提供同条件的现场记录，否则比较器会保留“缺证据/不可归因”。
  条件文件为 JSON，至少包含 `JC`、`SC`、`LC` 三组，各组填 `topology`、`tx_power`、`firmware_build`、`attenuation` 的**实际记录值**；不得用占位文本或推测值补齐。三轮同点、同策略与接收配置也须由分析器检查。LC 的 BLE 信道差异仍阻止单独归因于封装格式。
  ```bash
  python3 python/control_match/uc1_analyze.py \
    --compare-jc python/experiments/<YYYYMMDD>_run<A_JC_RUN>/analyses/uc1_jc_core/uc1.summary.json \
    --compare-sc python/experiments/<YYYYMMDD>_run<A_SC_RUN>/analyses/uc1_sc_core/uc1.summary.json \
    --compare-lc python/experiments/<YYYYMMDD>_run<A_LC_RUN>/analyses/uc1_lc_core/uc1.summary.json \
    --conditions python/control_match/configs/<A_K1_CONDITIONS>.json \
    --output-dir python/experiments/<YYYYMMDD>_run<A_JC_RUN>/analyses/compare_a_k1
  ```

---

## 3. P2 桥接初验（H1–H6）逐项执行清单

### H1：实录同 IQ 布局标记差验证（核对 `400 + 8b µs`）

在完成 H2 的 A 点（`b=0`）与 B 点（`b=26`）JC 录制后，直接取该轮 BLE 接收端保存的 `rx.ci8`（2410 MHz），离线送入 IEEE 接收端解码，验证实录同 IQ 上 BLE 与 IEEE 前导码位置差：

```bash
python3 python/zigbee_rx/control_receive.py --run-id <JC_RUN> \
  --uc1-config python/control_match/configs/uc1_<JC_RUN>.json \
  --iq-file python/experiments/<YYYYMMDD>_run<JC_RUN>/captures/ble/<TIMESTAMP_DIR>/rx.ci8 \
  --format ci8 --sample-rate 4000000 --channel 12 --control-layout joint \
  --duration 0 --analysis-id h1_same_iq_ieee
```

> 该命令只生成同 IQ 的 IEEE 解码结果。另取**同一个 BLE IQ 文件**对应的 BLE `rx.packets.jsonl`，按 `(run_id, slot_index)` 匹配两侧各自 CRC 正确的记录，以两侧 `sample_start / sample_rate` 计算位置差；先核对解码器 `sample_start` 的起点定义及固定延迟，再检验 `400+8b µs` 的符号、残差与分布。不能把配置里的 `marker_offset_us` 直接当测量值。A/B/C 三布局生成 IQ 的独立解码也须完成并保存输出；此实录同 IQ 对照不作为独立双接收端证据。

### H2：稳定链路 9 组 `K=1` 短配置（A/B/C × JC/SC/LC）

每轮 10 任务、70 槽、板端 35 s、接收 60 s。建议先逐一用 `uc1_config.py` 生成对应 manifest 和 `.host.sh` 后按表执行：

| 示例 Run | 点 (`b,z`) | 模式 | 板端命令（逐轮发送） | BLE `--channels` & `--control-layout` | ZigBee `--control-layout` |
| ---: | --- | --- | --- | --- | --- |
| （2701作为测试实验已有参数）2704 | A (`0,0`) | JC | `b2z_uc1_start? 2704 500 10 0 0 1 0 1 0` | `--channels 3 --control-layout joint` | `joint` |
| 已完成 2702 | A (`0,0`) | SC | 已采集；重采时用新编号 | `--channels 3 --control-layout separate` | `separate` |
| 2703 | A (`0,0`) | LC | `b2z_uc1_start? 2703 500 10 0 0 3 0 1 0` | `--channels 39 --control-layout separate` | `separate` |
| （2701 已完成预算 K=3 的另组初验）2718 | B (`26,0`) | JC | `b2z_uc1_start? 2718 500 10 26 0 1 0 1 0` | `--channels 3 --control-layout joint` | `joint` |
| 2705 | B (`26,0`) | SC | `b2z_uc1_start? 2705 500 10 26 0 2 0 1 0` | `--channels 3 --control-layout separate` | `separate` |
| 2706 | B (`26,0`) | LC | `b2z_uc1_start? 2706 500 10 26 0 3 0 1 0` | `--channels 39 --control-layout separate` | `separate` |
| 2707 | C (`2,6`) | JC | `b2z_uc1_start? 2707 500 10 2 6 1 0 1 0` | `--channels 3 --control-layout joint` | `joint` |
| 2708 | C (`2,6`) | SC | `b2z_uc1_start? 2708 500 10 2 6 2 0 1 0` | `--channels 3 --control-layout separate` | `separate` |
| 2709 | C (`2,6`) | LC | `b2z_uc1_start? 2709 500 10 2 6 3 0 1 0` | `--channels 39 --control-layout separate` | `separate` |

### H3：LC `b=1, z=0` 直接 Legacy 27 B 边界初验

- 生成 manifest：`--run-id 2710 --mode LC --profile core --ble-extra 1 --ieee-extra 0 --tasks 10 --policy k --value 1`
- 板端命令：
  ```text
  b2z_uc1_start? 2710 500 10 1 0 3 0 1 0
  ```
- 接收参数：BLE `--channels 39 --control-layout separate --duration 60`；ZigBee `--channel 12 --control-layout separate --duration 60`。
- 验收核对：`uc1.summary.json` 中 `ble_fragment_reassembly` 不应出现 C3 分片（`c3_fragments` 为 0 或缺失），10 条 27 B 记录直接单帧恢复。

### H4：4 组重发与同预算短配置（`Q=6000 µs`）

后续新采集的 manifest **必须**使用 `--policy budget --value 6000` 生成，不能只按表中的期望 K 使用 `--policy k`；生成后核对 `policy=budget`、`budget_us=6000`、`unused_per_task_us`，并以导出的 `.board.txt` 为板端命令来源。2026-11-20 已采集的 2711–2714 使用显式 K manifest、板端却记录 6000 µs 预算；原记录保留，显式 `--reconcile-board-budget` 的独立核验已证明实际 K、每次成本和剩余预算与 P2 预期一致，可作为 H4 桥接初验通过依据，无须为 P2 重采。原始板端命令未独立保存，这四轮不能冒充 manifest 完全一致的确认性重复。

| 示例 Run | 点 (`b,z`) | 模式 | 期望 K | 期望单尝试成本 (µs) | 板端命令 |
| ---: | --- | --- | ---: | ---: | --- |
| 2711 | A (`0,0`) | LC | 4 | 1456 | `b2z_uc1_start? 2711 500 10 0 0 3 1 6000 0` |
| 2712 | B (`26,0`) | JC | 3 | 1856 | `b2z_uc1_start? 2712 500 10 26 0 1 1 6000 0` |
| 2713 | B (`26,0`) | SC | 3 | 1856 | `b2z_uc1_start? 2713 500 10 26 0 2 1 6000 0` |
| 2714 | B (`26,0`) | LC | 2 | 2904 | `b2z_uc1_start? 2714 500 10 26 0 3 1 6000 0` |

验收核对：同一任务跨槽重发后绝对 `V/E` 不变、`extra_hex` 稳定、C3 按 `(AdvA, run_id, slot_index, command_id)` 独立重组。

### H5：时间参考支撑桥接初验（`time` profile，B 布局 `b=26, z=0`）

固定 300 槽（6 任务 K=3 + 282 纯时间更新槽）、500 ms 周期、150 s 板端计划、180 s 接收。共 3 轮：
- `2715`：正常无干预
- `2716`：仅 BLE 侧失更
- `2717`：仅 IEEE 侧失更

1. **生成 manifest**（以 `2716` 仅 BLE 失更为例；无干预轮次省略 `--intervention-window`）：
   ```bash
   python3 python/control_match/uc1_config.py \
     --run-id 2716 --mode JC --profile time \
     --ble-extra 26 --ieee-extra 0 --tasks 6 \
     --policy k --value 3 --phase P2 --stage verification --rf-condition R0 \
     --sample-rate 4000000 --lna 16 --vga 10 --save-iq \
     --firmware-build "20261119-uc1-r1" \
     --intervention-description "BLE-only attenuation/disconnect around 55-80s" \
     --intervention-window 110 160 \
     --output python/control_match/configs/uc1_2716.json \
     --board-commands python/control_match/configs/uc1_2716.board.txt \
     --host-commands python/control_match/configs/uc1_2716.host.sh
   ```
2. **双接收端启动（`time` profile 必须带 `--control-target-id 1/2`，不加假设参考界，duration=180 s）**：
   - **终端 1（BLE）**：
     ```bash
     python3 python/exadv_rx/receive.py --run-id 2716 \
       --uc1-config python/control_match/configs/uc1_2716.json \
       --channels 3 --control-layout joint --control-target-id 1 \
       --sample-rate 4000000 --lna 16 --vga 10 \
       --duration 180 --save-iq
     ```
   - **终端 2（ZigBee）**：
     ```bash
     python3 python/zigbee_rx/control_receive.py --run-id 2716 \
       --uc1-config python/control_match/configs/uc1_2716.json \
       --channel 12 --control-layout joint --control-target-id 2 \
       --sample-rate 4000000 --lna 16 --vga 10 \
       --duration 180 --save-iq
     ```
3. **板端命令**：
   ```text
   b2z_uc1_start? 2716 500 6 26 0 1 0 3 1
   ```
4. **单侧失更操作要点（仅 `2716` / `2717`）**：
   - 以**板端发射计划起点**计时，约 **55 s**（确保两侧完成初始训练进入 `tracking`），在 **55–80 s** 窗口内仅对目标侧（`2716` 仅动 BLE 接收侧，`2717` 仅动 IEEE 接收侧）遮挡/断开超过 **12–20 s**（确保超过 10 s stale 阈值），随后恢复并等待 180 s 结束。
   - 在 `notes.md` 如实记录操作方式与大致时间；若未触发 `stale`，保留原目录并标为“干预未覆盖”，换新 `run_id` 补采。
5. **分析**：运行 `uc1_analyze.py`，自动输出 `uc1.missing.csv`、`uc1.recovery.csv`、`uc1.live_probes.csv`、`uc1.live_pairs.csv`、`uc1.replay_probes.csv`、`uc1.replay_summary.csv`、`uc1.transitions.csv`。

### H6：离线异常注入验证

- 先运行现有单元级异常测试：
  ```bash
  python3 -m unittest python.control_match.tests.test_uc1_receive -q
  ```
  其中覆盖坏 CRC、未知版本/类型、跨尝试混片、`pending_overflow` / `closed_capacity_exhausted`、错布局拒绝时间处理；保存命令、测试结果和代码版本，标为合成/本地证据。
- 使用独立的 [实录包流回放工具](../../python/control_match/uc1_h6_replay.py) 在已解码包副本的内存中注入故障。2714 C3 分片的 7 个案例（含跨 slot 混片）、2715 时间配置的 4 个案例已通过，报告分别保存在 `20261120_run2714/analyses/h6_fault_injection_replay_v3/` 和 `20261120_run2715/analyses/h6_fault_injection_replay_v2/`。复跑时把 `--analysis-id` 换为未使用的新名称，工具会拒绝覆盖已有输出：
  ```bash
  python3 python/control_match/uc1_h6_replay.py \
    --experiment-dir python/experiments/20261120_run2714 \
    --config python/control_match/configs/uc1_2714.json \
    --analysis-id h6_fault_injection_replay_recheck
  python3 python/control_match/uc1_h6_replay.py \
    --experiment-dir python/experiments/20261120_run2715 \
    --config python/control_match/configs/uc1_2715.json \
    --analysis-id h6_fault_injection_replay_recheck
  ```
  此证据类型为实录包流上的**离线合成故障注入**，不是空口异常实测；原始逐包文件、IQ 和冻结 manifest 保持只读。H4 的 2711–2714 已按上一节独立对账通过 P2 初验，配置溯源例外须继续披露。

---

## 4. P3 先导与 P4 正式重复的参数切换

H1–H6 全部通过并冻结固件与主机代码版本后，沿用同一套 6 步 SOP，仅调整 `uc1_config.py` 参数（`--duration` 自动计算）：

- **P3 RF 先导（B 点，最多两组 R1 候选布局，各在两个独立录制块内做 JC/SC/LC；最多 12 个 run，无线天线起步 `--lna 16 --vga 16`）**：
  - `--tasks 30`（190 槽，板端 95 s / 接收 120 s），`--phase P3 --stage pilot --rf-condition R1 --lna 16 --vga 16`
- **P4 核心成本/可靠性矩阵（R0 27 轮 + R1 54 轮）**：
  - `--tasks 100`（610 槽，板端 305 s / 接收 330 s），`--phase P4 --stage confirmatory --rf-condition R0|R1 --block 1|2|3`（`R0` 馈线直连用 `--lna 16 --vga 10`，`R1` 无线天线用先导冻结后的增益）
  - 每主要配置至少 1 轮保持 `--save-iq`，其余轮次按预登记策略使用 `--no-save-iq` 控制磁盘占用。
  - R0 区组顺序：`JC→SC→LC`、`SC→LC→JC`、`LC→JC→SC`；R1 区组顺序按 [实验计划 §6.2](uc1_paper_experiment_plan.md#62-确认性矩阵上限与执行顺序) 交替执行。
- **P4 时间参考支撑（9 轮）**：
  - 沿用 H5 的 `--profile time --ble-extra 26 --ieee-extra 0 --tasks 6 --policy k --value 3`（180 s 接收），正常 / BLE 失更 / IEEE 失更各 3 轮。

---

## 5. 实机避坑核对清单

1. **先收后发**：始终先启动双端接收，确认收流后再发送 `b2z_uc1_start?`。
2. **禁止连贴命令**：上一轮未打印完整 `final=1` 与 `CONTROL_TIME_END`/`COMPACT_TIME_END` 前，不要发送下一条板端命令。
3. **信道与 layout 对应**：`JC` = BLE `ch3 + joint`；`SC` = BLE `ch3 + separate`；`LC` = BLE `ch39 + separate`；IEEE 固定 `ch12`。
4. **失败轮次全量保留**：出现 0 包、队列溢出、截断或未达 `stale` 的轮次不删除、不覆盖，在 `notes.md` 记录原因，修复后使用新 `run_id` 重跑。
5. **归档完整性**：每轮实验目录必须同时具备 `captures/ble/.../rx.*`、`captures/zigbee/.../rx.*`、`board.board.log`、`notes.md` 以及对应的 `uc1_<run_id>.json`。
