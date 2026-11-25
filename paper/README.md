# B2Z UC1 Conference Paper Project（ITCA 常规 4 页版 + 中文伴生版）

当前状态：
- **英文投稿主版**（`paper/`）：按 ITCA 检查表与常规 4 页篇幅标准定稿（US Letter 双栏、`Figure`/`Table` 全称与阿拉伯数字编号、带方括号上标引文、7 篇带 DOI/链接核心文献），使用 pdfLaTeX/BibTeX 从干净目录生成 [4 页英文 PDF](build/main.pdf)（双栏均衡收尾、0 警告、0 Overfull、全部字体嵌入）。英文 4 页紧凑图使用独立文件名（`*-4p.pdf`），不影响中文稿图件。
- **中文审阅伴生版**（`paper/zh/`）：保留完整 6 节详尽中文学术审阅稿（[build/zh/main_zh.pdf](build/zh/main_zh.pdf)）及原 `fig-uc1-layout-bursts.pdf` / `fig-p4-tradeoff.pdf`；
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

## 英文 4 页常规会议结构与文件映射

| 英文文件（`sections/`） | 英文节标题（5 节结构） | 图表锚点 | 说明 |
| --- | --- | --- | --- |
| `01-introduction.tex` | I. Introduction and Related Work | 回链 Sec. II–IV、Figures 1–2、Tables 1–2 | 合并引言与相关工作（原 `02-related-work.tex` 保留备查） |
| `03-protocol-design.tex` | II. Co-Packaged Protocol and Baselines | **Figure 1** (`*-4p.pdf`) + **Table 1** (`tab-budget.tex`) | 包含成本公式 `(1)–(2)`、确定性偏置与 `C3` 隔离 |
| `04-prototype-methodology.tex` | III. Prototype and Evaluation Methodology | — | 双链 SDR 台架、预注册矩阵与四项审计规则 |
| `05-evaluation.tex` | IV. Empirical Results | **Table 2** (`tab-p4-main.tex`) + **Figure 2** (`*-4p.pdf`) | 含 `R0` 验证、`P4` 3,600 任务对照与时间/断馈行内报告（原 `tab-p2-time.tex` 保留备查） |
| `06-discussion-conclusion.tex` | V. Discussion, Limitations, and Conclusion | — | 四项有效性边界、结论与后续工作 |

## 统一宏与写作硬性红线（中英双版共同遵守）

- **术语宏**：`\proto` (`UC1`)、`\fragproto` (`C3`)、`\modejc` (`JC`)、`\modesc` (`SC`)、`\modelc` (`LC`)、`\ble` (`BLE`)、`\stdfour` (`IEEE 802.15.4`)；`BlueBee` 专指 Jiang et al. SenSys 2017 前作。
- **严禁越界表述**：不写 `"first"`；不对跨零 `df=2` 区间宣称统计显著，不对 `JC vs SC` 宣称等效；`JC vs LC` 始终声明 ch3 vs ch39 封装+信道配置级边界；截止期按 `2,730/3,600 unknown + 870/3,600 not_decoded` 列报；波形成本明确为提交设计波形代理时长；时间残差仅限本侧 IQ 采样域留出预测，不与 X-Sync 跨设备同步精度排名。

## 推进顺序

- [x] Stage-1 英文框架、冻结三线表与 2 张矢量图
- [x] 中文伴生版完整正文生成、两轮审计修订与 XeLaTeX 编译验证
- [x] 按中文版展开英文投稿正文初稿及内容审计修订（`paper/sections/`）
- [x] 按 `ITCA_Templates/` 完成 IEEE Conference 排版适配并实排收敛至常规 **4.0 页**（`build/main.pdf`）
- [ ] 投稿前终检作者信息与通讯邮箱（如有基金资助再启用 `\IEEEoverridecommandlockouts`）
