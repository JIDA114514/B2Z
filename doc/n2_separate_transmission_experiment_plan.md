# N2：分别发送基线与共包控制效率实验方案

制定日期：2026-11-10。承接 [N1 执行方案](n1_cross_channel_experiment_plan.md)与 [Run 2001 联合结果](../python/experiments/20261110_run2001/analyses/n1_joint/plan.summary.json)。2001 三项任务均获双端独立解析及 BLE 跟随证据，满足 N1 首轮功能目标；逐槽联合有效为 93/120，不能视作可靠性验收完成。本阶段先完成各对照的一次有效实验，主要配置的独立重复集中后续开展。

## 1. 问题与对照定义

检验相同应用任务下，共包相对分别发送的发送成本、联合有效解析及适用条件，不预设共包更优。射频封装与软件处理策略是两个不同因素，分别比较，避免将主动等待 execute_at 的时间算成系统性能下降。

| 组别 | RF 发送方式 | 接收处理与用途 |
| --- | --- | --- |
| A：分别发送 | 同一 SDR 顺序发送 BLE primary、仅含 BLE 记录的 secondary、单独承载 IEEE 记录的纯 BlueBee 波形 | 两侧独立解析；与共包比较 RF 成本和联合解析。首版明确称为“BLE + 独立 BlueBee 分别发送” |
| B：共包立即处理 | 当前 primary + 共包 secondary | 解码后立即软件处理，保留目标/命令校验和去重；作为软件策略基线 |
| C：共包时间模型处理 | 与 B 完全相同的 RF 序列 | 使用时间模型映射目标时刻；无校准参考界时如实拒绝，不能报告同步执行收益 |

A 复用现有 BlueBee 波形生成能力，但需要新增 B2 43 控制发送路径；不能直接用旧 B2 5A 性能命令冒充控制基线。A 不等于标准原生 IEEE O-QPSK 发送，报告中须明确；若后续实现并实测原生 IEEE 发射，可增加 A-native 对照。在此之前不能将 A 的结论泛化为相对所有分别发送方案的优势。

先在同一批独立接收记录上回放 B/C，以控制输入差异；该对照是离线软件功能和本侧样本域评价，不增加物理重复次数。真实主机处理时延需要另行记录主机事件。

## 2. 字节预算与成本预期

保持两侧 35 B 控制记录、Flags AD、Company ID、AdvA/ADI 和 LE 1M 条件。A 的 BLE secondary 删除 172 B BlueBee 区域，不保留无意义填充。单独 IEEE 数据为 43 B PHY 帧，其中 35 B 控制记录、2 B FCS，以及 6 B PHY 前缀；BlueBee 映射为 172 B BLE 比特字节。

| 项目 | 共包 B/C | 分别发送 A（已实现，待实测） |
| --- | ---: | ---: |
| primary 有效波形 | 136 µs | 136 µs |
| BLE secondary PDU payload | 224 B | 52 B |
| BLE secondary 有效波形 | 1872 µs | 496 µs |
| 独立 BlueBee 有效波形 | 无额外突发 | 1376 µs |
| 每个逻辑尝试的有效波形合计 | 2008 µs | 2008 µs |
| 每尝试有效 RF 突发数 | 2 | 3 |

以上是按当前设计字节数及标称速率计算的预算，尚不是 A 的实测结果。相同开销下共包可能主要减少突发/提交次数，而没有净波形时长优势；实验需允许零收益或负收益。

分别记录：有效调制波形时间、padding/尾部残留、实际 RF 发射占用（若可测）、DMA 持续时间、切频时间、突发间静默及事件起止跨度。纯 BlueBee 生成器原有 padding 不可静默忽略；零样本不自动证明空口零能量。无法测得实际 RF 占用时用“按波形长度核算的 RF 成本”命名，并注明边界。

