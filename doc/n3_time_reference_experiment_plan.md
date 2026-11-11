# N3：板端取时、跨信道相对时间保持与误差归因实验方案

制定日期：2026-11-11。依据 [next_stage_plan.md](next_stage_plan.md) 的 N3、N3-A、N3-B；承接 N2 的 2101–2103 首轮功能与成本初验。本文件是待执行计划，不是新增实验结果。先完成软件与一次有效初验，主要配置独立重复随后集中开展。

## 1. 本阶段要回答的问题

1. 现有 `secondary_dma_late_us` 与 `auxptr_dma_window_miss` 中，哪些变化发生在生成、缓存刷新、寄存器提交或函数返回阶段？
2. 最终 ch39 primary/ch3 共包 secondary 配置下，两条独立接收链能否仅用各自历史包，预测未参与训练的后续包参考时刻？预测随历史包数、训练跨度、更新间隔和失更年龄如何变化？
3. 发送侧软件时延与单侧预测残差、双侧相对估计差是否有关联？哪些现象仍无法区分？
4. BLE 实际跟随的时间轴是否可审计？若不能，明确其只支持功能与阶段诊断。

仅使用现有发送 SDR、两块 HackRF 和主机。无新增硬件测量要求，也不以测得绝对同步误差作为阶段完成条件。不得把串口应答、USB 回调、主机墙钟差或 DMA 完成当作 RF 起点；不报告执行器动作、绝对跨设备同步或严格 AuxPtr 空口时间精度。

## 2. 起点与已有数据用途

| 数据 | 用途 | 不能替代的证据 |
| --- | --- | --- |
| 2101 共包固定接收，两侧 120/120 | 500 ms 混合任务解析、时间保持工具适配和探索性分析；已有逐突发软件括号时刻 | 只有 60 s；不能在看过结果后称为预登记验证集 |
| 2102 分别发送，两侧 120/120 | 比较不同 DMA 缓冲长度对应的软件调用耗时 | 两侧非同一 RF 起点，不作为共包相对时间保持主样本 |
| 2103 分别发送 BLE 跟随 75/120，IEEE 120/120 | 已有阶段分类：32 槽无有效 primary、13 槽跟随窗口未成功；跟随能力核查 | 没有 BLE 连续 IQ，不能生成 BLE 样本时间戳或推算跟随同步精度 |
| 1703–1705 同频、200 ms | 历史方法参考与回归测试 | 周期/配置不同，不能将结果差异全部归因于跨信道 |

2101 secondary DMA 调用括号平均约 995 µs，2102 约 262 µs；返回后越窗分别 120/120 与 0/120。这是进一步拆分软件耗时的动机，不是已确定缓存刷新为根因。约 80 ms 的 late 也不是已测得的空口同步误差。

N2 `tx_power=UNKNOWN` 继续保留；新实验优先记录可读取的 TX 配置值、固件构建标识和接线。配置值不等于校准后的实际输出功率。

## 3. 软件前置任务与接口状态

以下实现完成并经主机验证后，再启动正式新采集。当前只制订计划，不假称这些新字段/分析选项已经支持。

### 3.1 板端：同位置取时与逐槽日志

保留既有命令、模式 0/1/2 和旧计数口径，新增独立诊断字段，不静默改写历史 `late` 定义。继续轮询 DMA 并设置超时。针对 primary、secondary、独立 IEEE 使用相同取时位置：

| 事件 | 定义 |
| --- | --- |
| slot_planned / secondary_planned | 明确两种计划原点：本轮槽计划；本槽 primary 参考 + AuxOffset |
| generation_begin/end | 本槽波形构建前后；另记 frame/mapping/GFSK 阶段耗时 |
| dma_call_before/after | 现有 DMA 启动调用括号，保持兼容 |
| dma_stop_clear_begin/end | 停止旧传输、清状态阶段 |
| cache_flush_begin/end | 对本次完整缓冲执行刷新前后；未执行时显式标记 |
| dac_sync_before/after | DAC 同步寄存器操作括号 |
| submit_write_before/after | 实际提交寄存器写入前后，不以函数入口替代；需检查 axi_dmac 驱动实际调用路径 |
| dma_poll_complete / timeout | 轮询完成或超时的记录点，附对应状态/错误码 |
| retune_begin/end | 切频调用括号及返回状态，包括返回 primary 频率 |

