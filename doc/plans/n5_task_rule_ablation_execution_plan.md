# N5 任务规则消融执行方案

> 整理标注（2026-11-18）：本文件保留实验设计、执行命令与预登记约束；阶段状态见[文档导航](../README.md)，已使用的 Run ID 不应直接复用。 已有结果见[任务规则消融结果](../results/n5_task_rule_ablation_results.md)。

本方案落实 [N5 计划第 7 节](n5_mechanism_experiment_plan.md#7-任务消融与异常行为)。目标是用已保存的、两侧独立解码的逐包轨迹检查重复次数、执行提前量、处理延迟和异常输入的规则行为。它属于离线软件回放及合成协议测试，不产生新的无线实验轮次、同步精度或执行器结果。

2504、2507、2508 的首轮回放已执行并归档；逐轮结果与限制见 [任务规则消融首轮结果](../results/n5_task_rule_ablation_results.md)。

## 1. 输入、分组和固定口径

首轮使用同任务表的三条轨迹：2504 无主动干预，2507 BLE 单侧缺失，2508 IEEE 单侧缺失。2501–2503 可作为补充历史轨迹，但应先核对当轮是否真正启用了 `--n5-config` 及现场干预；不能按原预留编号把它们自动归入三种条件。2507 第二次干预超出其预登记窗口，单列探索性结果。三条轨迹各只有一轮，不当作三轮独立重复。

| 轮次 | 实验目录 | N5 配置 | 主要用途 |
| --- | --- | --- | --- |
| 2504 | `python/experiments/20261116_run2504` | `python/control_match/configs/n5_2504.json` | 无干预参照 |
| 2507 | `python/experiments/20261116_run2507` | `python/control_match/configs/n5_2507.json` | BLE 缺失轨迹 |
| 2508 | `python/experiments/20261116_run2508` | `python/control_match/configs/n5_2508.json` | IEEE 缺失轨迹 |

各轮板端计划固定 300 槽、500 ms 周期、六个非零命令。命令 51 为 K=1，52、53、55、56 为 K=3，54 为 K=5。任务分母固定六个；命令 0 是时间更新，不计控制任务，仍保留在时间模型输入和原始发送成本中。任何消融均使用每侧自己的 `rx.packets.jsonl`、`available_sample` 和 `rx.summary.json`；两侧仅在各自回放后按同一 `run_id/command_id` 合并。探测槽仍固定，不用它们训练模型，也不以其他包补缺。

报告至少分别列出逐侧有效解析、逐任务首次有效尝试、去重、接受、拒绝原因、软件处理、联合有效解析、零接收任务及缺失数。全部比例写分子/分母，分母为零写 `N/A`。原始板端空口成本保持原值；输入筛选产生的“假如只发 K 次”只能计算反事实尝试数，不能冒充实测 RF 发射时长。真实接受/执行结论仍受未校准参考界限制。

## 2. 现在即可运行的输入核验和基线

以下命令从仓库根目录运行。分析输出放在 `/tmp`，避免改写实验目录；`replay_engine.py` 拒绝覆盖既有输出目录，重复运行时先换一个新的输出根目录名。

```bash
PYTHONPATH=python python3 -m unittest discover -s python/control_match/tests -p 'test_n5*.py'

for run_id in 2504 2507 2508; do
  exp="python/experiments/20261116_run${run_id}"
  config="python/control_match/configs/n5_${run_id}.json"
  test -f "$exp/board.board.log" && test -f "$config" || exit 1
  rg --files "$exp/captures" | rg '/rx\.packets\.jsonl$'
  sha256sum "$config" "$exp/board.board.log"
done
```

用现有 N5 汇总确定六任务分母、现场状态和失更覆盖：

```bash
for run_id in 2504 2507 2508; do
  jq '{run_id, joint_parsing, live_probe_summary, recovery, limitations}' \
    "python/experiments/20261116_run${run_id}/analyses/n5_mechanism/n5.summary.json"
done
```

现成的立即处理基线可直接回放。它在包的 `available_sample` 处处理首次有效命令，不判断定时截止；两侧各自输出，不能由 `software_processed` 推断物理动作。以下命令使用 2504 的原始逐包文件作为可复制的完整示例：

```bash
python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261116_run2504/captures/ble/112031_953819_zgq_3ypu/rx.packets.jsonl \
  --side ble --run-id 2504 --target-id 1 --policy immediate \
  --output-dir /tmp/n5_task_rules_2504_ble_immediate_v1

python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261116_run2504/captures/zigbee/112030_270549_t3mb8b3c/rx.packets.jsonl \
  --side zigbee --run-id 2504 --target-id 2 --policy immediate \
  --output-dir /tmp/n5_task_rules_2504_ieee_immediate_v1
```

可用下式检查基线事件数；同一 `command_id` 的多次重复不会增加软件处理任务数：

```bash
jq '{run_id, side, control_observations, events, reasons, assumption_status}' \
  /tmp/n5_task_rules_2504_ble_immediate_v1/control.summary.json \
  /tmp/n5_task_rules_2504_ieee_immediate_v1/control.summary.json
```

## 3. 消融入口与完整执行命令

`replay_engine.py` 保留单侧原始回放接口。`python/control_match/n5_task_ablate.py` 已实现双侧独立回放、计划尝试筛选、提前量字段及应用 CRC 重建、处理延迟注入、合成规则案例和结果归档。先以 `--help`、专项单测和一轮临时输出验收，再运行全矩阵。入口的契约如下：

- 输入：`--experiment-dir`、`--config`、`--run-id`、`--output-dir`；显式读取两侧唯一的完整录制和板端逐槽日志，拒绝多份歧义录制、配置/Run ID 不符、无 `available_sample`、时间轴异常和既有输出目录。
- 固定输出：`manifest.json`（输入文件 SHA256、配置哈希、代码版本、参数及证据类型）、`conditions.csv`、`tasks.csv`、`events.jsonl`、`rule_cases.csv`、`report.md`；每个条件保留每侧的原始观察数、被筛选数和拒绝原因。两侧独立回放，最后才生成联合表。
- 原始 5 s 条件保持真实字节和原始有效期；修改提前量时重建 v1 的 `execute_at_ms`、`valid_until_ms` 和应用 CRC16，并明确标记 `synthetic_protocol_replay`，不得修改原始 JSONL。
- 定时接受分成 `uncalibrated` 与 `synthetic_bound_1ms` 两张表。1 ms 是功能测试假设，不是设备校准值；立即处理基线只报告解析、去重和软件事件，不评价截止时间。

运行前检查：

```bash
PYTHONPATH=python python3 -m control_match.n5_task_ablate --help
PYTHONPATH=python python3 -m unittest discover -s python/control_match/tests -p 'test_n5_task_ablate.py'
```

正式一键命令（每轮输出目录必须尚不存在）：

```bash
for run_id in 2504 2507 2508; do
  PYTHONPATH=python python3 -m control_match.n5_task_ablate \
    --experiment-dir "python/experiments/20261116_run${run_id}" \
    --config "python/control_match/configs/n5_${run_id}.json" \
    --run-id "$run_id" \
    --output-dir "/tmp/n5_task_rules_run${run_id}_v1"
done
```

### 3.1 重复 K：实际收包轨迹的反事实输入筛选

对每个任务按板端登记的物理尝试序号保留前 1、前 3、全部尝试。K=1 的 51 在三列相同；K=3 的任务在“前 3”和“全部”相同；仅 54 有第 4、5 次机会。筛选依据是**计划槽序号**，不能按实际收到的第 1/3 个包补位；未收到的计划尝试继续缺失。命令 0 的训练/探测输入固定保留，以免改变时钟模型。对每侧报告该任务在各条件下的解析、去重和首次有效机会，再按命令求联合解析。逐任务还列原始 `planned_attempts`、`observed_attempts`、`selected_planned_attempts` 与 `selected_observed_attempts`。

在同一任务表中不同 K 对应不同任务和时间段，因此只比较**同一命令自身**被裁掉后失去或保留的机会。若需要论文级 K 收益数字，另做只改变 K、保持首槽/截止/周期/RF 条件的物理对照和独立重复。

### 3.2 执行提前量：0.5/2/5 s

为隔离目标时刻变化，本组只用每个任务首发计划槽的一次机会，保留相同可用样本位置；有效期固定为首发计划时刻后 400 ms，目标时刻分别为首发后 500、2000、5000 ms。这样三种条件的接收机会和接受截止相同，且 `valid_until_ms < execute_at_ms`；它们全是**合成字段**，包括这组的 5 s 条件。另列原始任务的 5 s/原始有效期作为物理字段锚点，不能与合成 5 s 混称同一协议条件。

每侧重建并重新校验完整 v1 应用记录及 CRC，保持 `run_id`、`command_id`、目标、opcode、参数、槽号、`ref_tick_ms` 和包的 IQ 样本索引不变。若固定有效期后首次可用时刻已晚于截止，按实际规则拒绝，不能把包移到较早时刻。报告 `accepted`、`late`、`expired`、冻结、取消和 `software_processed`；未校准表仅描述解析和严格拒绝。
改写后的应用字节直接进入软件引擎，不重建 BLE 外层 CRC 或 IEEE FCS，也不声称这些合成字段曾在空口发送。

### 3.3 处理延迟：0/10/100 ms

以原始 5 s 字节为输入，把每个包的 `available_sample` 增加 `round(delay_ms * sample_rate / 1000)`，保持 `sample_start` 不动，按新可用时刻稳定排序；接收处理顺序与引擎进度单调。超出录制终点的包计为右删失，不延长 IQ，也不重置样本零点。分别在未知参考界和显式合成 1 ms 参考界下回放。0 ms 行应与相同引擎/相同输入的未注入回放逐事件一致；它不代表主机实际零延迟。延迟行报告可用时刻、接受截止、冻结、过晚取消、事件样本及原因，不能称为测得 USB/主机时延。

### 3.4 异常行为规则表

用独立合成 v1 记录逐项构造并记录输入、预期、实际事件、证据类型。不得把合成包计入 2504/2507/2508 的无线成功率。

现有规则单测可直接运行；消融入口也已将逐案例结果导出为 `rule_cases.csv`：

```bash
PYTHONPATH=python python3 -m unittest discover -s python/control_match/tests -p 'test_control_engine.py'
PYTHONPATH=python python3 -m unittest discover -s python/control_match/tests -p 'test_n5_observation.py'
```

| 场景 | 至少验证的规则 |
| --- | --- |
| 错误目标；合法但本机不支持的 opcode | `wrong_target`、`unsupported`，无软件处理 |
| 未知 opcode、应用 CRC 错误、非法字段 | 解析拒绝为 `invalid_record`；板端不必发出非法空口包 |
| 同命令号冲突、同命令重复、重复槽 | 冲突拒绝；重复不二次处理；时钟重复不刷新模型 |
| 乱序可用、过期、迟到 | 按 `available_sample` 判决，不能用包起点提前接受 |
| 失更、流中断、显式重启、跨 Run ID | 未知参考严格拒绝；时间轴异常取消待处理任务；重启后重新取样建模；外轮包不污染本轮状态 |
| 0/全部任务缺失、零分母 | 六任务清单仍完整，零分母为 `N/A` |

`protocol.py` 当前只允许 opcode 0/1/2；“未知 opcode”应在协议解析层拒绝。`unsupported` 分支用协议合法但本机 `supported_opcodes` 不包含的操作验证，不能为了制造测试输入放宽正式解析器。

## 4. 验收与归档

1. 新入口的单测覆盖计划槽筛选而非收到包补位、首发合成字段/CRC、延迟排序和尾部删失、每侧独立解析、严格未知参考、合成有界分支、异常矩阵与零分母。`PYTHONPATH=python python3 -m unittest discover -s python/control_match/tests` 通过。
2. 2504 的未筛选原始任务解析结果与现有 N5 分析一致；K=全部与未筛选一致；提前量组的 5 s 合成行与原始 5 s 行分别列出；延迟 0 ms 与同输入未注入回放一致。差异必须能回溯到任务、侧别和包槽。
3. 每轮报告保留六任务和两侧结果，不以成功子集代替计划分母。反事实 K、合成协议、延迟注入、合成时钟界、软件事件分别标证据类型。失败原因不明和无真实执行器结果如实列出。
4. 先在 `/tmp` 核对输出，再将确认后的 `manifest.json`、CSV/JSON、Markdown 和必要的命令记录归入该轮新建的 `analyses/n5_task_rules_v1/`；不重写原始捕获、已有分析或历史目录。三轮独立重复与物理 K 对照仍为后续事项。
