# 结果目录已迁移

历史结果现存于 [`python/experiments/`](../../experiments/)，从[实验索引](../../experiments/index.md)进入。实时采集按原前缀归档，有明确输入 IQ 的回放进入对应采集的 `analyses/`，跨轮报告位于 `history_exadv_rx_reviews`。

历史原文件内容未修改。使用 `python3 python/experiment_tools/manage.py locate <旧路径>` 查询新位置，完整迁移记录见 [migration.manifest.json](../../experiments/migration.manifest.json)。

本目录保留旧 `--output` 前缀的兼容规则及外部归档清单示例；新运行默认使用统一归档。目录结构、指标边界、Git 规则与备份要求见[项目 README](../../../README.md#接收结果与实验归档)。

完整 IQ 和逐包流不进入普通 Git 历史；忽略规则不等于备份。`*.config.json` / `*.manifest.json` 应记录实际条件和原始文件位置，不把模板当作已有测量或备份证据。
