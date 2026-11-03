# 连续单包双协议控制与粗粒度同步：v1 负载草案

状态：**P1 设计草案；发送端原型已上板，BLE 与 IEEE 802.15.4 软件接收链已在不同轮次分别恢复新控制记录；[ZigBee 侧实时控制接收](../python/zigbee_rx/README.md#b2-43-控制包实时分析)与[离线双侧匹配](../python/control_match/README.md)已实现，尚未完成同一轮独立双接收端的联合验证**。更新：2026-11-03。串口使用方法见[FreeRTOS 命令说明](../app_FreeRTOS/README.md#十六v1-双协议控制与时间广播命令待上板验证)。该格式服务于一个发送 SDR、两个独立接收 SDR 的实验。每个广播事件只有一个携带应用数据的 secondary `AUX_ADV_IND`；同一任务可以在后续事件重发。此处的 IEEE 802.15.4 侧首先使用现有接收器可恢复的 **PHY 帧及实验应用负载**，不是已经实现的 ZigBee MAC/NWK/APS/ZCL 命令，也不承诺商用设备兼容。

## 0. 现有接收证据及其边界

[`20261029_run1001`](../python/experiments/20261029_run1001/report.md) 的 BLE 接收器记录 93 个同频辅助包，其中 81 个与 primary 形成同频诊断配对；严格 AuxPtr 配对为 0。ZigBee 接收器记录 118 个 FCS 正确帧，逐包内容实际为 **20 B** 性能测试负载，而采集参数设为 `--payload-len 30`，故原报告的 `unique=0` 是长度过滤结果。用现有完整填充校验器按 20 B 对 118 行逐包记录重新检查，118 行均通过 Run ID 1001、Sequence 和填充校验，118 个 Sequence 各不相同（范围 0–149）。这支持两条独立 PHY 接收链在该轮均可恢复目标信号；但两侧还没有共同的控制字段，BLE 未按 Run ID 解码，同频模式未证明规范 AuxPtr 跟随，且缺少配对板端最终计数，不能据此计算联合成功率或无线 PRR。

## 1. 每个广播事件的层次

```text
primary ADV_EXT_IND  ── AuxPtr ──>  一个 secondary AUX_ADV_IND
secondary AdvData:
  Flags AD (3 B)
  一个 Manufacturer Specific Data AD (211 B)
    ├─ Company ID (2 B；实验占位值 0xFFFF)
    ├─ BLE 控制记录 (35 B；BLE 接收器直接解析)
    └─ BlueBee 区域 (172 B；映射完整 IEEE 802.15.4 PHY 帧)
          └─ 802.15.4 PSDU = 本侧实验控制负载 (35 B) + FCS (2 B)
```

BLE 控制记录和 802.15.4 实验控制负载各自含完整的共同字段及本侧命令，分别校验后才能按 `(run_id, command_id)` 合并。两条命令可以相同，也可以有不同的 `target_id`、`opcode` 和 `arg`；共同时间和任务标识必须一致。BLE 接收器只解析 Manufacturer AD 中前 35 B 控制记录，后续 BlueBee 字节视为不透明数据。发送端仅对 BlueBee 区域作现有的白化预补偿，随后按实际 BLE PDU 计算 CRC；BLE 控制记录和 AD 头不作该预补偿。IEEE 802.15.4 接收器只从空口 BlueBee 波形独立恢复 PHY 帧，不从 BLE 控制记录取值。

`0xFFFF` 是沿用现有生成器的**实验占位 Company ID**，不代表已获 Bluetooth SIG 分配的厂商编号；将来要做正式 GAP/商用兼容声明，需换用合法分配值并独立验证。v1 选择 non-connectable / non-scannable AdvMode，保留现有测试中使用的 Flags AD，不带 Local Name，不使用 `AUX_CHAIN_IND`。每个时隙的 AdvData 会随时间字段变化，因此 ADI/DID 应按实际数据更新；DID 不等于 `command_id`。

## 2. 两侧控制记录：固定 35 B

除单字节字段外，所有多字节整数均为**小端无符号整数**。下表偏移以各侧控制记录的第一个字节为 0；BLE 记录与 802.15.4 的 35 B 实验控制负载使用同一字段布局。

| 偏移 | 大小 | 字段 | v1 语义 |
| ---: | ---: | --- | --- |
| 0 | 2 | `magic` | 固定 `B2 43`，与旧性能头 `B2 5A` 区分。 |
| 2 | 1 | `version` | 固定 `1`；未知版本拒绝解析。 |
| 3 | 1 | `flags` | bit 0：命令有效；其余位必须为 0。`0` 为纯时间更新。 |
| 4 | 2 | `run_id` | 本轮标识，不能单独作为全局防重放凭据。 |
| 6 | 4 | `slot_index` | 计划广播时隙编号，含未成功发射的时隙；每个时隙递增。它不是命令重发次数。 |
| 10 | 4 | `ref_tick_ms` | 从本轮时间域起点到**本时隙计划的 secondary BLE 前导码起点**，单位 1 ms；不是生成、DMA 提交或未经校准的实际空口发射时刻。 |
| 14 | 2 | `period_ms` | 名义时隙间隔，单位 1 ms；v1 每轮固定且大于 0，允许漏时隙。它不能替代对实际发射抖动的测量。 |
| 16 | 4 | `command_id` | 本轮逻辑任务编号；同一任务的全部广播尝试保持不变。纯时间更新为 0。 |
| 20 | 2 | `target_id` | `0x0001–0x7FFF` 单节点、`0x8000–0xFFFE` 组、`0xFFFF` 本侧广播；0 保留。目标编号由各侧接收软件配置解释。 |
| 22 | 1 | `opcode` | 0=`NOOP`、1=`SET_STATE`、2=`TRIGGER`；未知值拒绝。v1 不声称执行 ZigBee ZCL 命令。 |
| 23 | 2 | `arg` | `SET_STATE` 的状态值或 `TRIGGER` 的代码；具体允许范围由命令类型规定。`NOOP` 时为 0。 |
| 25 | 4 | `execute_at_ms` | 共同时间域中的目标软件处理时刻。所有重发保持同一值。 |
| 29 | 4 | `valid_until_ms` | 命令的最迟接受时刻，命令包要求 `ref_tick_ms ≤ valid_until_ms < execute_at_ms`；超过即拒绝，不补执行。所有重发保持同一值。 |
| 33 | 2 | `app_crc16` | 对偏移 0–32 计算，低字节在前。采用 CRC-16/CCITT-FALSE：多项式 `0x1021`、初值 `0xFFFF`、不反射、无末尾异或；与现有 802.15.4 FCS 算法区分。它只用于检错，不提供鉴权。 |

纯时间更新要求 `flags=0`，且 `command_id`、`target_id`、`opcode`、`arg`、`execute_at_ms`、`valid_until_ms` 均为 0。命令包要求 `flags=1`、`command_id≠0`，两侧共同字段（除 CRC 外的时间、轮次和命令标识）相同。若一侧不需改变状态，仍可用相同 `command_id`、`flags=1`、`opcode=NOOP` 明确参加该任务；主要双端实验应使用两侧均有实际软件命令的样本。v1 每个计划时隙最多发送一次广播事件；同一任务在多个时隙重发时用不同 `slot_index` 区分物理尝试，并在板端日志中独立累计发送尝试与完成数。

v1 每轮持续时间限制在 24 小时内，`slot_index` 与毫秒时间字段均不得回绕；`period_ms` 上限由 16 位表示范围限定为 65,535 ms。每次换轮须使用新的 `run_id`，并重置接收器的轮内去重状态。正式长期运行或跨重启防重放需另加持久化新鲜度/鉴权设计，不能靠此 v1 格式声称安全性。

### 时间与异常处理

- 发射端将 `ref_tick_ms` 绑定到计划的 secondary BLE 前导码起点。必须另外记录该计划时刻与实际 RF 发射起点之间的偏差/上界；若板端只能记录 DMA 提交，先测 DMA 到空口的延迟与抖动。**不能把计划时间戳写成实测空口时间戳。**
- 两侧记录自身 IQ 中的包起始采样索引。按字段布局补偿 ZigBee 前导码与 BLE 前导码的固定位置差，再用多次接收的 `(ref_tick_ms, local_sample_index)` 估计本地时间映射；非相邻包的 `slot_index` 和 `ref_tick_ms` 允许识别间隔内漏收。接收端遇到间隔/时戳不一致时标记异常，不用名义周期强行修正实际发射抖动。
- 两侧先做应用 CRC、外层 BLE CRC 或 802.15.4 FCS、版本、目标和时间有效性检查，再处理命令。重复 `(sender, run_id, command_id, side)` 只保留首次合格记录；后续包可更新时钟模型，但不得重复处理命令。`sender` 在本实验由固定发送源配置与 BLE AdvA/实验元数据确定，不能把 ZigBee 侧未知的 AdvA 当作其已解码内容。
- 只有当接收侧估计的当前时间及不确定度仍早于 `valid_until_ms`，且距 `execute_at_ms` 足够覆盖处理时延和不确定度，才接受定时命令；否则标记迟到、过期或时间质量不足。失去更新时误差界随时钟漂移和更新年龄增大，超过预设容差即拒绝定时处理。单向广播不保证两侧同时成功。
- 两侧分别记录解码、校验、接受、计划软件处理、实际软件处理事件。没有可观测执行器时，不把软件事件记为物理动作。不得用两块 HackRF 各自的零点直接相减测同步精度；校准集和验证集分开。

## 3. 单个 secondary 的字节预算

沿用当前波形生成器的扩展头：secondary payload 中 `ExtHdrLen/AdvMode` 1 B、扩展头标志 1 B、AdvA 6 B、ADI 2 B，合计 **10 B**。一个 Flags AD 为 3 B。一个 Manufacturer AD 的外壳为 `Length` 1 B、`Type=0xFF` 1 B、Company ID 2 B，共 **4 B**。现有 `phy-frame` BlueBee 映射将每个 IEEE 802.15.4 PHY 字节展开为 4 个 BLE 字节：4 B 前导码 + 1 B SFD + 1 B PHR + 35 B 实验控制负载 + 2 B FCS = **43 B → 172 B**；其中 PSDU 长度为 37 B。

| 部分 | 大小 |
| --- | ---: |
| secondary 扩展头及长度字节 | 10 B |
| Flags AD | 3 B |
| Manufacturer AD 外壳 | 4 B |
| BLE 控制记录 | 35 B |
| BlueBee 区域：43 B PHY 帧 × 4 | 172 B |
| **secondary PDU payload 合计** | **224 B / 255 B** |
| **剩余** | **31 B** |

Manufacturer AD 的 Length 值为 `1 + 2 + 35 + 172 = 210 (0xD2)`，整个 AD 结构为 211 B；AdvData 共 214 B。相对 secondary PDU payload 起点，Flags 占偏移 10–12，Manufacturer Length/Type/Company ID 占 13–16，BLE 控制记录占 17–51，BlueBee 区域占 52–223。若空口参考点选 BLE 前导码起点，则 ZigBee 前导码起点的**设计位置差**为 `(5 B BLE 前导码与 AA + 2 B PDU 头 + 52 B) × 8 µs/B = 472 µs`（LE 1M）；这只是布局差，实际检测误差仍需测量，布局一变须重算。

一般化公式（Flags 保留、BLE 控制记录长度为 `B`、IEEE 802.15.4 侧 FCS 前实验负载长度为 `Z`）：

```text
secondary_pdu_payload_B = 10 + 3 + 4 + B + 4 × (Z + 8)
                        = 49 + B + 4Z
v1: B = Z = 35  → 224 B
固定 B = 35 时，单 PDU 容量允许 Z ≤ 42 B（含 FCS 的 PSDU 为 44 B）；需另测解码可靠性。
```

每加 1 B 802.15.4 实验负载，占 4 B secondary；如果两侧控制记录都加 1 B，总开销增 5 B。BLE LE 1M 空口中，v1 secondary 还要计入 5 B 前导码/AA、2 B PDU 头和 3 B BLE CRC，合计 `234 B × 8 = 1872 µs` RF 发射时间。当前单个 primary 布局的 PDU payload 为 7 B，其 RF 发射时间为 `(5+2+7+3)×8 = 136 µs`。**一次事件的一 primary + 一 secondary 为 2008 µs RF 发射时间**；若使用多个 primary、重复 K 次或改变 PHY，须按实际发射重新核算，包间静默单列而不算 RF 发射时间。

## 4. 可复核测试向量

示例：`run_id=1001`、`slot_index=7`、`ref_tick_ms=1400`、`period_ms=200`、`command_id=42`、`execute_at_ms=3000`、`valid_until_ms=2500`、`flags=1`、`opcode=SET_STATE`。BLE 侧向节点 1 设置值 1；IEEE 802.15.4 侧向节点 2 设置值 2。两侧共用任务和目标时刻，但命令参数可以不同。

```text
BLE 35 B:
B2 43 01 01 E9 03 07 00 00 00 78 05 00 00 C8 00
2A 00 00 00 01 00 01 01 00 B8 0B 00 00 C4 09 00 00 80 98

IEEE 802.15.4 侧实验控制负载 35 B（FCS 前）:
B2 43 01 01 E9 03 07 00 00 00 78 05 00 00 C8 00
2A 00 00 00 02 00 01 02 00 B8 0B 00 00 C4 09 00 00 EA E6
```

其中 `80 98`、`EA E6` 是各自应用 CRC。示例 802.15.4 PHY 帧的 PHR Length 为 `0x25`（35 B 实验负载 + 2 B FCS），对完整 35 B 实验负载计算的 FCS 为 `97 3D`；完整 PHY 帧前 6 B 为 `00 00 00 00 A7 25`。测试向量只确定字段编码，尚未证明这份新布局在 RF 上可解码。

## 5. P1 冻结前的检查

1. 用独立构造器生成两个 35 B 记录及完整 43 B PHY 帧，验证上述向量、CRC、BlueBee 映射、BLE 白化预补偿和完整 PDU 长度；对未知版本、错误 CRC、字段越界及重复任务给出确定性错误结果。
2. 明确板端能否在发射前确定 `ref_tick_ms`，并测出计划时刻至实际空口时刻的抖动上界；若不能满足候选 50 ms 容差所需预算，先修改时间语义或实验目标，不把不可测延迟藏在同步算法里。
3. 按规范修正当前生成器 `Aux PHY LE 1M=0x01` 的错误编码（应为 0），核实 primary AuxPtr 指示的信道/偏移与实际 secondary 一致；固定频点同频调试和完整 exadv 跟随分别验收。
4. 在同 IQ 双解码确认后，再进行独立双 HackRF 的命令匹配和时间模型实验。P1 草案不修改旧 `bluebee_*_perf_start?` 命令、测试头、填充或 Sequence 规则。

规范依据：[Bluetooth Core Link Layer](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core_v6.3/out/en/low-energy-controller/link-layer-specification.html)、[Bluetooth GAP AD 结构](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-60/out/en/host/generic-access-profile.html)、[Bluetooth CSS Manufacturer Specific Data](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/CSS_v12/out/en/supplement-to-the-bluetooth-core-specification/data-types-specification.html)；实际 4:1 映射、扩展头和 PHY/FCS 算法以仓库[现有生成器](../python/std_ble/generate_ble_exadv_iq_30_72M.py)为准。