记录 `(run_id, slot_index, burst_kind)`、缓冲字节数、有效波形/padding 长度、事件有效标志。缺失事件用显式缺失，不能用 0 冒充有效时刻。时戳为板端同一单调计数器，保存单位和换算率；在支持的最长实验中不得溢出。原始计数或 64 位时戳序列化方案在实现时冻结。

将 `pre_call_late`、`pre_submit_late`、`post_return_late` 分开，均注明相对哪个软件目标；它们都不等于 RF 越窗。针对 primary→secondary 分别计算同位置的 call→call、submit→submit 和 return→return 间隔，不能再混用 primary 调用前与 secondary 返回后。

日志缓存在内存中，RF 调度结束后再打印；容量覆盖 300 槽。记录插桩是否启用、定时器读取开销估计和日志溢出；开销只能估计，不能直接逐槽减去得到“真实 RF 时间”。修改驱动时用宏或可选观测入口限制到控制实验，不改变旧性能发送语义。所有 FreeRTOS 修改同步 SDK；语法检查由软件侧完成，构建/上板由实验者执行。

### 3.2 主机：时间保持分析器

扩展现有 `python/control_match/holdover_analyze.py`，保留旧配置的可复查入口，新版必须支持：

- 显式 run、period、slot 清单和混合 command_id；读取完整板端计划核对，而非固定 300 槽/200 ms/command_id=0。
- 使用各侧 `sample_start`、`available_sample`、实际 sample_rate 与有效校验记录；按可用顺序回放。验证包不得先更新再评分；预先保留的探测包永不进入模型。
- 固定偏移、仿射估频后冻结、因果周期更新三类模型；输出真实训练槽集合、跨度、速率、更新时间、更新年龄及未就绪原因。
- 无共同训练包的独立训练模式；只有独立解码完成后，才按同槽探测包关联评价。
- 区分本侧自然缺失、训练观察掩码、探测缺失、训练不足和质量不明。不得按结果好坏重新挑选训练/验证槽。
- 逐槽连接板端诊断，导出 CSV/JSON、配置/输入/源码哈希及报告，不覆盖旧分析。

现有 holdover 脚本尚不能直接对本方案运行；本文件不提供未实现的 CLI。实现后须把最终可复制分析命令补入本文件，再开始正式分析。

### 3.3 跟随观测：优先核查，不预设可测时间精度

扩展 std_ble 的逐事件记录：primary 候选/CRC/字段、切频请求/返回、窗口进入/退出、secondary 候选/CRC/应用校验、匹配、返回扫描、队列/流重置及调谐错误。主机时间仅计算这些软件阶段的耗时。

如保存 IQ 片段，附信道、流内计数器、切频前后范围和不可观测间隙。即使样本计数单调也不自动证明设备连续采样；无法界定切频丢样或重启间隙时，明确输出 `timeline_unverified`，禁止把多段 IQ 拼成连续 RF 时间轴。不能实现可靠时间轴不阻塞 N3 固定频点主实验；跟随能力审计及未知项说明仍是必交付。

### 3.4 软件验收

测试至少覆盖：500 ms/300 槽纯更新时间和 500 ms/120 槽混合任务；延迟可用的历史包不能提前用于预测；探测包不进入更新；缺失、不足、重复及冲突记录；缺失板端字段不回填；零样本为 N/A；同频 472 µs 位置补偿只用于对应共包布局。合成漂移/跳变测试只标为算法测试，不计入物理实验数量。

## 4. 预登记采集矩阵

Run ID 为预留，若已使用则换新 ID。先核对设备序列号，不用设备索引猜测角色。

| 顺序 | 数据/Run | 发射与接收 | 目的及执行条件 |
| --- | --- | --- | --- |
| S0 | 复用 2101、2102、2103 | 不新增 RF 实验 | 软件适配/探索、已有 DMA 括号与跟随阶段核查，结果不用于调参后再声称独立验证 |
| S1 | 2201（必做） | 模式 1，共包跨信道；BLE 固定 ch3、IEEE 固定 ch12，各 4 Msps | 300 槽×500 ms=150 s，纯更新时间；完整新板端取时与两侧 IQ，N3-A/B 主样本 |
| S2 | 2202（条件对照） | 诊断同频共包；两侧固定对应频率 | 若归因需要比较切频，必须先实现与 S1 相同 AuxOffset、周期、负载和准备策略的配置，再采集 |
| S3 | 2203（必做能力核查；新增采集待诊断实现） | 模式 1 共包；BLE 实际跟随 8 Msps、IEEE 固定 ch12 4 Msps | 沿用 N1 的 120 槽三任务，检查阶段与时间轴；不作为 S1 的同配置误差对照 |
| S4 | 2204（条件优化验证） | 与 S1 一致，仅改变一项已证实的软件准备策略 | 仅在 S1 定位到可处理的软件阶段后开展；冻结改动与评价规则，再采集新验证轮 |