120 次逻辑尝试的名义有效波形总量两组均为 240.96 ms；共包 240 个突发，A 为 360 个突发。若恰好三项任务均成功，则名义全轮成本为 80.32 ms/成功联合任务；必须包含 111 个时间更新槽，不能只计算 9 个命令槽。该数字仅是预算示例，不是已获得的效率结论。

## 3. 首轮任务、调度与采集

沿用 N1 的 500 ms 周期、120 槽/60 s、三任务清单：槽 20–22 发命令 43，60–62 发 44，100–102 发 45；其余 111 槽为纯时间更新。目标分别为 20/40/60 s，有效期分别为 15/35/55 s；两侧参数与 N1 完全相同。每侧每项任务 K=3；A 的同一逻辑尝试包含两侧独立发射，不能把它算成两项任务。

- 共包组：ch39 primary → BLE ch3/IEEE ch12 共包 secondary。
- A 组：ch39 primary → ch3 BLE-only secondary → 同一 2410 MHz 上的独立 BlueBee 波形。首轮顺序固定为 BLE 在前，IEEE 在后；后续顺序互换作为偏置检查，不能以首版顺序泛化两侧时延优势。
- BLE primary/AuxPtr 的配置保持一致；两个数据突发之间先拟定 1 ms 空闲保护间隔，实施时核对 RF 尾部、DMA 完成与最坏准备时间。准备提前完成，若不能满足间隔则记录实际值并调整冻结配置，不在槽内追加未计数重发。
- 两侧记录保留相同 run_id/command_id/slot_index。A 中两次发射不共享实际空口起点；包内 ref_tick_ms 保持名义计划语义，另外记录两侧提交与配置偏移。本阶段不把 A 的两个起点强行视作同一瞬间。

首轮分两步，预留 Run ID 如已使用则换新 ID：

| 轮次 | 配置 | 作用 |
| --- | --- | --- |
| 2101 | 共包；BLE 固定 ch3，IEEE 固定 ch12 | 两侧完整 IQ 与软件策略回放输入，建立固定频点成本/解析参考 |
| 2102 | A 分别发送；两侧同样固定频点 | 主公平对照，与 2101 保持解码器、增益、接线、观察时长和任务清单一致 |
| 2103 | A 分别发送；BLE 实际跟随，IEEE 固定 ch12 | 检查新 BLE-only secondary 可跟随；与 N1 的共包功能证据对应，不能用固定频点 2101 直接推断跟随优劣 |

两块 HackRF 接收相同任务，不能同时要求同一块设备既固定接收又跟随。固定频点 BLE 用 exadv_rx，IEEE 用 control_receive；实际跟随用 std_ble。BLE-only 格式解析需先适配，现有 224 B 固定检查不能直接放行新格式。固定频点采样率首轮采用两侧 4 Msps，参照既有独立录制条件；若质检不通过，先修正接收条件并统一重采 A/B，不能只优化某一组。跟随模式仍用已验证的 BLE 8 Msps、IEEE 4 Msps，单列配置差异。

采集覆盖板端启动前后，默认 90 s。每次先核对两块设备序列号，再启动接收，最后启动板端。模式 2 已完成软件实现；新命令、采集参数及分析入口见第 7 节，仍需用户构建上板。

## 4. 必须先实现的软件与固件

1. **A 发射路径**：新增独立模式入口，复用任务计划与 35 B 控制构造器；生成 BLE-only secondary 和独立 BlueBee 波形，primary 绑定正确 AuxPtr。保持现有共包与旧性能命令兼容。每槽记录各 RF 突发的类型、长度、准备/提交/完成计数和错误；一侧失败不删除另一侧证据。
2. **接收格式区分**：显式区分 224 B 共包和 52 B BLE-only，按模式核验 AD、应用 CRC 与预算；保留完整 CRC 判据。IEEE 侧独立校验本侧记录。不能仅删掉长度检查来“兼容”。
3. **A 统计适配**：板端计划区分 logical_slots、ble_tx_completed、ieee_tx_completed 和全部物理突发数。联合分析器不把共包的一次 secondary DMA 完成语义原样套给 A。
4. **成本报告**：逐槽连接真实发送清单与独立接收结果；全部尝试计入成本。输出共同计划、射频/硬件条件、成功任务、缺失与单侧结果、预算及实际计数，保存版本和输入哈希。
5. **软件策略比较**：固定频点录制提供 sample_start 与 available_sample，沿用 immediate/scheduled 回放。旧 BLE 跟随 flow 不含这两个字段，不能编造时间戳接入调度器。

