# Run 2507：N5 任务规则消融执行记录

输入为本轮板端日志、N5 配置及两侧独立逐包记录；文件路径和 SHA256 见 [manifest.json](manifest.json)。执行前确认两侧录制 `status=complete`、目录中各只有一份有效逐包记录，N5 专项测试 19 项通过。输出先在 `/tmp/n5_task_rules_run2507_v1` 核对，再复制到本目录；原始记录未改写。

```bash
PYTHONPATH=python python3 -m control_match.n5_task_ablate \
  --experiment-dir python/experiments/20261116_run2507 \
  --config python/control_match/configs/n5_2507.json \
  --run-id 2507 --output-dir /tmp/n5_task_rules_run2507_v1
```

核对：21 个条件、126 条逐任务记录、20/20 合成规则案例；原始联合解析 4/6，与本轮 N5 完整性分析一致；`repeat_all` 与原始、`delay_0ms` 与原始逐事件一致。前 1 次联合解析 3/6；命令 53 的 BLE 首槽缺失，后续计划尝试使两侧都能解析，该变化只属于同轨迹反事实输入筛选。第二次现场干预超出预登记窗口，须按探索性证据解释。