S2 不是简单把现有启动命令末尾改成 0：当前模式 0 的 AuxOffset 为 30 ms，模式 1 为 300 ms，还可能改变频率和信道响应。未经匹配只能称配置间比较，不能分离纯切频因果。若不作切频因果主张，允许 S2 暂缓并将原因未定写入报告。

S4 不默认实施“提前刷新”；必须检查缓存一致性、波形缓冲生命周期及 DMA 提交安全性。保留未优化结果；不在同一验证段反复选取最优版本。

## 5. S1 可用的采集命令

以下命令使用现有接口；但应在第 3 节软件和新固件准备完成后用于正式 N3。根目录运行，先 `hackrf_info`；保持 N2 接线及增益，有调整则记录原因。两接收器各录制 180 s，先在约 10 s 内启动两侧，随后约 5 s 内启动发送；观察边界不足则保留该轮但不能按全轮统计。

串口先准备任务：

```text
b2z_plan_clear?
b2z_plan_add? 0 300 0 0
```

终端 A：

```bash
python3 python/exadv_rx/receive.py --run-id 2201 --channels 3 \
  --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 \
  --duration 180 --save-iq --quiet
```

终端 B：

```bash
python3 python/zigbee_rx/control_receive.py --run-id 2201 --channel 12 \
  --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --expected-packets 300 \
  --duration 180 --save-iq --quiet
```

两侧开始接收后串口启动：

```text
b2z_plan_start? 2201 500 1
```

不填写假设参考界，也不打开定时执行。默认按运行日和 Run ID 自动建目录，约保存两份各 1.44 GB 的 ci8 IQ。保存完整串口内容，直到所有逐槽/逐突发/新增诊断行输出结束；不要在接收进程结束时截断串口日志。

基础完整性分析使用现有入口，日期按实际修改：

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261111_run2201 \
  --run-id 2201 --analysis-id n3_integrity
