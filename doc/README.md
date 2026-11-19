# 文档导航

更新：2026-11-19。先从本页了解进度，再进入对应方案或结果。实验原始数据统一在 [实验目录](../python/experiments/index.md)；计划中的预期不是实验结论。

## 当前入口

当前按用户确定的顺序推进：**确定最终论文目标 → 完成必要实现与实验 → 冻结结果 → 撰写论文**。UC1 修订版已接受为设计基准；当前围绕容量、成本与联合解析可靠性收敛，时间参考与失更管理作为支撑。具体确认性实验矩阵和投稿对象待定，收录与录用不是既定结果。

1. [当前论文决策与实验清单](paper/current_research_plan.md)：下一步要做什么、哪些选择尚未确认。
2. [查新报告审查](paper/novelty_ab_claims_review_20261118.md)：现有创新性与证据判断的纠正；与 [原始查新报告](paper/novelty_search_ab_claims_20261117.md) 配套阅读。
3. [均一 K 试采结果](results/n5_uniform_k_pilot_results.md)：2518–2520 为 K=5/3/1，各一轮；已看到重发挽回任务，尚未确认一般可靠性收益。

下一步执行入口：[UC1 论文主线实验计划](plans/uc1_paper_experiment_plan.md)。先实现并初验，再冻结后重复；旧 N1–N5 保留历史方案与结果。

## 实验方案与当前状态

方案保留制定时的任务、命令和预登记约束。历史“待实现”“下一轮”以本表及对应结果为背景阅读，不能直接复用已经占用的 Run ID。

| 入口 | 当前状态与证据 |
| --- | --- |
| [N1 跨信道双端](plans/n1_cross_channel_experiment_plan.md) | 2001–2003 已有跟随和双端任务解析；跟随覆盖不等于全槽成功 |
| [N2 分别发送对照](plans/n2_separate_transmission_experiment_plan.md) | 已有三组配对记录；减少发送操作、有效波形预算不变。见 [证据审查](paper/novelty_ab_claims_review_20261118.md) |
| [N3 时间参考](plans/n3_time_reference_experiment_plan.md) | 固定频点相对预测已有记录；2204 缺同期 IEEE；仅在新主张需要跟随双端验证时新建同轮补采，不作当前主线前置 |
| [N4 容量](plans/n4_capacity_experiment_plan.md) / [公平对照](plans/n4_fair_comparison_plan.md) | 容量与两层对照首轮完成；[两层结果](results/n4_two_layer_results.md)。等预算重发待实现、待实测 |
| [N5 机制](plans/n5_mechanism_experiment_plan.md) / [独立重复](plans/n5_independent_repeat_experiment_plan.md) | [2509–2517 结果](results/n5_independent_repeat_results.md)已形成机制覆盖；不再因已记录操作偏差补采该组 |
| [N5 任务规则消融](plans/n5_task_rule_ablation_execution_plan.md) | [首轮回放结果](results/n5_task_rule_ablation_results.md)已完成，含合成测试，不能当作新物理重复 |
| [N5 均一 K](plans/n5_uniform_k_experiment_plan.md) | 配置生成与三种 K 物理试采已跑通；[试采结果](results/n5_uniform_k_pilot_results.md)。确认性重复按论文目标决定排期 |

## 目录分工

| 目录 | 内容 |
| --- | --- |
| `paper/` | 论文目标、查新与证据判断；候选主张不等于已确认贡献 |
| `plans/` | N1–N5 具体实验方案、执行命令和验收约束 |
| `results/` | 经过核查的实验汇总与限制 |
| `reference/` | 包格式、架构评估、图片等技术资料 |
| `archive/` | 早期路线、旧阶段手册；保留设计历史，不作为当前任务入口 |

补充结果：[1201–1203 时间字段](results/sync_1201_1203_review.md)、[1703–1705 相对时间保持](results/holdover_1703_1705_review.md)。

技术资料：[v1 包格式](reference/control_sync_packet_v1_draft.md)、[接收架构评估](reference/receiver_architecture_review.md)、[早期负载调研](paper/sync_control_payload_research.md)、[BLE 5.1 规范](BLE_Core_v5.1.pdf)。规范 PDF 保留原路径，兼容项目指引。

已接受的设计基准：[统一紧凑协议 UC1 方案](reference/unified_compact_protocol_proposal.md)（2026-11-19）。固定布局配置下连接紧凑格式与在线机制；板端本地实现已完成，主机适配与实机验证待完成，不替代历史协议及实测结果。旧性能命令和可选扫描见[旧性能协议](reference/legacy_performance_protocol.md)。

历史入口：[原 N1–N5 总路线](archive/next_stage_plan.md)、[N3 前重复手册](archive/pre_n3_repetition_manual.md)、[功能路线](archive/control_sync_function_plan.md)、[多任务初验](archive/multi_task_control_experiment_plan.md)、[1801 连续更新时间与任务](archive/integrated_sync_control_experiment_plan.md)、[早期独立时间保持](archive/independent_sync_holdover_experiment_plan.md)。

## 维护约定

- 当前优先级只在 `paper/current_research_plan.md` 更新，阶段方案保存技术细节。
- 新结果写入 `results/` 并引用实际实验目录；原始配置、日志和预登记内容不事后改写。
- 历史报告发现错误时保留修订依据；原始查新报告须连同后续审查一起引用。
- 文档链接使用相对路径；移动时更新活动文档引用。根目录两个旧文件是历史引用兼容入口，没有重复正文。
- 本次整理移动 26 篇 Markdown 和 1 张图片；实验数据、实验索引及原始日志未改动。

板端实现进度：[UC1 板端接口与本地验证](reference/uc1_board_interface.md)，主机适配和实机验证待完成。