实施前冻结新模式接口和字段说明，再生成最终可执行命令。主机测试覆盖两种格式、不同任务、单侧发送失败、重复计数、成本分母和零成功的 N/A；固件源码同步 SDK 实际编译目录，由用户构建上板。

## 5. 指标与公平评价

首轮必报：计划尝试和任务数、板端两侧发送完成数、逐槽四象限、逐任务联合有效解析、每任务各侧有效重发数、全部 RF 突发数、按波形核算的全轮成本及单位成功任务成本。分母为零写 N/A；发送失败、接收失败和原因未定分开。共包的联合率直接匹配，不能用两侧边际率相乘。

使用现有逐任务接收记录检验本侧字段和去重；没有共同参考时，跨机组完成时延、绝对截止时间达标率和同步执行率写未测。可报告本侧包起点到解码可用样本的耗时，注明块量化及样本时间域；板端提交跨度另报。不能用 slot_index 推断实际请求时刻，不能把立即处理与目标调度之间的主动等待称为同步改善。

A/B 比较固定相同任务、格式语义、功率/接线/增益、截止时间与重发规则；分别核算有效波形预算和实际总代价。本设计 K 相同时名义有效波形预算相同，实际 padding、失败和调度差异仍须列出。完成初验后再扫描 K=1/3/5 等配置，比较同预算下的联合率；“同可靠性下成本”需预先规定目标和统计方法，未达到目标的配置保留，不凭一轮三任务成功筛选最优点。

B/C 先使用完全相同的独立逐包输入。无参考界时 C 的拒绝是当前能力边界，不能当作时间模型劣于立即处理的性能结论；假设界回放只能用于功能说明。N3 建立参考后再补实际目标偏差、同步容差达标和统一后验截止规则下的性能比较。

## 6. 归档、进入后续阶段的条件

每组使用独立 run_id，保存完整命令、板端计划/逐突发日志、两份 IQ、逐包与逐任务记录、代码/固件版本、观察起止及数据质量。建立一份跨轮 comparison 配置，明确哪些差异来自发送模式、接收模式或处理策略。不要覆盖或将旧 N1 数据计为新的重复。

本阶段首轮有效的条件：A 确实分别发送并被两侧独立解码，至少一组多任务结果与共包组可公平核对，成本可追溯至实际发送清单，缺失结果保留，报告如实给出收益/代价/无差异。若两组名义 RF 成本相等，这是有效结果；不得为制造优势人为添加冗余包。

满足功能和成本初验后可进入 N3/N4/N5；同步效果与尾部可靠性未测部分继续登记。最终主要配置至少三轮独立重复，交替 A/B 顺序；如后续改变发射格式或接收算法，最终对照需使用冻结后的同版本重测。

最近一步：按第 7 节构建并上板，先完成 2101/2102 公平对照与 2103 BLE-only 跟随初验。现阶段无需先补 N1 的重复轮次。

## 7. 已实现接口与首轮执行指令（2026-11-10）

软件实现已完成主机验证，尚未上板验证。此次修改后需重新构建固件；`app_FreeRTOS/app/` 的四个改动文件已同步到 SDK 的 `app/src/app/`。旧性能命令与控制模式 0/1 保持兼容。

### 7.1 板端接口

`b2z_plan_start? <run_id> <period_ms> [rf_mode]` 以及 `b2z_control_start?` 的末尾参数新增 `2`：

