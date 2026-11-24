# UC1 论文大纲复核：四处修正意见

2026-11-24。当前六节大纲可以进入正文写作。以下四处修订均可依据现有协议、日志和冻结结果完成。

## 1. 优先修正 H5 恢复耗时的起止事件和干预方式

方法节 IV-B1 和结果节 V-C1 应统一写明：2716 人工断开 BLE 侧馈线，2717 人工断开 IEEE 侧馈线，两轮均采用 R0 馈线直连拓扑。现场笔记记录的是干预的大致包序范围。恢复耗时取自受干预接收机的本侧 IQ 采样索引，起止点由状态转换确定。[方法节 IV-B1](sections/04-prototype-methodology.tex#L29) · [结果节 V-C1](sections/05-evaluation.tex#L69) · [2716 现场记录](../python/experiments/20261120_run2716/notes.md#L6) · [2717 现场记录](../python/experiments/20261120_run2717/notes.md#L6)

| 实验 | 受干预侧 | 进入 `stale` 至恢复 `tracking` | 其中，从首次进入 `reacquiring` 至恢复 `tracking` |
| --- | --- | ---: | ---: |
| 2716 | BLE | 23.0 s | 7.0 s |
| 2717 | IEEE | 24.0 s | 9.0 s |

建议用表中两个状态区间替换“覆盖人工断开至重连全过程”的解释。两段计时共用恢复 `tracking` 这一终点，每轮重获阶段均收集了 8 个训练包。[计时实现](../python/control_match/n5_analyze.py#L60) · [P2 恢复审计](../doc/results/uc1_p2_2701_2718_review_20261120.md#L78)

## 2. 为 VI-P1 的 LC 单次成本补全负载条件

`b≤1` 决定 BLE 记录能否由一个 legacy 广播直接承载。一次完整尝试还包含独立 IEEE 突发，其波形成本随 IEEE 扩展长度 `z` 变化。建议将 VI-P1 中的括号改为“在 A 点 `(b,z)=(0,0)` 和 B1 点 `(1,0)`，LC 单次尝试的波形成本分别为 1456 µs 和 1464 µs”。这样两项数值都明确限定在 `z=0`。[讨论节 VI-P1](sections/06-discussion-conclusion.tex#L13) · [成本公式](sections/03-protocol-design.tex#L44) · [预算表](tables/tab-budget.tex#L20)

## 3. 按测点对齐摘要提纲中的同 IQ 偏移中位数

摘要第三句的写作注释按 A、B、C 列出完整记录对，偏移中位数却按 A、C、B 排列。建议在注释中逐点配对：**A（26/26 B）为 400.25 µs，B（52/26 B）为 608.00 µs，C（28/32 B）为 416.25 µs**。记录长度均按 BLE/IEEE 排列。当前排版摘要仅给出偏移公式，本处修正针对写作注释。[摘要提纲](main.tex#L87) · [同 IQ 实测结果](sections/05-evaluation.tex#L16)

## 4. 补全 P3 采集质量门槛的英文表述

方法节 IV-B1 中的 `zero queue overflow or significant clipping` 遗漏了采集截断，也使削顶条件的含义不清。建议改为 **“no queue overflows, no capture truncation, and no significant clipping”**。其中 *significant* 对应原计划按削顶占比及伴随异常判定显著饱和的规则。按该口径，0.10 m 条件仍满足入选要求。[方法节 IV-B1](sections/04-prototype-methodology.tex#L30) · [P3 入选规则](../doc/plans/uc1_post_p2_experiment_plan.md#L15) · [P3 条件冻结记录](../doc/results/uc1_p3_r1_freeze_20261123.md)
