# 实验归档

从 [index.md](index.md) 选择实验，再打开该目录的 `report.md`。完整结构、启动示例、统计边界和备份规则见[项目 README](../../README.md#接收结果与实验归档)。

- `index.csv`：每个归档目录一行，实时、回放、分析数量分开。
- `runs.csv`：每条 BLE/ZigBee 接收记录一行；有效 PDU 数不等于目标测试包数。
- `artifacts.csv`：本机文件清单、字节数及历史文件 SHA-256/旧路径；不是外部备份证明。
- `migration.manifest.json`：375 个历史文件的迁移与完整性记录；原文件内容不变。
- `history_*`：历史采集、回放或组合分析；目录数不代表独立重复轮数。

自动生成的 `report.md` / `*.report.md` 和索引可以重建；人工观察写入 `notes.md`。旧的 `.summary.txt`、JSON 和人工报告作为历史证据保留，可能含旧路径。

```bash
python3 python/experiment_tools/manage.py index
python3 python/experiment_tools/manage.py locate python/exadv_rx/results/rx_20261026_161955_853914.ci8
python3 python/experiment_tools/manage.py verify
```

完整 IQ、逐包流和控制台日志默认不进入 Git，关键数据需另行备份。
