# UC1 板端接口与本地验证

日期：2026-11-19。依据 [UC1 协议](unified_compact_protocol_proposal.md)和[实验计划](../plans/uc1_paper_experiment_plan.md)。板端源码已实现并同步 SDK；本地生成/解码测试与 ARM 语法检查通过。用户尚需构建上板验证。主机正式接收/分析链的 UC1/C3 适配仍待实现，不能用历史解析器进行本轮验收。

## 1. 新命令

```text
b2z_uc1_start? <run_id> <period_ms> <tasks> <ble_extra> <ieee_extra> <mode> <policy> <value> <profile>
bluebee_perf_status?
bluebee_perf_stop?
```

严格九个十进制整数，与其他性能/控制命令共用忙状态和发送工作任务。旧 v1/v2/C1/C2 入口和字节含义不变。

| 参数 | 范围/语义 |
| --- | --- |
| run_id | 1..65535，用户在实际采集前检查未占用 |
| period_ms | 500..10922，且整轮不超过 600 s；仍受总槽数和 profile 约束 |
| tasks | core 为 1..169，time 固定 6；核心 100 任务对应 610 槽 |
| ble_extra / ieee_extra | b=0..26、z=0..6，b+4z≤26；保持原公平比较工作域 |
| mode | 1=JC 共包，2=SC exadv 分别发送，3=LC legacy BLE + 独立 BlueBee |
| policy | 0=显式 K；1=每任务有效波形预算上限（µs） |
| value | policy=0 时 K=1..4；policy=1 时 K=floor(value/一次完整尝试成本)，计算结果必须在 1..4，拒绝而非截断 |
| profile | 0=core，未使用槽静默；1=time，固定 JC、6 任务、显式 K=3，其余槽发等长纯时间更新 |

time profile 只允许 `mode=1, policy=0, value=3, tasks=6`，因此不把固定时间更新开销藏在每任务预算内。core 的预算针对全部命令尝试，未使用预算不填充。

以下是实现后的板端命令示例，2701–2704 仅示例、不预占编号；应在新版主机接收完成后核对条件再执行：

```text
b2z_uc1_start? 2701 500 10 26 0 1 1 6000 0
b2z_uc1_start? 2702 500 10 26 0 2 1 6000 0
b2z_uc1_start? 2703 500 10 26 0 3 1 6000 0
b2z_uc1_start? 2704 500 6 26 0 1 0 3 1
```

前三条分别是 B 点 JC/SC/LC 的短初验，K=3/3/2，每轮 70 槽、35 s；必须逐轮运行，不连续粘贴抢占忙状态。第四条为 300 槽、150 s 时间支撑。

## 2. 已实现的固定任务生成

core：任务 j=0..tasks−1，command_id=j+1，首槽 `10+6j`，前 K 槽发送，其余静默。V=`(首槽+5)×period_ms`，E=`(首槽+6)×period_ms`。同任务各次发送重算相对偏移，绝对 V/E 不变。时隙编号包括静默、漏发和失败，不重用。

time：六任务首槽 70/90/150/190/240/270，command_id=1..6，每项连续三槽；V=`(首槽+4)×period_ms`，E=`(首槽+6)×period_ms`。其他 282 槽纯时间更新；固定 b/z，全零扩展保持共包位置。此命令不执行接收端动作，也不自动干预 RF 条件。

两种 profile 的命令测试内容：BLE target/opcode/arg=`1/1/(j+1)`，IEEE=`2/1/(j+2)`。当前 CLI 生成固定测试任务，不是任意应用命令加载器。UC1 应用扩展测试填充冻结为：

```text
state = 0xB2430100 ^ (run_id << 16) ^ command_id ^ (side * 0x9E3779B9)
side: BLE=1, IEEE=2
每字节先 state=(state*1664525+1013904223) mod 2^32，再取最高 8 位
```

填充不包含 slot，保证同任务重发一致。纯时间更新扩展全零。CRC 覆盖本侧完整记录；测试预期只能在独立恢复字节后用于校验。

## 3. 封装、调度与统计

