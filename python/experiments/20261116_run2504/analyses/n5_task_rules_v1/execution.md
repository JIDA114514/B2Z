# Run 2504：N5 任务规则消融执行记录

输入为本轮板端日志、N5 配置及两侧独立逐包记录；文件路径和 SHA256 见 [manifest.json](manifest.json)。执行前确认两侧录制 `status=complete`、目录中各只有一份有效逐包记录，N5 专项测试 19 项通过。输出先在 `/tmp/n5_task_rules_run2504_v1` 核对，再复制到本目录；原始记录未改写。

```bash
PYTHONPATH=python python3 -m control_match.n5_task_ablate \
  --experiment-dir python/experiments/20261116_run2504 \
  --config python/control_match/configs/n5_2504.json \
  --run-id 2504 --output-dir /tmp/n5_task_rules_run2504_v1
```

另执行两侧立即处理基线，原始命令分别使用本轮 BLE 与 IEEE 的 `rx.packets.jsonl`、`--policy immediate`、目标 1/2；输出归档在 [immediate_ble](immediate_ble/control.summary.json) 与 [immediate_ieee](immediate_ieee/control.summary.json)。两侧各 300 条控制观察、6 个首次软件处理事件；该基线不评估定时截止。

```bash
python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261116_run2504/captures/ble/112031_953819_zgq_3ypu/rx.packets.jsonl \
  --side ble --run-id 2504 --target-id 1 --policy immediate \
  --output-dir /tmp/n5_task_rules_2504_ble_immediate_v1
python3 python/control_match/replay_engine.py \
  --packets python/experiments/20261116_run2504/captures/zigbee/112030_270549_t3mb8b3c/rx.packets.jsonl \
  --side zigbee --run-id 2504 --target-id 2 --policy immediate \
  --output-dir /tmp/n5_task_rules_2504_ieee_immediate_v1
```

核对：21 个条件、126 条逐任务记录、20/20 合成规则案例；原始联合解析 6/6，与本轮 N5 完整性分析一致；`repeat_all` 与原始、`delay_0ms` 与原始逐事件一致。计划任务分母始终为 6。合成 1 ms 参考界下的软件处理不代表实测同步执行。
