# 板端 BLE exadv 流程验证

- Run ID：1906；模式：live_hop；结论：`incomplete_follow_observation`。
- primary 有效 DID：[0, 1, 3, 4, 5, 6, 7, 8, 9]。
- secondary 有效 DID：[0, 1, 3, 4, 5, 6, 7, 8, 9]。
- 同轮关联／实际跟随 DID：[0, 1, 3, 4, 5, 6, 7, 8, 9]。
- 软件跟随观察：False；空口 AuxPtr 时间窗：未校准、未验证。
- 计数：{'primary_observed': 9, 'secondary_observed': 9, 'followed_events': 9, 'demod_crc_errors': 0}。
- 板端日志：未提供。

CRC 正确、AuxPtr 字段正确与同一接收机跟随成功分别记录；它们不自动证明实际空口间隔满足 BLE 规范。
原始逐包与原因见 `flow.events.jsonl`，结构化计数见 `flow.summary.json`。