```

本轮 command_id=0，无控制任务，因此任务成功率和单位成功任务成本为 N/A，这是设计结果。真正时间评价须等新版 holdover 和诊断分析器就绪，不能拿这个联合报告代替。

S3 三任务准备和接收沿用 [N1 指令](n1_cross_channel_experiment_plan.md)，run_id 改为 2203、发送模式仍为 1、BLE payload-mode 为 joint；使用补齐诊断后的 std_ble。不要照搬 2103 的 `rf_mode=2` 或 `--payload-mode ble-only`。新诊断命令行参数在实现后补充。

## 6. 时间参考、模型及留出规则

### 6.1 参考点与可报告的误差

共包参考点统一为 BLE secondary 前导码起点。BLE 用本侧采样索引；IEEE 从本侧 PHY 前导码索引减去当前格式的已知 472 µs 包内位置偏移。记录这一偏移的格式依据；滤波/检测器固定偏差仍未知，不能因此宣称 RF 标记已校准。

令计划时间 `T_s = slot_index × 500 ms`，本侧样本标记为 `x_i(s)`，历史拟合 `x_i ≈ a_i + b_i T`。报告：

- 本侧预测残差 `(x_i(s) − predicted_x_i(s)) / (sample_rate_i / 1000)`，单位 ms；同时保存原始样本残差。
- 本侧逆映射计划时间估计 `T_hat_i(s) = (x_i(s) − a_i) / b_i`。
- 同一探测包上 `T_hat_ble(s) − T_hat_ieee(s)`：命名为“双侧相对时间估计差”，不是两个真实本地时钟的绝对偏差。

共同包在这里仅是后验探测事件，不逐包平移/拉伸两侧 IQ，不重新拟合验证段。共同发射抖动可能在双侧差中抵消，所以必须同时报告两个单侧残差。计划时间到实际 RF 的偏差、采集起点和未知固定延迟不由这些量独立确定。

### 6.2 S1 的主训练/探测划分

在看 2201 结果前冻结如下规则，全部选择写入配置文件：

- 初始训练区间：槽 0–59，计划跨度约 30 s。后续评价区间槽 60–299，约 120 s。
- 固定探测槽：评价区间内 `slot % 10 == 9`，共 24 个，每 5 s 一个；任何模型均不能使用这些包更新。自然缺失保留分母，不用邻包替换。
- 不同包训练主模式：BLE 用训练区间偶数槽、IEEE 用奇数槽；各自独立恢复，无需两侧收到相同或相邻训练包。
- 历史包数 N=2/4/8/16。冻结模型在各侧预定候选跨度内选等间隔槽，取整规则与具体清单在采集前由配置生成并保存；缺包时标训练不足，不按残差选替代包。两侧实际端点可能相差 500 ms，须报告真实跨度。
- 固定偏移基线：使用预定训练区间末端的一个有效指定包和标称采样率；指定包缺失则模型未就绪。仿射模型：使用上述 N 个包估偏移/速率并冻结。
- 周期更新主配置 N=8，目标更新间隔 1/5/10 s，即每 2/10/20 槽。槽 60 起按周期安排 BLE 候选，IEEE 候选延后一槽，保持两侧不同包；排除探测槽。只使用已经解码可用的历史记录更新，使用最近 N 个合格记录，记录实际更新年龄。
- 不把 N 与跨度混为一个因素：主 N 扫描固定约 30 s 候选跨度；另以 N=8 比较约 10/20/30 s 初始跨度。缺包或跨度不能满足的配置标未就绪。

所有预测必须基于探测包到达之前已可用的记录。探测包的到达标记仅用于评分/审计可用性，不允许用其内容或时间拟合当前模型。离线回放不冒充在线实时结果。

### 6.3 保持和失更观察

冻结模型按探测时刻报告更新年龄，分箱 0–10、10–30、30–60、60–120 s；右边界规则在配置中固定，尾部超界另列。周期更新模型另做 5/15/30 s 的禁止更新区间，统一从槽 120 开始，分别屏蔽候选训练槽 120–129、120–149、120–179；探测包保留评分且永不训练。

这些是同一录制上的离线更新掩码，不是三个新实验，也不是真实 RF 丢包。真实丢包仍按原始记录保留，不保证每个区间都可评分。N5 再评价真实失更的在线状态与恢复。

## 7. N3-B：逐槽软件延迟与残差关联

按 `(run_id, slot_index)` 连接板端新日志、各侧事件及残差。输出两套分母：全部 300 计划槽的发送/接收统计；24 个预定探测槽的评价覆盖率。

1. 每个软件阶段给出原始耗时/偏差、相邻槽差值、n、min、中位数、P95、P99、max及时间轨迹；有符号偏差与绝对值不混报。
2. 逐侧报告相邻有效包间隔相对 `Δslot × period` 的偏差；缺包不当作相邻槽。保存 IQ 异常、检测质量和主机队列记录。
3. 同时看单侧残差与双侧相对差；固定生成偏置、速率趋势和离散跳变分别讨论。模型训练中包含异常时，保留训练清单以解释其后续影响。
4. 对阶段耗时、late及其变化量与残差做散点/秩相关等探索。每对关联报告可配对 n 和缺失原因，避免在少量尾部样本上作因果断言。
5. 不逐验证槽减去板端 late 再宣称同步改善；板端串口事后记录对无线接收端不可因果获得。若提出补偿，另行定义包内可用信息、软件修改及新验证集。

S2/S4 只在解释需要时做匹配条件干预。不能区分 RF 起点、接收固定延迟或不透明 USB 间隙时，将它们留在未知误差预算中。

## 8. 输出、判定与失败处理

每轮输出：

- `notes.md`：接线图/描述、实际 TX 配置、接收条件、固件构建/哈希、操作顺序及异常；不只写主机源码版本。
- 完整板端日志、两侧原始事件与关键 IQ；跟随 IQ如不能保存，明确缺失及影响。
- `analyses/n3_integrity/`：板端与独立解码完整性；纯时间实验任务率为 N/A。
- 拟新增 `analyses/n3_holdover/`：冻结的配置、逐探测槽模型/训练清单/残差 CSV、汇总 JSON、CDF与年龄曲线。
- 拟新增 `analyses/n3_timing/`：逐突发阶段 CSV、逐槽关联表、分布/轨迹/未知原因及误差预算。
- 跟随报告：逐阶段条件计数和互斥结果类别；`timeline_unverified` 时不输出 RF 精度。

汇总须报告有符号偏差、绝对残差中位数/P95/P99/max、CDF、有效 n、缺失数、模型未就绪数。24 个探测点只够首轮功能检查，P99不稳定且接近最大值，不能声称尾部保证。后续增加独立轮次/延长冻结配置录制，采用轮次或相关块统计，不把模型扫描结果当独立样本。

候选主容差 50 ms，敏感性 10/100 ms，只用于“相对估计差/预测残差”的描述。另报阈内且可评价数/24及条件阈内数/有效数；缺失单列，前者也不能命名同步执行成功率。若超阈，应如实报告适用范围，不事后放宽阈值让初验通过。

首轮完成条件：新取时可审计；至少有一个预登记冻结配置和周期更新配置在训练区间之后获得两侧独立探测记录；同时报告全计划缺失与时序异常；完成跨信道保持、软件时延关联和跟随时间轴能力审计。数据不足时只针对缺失环节补采，不删掉失败轮。硬件未知误差界、真实 RF 起点与执行器动作列为未测，不阻塞进入 N4/N5。

## 9. 实施顺序

1. 先适配 holdover，并用 2101 验证混合任务、500 ms 和可用时间因果性；保留探索标签。
2. 实现板端取时及解析、跟随阶段诊断，完成主机测试、SDK 同步和固件构建；冻结新字段/配置及分析命令。
3. 采集 2201，先完整性检查，再按冻结规则输出 N3-A/N3-B；不先看残差再挑训练包。
4. 用已有跟随记录完成能力审计；诊断功能就绪后采集 2203，更新阶段失败和时间轴边界，不强求无硬件条件下无法测得的量。
5. 有明确假设才开展 2202/2204；汇总首轮结论后推进 N4/N5，主配置重复集中后续进行。

## 10. 板端实现状态与日志接口（2026-11-11）

板端取时已实现，主机时间保持/诊断分析适配仍待完成。命令不变，使用 `b2z_plan_start? 2201 500 1`；只有 plan 实验输出新诊断，单任务 control 和旧性能入口不启用此次诊断。默认 `B2Z_N3_TRACE_ENABLED=1`，编译时置 0 可禁用；禁用轮须单独记录固件版本，不与开启轮混用。

新增记录在原有计划、逐槽和突发日志之后输出：

| 日志 | 内容 |
| --- | --- |
| `CONTROL_TIME_META` | schema=1、enabled、tick_hz、epoch_ticks、容量、overflow、32 次相邻计数器读取差的 min/max；该差不等于完整插桩开销 |
| `CONTROL_TIME_SLOT` | 槽计划时刻、旧 primary 调用前 anchor、anchor+AuxOffset target；frame/mapping/GFSK 的既有生成器统计 |
| `CONTROL_TIME_STAGE` | run/slot/kind/stage、before_ticks/after_ticks、valid、status、remaining_bytes |
| `CONTROL_TIME_LATE` | secondary 调用前/提交写入前/函数返回后的有符号偏差，目标均为旧 primary anchor+AuxOffset；各有独立 valid |
| `CONTROL_TIME_END` | 输出结束标记、计划槽数和 overflow |

时戳为 **16 位十六进制文本表示的原始 64 位 tick**（没有 `0x`），先按十六进制解析，再用 `(tick - epoch_ticks) / tick_hz` 转为本轮秒数；其他计数/状态为十进制。禁止将原始时戳作为浮点数相减后才减 epoch。板端计数器低 32 位回绕不影响完整记录。

kind：0 primary、1 secondary、2 独立 IEEE、3 本槽生成/切频。模式 0/1 不输出 kind=2。stage 包括 call、stop_clear、cache_flush、dac_sync、submit_write、poll、generation、retune_secondary、retune_primary。每阶段 valid 的 bit0 表示 before 有效、bit1 表示 after 有效；valid=0 表示未观测，绝非耗时为零。status 仅在 after 有效时解释：call/poll/generation/retune 是函数返回值；submit_write 是写寄存器返回值；stop_clear 是清中断状态写入返回值，停止接口无返回值；cache_flush 和 dac_sync 接口无返回值，0 仅表示调用返回，不代表硬件验证通过。

`remaining_bytes` 是启动函数返回时尚待后续分段提交的字节数，仅 kind=0/1/2 有意义。submit_write 仅覆盖本次启动中的**第一次提交写入**，不涵盖驱动后续分段续传；若 remaining_bytes 非零，不能将这一对时刻视作完整波形的全部提交事件，分析中须单列。驱动原有返回语义保留，写入错误可由新 status 发现，不能仅凭旧 tx_started 判断写入成功。

新 late 是相对软件目标的有符号偏差，可为负；原 `secondary_dma_late_us` 和 `auxptr_dma_window_miss` 保持旧语义。需要比较同位置的 primary→secondary 间隔时，分别减两者相同 stage 的 before 或 after，并减 AuxOffset；不能混用 `anchor` 与提交后时刻。主机分析器尚需实现这些派生指标。

缓冲容量为 1024 槽，当前新增 trace 与 anchor 缓冲约 0.8 MiB，使用静态 DDR，不使用 FreeRTOS 堆。超界访问计入 overflow；分析必须拒绝把 overflow 非零当作完整诊断。正常取时路径不增加串口输出；既有 DMA 超时路径的打印仍保留，poll 耗时可能包含该诊断输出，超时样本不可并入正常耗时而不作标记。

300 槽共包轮新增约 5102 行日志（4500 阶段、300 槽、300 late、meta/end），完整串口输出可能持续一分钟以上。**接收完成后仍应继续保存串口，直到 CONTROL_TIME_END**，不能在旧 CONTROL_COST_STATS 处停止。保存路径仍是本轮 `board.board.log`。

已验证 ARM GCC 语法、真实 DMA 启动代码在模拟 MMIO 下的正常/队列满/零长度/不支持模式/写入失败/分段行为，以及原始 tick 格式化跨低位回绕。实际调度开销、RF 接收与时间分布仍待构建上板；不得将主机测试写成硬件通过。板端源码及驱动已同步 SDK 实际编译目录。

## 11. 主机实现与最终分析命令（2026-11-11）

主机适配已完成。新增 `n3_analyze.py` 统一执行固定 IQ 完整性、因果时间保持、软件取时与逐槽关联；`n3_follow_analyze.py` 单独审计跟随阶段。旧 `holdover_analyze.py` 不带 `--config` 时仍执行历史 300 槽/200 ms 方法；指定新配置时委托 N3 分析，不能把两种方法的结果混为同一算法版本。

### 11.1 正式配置先冻结

已提供 `python/control_match/configs/n3_2201.json`：300 槽、500 ms、24 个固定探测槽，包含全部初始训练清单、更新候选清单和离线掩码。初始等间隔取样使用 `floor(i*(len(pool)-1)/(N-1))`，N=1 取末端锚点。不得看过 2201 残差后修改此配置再声称预登记验证。

另有 `n3_2101_exploratory.json`，明确标为探索性，120 槽/6 个探测点；用于历史混合任务适配，不增加物理重复轮数。需要另存一份新配置时执行：

```bash
python3 python/control_match/n3_analyze.py \
  --write-config /tmp/n3_2201_copy.json --slots 300 --period-ms 500
