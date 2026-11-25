# UC1 英文论文内容审计意见

审阅日期为 2026-11-25。审阅对象为 `paper/` 下的英文摘要、六节正文和图表说明，核查依据为中文审阅稿、UC1 协议定义及 P5 冻结数据。

**审计结论：英文稿的主要实验结果与冻结数据一致。** 同频 JC 相对 SC 将每次尝试从 3 个突发减至 2 个；在短负载 A 点的 6 ms 波形预算上限下，JC 的合并单位成功任务成本比 LC 低 14.8%；在长负载 B 点的同一上限下，JC 和 LC 分别联合解析 291/300 和 93/300 项任务。以下七处建议均可依据现有记录完成修订，无需补采。[P5 冻结结果](../results/uc1_p5_frozen_results_20261124.md#L111)

## 优先修正

### 1. 摘要明确波形成本的口径与长负载对照的信道

“At the same waveform duration” 容易被读作实测 RF 发射时长相等。JC 与 SC 相等的是每次尝试的提交波形时长。长负载结果后的 “in the tested channel configurations” 也应明确给出 BLE 信道，使只读摘要的读者能判断 291/300 与 93/300 的适用条件。[英文摘要](../../paper/main.tex#L53)

建议分别写为：

> At the same submitted waveform duration per attempt, co-packaging reduced the burst count from three to two relative to separate co-channel transmission.
>
> Under the 6-ms cap, joint resolution was 291/300 for co-packaging on BLE channel 3 and 93/300 for legacy advertising on channel 39.

### 2. 区分 500 ms 的槽周期与 P4 新任务的启动间隔

“Broadcasts periodic control tasks at slot period … 500 ms” 容易让读者理解为每 500 ms 产生一项新任务。P4 板端计划中，相邻任务的首槽依次为 10、16、22，间隔 6 槽，即 3 s。建议分别说明槽调度和任务调度。[英文协议设计](../../paper/sections/03-protocol-design.tex#L12) · [P4 板端计划](../../python/experiments/20261123_run2731/board.board.log#L3)

> The transmitter schedules attempts in 500-ms slots. In P4, successive logical tasks start six slots apart (3 s).

### 3. 将 K 定义为总尝试次数，明确每次尝试保留哪些内容

“Across K open-loop retries, payload bytes … stay fixed” 包含两处歧义。K 包含首次发送，K=1 表示只发一次。各次尝试保持本侧应用命令内容及绝对有效期和目标处理时刻 V/E；槽号和相对时间偏移会更新，因此整条记录的空口字节会变化。[英文重发语义](../../paper/sections/03-protocol-design.tex#L41) · [协议定义](../reference/unified_compact_protocol_proposal.md#L63)

> Across the K planned attempts, each side’s application command content and the absolute validity and execution targets remain unchanged. Each attempt carries its own slot index and recomputed relative offsets.

### 4. 时间结果使用绝对误差，并说明 0/6 是软件判定

表 III 报告本侧预测误差绝对值 `|e|` 的中位数和 P95。正文 “local IQ prediction residuals” 未指明取绝对值，容易被理解为有符号残差的中位数。“Timed execution remains 0/6” 又容易暗示实验观测了物理执行器。建议在正文和表 III 脚注统一使用以下口径。[时间结果](../../paper/sections/05-evaluation.tex#L30) · [表 III](../../paper/tables/tab-p2-time.tex#L16)

> We report the median and 95th percentile of the absolute local IQ prediction error.
>
> In each run, 0/6 planned tasks qualified for timed software processing because the external RF reference bound was uncalibrated.

## 其他内容修正

### 5. 区分 20 B 外层总开销与 15 B 的 C3 分片头

“C3 prepends 20 B outer framing and a 15 B fragment header” 将全部 20 B 外层开销都放在了记录前面。其中 3 B 是位于帧尾的 BLE CRC。当前成本公式正确，修正字节布局描述即可。[英文协议设计](../../paper/sections/03-protocol-design.tex#L29) · [成本拆分依据](../reference/unified_compact_protocol_proposal.md#L158)

> Each fragment incurs 20 B of legacy framing overhead and carries a 15-B C3 header followed by up to 12 B of record data.

### 6. 将 C3 重组限定到 LC 模式的 BLE 接收链

“Each chain independently checks outer framing, C3 reassembly …” 把 C3 重组列为两条接收链的共同步骤。两侧均独立校验各自的记录；LC 的 BLE 侧在启用分片时还需先在同一尝试内集齐分片。建议先列出共有的校验步骤，再单独交代重组条件。[英文方法节](../../paper/sections/04-prototype-methodology.tex#L7)

> Each chain independently validates its outer framing, UC1 header, and record CRC. For fragmented LC records, the BLE chain first reassembles all C3 fragments from the same attempt.

### 7. 分开说明估计精度与信道混杂

讨论节将增加区组数和控制信道并列为两个问题的补救措施。增加区组有助于估计精度；若 JC 始终用 ch3、LC 始终用 ch39，则增加同配置重复仍无法区分格式和载频的影响。建议分句说明各项设计改动具体能回答什么。[英文讨论](../../paper/sections/06-discussion-conclusion.tex#L5)

> Additional blocks could improve precision. Isolating the format effect would require controlling or independently varying the BLE channel.

摘要可保留现有的研究提问，以及短负载在 6 ms 上限下由四次与三次开环发送导致成本排序翻转的解释。这两句能帮助读者理解研究发现适用于怎样的任务和重发策略。
