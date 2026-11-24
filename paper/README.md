# B2Z UC1 5-Page English Short Paper Project

当前状态：**Stage-1 框架与逐段大纲已对齐 P5 冻结结果**（数据归档提交 `82d56a5`，汇总源 `python/experiments/p5_freeze_20261124/`）。
目标形态：**约 5 页英文短论文（Short Paper / Letter）**，当前采用 `IEEEtran` 双栏 `journal` 模式作为通用基准模板；确定具体目标期刊/会议后仅需调整 `main.tex` 顶部 `\documentclass` 与作者栏。

## 编译与清理

```bash
cd paper
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
# 输出：paper/build/main.pdf；清理中间文件：latexmk -C
```

## 5 页短论文结构与篇幅预算（总计约 5.0 页 / ~3,350 词 + 2 图 + 3 表）

| 文件 | 章节 | 目标页数 | 目标词数 | 图表配置 |
| --- | --- | :---: | :---: | --- |
| `main.tex` | Title + Abstract + Keywords | `0.35 p` | `150–180 w` | — |
| `sections/01-introduction.tex` | **I. Introduction**（4 段漏斗结构 + 3 条有界贡献） | `0.65 p` | `~530 w` | — |
| `sections/02-related-work.tex` | **II. Related Work and Scope Boundaries**（3 段，若投 4 页 Letter 可并入 Sec. I） | `0.45 p` | `~400 w` | — |
| `sections/03-protocol-design.tex` | **III. Co-Packaged Protocol and Baseline Encapsulations**（UC1/C3 布局、预算公式、`400+8b µs` 偏移与状态机） | `1.10 p` | `~720 w` | **Fig. 1** + **Table I** (`tables/tab-budget.tex`) |
| `sections/04-prototype-methodology.tex` | **IV. Dual-Chain SDR Prototype and Evaluation Methodology**（Zynq+双 HackRF 独立接收链、P2/P3/P4 矩阵与审计口径） | `0.65 p` | `~540 w` | — |
| `sections/05-evaluation.tex` | **V. Empirical Results**（P2 容量/同 IQ/H6 回放 → P4 36 轮/3,600 任务权衡 → P2 H5 时间与单侧恢复） | `1.35 p` | `~940 w` | **Table II** (`tables/tab-p4-main.tex`) + **Fig. 2** + **Table III** (`tables/tab-p2-time.tex`) |
| `sections/06-discussion-conclusion.tex` | **VI. Discussion, Limitations, and Conclusion**（适用域总结、有效性威胁与局限、结论） | `0.45 p` | `~400 w` | — |
| `refs.bib` | **References**（9 条已核验核心文献，区分全文核对与书目/摘要核对） | `0.30 p` | — | — |

## 统一宏与写作硬性红线（与 `AGENTS.md` 一致）

- **术语宏（定义于 `main.tex`）**：`\proto` (`UC1`)、`\fragproto` (`C3`)、`\modejc` (`JC`)、`\modesc` (`SC`)、`\modelc` (`LC`)、`\ble` (`BLE`)、`\stdfour` (`IEEE 802.15.4`)。**严禁**将本系统命名为 `BlueBee`（`BlueBee` 专指 Jiang et al. SenSys 2017 前作）。
- **严禁越界表述**：
  1. 不写 `"first"`（首次双协议广播 / 首次共包 / 首次无网关控制 / 首次单包同步）；
  2. 不写 `"statistically significant"`（`df=2` 三区组 95% $t$-CI 跨零且在小样本高方差下超出 $\pm 100\,\text{pp}$）或 `"equivalent"`（`JC vs SC` 写未观察到稳定联合解析优势）；
  3. `JC vs LC` 可靠性对比始终声明 **ch3 (2410 MHz) vs. ch39 (2480 MHz)** 封装+信道配置级边界；
  4. 截止期统一按 `2,730/3,600 unknown + 870/3,600 not_decoded` 披露，主指标固定为 `within planned attempts`；
  5. 波形成本明确为**提交设计波形代理时长（`µs`）**而非功率计实测 RF 空口时长或能耗；
  6. 时间支撑仅报告本侧 IQ 采样域留出预测残差与单侧失更恢复实例，不与 X-Sync 等跨设备同步精度直接排名。

## 下一阶段推进顺序（Stage 2 正文撰写）

- [ ] 确认候选标题、章节划分与图表规划（如确定目标期刊，先拉取该刊最新模板、摘要字数上限与 AI 披露规范）
- [ ] 生成 2 张矢量图脚本与 PDF（`figures/fig-uc1-layout-bursts.pdf`、`figures/fig-p4-tradeoff.pdf`）
- [ ] 按 `03 → 04 → 05 → 01/02 → 06 → Abstract` 顺序将 `\outlinepara` 块逐段替换为紧凑英文学术散文并移除大纲辅助宏
