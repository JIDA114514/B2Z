# 实验归档与 Git 提交约定

本目录可保存自动接收结果和人工整理记录。Git 默认纳入小型结构化结果、板端原始日志与分析报告；完整 IQ 和完整逐包流保存在外部归档中，并通过 manifest 关联。`.gitignore` 只控制是否进入版本管理，不会删除本地实验文件，也不会备份被忽略的文件。

## 已配置的规则

| 文件后缀 | 默认提交 | 内容 |
|---|---|---|
| `.summary.json` / `.summary.txt` / `.summary.csv` | 是 | 接收参数、采集状态、计数、时长与处理性能 |
| `.board.log` | 是 | 板端原始命令、启动、状态与最终计数 |
| `.hackrf.log` | 是 | HackRF 采集工具原始输出 |
| `.config.json` | 是 | 固件版本、RF 配置、位置与实验条件 |
| `.payload_validation.json` | 是 | Run ID、Sequence、FCS 与确定性填充复核 |
| `.metrics.csv` | 是 | 汇总曲线与统计分析表 |
| `.events.jsonl` / `.commands.jsonl` | 是 | 事件匹配或精简逐命令记录；提交前检查大小 |
| `.md` | 是 | 人工记录、分析、局限与结论 |
| `.manifest.json` | 是 | 外部原始文件的位置、格式、大小与 SHA-256 |
| `.packets.jsonl` | 否 | 完整逐包流，高包率时可能很大 |
| `.packets.sample.jsonl` | 是 | 人工选择的小型逐包片段，不能代替完整原始数据 |
| `.ci8` / `.cf32` / `.iq` | 否 | 原始 IQ |
| 其他未知文件或子目录 | 否 | 按需明确扩充规则 |

根目录仍保留原有 JSON/CSV 默认忽略行为，避免一次性改变其他工程目录的策略。已有 `python/perf_test/` 及其 `results/` 中的 JSON/CSV 按路径放行；本目录通过局部规则放行指定文件。后续新增目录或后缀时，需要相应扩展规则，不能假设任意 JSON 都会自动提交。当前结果目录的规则是平铺结构；如改为按轮次建立子目录，需先调整目录放行规则。

## 每轮建议保存

沿用接收器自动生成的前缀，不必修改或搬移历史文件。例如：

```text
rx_20261026_152018_750312.summary.json
rx_20261026_152018_750312.summary.txt
rx_20261026_152018_750312.hackrf.log
rx_20261026_152018_750312.board.log
rx_20261026_152018_750312.config.json
rx_20261026_152018_750312.payload_validation.json
rx_20261026_152018_750312.manifest.json
run_10262_review.md
```

1. **开始前**记录板端完整命令、Run ID、源码提交号、固件/bitstream 标识、操作系统模式、接收命令、设备序列号、频率/采样率/增益、位置/距离等。存在未提交源码修改时，保存对应补丁或文件哈希；仅记录 HEAD 不能代表实际运行代码。
2. **运行时**保存串口原文，包括启动与最终统计。人工计数单独注明来源、方法和观察窗口；不能回填成看似板端自动输出的日志。
3. **结束后**保存接收摘要、逐命令复核和结论，明确统计分母、时间边界、缺失信息及异常。60 s 板端实验和 30 s 接收窗口分别记录，不能混用分母。
4. **外部归档**保存完整 IQ 与逐包流，记录相对路径/稳定 URI、字节数和 SHA-256。接收摘要中的本机绝对路径只是线索，不是可移植的归档地址。`.ci8` 必须同时保存采样率、中心频率和 IQ 格式说明。
5. **修复回放**使用新前缀，保留原始结果，记录输入文件哈希、接收代码版本、修改参数和原实验前缀。不能用离线改善覆盖实时实验记录。

`*.config.json` / `*.manifest.json` 是人工补充或后续自动化的约定，当前接收器不会自动生成。参考 `archive.manifest.example.json`；示例不是已有备份的证明。

## 提交检查

在项目根目录运行：

```bash
git status --short --untracked-files=all -- python/exadv_rx/results python/perf_test
git check-ignore -v python/exadv_rx/results/rx_20261026_152018_750312.ci8
git check-ignore -v python/exadv_rx/results/rx_20261026_152018_750312.packets.jsonl
git add -- python/exadv_rx/results
git diff --cached --stat
git diff --cached --check
```

确认暂存文件后再提交。`.gitignore` 不能按文件大小筛选，应检查 JSONL/CSV 是否异常膨胀；大型事件日志也应转外部归档。一般不对完整 IQ 使用 `git add -f`。规则不影响已经被追踪的文件，本次仅修改规则，不自动暂存、提交、删除或移出已有 Git 历史。

常规 Git 仓库适合小型可审查记录；完整 IQ 可放在有备份的磁盘、NAS 或对象存储中。只有明确配置和管理大文件存储后再考虑 Git LFS；这里未启用 LFS。
