# Run 2508：N5 任务规则消融执行记录

输入为本轮板端日志、N5 配置及两侧独立逐包记录；文件路径和 SHA256 见 [manifest.json](manifest.json)。执行前确认两侧录制 `status=complete`、目录中各只有一份有效逐包记录，N5 专项测试 19 项通过。输出先在 `/tmp/n5_task_rules_run2508_v1` 核对，再复制到本目录；原始记录未改写。

```bash
PYTHONPATH=python python3 -m control_match.n5_task_ablate \
  --experiment-dir python/experiments/20261116_run2508 \
  --config python/control_match/configs/n5_2508.json \
  --run-id 2508 --output-dir /tmp/n5_task_rules_run2508_v1
```

核对：21 个条件、126 条逐任务记录、20/20 合成规则案例；原始联合解析 2/6，与本轮 N5 完整性分析一致；`repeat_all` 与原始、`delay_0ms` 与原始逐事件一致。前 1 次、前 3 次和全部尝试在此轨迹中均为 2/6；这不构成重复无效的普遍结论。
