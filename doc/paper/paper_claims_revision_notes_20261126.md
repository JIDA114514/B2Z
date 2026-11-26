# 四页英文稿宣称与实验证据修订清单

2026-11-26。按论文出现顺序整理。投稿前优先修订第四、五节中涉及性能匹配、分片因果归因和逐区组成本的句子，并将相同口径同步到摘要。[P5 冻结结果与逐轮数据](../results/uc1_p5_frozen_results_20261124.md)

## 摘要

- [x] **改写研究设问。** `normally requires sequential bursts and multi-frame legacy fragmentation` 把分片写成了一般要求，但 A 点的 26 B 和 B1 点的 27 B 记录均可直接承载。`remain unquantified` 也超出已核查的前作范围。可合并为一句：*For a single transmitter serving Bluetooth Low Energy and IEEE 802.15.4 receivers, how do encapsulation and retry policy affect the waveform cost per jointly resolved task?*
- [x] **明确 14.8% 的比较对象。** `a 6-ms cap forces four legacy attempts` 应写出开环策略。14.8% 是同一策略下共包相对 legacy 的合并单位成功成本降幅。建议：*Under the 6-ms open-loop policy, co-packaging used three attempts and legacy advertising used four. The pooled waveform cost per jointly resolved task was 14.8% lower for co-packaging.*
- [x] **分开报告封装与无线观测。** 拆开 `avoids five-fragment reassembly, achieving …`。建议：*Co-packaging carried the 52-byte Bluetooth Low Energy record in one secondary packet, while legacy advertising required five fragments. Under the 6-ms cap, joint resolution was 291/300 on channel 3 for co-packaging and 93/300 on channel 39 for legacy advertising.*

[摘要源文件](../../paper/main.tex)

## 第一节 · 引言与贡献

- [x] **收准前作与研究空白。** 将同时修饰 X-Sync 和 TimeBee 的 `bidirectional external-reference clock synchronization` 收为 *cross-technology clock synchronization*。已有 TimeBee 核查只支持其研究方向。引言中的 `prior work does not quantify` 可同步改为本文具体比较的对象，例如 *We quantify encapsulation cost, retry behavior under a common waveform budget, and complete legacy reassembly when both receivers must validate their commands.* [前作核查表](prior_work_fulltext_comparison_20261124.md)
- [x] **用观测量写出分片贡献。** 将 `quantify … fragmentation loss` 中有关分片的部分改为 *quantify fragment reception, complete reassembly, and joint resolution in the tested legacy configuration*。日志能区分上述三个环节，信道与封装共同变化的实验无法分离格式造成的损失。[引言源文件](../../paper/sections/01-introduction.tex)

## 第二节 · 协议与成本模型

- [x] 将 `K=1 denotes a single transmission` 改为 *K = 1 denotes one scheduled attempt*。图 1 的长负载条件下，一次尝试分别包含 2、3 或 6 个突发。
- [x] 将 `slot timestamp … marks the secondary BLE preamble` 改为 *The slot timestamp refers to the scheduled start of the secondary BLE preamble.* 时间字段采用计划参考点；同 IQ 验证测得的是包内相对位置。
- [x] 将 `missing or mismatched b disables timing` 改为 *Missing configuration or a detected layout mismatch disables timing.* IEEE 侧依赖预共享的 BLE 扩展长度，只有能被检测出的配置冲突才可触发拒绝。[第二节源文件](../../paper/sections/03-protocol-design.tex) · [协议设计基准](../reference/unified_compact_protocol_proposal.md)

## 第三节与表 2 · 成功指标

- [x] 将方法中的 `within-attempt metrics` 和表注中的 `within-attempt dual-chain decoding` 统一为 *joint resolution within the planned attempts*。建议表注：*A task counts as jointly resolved when both receivers validate their respective records across up to K planned attempts.* 保留方法中 C3 各片须在同一次尝试内收齐的规则。B 点 6 ms 下，LC 的 93 个联合成功任务中有 7 个依靠两侧跨槽互补。[第三节源文件](../../paper/sections/04-prototype-methodology.tex) · [表 2 源文件](../../paper/tables/tab-p4-main.tex)

## 第四节 · 实验结果

| 待改表述 | 修改理由与建议英文 |
| --- | --- |
| A 点 `saturate at K=3` | 实验给出该策略下的成功数，未测定饱和所需的最小 K。改为 *Under the 6-ms policy, JC and SC each used three attempts and resolved 294/300 and 299/300 tasks, respectively.* |
| B 点 `Across all three independent blocks … outperforms … in joint resolution and unit cost` | 逐区组能够比较联合解析数；2743 的 LC 单轮单位成本为 N/A。改为 *Joint resolution was higher for ch3 JC than for ch39 LC in each of the three observed blocks under both policies. Pooled unit cost was 76.9% lower at K = 1 and 69.4% lower under the 6-ms cap.* 保留三区组配对差的置信区间。 |
| 2743 的 `losing at least one fragment per attempt prevented all reassembly` | 直接描述有效分片与完整集合。建议：*The BLE receiver logged 210 valid fragments across 200 attempts, but no attempt yielded a complete five-fragment set.* 保留同轮 IEEE 成功 98/100 和联合成功 0/100。 |
| JC 与 SC 的 `matching … within −2.33 to +7.33 pp` | 这两个端点是四个条件的区组平均差范围。B 点单次尝试的 95% 区间达到 [−17.55, +32.22] pp，无法据此主张等效或非劣。改为 *Across the four conditions, mean paired JC–SC differences ranged from −2.33 to +7.33 percentage points; all four confidence intervals included zero.* |
| `shifts losses … to coupled … outcomes` | 四分类为观测计数，未检验丢包耦合机制。改为 *At both tested loads under K = 1, JC had fewer BLE-only outcomes and more neither-side outcomes than SC.* |
| `each disrupted side … resolves 5/6 joint tasks` | 19/24 覆盖和 1/1 重获属于受扰侧，5/6 属于整轮双侧。改为 *In each disrupted run, the affected receiver covered 19/24 probes and recovered from its one in-schedule loss event. The two receivers jointly resolved 5/6 tasks.* |
| `0/6 executed per run` | 数据记录的是软件准入判定。改为 *In each run, 0/6 planned tasks qualified for timed software processing.* |

[第四节源文件](../../paper/sections/05-evaluation.tex) · [P2 时间支撑实验复核](../results/uc1_p2_2701_2718_review_20261120.md)

## 第五节 · 结论

- [x] **同频共包。** 将 `without losing joint resolution` 改为 *At equal submitted waveform duration per attempt, JC reduced the co-channel burst count from three to two. Across the four tested conditions, neither JC nor SC showed a consistent joint-resolution advantage.*
- [x] **短负载。** 将 `saturates … while forcing a fourth … attempt` 改为 *For short records, LC had the lowest pooled cost per jointly resolved task at one attempt. Under the 6-ms open-loop policy, JC and SC used three attempts and LC used four. Their pooled unit costs were 14.8% and 16.2% lower than LC’s, respectively.*
- [x] **长负载。** 将 `avoids five-fragment … fragility, raising joint resolution` 拆为结构结果和配置级观测。建议：*At 52 bytes, JC carried the BLE record in one secondary PDU, while LC required five fragments. Under the 6-ms cap, ch3 JC resolved 291/300 tasks and ch39 LC resolved 93/300. The comparison does not isolate the effect of fragmentation.* 若保留 69.4%–76.9% 降幅，按第四节分别标明策略及合并成本口径。[第五节源文件](../../paper/sections/06-discussion-conclusion.tex)