- UC1 使用 C1 判别字加显式 0x10/0x11；历史 C1 01 保留。JC/SC 复用现有 primary/AuxPtr 调度，LC 不发 exadv primary。
- C3 15 B 分片头、每片最多 12 B，携带 run/slot/command；b≤1 直接 legacy，b≥2 为 3..5 片。新增第五星片缓冲和第六个逐突发记录，末片不填充。pending/closed 是接收端职责，未在板端实现。
- 三组实际生成的波形成本在 DMA 前与预算核对；不符拒绝发送。每次 UC1 突发提交前检查当前软件时隙余量（含波形、pad 和 DMA margin），不足则停止该槽余下发送，保留失败；不延后任务截止时间。调谐恢复失败终止实验。
- 周期下限和波形预算只提供配置可行性检查，实际生成/调谐/USB/RF 性能须上板验证。DMA 轮询有界；上述软件时间保护不证明真实空口截止精度。
- JC/SC 的计划参考原点对应工作任务 epoch+300 ms；LC 为 epoch 的 legacy 槽起点。它们都不是校准 RF 时间，LC/SC 没有同包 marker offset，日志 `marker_offset_valid=0` 时数值 0 仅为占位，接收侧应转换为未知。保持分别发送事件与共包参考分列。

日志入口：

| 记录 | 内容 |
| --- | --- |
| `UC1_CONFIG` | 模式、profile、任务/槽数、K、预算/剩余预算、长度、周期、marker 候选值/有效标志、计划原点偏移与填充版本 |
| `CONTROL_PLAN_ENTRY/TASK/SLOT` | 固定任务语义、尝试覆盖、发送计数；core 静默明确标为 silent=1 |
| `UC1_STATS` | `final=0` 为状态快照、`final=1` 为最终统计；计划/已处理/完整成功/失败尝试、静默槽数、全部计划波形预算；完整成功要求各突发 DMA 完成且频率恢复成功 |
| `COMPACT_SLOT` | 该 slot 的记录与布局长度；UC1 command_id 按真实任务输出，不再假设 slot+1 |
| `UC1_BURST` | primary/secondary/fragment0..4/ieee 的生成、提交、完成、超时、波形/pad 与软件时间括号 |
| `UC1_COST_STATS` | 逐突发汇总；历史 `tx_completed` 仍表示 BLE 部分完成，IEEE 与完整尝试另计 |

分析器仅采用终态 UC1_STATS；重复终态必须一致。旧固件没有 final 字段时，按同 run_id 的 CONTROL_PLAN_STATS final=1 上下文识别，兼容 2701 原日志。

计划尝试未进入处理可能来自时隙跳过或提前停止；结合 reached_slots 与逐槽日志判断，不以 processed 数作任务分母。全部失败时运行循环仍可能到达 complete，这只表示计划结束，不表示实验验收成功。

## 4. 本地验证与同步

已覆盖：UC1/C3 三模式真实 C 生成字节和波形、独立 IEEE 解码、BLE 分片 CRC/重组、A/B/C 与 b=1 边界成本、重发时间/内容稳定、纯更新时间填充、非法参数和预算、610 槽任务生成、300 槽时间 profile、过晚 DMA 提交拒绝及旧协议回归。

```bash
python3 -m unittest \
  python.perf_test.tests.test_uc1_start \
  python.perf_test.tests.test_uc1_generator \
  python.perf_test.tests.test_capacity_schedule \
  python.perf_test.tests.test_compact_generator \
  python.perf_test.tests.test_b2z_control_generator \
  python.perf_test.tests.test_n3_dma_observer \
  python.perf_test.tests.test_bluebee_perf_protocol -q
```

ARM 检查使用本机 Vitis 2021.1 `arm-none-eabi-gcc -fsyntax-only`，分别打开/关闭 N3 trace。未执行固件链接、烧录或 RF 发送。以下五个文件已同步 `hdl/projects/antsdre310/antsdre310.sdk/app/src/app/`：`ble_exadv_secondary_gen.c/.h`、`bluebee_perf.c/.h`、`command.c`。该 SDK 目录可能不被 Git 跟踪，交付时另核对内容一致性。
