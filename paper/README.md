# 论文工程

当前模板：IEEEtran journal 模式（目标会议/期刊未定）。投会议时改 main.tex 第 8 行。

## 编译

    cd paper
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

产物在 build/main.pdf，清理用 latexmk -C。在 VS Code 里按 Ctrl+Alt+B。

## 结构

    paper/
      main.tex              导言区 + input，不写正文
      sections/
        01-introduction.tex      引言（已有框架段 + 2 处引用）
        02-related-work.tex      相关工作
        03-system-model.tex      系统模型与问题定义
        04-packet-design.tex     单包双协议设计（核心贡献）
        05-receiver-design.tex   双链接收与配对
        06-implementation.tex    实现
        07-evaluation.tex        实验与结果
        08-discussion.tex        讨论与局限
        09-conclusion.tex        结论
      figures/              矢量图（PDF 优先）
      tables/               脚本生成的 .tex 表片段
      refs.bib              参考文献库
      latexmkrc             编译配置

每个 section 文件里都有 写作要点 注释块，写完就删掉。

## 约定

- 术语宏：\ble、\stdfour、\sysname 在 main.tex 导言区，改术语只改一处。
- 图：figures/fig-<内容>.pdf，单栏 3.5 in、双栏 7.16 in，图内字号不少于 7 pt。
- 表：booktabs，不画竖线；表注写清样本量与重复轮数。
- 引用：正文 \cite{key}，条目放 refs.bib；不凭记忆写文献。
- 数字：正文每个数字都要能追到 python/*/results/ 下的文件。

## 待办

- [ ] 定标题与作者信息（main.tex 顶部两处 TODO）
- [ ] 写摘要（150-250 词，四句结构）
- [ ] 第二节文献：先查新，再动笔
- [ ] 第四节字节预算表：按实际字段重算，不沿用 46 B 上限
- [ ] 第七节指标口径：分子/分母、N/A 规则先写死再跑数据
