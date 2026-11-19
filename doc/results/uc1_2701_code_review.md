# UC1 2701 功能测试与代码检查

检查日期：2026-11-19。对象为当前工作区板端与接收端实现，以及 `python/experiments/20261119_run2701/` 的配置、板端日志、两侧逐包记录和联合报告。本次仅检查与归档，未修复代码、重写原始实验结果或上板。

## 结论与实测证据

2701 通过 **JC / core / B 点 / K=3 的初次共包解析功能验证**。可以保留为有效功能证据，但不足以冻结全部实现，也不能证明重复 K 次的增益、截止期满足或同步执行。

| 项目 | 结果 |
|---|---|
| 配置 | period=500 ms，10 个任务，70 个槽，b=26、z=0，每任务预算 6000 µs，K=3 |
| 板端 | 30 次尝试生成并完成 DMA；40 个计划静默槽；deadline_miss、dma_timeout、retune_failure 均为 0 |
| 两侧逐包解析 | BLE 30/30，IEEE 802.15.4 30/30；对应相同的 30 个活动槽 |
| 联合任务解析 | 首次尝试 10/10；计划尝试内 10/10；异槽互补 0 |
| 截止期 | unknown 10/10；独立采样时间轴未校准，这不是失败率 100% 或准时率 0% 的证据 |
| 波形成本代理 | 计划、提交及 DMA 完成有效波形均为 55,680 µs；padding 600 µs；每成功联合解析任务 5,568 µs |
| 采集 | 两侧均正常结束，未记录队列溢出；各保存 480,000,000 字节 IQ |

逐任务的重发保持命令标识、V/E 与负载一致。检查的源文件哈希与采集配置记录一致；五个板端实现文件与 SDK 副本一致。固件 build 标签不是独立的二进制哈希证明。

## 需要修复的问题

### 1. 对照分析错误地授予协议归因资格（优先）

位置：`python/control_match/uc1_analyze.py:612–641`。

接收配置仅比较两边均存在的字段；外部条件仅在传入 conditions 时检查。更直接的问题是，SC 对照的 `reliability_protocol_effect_identifiable` 恒为 true，与 differences 无关。

最小验证使用真实 2701 summary 的深拷贝构造**合成 SC 输入**，将 BLE LNA 改为 99：输出同时出现 `recorded_conditions_match=false`、`differences=[receiver.ble.lna]` 和 `reliability_protocol_effect_identifiable=true`。不提供外部条件时也可能得到条件匹配。这不是实际 SC 实验结果，而是分析器反例。

影响：不改变 2701 单轮解析计数，但会误导后续公平性与可靠性归因结论。

建议：区分一致、不一致、缺证据；必需条件缺失不能作为一致证据；归因资格依赖完整的公平性检查。还应比较任务语义，而不只是任务数量；保留 LC 的频率混杂限制。

### 2. 在线引擎的任务冲突标记未形成完整隔离（优先）

位置：`python/control_match/control_engine.py:352–358`、`:391–410`，以及 `advance()`。

检测到同一 command_id 的语义冲突时，只加入 conflicted_tasks，已有 pending 任务仍保留。后续恢复原语义的包还会先更新时钟、进入 duplicate 分支，绕过冲突检查；advance 不排除该任务。

合成验证：使用明确假设的 1 ms 外部参考界限，先建立时钟，接受 command 1 / arg 1，再输入同 ID / arg 99，随后输入原 arg 1。冲突包被拒绝，但后续包仍产生 clock_updated；推进时间后原任务产生 software_processed。该验证不代表 2701 已完成时钟校准或发生过实际执行。

影响：2701 未出现冲突，当前联合解析结果不受影响；异常输入与后续 time profile 的软件处理规则仍不闭合。

建议：明确冲突后的任务状态策略；对尚未处理的任务取消 pending 并阻止重新接受及其时间更新，对已经处理的任务保留事实并报告冲突。将冲突检查移到时钟更新和重复分支之前，增加“冲突后继续输入并推进时间”的回归测试。

### 3. 板端状态查询与日志分析器不兼容

位置：`app_FreeRTOS/app/bluebee_perf.c:667–675`；`python/control_match/plan_analyze.py:43–46`。

板端非最终状态输出也包含 UC1_STATS，而该行没有 final 标识；分析器要求恰好一行 UC1_STATS。正常查询 `bluebee_perf_status?` 后，包含状态快照与最终统计的日志可能无法分析。

最小验证在临时副本中增加一行现有 UC1_STATS，read_plan 报错 `expected one UC1_STATS, found 2`。2701 原日志仅有一行，因此没有触发。

建议：板端增加终态标识；分析器选择同 run_id 的有效终态记录，并校验重复终态一致性。旧日志可结合 CONTROL_PLAN_STATS 的终态上下文兼容，不能无条件选最后一行。

### 4. 接收汇总把静默槽计入连续丢包

位置：`python/zigbee_rx/control_receive.py:96–107`。

longest_loss_burst 遍历连续 slot 编号，未使用 UC1 配置排除静默槽。2701 全部 30 次活动尝试均收到，IEEE 接收汇总仍报告最长丢包串 3；这是计划中的静默间隔。若以全 70 槽作为 expected_packets，还会把开头 10 个静默槽算入。