```

生成器不会覆盖已有文件；非默认周期/自定义实验需显式编辑并核对 JSON，不会自动猜测训练规则。

### 11.2 2201 固定频点分析

按第 5 节完成录制与完整串口保存后，从根目录运行（日期按实际执行日修改）：

```bash
python3 python/control_match/n3_analyze.py \
  --experiment-dir python/experiments/20261111_run2201 --run-id 2201 \
  --config python/control_match/configs/n3_2201.json \
  --output-dir python/experiments/20261111_run2201/analyses/n3_full
```

默认读取实验根目录的 `board.board.log`，自动发现唯一完整 BLE/IEEE 包流；多个采集候选时用 `--ble-packets`、`--zigbee-packets` 明确指定，不能混合多轮。新实验不得加 `--allow-legacy-timing` 来掩盖日志截断：缺少 META/END、重复阶段、溢出、无效 tick、目标不符或新日志不完整均会拒绝。

该入口同时产生联合完整性结果（JSON 的 integrity）；独立运行原 `plan_analyze.py` 可获得其原有 Markdown，但不必为了 N3 重复执行。输出目录必须尚不存在。

输出包括：

| 文件 | 含义 |
| --- | --- |
| `n3.report.md` / `n3.summary.json` | 概览、完整配置、接收质量、源码和输入哈希、限制 |
| `holdover.validation.csv` | 每策略每探测槽的本侧状态、训练槽、样本域模型、跨度、年龄、速率和误差 |
| `holdover.summary.csv` / `holdover.age.csv` | 单侧及相对差分布、阈内分子和两种分母、更新年龄分箱 |
| `timing.stages.csv` / `timing.slots.csv` | 原始 tick、有效掩码、阶段耗时、同位置 primary→secondary 间隔及软件偏差 |
| `timing.summary.csv` / `timing.qc.csv` | 软件分布与相邻槽差、相邻有效包间隔和本侧检测质量 |
| `timing.joined.csv` / `timing.associations.csv` | 按槽连接的预测与板端记录，描述性 Spearman 相关及缺失数 |
| `holdover.cdf.png` / `holdover.age.png` / `timing.trace.png` | 条件 CDF、残差随更新年龄、软件时延轨迹 |

任何一侧探测缺失时，该侧及相对差不评分；另一侧仍可独立评分。可用历史必须满足本侧 `available_sample < probe.sample_start` 且属于显式训练清单，不允许使用探测包解码期间才可用的训练包。更新掩码只影响训练，探测始终留出。原始 sample_start 不单调、缺少 available_sample 或超出录制范围时拒绝，不自动修补时间轴。

### 11.3 已有样本探索性复核

已对 2101 运行并保存：

- [探索报告](../python/experiments/20261110_run2101/analyses/n3_exploratory_20261111/n3.report.md)：两侧各120条混合任务记录；6个探测点。仅用于工具适配，不能推断尾部分位数或选取最优策略。
- [2103 跟随能力审计](../python/experiments/20261110_run2103/analyses/n3_follow_audit_20261111/follow.audit.md)：75次成功、32槽无有效primary、13槽primary后缺失；旧日志细分阶段为未知，时间轴未验证。

2101 没有 N3 新取时，使用显式 `--allow-legacy-timing`，输出 `legacy_missing_stages`，保留已有逐槽 late，不用全轮均值回填。复核命令如下；已有输出不可覆盖，重跑时换一个分析目录：

```bash
python3 python/control_match/n3_analyze.py \
  --experiment-dir python/experiments/20261110_run2101 --run-id 2101 \
  --config python/control_match/configs/n3_2101_exploratory.json \
  --allow-legacy-timing \
  --output-dir python/experiments/20261110_run2101/analyses/n3_exploratory_review
