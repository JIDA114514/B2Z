# 实验归档

从 [index.md](index.md) 选择实验，再打开该目录的 `report.md`。完整结构、启动示例、统计边界和备份规则见[项目 README](../../README.md#接收结果与实验归档)。

两接收器的短命令分别为 `python3 python/exadv_rx/receive.py --run-id 10270` 和 `python3 python/zigbee_rx/receive.py --run-id 10270 --payload-len 30 --expected-packets 150`。默认使用主机本地日期建立 `YYYYMMDD_run10270/`，每次实时启动单独保存到 `captures/<接收链>/<启动时间_唯一后缀>/`。长期参数与两块 HackRF 的序列号见 [`receiver_defaults.py`](../experiment_tools/receiver_defaults.py)。

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

实验归档及兼容结果目录中的 JSON、CSV、JSONL 和文本日志现在允许进入 Git，包括完整逐包解码记录、对照条件、比较结果、逐突发成本、取时阶段、关联表和异常日志。具体包括 `rx.packets.jsonl`、`conditions.json`、`comparison.json`、`plan.bursts.csv`、`timing.*.csv`、`follow.audit.json` 和控制台/回放日志。

完整 IQ（`.ci8`、`.cf32`、`.iq`）、缓存、锁文件和临时文件仍忽略，关键 IQ 需要外部备份。逐包记录应保留完整负载、校验结果和采样索引；它不能替代 IQ 的重新解调能力。更改忽略规则只使文件可被 Git 发现，不等于已经提交或推送。较大的长期逐包记录可先查看单文件体积，再决定独立归档或外部备份；不要通过删除完整负载来缩小关键证据。

## 阶段综合报告

- [N4两层公平对照首轮报告](../../doc/n4_two_layer_results.md)：2401–2406与2411–2416的联合解析、成本、适用范围及证据限制；[CSV/JSON与图表](n4_two_layer_summary/README.md)。该汇总不代表新增实验轮次。
