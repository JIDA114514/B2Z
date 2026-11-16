# N5 任务规则消融

Run 2507；21 个回放条件；任务分母 6。
所有结果均为本侧 IQ 样本域软件回放。1 ms 参考界为合成假设。
原轮全部已提交波形预算 602400 µs；实际 RF 发射时长未测。

| 条件 | 联合有效解析 | 联合软件处理 |
| --- | ---: | ---: |
| immediate_original | 4/6 | 4/6 |
| original_uncalibrated | 4/6 | 0/6 |
| repeat_first1_uncalibrated | 3/6 | 0/6 |
| repeat_first3_uncalibrated | 4/6 | 0/6 |
| repeat_all_uncalibrated | 4/6 | 0/6 |
| lead_500ms_uncalibrated | 3/6 | 0/6 |
| lead_2000ms_uncalibrated | 3/6 | 0/6 |
| lead_5000ms_uncalibrated | 3/6 | 0/6 |
| delay_0ms_uncalibrated | 4/6 | 0/6 |
| delay_10ms_uncalibrated | 4/6 | 0/6 |
| delay_100ms_uncalibrated | 4/6 | 0/6 |
| original_synthetic_bound_1ms | 4/6 | 4/6 |
| repeat_first1_synthetic_bound_1ms | 3/6 | 3/6 |
| repeat_first3_synthetic_bound_1ms | 4/6 | 4/6 |
| repeat_all_synthetic_bound_1ms | 4/6 | 4/6 |
| lead_500ms_synthetic_bound_1ms | 3/6 | 3/6 |
| lead_2000ms_synthetic_bound_1ms | 3/6 | 3/6 |
| lead_5000ms_synthetic_bound_1ms | 3/6 | 3/6 |
| delay_0ms_synthetic_bound_1ms | 4/6 | 4/6 |
| delay_10ms_synthetic_bound_1ms | 4/6 | 4/6 |
| delay_100ms_synthetic_bound_1ms | 4/6 | 4/6 |

合成规则案例 20/20 通过。
逐任务、拒绝原因和事件见 CSV/JSONL；原板端成本不随反事实筛选改变。