| rf_mode | 发送行为 |
| --- | --- |
| 0 | 原同频诊断共包，保留 |
| 1 | ch39 primary → ch3 共包 secondary，保留 |
| 2 | ch39 primary → ch3 BLE-only secondary → 2410 MHz 独立 BlueBee |

模式 1/2 周期至少 500 ms，AuxOffset 均为 300 ms。模式 2 两份数据波形在 primary 发送前准备完毕，BLE secondary DMA 完成后至少等待 1000 µs，再提交独立 BlueBee；这是软件保护间隔，不是已校准 RF 静默时长。每个突发均包含 10 µs 标称零样本尾部，没有旧 pure 生成器的长前置 padding。前级失败时跳过本槽后续突发；IEEE 失败保留已完成的 BLE 记录，不在槽内偷偷重试。

将第 3 节任务清单逐条输入串口（与 N1 相同）：

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

### 7.2 固定频点采集：先 2101，再 2102

以下从仓库根目录执行，先运行 `hackrf_info` 核对序列号。两轮维持接线、功率、衰减与增益一致。每轮两终端各运行一条命令，接收已启动后才发板端启动命令。90 s 时长从接收进程开始计，尽量在 10 s 内启动两侧，随后 5 s 内启动板端。

2101 BLE：

```bash
python3 python/exadv_rx/receive.py --run-id 2101 --channels 3 \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 90 --save-iq --quiet
```

2101 IEEE：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2101 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --expected-packets 120 \
  --duration 90 --save-iq --quiet
```

随后串口输入 `b2z_plan_start? 2101 500 1`。本轮不启用在线定时处理，B/C 使用同一份接收结果离线回放。

2102 BLE：

```bash
python3 python/exadv_rx/receive.py --run-id 2102 --channels 3 --control-layout separate \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 90 --save-iq --quiet
```

2102 IEEE：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2102 --channel 12 --control-layout separate \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --expected-packets 120 \
  --duration 90 --save-iq --quiet
```

随后串口输入 `b2z_plan_start? 2102 500 2`。两侧都省略 `--command-id`，不能只保留某一个命令。`--control-layout separate` 记录波形布局并禁止启动共包定时处理；分别发送的 IEEE 起点不沿用共包的 472 µs 补偿。离线立即处理可用，分别发送的 scheduled 回放会被拒绝。

日志目录依据当天日期与 run_id 自动创建，无需 EXP_DIR。完整串口日志放在对应实验目录的 `board.board.log`，不要在出现 `CONTROL_PLAN_STATS` 后立即停止保存：还要保存 7 条 TASK、120 条 SLOT、模式 1 的 240 条/模式 2 的 360 条 `CONTROL_BURST` 以及最后的 `CONTROL_COST_STATS`。新增日志在 RF 调度结束后输出，串口传输可能持续数秒。

### 7.3 逐槽联合分析和成本