影响：本次已触发的统计口径问题；UC1 联合报告的 10/10 不因此失效。notes 中 30/70 只能表示槽覆盖，不能当接收成功率。

建议：根据 manifest 的活动尝试计算接收缺失，分别记录静默、板端漏发和接收缺失；明确定义连续活动尝试丢失与实际持续时间。无计划时不要把槽号缺口直接命名为无线丢包。

## 板端时间参考的实际限制

板端 `secondary_dma_late_avg_us=74052`、最大 74829；primary 至 secondary 的 DMA 时间差为 300011–300017 µs。逐槽 GFSK 生成平均约 73.24 ms，当前到槽后生成再发送的路径可以解释主要偏移。

这说明“计划 secondary 时间”与 DMA 提交并不相同；不是 74 ms 的实测 RF 同步误差，也不能用 deadline_miss=0 推导零时间误差。该偏移不否定 2701 的解析和波形预算，但后续时间实验必须保留其语义、校准与误差界限。若要改善计划时刻兑现能力，可评估提前生成；是否必要应按目标提前量与可接受误差判断。

## 验证、覆盖缺口与推进建议

已执行以下测试，20 项通过；另以上述合成反例验证现有测试未覆盖的路径：

```bash
python3 -m unittest python.control_match.tests.test_uc1_receive python.perf_test.tests.test_uc1_start python.perf_test.tests.test_uc1_generator -q
```

2701 未覆盖 SC、LC/C3 空口分片、time profile、连续漏收/重获、异常命令或公平性比较。全收的 10 个任务只能作功能初验，不能支持 K 增益或稳定可靠性结论。

建议先修复以上四项并补针对性回归，再完成 SC、LC/C3 与 time profile 的各一次功能测试后评估冻结。2701 可继续保留，无需仅因这些未触发路径而重做。其 notes 仍使用 N5 模板并引用不存在的旧分析路径，后续整理时应改为 UC1 配置、证据路径与限制说明；本次未改动原记录。

## 后续修复与本地验收（2026-11-19）

用户授权修复后，以上四项均已修改：

1. 对照输出 `conditions_status=match/mismatch/unknown` 与 `missing_evidence`；条件缺失时 `recorded_conditions_match=null`，协议归因资格为 false。SC 仅在必需条件齐全且一致时取得该资格，LC 保留信道混杂限制；该资格不代表统计显著。新增由计划生成的 `planned_task_semantics`，不使用已解码任务子集判断任务公平性；同预算允许 K 不同。旧 summary 缺少该字段时仍可读取，但比较资格为未知，需从原始记录另建分析输出。
2. UC1 冲突时取消尚未处理的 pending 任务，保留已处理事实；后续同任务包在时钟更新和重复处理前被拒绝。协议文档补充该异常处理决定；未改字节格式、时序字段或成本。
3. 板端 UC1_STATS 增加 final 字段，已同步 SDK 副本。分析器按终态选择，校验重复终态一致性，兼容旧日志的 CONTROL_PLAN_STATS 终态上下文；状态快照不会替代最终结果。
4. IEEE 接收汇总按 UC1 manifest 的活动尝试计算连续缺失；core 排除静默，time 包含纯时间更新，命令筛选只计算对应槽。指标注明它包括板端及接收缺失，不能独自归因于无线。已识别 UC1 但无 manifest 时返回未知，不把编号缺口当作丢包。

验证记录：

| 验证 | 结果与边界 |
|---|---|
| `python3 -m unittest discover -s python/control_match/tests -q` | 111 项通过，覆盖历史解析、在线引擎、分析及 UC1 三封装/C3/时间更新的本地功能链 |
| `python3 -m unittest python.zigbee_rx.tests.test_control_receive python.perf_test.tests.test_uc1_start python.perf_test.tests.test_uc1_generator -q` | 14 项通过，包含接收计数、板端启动预检与生成器 |
| 新增/增强回归 | 参数不一致、条件缺失、零值条件、任务语义差异；冲突后重发及推进时间；新旧日志状态快照/终态缺失/冲突；静默与活动尝试缺失 |
| 2701 原始记录重分析 | 输出到临时目录；first_attempt、within_planned_attempts、deadline_class、waveform_cost 与原结果一致 |
| 2701 IEEE 已恢复负载回放 | 30/30 活动尝试，最长连续缺失为 0；未重新解调 960 MB 原始 IQ |
| ARM 语法检查 | Vitis 2021.1，bluebee_perf.c，N3 trace=0/1 均通过；未链接或刷写固件 |
| SDK 同步 | `app_FreeRTOS/app/bluebee_perf.c` 与 SDK `app/src/app/bluebee_perf.c` 内容一致 |

没有改写 2701 的原始日志、IQ、summary、notes 或历史索引。源代码已变化，下轮实验应重新生成并冻结配置/源码版本记录。本地 SC、LC/C3 与时间测试使用合成输入或生成器波形，不替代这些配置的独立双端实测。用户仍需编译上板验证新日志，再完成对应物理初验；2701 的约 74 ms 生成/提交偏移保持原有语义，本次未更改调度策略。
