# B2Z UC1 5-Page Short Paper Project（中英双版共享架构）

当前状态：
- **英文投稿主版**（`paper/`）：Stage-1 框架、已核验文献库、冻结三线表及 2 张矢量图已就绪，待中文版审校定稿后逐段展开为约 5 页英文正文；
- **中文审阅伴生版**（`paper/zh/`）：已完成 6 节完整中文学术正文初稿与双栏编译（[build/zh/main_zh.pdf](build/zh/main_zh.pdf)），与英文主版严格 1:1 章节/段落/标签对应，用于审校论点、数值与逻辑边界；
- **冻结数据溯源**：`python/experiments/p5_freeze_20261124/`（P4 数据归档提交 `82d56a5`）。

## 双语项目组织原则（单点维护、互不污染）

```text
paper/
├── figures/                      # [共享] 矢量图 PDF（中英双版共用，不重复存两份）
├── scripts/                      # [共享] 可复现绘图脚本（直接读取冻结 CSV）
├── refs.bib                      # [共享] 唯一已核验参考文献库（单点维护）
├── main.tex                      # [英文投稿主版] pdflatex + IEEEtran
├── sections/                     # [英文投稿章节] 01–06（与 zh/sections/ 同名 1:1 映射）
├── tables/                       # [英文冻结三线表] tab-budget / tab-p4-main / tab-p2-time / tab-p4-supp
├── latexmkrc                     # 英文版编译配置 -> build/main.pdf
├── zh/                           # [中文审阅伴生版] 独立子目录，打包英文投稿时直接排除
│   ├── main_zh.tex               # xelatex + IEEEtran + ctex（Noto Serif CJK SC）
│   ├── latexmkrc                 # 中文版编译配置 -> ../build/zh/main_zh.pdf（共享 ../refs.bib）
│   ├── sections/                 # 01–06 完整中文正文（与 ../sections/ 同名 1:1 对应）
│   └── tables/                   # 中文表头/表注版三线表（数字与 ../tables/ 100% 同步）
└── build/                        # [git-ignored] 编译产物（build/main.pdf 与 build/zh/main_zh.pdf）
```

## 编译命令

```bash
# 英文主版（pdflatex -> paper/build/main.pdf）
cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

# 中文伴生版（xelatex -> paper/build/zh/main_zh.pdf）
cd paper/zh && latexmk -xelatex -interaction=nonstopmode -halt-on-error main_zh.tex
```

## 5 页短论文结构与 1:1 章节映射

| 章节文件（`sections/` 与 `zh/sections/` 同名） | 英文标题 / 中文标题 | 目标篇幅 | 图表锚点 |
| --- | --- | :---: | --- |
| `01-introduction.tex` | I. Introduction / 引言 | `0.65 p` | 回链 Sec. III–V、Fig. 1–2、Table I–III |
| `02-related-work.tex` | II. Related Work and Scope Boundaries / 相关工作与研究边界 | `0.45 p` | — |
| `03-protocol-design.tex` | III. Co-Packaged Protocol and Baseline Encapsulations / 共包协议设计与对照封装 | `1.10 p` | **Fig. 1** + **Table I** (`tab-budget.tex`) |
| `04-prototype-methodology.tex` | IV. Dual-Chain SDR Prototype and Evaluation Methodology / 双链 SDR 原型与实验评估方法 | `0.65 p` | — |
| `05-evaluation.tex` | V. Empirical Results / 实测结果 | `1.35 p` | **Table II** (`tab-p4-main.tex`) + **Fig. 2** + **Table III** (`tab-p2-time.tex`) |
| `06-discussion-conclusion.tex` | VI. Discussion, Limitations, and Conclusion / 讨论、局限与结论 | `0.45 p` | — |

## 统一宏与写作硬性红线（中英双版共同遵守）

- **术语宏**：`\proto` (`UC1`)、`\fragproto` (`C3`)、`\modejc` (`JC`)、`\modesc` (`SC`)、`\modelc` (`LC`)、`\ble` (`BLE`)、`\stdfour` (`IEEE 802.15.4`)；`BlueBee` 专指 Jiang et al. SenSys 2017 前作。
- **严禁越界表述**：不写 `"first"`；不对跨零 `df=2` 区间宣称统计显著，不对 `JC vs SC` 宣称等效；`JC vs LC` 始终声明 ch3 vs ch39 封装+信道配置级边界；截止期按 `2,730/3,600 unknown + 870/3,600 not_decoded` 列报；波形成本明确为提交设计波形代理时长；时间残差仅限本侧 IQ 采样域留出预测，不与 X-Sync 跨设备同步精度排名。

## 推进顺序

- [x] Stage-1 英文框架、冻结三线表与 2 张矢量图
- [x] 中文伴生版完整正文生成与 XeLaTeX 编译验证
- [ ] 根据中文伴生版审阅修改意见定稿论点与表述
- [ ] 将审定后的中文版 1:1 展开为英文投稿正文（`paper/sections/`）并精确控页至 ~5.0 页