日期按实际实验日修改。每轮只有一份完整 BLE 与 IEEE 采集时，分析器自动发现包文件；有多个候选则显式指定 `--ble-packets` 和 `--zigbee-packets`，不自动选最新。

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261110_run2101 --run-id 2101 --analysis-id n2_joint
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261110_run2102 --run-id 2102 --analysis-id n2_separate
```

输出 `plan.report.md`、`plan.summary.json`、`plan.slots.metrics.csv`、`plan.tasks.metrics.csv` 和新增 `plan.bursts.csv`。历史日志没有突发观测时成本为未测；模式 2 缺少完整突发清单会拒绝分析。旧 `tx_completed` 明确保留 BLE secondary DMA 完成语义，IEEE 完成数来自独立突发记录。两侧有效命令也与新增 TASK 中的目标、操作和参数核对。

`CONTROL_BURST` 的时间字段单位为 µs、原点为本轮板端软件运行起点：`prepared_us` 为全部波形准备完成后的记录点，`submit_before_us`/`submit_after_us` 包围 DMA 启动调用，`finish_us` 为轮询返回点。未提交时对应字段为 0，须结合状态字段解释。`generated/attempted/started/completed/timeout` 区分准备、调用、成功返回、轮询完成和超时；没有对应波形生成时长度为 0。`iq_bytes` 为完整 DMA 缓冲长度，`air_us` 为标称有效调制长度，`pad_us` 为标称零样本长度。

成本按成功提交的整段波形核算，DMA 超时仍计入；失败提交另计 attempted 预算，实际发出了多少保持未知。所有时间更新、重发与失败保留，成功任务为零时单位成本为 `N/A`。本侧解码可用延迟在 JSON 中单列，不能作跨机完成时延。输入文件哈希和分析代码版本写入 JSON，运行固件的构建版本需人工保存，不能由主机当前 Git HEAD 推断。

### 7.4 同输入 B/C 回放

将以下包路径替换为 2101 本轮的实际文件。先对 BLE 执行：

```bash
python3 python/control_match/replay_engine.py \
  --packets <2101_BLE_rx.packets.jsonl> --side ble --run-id 2101 --target-id 1 \
  --policy immediate --output-dir python/experiments/20261110_run2101/analyses/n2_immediate_ble
python3 python/control_match/replay_engine.py \
  --packets <2101_BLE_rx.packets.jsonl> --side ble --run-id 2101 --target-id 1 \
  --policy scheduled --output-dir python/experiments/20261110_run2101/analyses/n2_scheduled_ble
```

IEEE 两次回放使用 IEEE 文件、`--side zigbee --target-id 2`，输出目录分别为 `n2_immediate_ieee` 和 `n2_scheduled_ieee`。不要填写假设参考误差界来获取通过。无参考界时 scheduled 拒绝执行符合预期；这不是同步收益结论。A 组如需软件处理记录，仅运行 `--policy immediate`，run_id 改为 2102。

### 7.5 跨轮比较

建立 `python/experiments/n2.conditions.json`，按实际填写两轮的条件，不能将模板内容作为实测：

```json
{
  "joint": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"},
  "separate": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"}
}
```

```bash
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/20261110_run2101/analyses/n2_joint/plan.summary.json \
  --separate-summary python/experiments/20261110_run2102/analyses/n2_separate/plan.summary.json \
  --conditions python/experiments/n2.conditions.json \
  --output-dir python/experiments/n2_comparison_2101_2102
```

输出比较 Markdown/JSON，核对任务、周期、接收参数和人工记录的 RF 条件。未填写/不一致项保留列出；不会把低发送完成率造成的成本下降算成效率提升。仅核对已记录条件，不代表所有环境因素受控。

### 7.6 2103 BLE-only 实际跟随

使用与 2102 相同板端任务，IEEE 固定接收命令中的 run_id 改为 2103；BLE 改用以下命令。先核对 `hackrf=0` 确为 BLE 设备，否则替换索引：

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2103 --expected-attempts 120 --period-ms 500 --payload-mode ble-only \
  --osmosdr-args hackrf=0 --sample-rate 8000000 --if-gain 16 --bb-gain 10 --duration 90
```

串口启动 `b2z_plan_start? 2103 500 2`。分析调用 `plan_analyze.py --run-id 2103 --experiment-dir <2103目录> --ble-flow <flow.events.jsonl> --zigbee-packets <IEEE_rx.packets.jsonl> --analysis-id n2_separate_follow`。不把这一轮与固定频点两轮合为同配置比较。

主机验证覆盖：C 生成的 BLE-only IQ 恢复、独立 BlueBee IQ 的 IEEE FCS/应用记录恢复、格式误用拒绝、任务重发关联、单侧 DMA 失败、缺失/重复日志、成本分母和零成功。ARM GCC 只作语法检查，真实调度、RF 接收和 BLE 跟随仍须上述上板实验确认。