```

### 11.4 跟随诊断和 2203

std_ble 原有运行命令不变，新版本默认记录 `tune_request/return/error`、`packet_dequeued`、窗口进入/退出、字段/身份校验失败和流 generation。调谐返回包含驱动返回频率，**不代表硬件锁定时刻**；跨 generation 的旧队列包单列丢弃，避免跨切频周期混配。

CRC候选计数仅统计已取得完整候选长度并计算CRC的情况；不代表所有 RF 包或所有前导码候选。没有有效身份的失败不能指定到某个计划槽，仍保持未知。流计数单位是解调后打包字节，不是IQ采样点。当前不保存跟随 IQ，不声称已解决切频间隙测量；`timeline_unverified` 是能力审计的明确结果。

2203 沿用 N1 三任务清单（120 槽），两侧接收启动后串口使用 `b2z_plan_start? 2203 500 1`。BLE 接收命令：

```bash
python3 python/std_ble/verify_board_exadv.py \
  --run-id 2203 --expected-attempts 120 --period-ms 500 --payload-mode joint \
  --osmosdr-args hackrf=0 --sample-rate 8000000 --if-gain 16 --bb-gain 10 --duration 90
```

核对索引0是BLE设备；IEEE使用第5节接收命令，run_id改2203、expected-packets改120、duration改90。默认joint布局，不使用separate。跟随侧不能接入固定IQ时间保持工具。

完成后，先按 N1 的 `plan_analyze.py --ble-flow` 联合分析，再审计阶段（替换实际日期和flow路径）：

```bash
python3 python/control_match/n3_follow_analyze.py \
  --flow /实际路径/flow.events.jsonl \
  --board-log python/experiments/20261111_run2203/board.board.log \
  --run-id 2203 \
  --output-dir python/experiments/20261111_run2203/analyses/n3_follow_audit
```

输出逐槽互斥分类和阶段计数、主机队列/切频分布与未知项。capture中断或错误必须先排查，不能把不完整流作为完成的联合验证。上述软件已经完成本地测试和历史数据适配；新增实时诊断仍需2203现场验证，不算已获得的新RF证据。
