# 最接近前作全文对照与论文贡献收敛表（P5 写作前置）

日期：2026-11-24（已依 [P5 审计建议](../results/uc1_p5_audit_recommendations_20261124.md) 同步修订）。依据 [AGENTS.md](../../AGENTS.md)、[当前研究计划](current_research_plan.md)、[2026-11-18 查新审查](novelty_ab_claims_review_20261118.md) 与 [P5 冻结结果总表](../results/uc1_p5_frozen_results_20261124.md) 编制。本文严格区分 **已核对全文** 与 **仅摘要/书目核对（全文未取得）**，不把未读全文的项作为本文贡献差异依据，也不把系统组合夸大为“首次提出”。

---

## 1. 最接近前作逐篇核对总表

| 前作（出处） | 核对层级与来源 | 前作已实现的能力 | 与本文（UC1）的重叠 | 关键结构与问题差异（本文针对的单发送机约束） | 本文对应实测证据与诚实边界 |
| --- | --- | --- | --- | --- | --- |
| **BlueBee**<br>Jiang et al., *ACM SenSys 2017* | **本地全文已核对**<br>[BlueBee.pdf](../../python/ctc_sim/bluebee/BlueBee.pdf) §4, §8.3.2 (p.10), §8.3.4 (p.10), §8.4 (p.11), §8.6 (p.12) | PHY 级 BLE→ZigBee 帧仿真；**双标准兼容**（CC2540 BLE 与 CC2530/CC2420 ZigBee 均可解）；BLE 4.2 数据信道长帧（至 257 B）与 ch39 广播信道应用；通道协调与智能灯泡控制（p.12 Fig.28）；商用芯片与 USRP N210 验证。 | 单帧双标准可解；BLE 载荷内嵌仿真的 IEEE 802.15.4 帧；2.4 GHz 控制应用。 | BlueBee 用 BLE 载荷承载仿真的 ZigBee 帧，未研究在**单个无连接 BLE 5 `AUX_ADV_IND`** 中固定并置独立的 BLE 与 IEEE 控制及共同时间记录，也未在**同任务与同波形预算上限**下与同频分别发送（SC）及 legacy C3 分片（LC）比较联合解析与单侧/共同缺失分布。 | **本文证据**：UC1 A/B/C 三布局及 H1 同 IQ 偏移实测；P4 36 轮/3,600 任务在 B 点三区组均观察到 JC 相对 LC 较高的联合解析率（K=1 `+29/+50/+73 pp`，Q=6000 `+23/+100/+75 pp`，均值 `+50.67/+66.00 pp`，95% t 区间跨零，限封装+信道组合）、A 点呈现策略相关的单位成本排序、同频 JC vs SC 呈现 3→2 突发缩减。<br>**本文局限**：仅 SDR 平台（Zynq+双 HackRF），未做商用芯片验证（BlueBee 已做商用芯片）。 |
| **BlueBee 期刊扩展版**<br>Jiang et al., *Boosting the Bitrate of Cross-Technology Communication on Commodity IoT Devices*, **IEEE/ACM ToN**, June 2019, 27(3): 1069–1083 | **仅书目与公开摘要核对（全文未取得）**<br>[机构书目与摘要](https://pure.kaist.ac.kr/en/publications/boosting-the-bitrate-of-cross-technology-communication-on-commodi/) | 据公开摘要：面向商用 IoT 设备的 PHY 级跨技术通信仿真与比特率/吞吐提升。 | PHY 级 BLE→ZigBee 仿真与双标准兼容路线。 | 全文未取得，**不宣称其能力缺项或具体章节细节**；正文引用仅基于已核对的 SenSys'17 原文与该公开摘要，如需细述期刊版扩展机制须先补读原文。 | 不以未读全文作差异论证。 |
| **Brunner et al.**<br>*Leveraging Cross-Technology Broadcast Communication to build Gateway-Free Smart Homes*, *IEEE DCOSS 2021* (Best Paper) | **公开全文/审查已核对**<br>[作者原文 PDF](https://www.carloalbertoboano.com/documents/brunner21smarthome.pdf) · [审查记录](novelty_ab_claims_review_20261118.md#L24) | 基于 X-Burst 的跨技术广播、与原生协议栈并存的调度机制；实现单设备（如智能手机）无网关同时控制 BLE 门锁与 ZigBee 灯泡等异构智能家居设备。 | 单发送端无网关跨技术广播控制 BLE + IEEE 802.15.4 异构设备。 | X-Burst 属于包级能量突发/长度调制路线；本文差异落在单个 BLE 5 `AUX_ADV_IND` 的固定共包布局、双侧结构化控制与共同时间字段、以及同任务与同波形预算下的 JC/SC/LC 联合解析对照。 | **本文证据**：单 secondary PDU 交付已测 A/B/C 三对完整记录（`26/26`、`52/26`、`28/32 B`）；P4 36 轮实测量化短/长负载下的成本与解析权衡。<br>**本文局限**：不具备手机商用无网关部署与真实门锁/灯泡执行器验证。 |
| **X-Sync**<br>Hofmann et al., *X-Sync: Cross-Technology Clock Synchronization Among Off-the-Shelf Wireless IoT Devices*, *IEEE LCN 2021* | **公开全文/审查已核对**<br>[作者原文 PDF](https://www.carloalbertoboano.com/documents/hofmann21xsync.pdf) · [审查记录](novelty_ab_claims_review_20261118.md#L23) | 商用 BLE 与 IEEE 802.15.4 设备间直接双向 CTC 时钟同步；利用变长能量突发与重复 RSS 二分搜索定位帧起点，在 Contiki-NG 商用芯片上实现 $\mu\text{s}$ 级同步精度。 | BLE 与 IEEE 802.15.4 协议对的跨协议时间同步/参考。 | X-Sync 面向商用设备间双向专用高精度时钟同步，采用独立参考测得跨设备时钟偏差；本文不宣称新时钟同步算法，而是把时间信息作为共包控制流的附属能力，在固定次信道下展示单向本侧留出预测残差与单侧失更/恢复状态轨迹。 | **本文证据**：P2 H5（`2715–2717`）展示本侧 IQ 采样域留出残差（中位 `0.13–0.24 ms`）与单侧断开后的计划内 `1/1` 恢复功能实例。<br>**对照口径**：与 X-Sync 并列时必须分别交代参考时基与观测量，**绝不直接排名同步精度**。 |
| **Crocs**<br>Yu et al., *Crocs: Cross-Technology Clock Synchronization for WiFi and ZigBee*, *EWSN 2018* | **仅摘要与公开出处核对（待补读作者全文细节）**<br>[作者 PDF 入口](https://xiaolongbupt.github.io/homepage_files/%5BPaper%5DCrocs_EWSN2018.pdf) | Wi-Fi 与 ZigBee 间的直接跨技术时钟同步；解耦 Barker 信标同步信号与时间戳传输，报告低于 1 ms 的同步误差。 | 跨技术时间信息分发。 | 针对 Wi-Fi/ZigBee 专用时钟同步；本文聚焦 BLE 5 `AUX_ADV_IND` 共包承载双侧控制+时间及单发送机波形预算权衡。 | 仅在 Related Work 归类引用，不以精度排名。 |
| **TimeBee**<br>Gao et al., *Time Synchronization Based on Cross-Technology Communication for IoT Networks*, *IEEE IoT-J*, Nov. 2023, 10(22): 19753–19764 | **仅书目与摘要核对（全文未取得）**<br>[DOI: 10.1109/JIOT.2023.3282202](https://doi.org/10.1109/JIOT.2023.3282202) | 据公开摘要：面向共存 IoT 网络的基于 CTC 的跨技术时间同步框架（Wi-Fi 辅助 ZigBee 授时）。 | 跨技术时间同步领域背景。 | 全文未取得，不沿用 Crocs 的机制或精度描述 TimeBee，也不以其未核对细节作为本文差异依据。 | 仅作相关工作背景引用。 |
| **WiCast**<br>Xia et al., *WiCast: Parallel Cross-Technology Transmission for Connecting Heterogeneous IoT Devices*, *IEEE TMC*, Oct. 2025, 24(10): 9506–9523 | **仅书目与公开摘要核对（全文未取得）** | 据公开摘要：利用 IEEE 802.11ax（Wi-Fi 6）OFDMA 单个 RU 合成复合信号，并行向 BLE、ZigBee 与 LoRa 接收端并发发射，减少多协议串行发射开销。 | 单次发射同时服务多协议接收端、减少突发数。 | 全文未取得；仅就已核公开摘要标明其采用 802.11ax Wi-Fi OFDMA 发射端，与本文 2 MHz 带宽 BLE 5 `AUX_ADV_IND` 载体不同；未核对的全文细节不作差异依据。 | **本文局限**：仅覆盖 BLE+IEEE 802.15.4，不涉及 Wi-Fi/LoRa。 |
| **AnchorSync**<br>Domadenik et al., *IEEE Access 2026* | **仅书目核对（全文未取得）**<br>[审查记录](novelty_ab_claims_review_20261118.md#L25) | 可核对题名与出版书目（BLE 单包同步方向）；具体机制、丢包重传口径及精度未独立取得全文核验。 | 文献检索中命中的 BLE 同步相关工作。 | 全文未取得，**不引用二手精度数字，也不以其能力缺项作为本文贡献差异依据**。 | 绝不宣称“首次单包同步”。 |
| **BLE 5.1 Core Spec**（Extended Advertising） | **本地标准全文已核对**<br>[BLE_Core_v5.1.pdf](../BLE_Core_v5.1.pdf) | 定义 `ADV_EXT_IND`（ch37/38/39）+ `AuxPtr` + `AUX_ADV_IND`（次信道至 255 B payload），突破 legacy 31 B 广告上限。 | 本文 JC/SC 的物理与链路封装载体。 | 标准仅规定 BLE 自身扩展广播；本文研究将其次信道 `AUX_ADV_IND` 作为单包双协议控制与共同时间载体时的字节布局、成本与可靠性权衡。 | **本文局限**：P2/P4 主实验采用固定次信道接收（未将完整 AuxPtr 跟随与在线时间机制合并验证；仅保留历史 N1 跟随作独立分项证据）。 |

---

## 2. 收敛后的论文核心问题与三条可辩护贡献（与冻结报告一致）

### 核心研究问题
> 在**单 SDR 发送机**约束下，将 BLE 与 BlueBee/IEEE 802.15.4 双侧应用控制命令及共同时间参考封装于同一个 BLE 5 `AUX_ADV_IND`（JC）中，相较于同频分别发送（SC）与 legacy 广告/分片基线（LC），其容量边界、波形成本交叉点、同预算计划尝试内联合命令解析权衡及固定次信道时间参考可用性究竟如何？

### 三条严格有实测闭环支撑的贡献（不使用 “first”，全部回链 [P5 冻结结果总表](../results/uc1_p5_frozen_results_20261124.md)）

1. **统一紧凑双协议共包架构与容量/布局核验（UC1 + C3）**：
   - 采用显式版本隔离（`0xC1 0x10/0x11`）、固定配置布局（共同约束 $b+4z \le 26$，不可将两个边际最大值 $b=26$ 与 $z=6$ 组合为已测点）、确定性包内字段位置（$400+8b\;\mu\text{s}$）及带独立 `pending/closed` 容量不变量的 C3 15 B 分片基线；
   - **已测 JC 完整记录长度与字节拆分**（每侧 UC1 完整记录为 `24 B 固定字段 + n B 本侧扩展应用数据 + 2 B CRC-16`。固定字段含目标、操作码、参数及时间字段；BLE 侧 n=b，IEEE 侧 n=z）：
     - **A 点（`b=0, z=0`）**：BLE/IEEE 完整记录 `26/26 B`，BlueBee 映射 `136 B`，JC secondary payload `179 B`；
     - **B 点（`b=26, z=0`）**：BLE/IEEE 完整记录 `52/26 B`，BlueBee 映射 `136 B`，JC secondary payload `205 B`；
     - **C 点（`b=2, z=6`）**：BLE/IEEE 完整记录 `28/32 B`，BlueBee 映射 `160 B`，JC secondary payload `205 B`；
     - **B1 点（`b=1, z=0`）**：验证 LC 侧 `27 B` legacy 直接承载边界（不进入 C3 分片）。
   - **冻结证据**：P2 H1 同 IQ 三点偏移实测（A `400.25 µs`、C `416.25 µs`、B `608.00 µs`，均 10/10）、H2/H3 10 分支 R0 全收、H6 实录流离线故障注入（`2714` C3 7/7、`2715` `time` 4/4 通过，显式标注离线合成注入）。

2. **单发送机下的成本—联合解析权衡实证（P4：36 轮 / 3,600 计划任务，3 独立交替区组）**：
   - **短负载 A（`b=0, z=0`，legacy 无需分片）**：LC 单次尝试波形代理最低（`1,456 µs` vs JC/SC `1,648 µs`），`K=1` 下 LC 合并单位成功成本最低（`2,141.2 µs/任务`，SC `2,332.1`，JC `2,411.7`）；在 `Q=6000 µs` 下三模式计划内联合解析率均接近饱和（JC `98.0%`、SC `99.7%`、LC `98.3%`），单位成功成本排序随策略改变——JC（`5,044.9 µs/任务`）低于 LC（`5,922.7 µs/任务`，低约 `14.8%`，SC 为 `4,960.5 µs/任务`）。
   - **长负载 B（`b=26, z=0`，LC 触发 C3 五片重组）**：三个独立区组中，JC 相对 LC 均观察到较高的联合解析率——`K=1` 逐区组差 `+29 / +50 / +73 pp`（均值 `+50.67 pp`，95% t 区间 `[-4.00, +105.34] pp`，合并单位成功成本低 `76.9%`）；`Q=6000 µs` 逐区组差 `+23 / +100 / +75 pp`（均值 `+66.00 pp`，95% t 区间 `[-31.58, +163.58] pp`，JC 总提交波形低于 LC 且合并单位成功成本低 `69.4%`）。两区间均跨零且端点超出 ±100 pp（源于 `df=2` 小样本 t 近似与区组波动），不宣称统计显著；且因 JC/SC 使用 ch3、LC 使用 ch39，结论严格限定在所测封装与信道组合。B2 `2743`（IEEE 恢复 `98/100`，BLE 收到 `210` 片 C3 分片但完整重组 `0` 条）及 B3 `2761/2764` 的分片与重组观测见冻结总表。B 点 LC 完整重组要求同一发送尝试的五片全部到齐。现有记录无法确定各片缺失的具体原因。用 $p^5$ 表示重组成功概率，还需假设五片接收相互独立且成功概率均为 $p$。
   - **同频公平对照 `JC vs SC`（12/12 满足配置匹配与协议归因检查）**：四个条件配对均值分别为 `-2.33 / -1.67 / +7.33 / -2.00 pp` 且 95% t 区间均跨零，**在已测条件下未观察到 JC 相对 SC 的稳定联合解析优势**（配置匹配与区间跨零均不证明等效）。四分类呈现出不同的单侧与共同缺失分布（例如 `A-K1` 合并 300 任务中 JC `ble_only=9/300`、`neither=33/300`，SC `ble_only=42/300`、`neither=12/300`；`B-K1` JC `12/300`、`21/300`，SC `41/300`、`8/300`，未对双侧相关性作形式检验）。可直接确认的结构收益是：A/B 点单次尝试波形预算与 SC 相等，但 JC 将每次尝试由 **3 个突发减至 2 个突发**，并提供经同 IQ 核验的固定包内位置。
   - **截止期口径**：3,600 个 P4 计划任务中，`2,730/3,600` 个已联合解析任务的截止期分类为 `unknown`，`870/3,600` 个未联合解析任务为 `not_decoded`（合计 `3,600`）。

3. **固定次信道共包时间参考可用性与单侧失更恢复功能实例（P2 H5）**：
   - 在不宣称新时钟同步算法或跨设备绝对精度的前提下，通过 `2715–2717`（300 槽含 282 等长纯时间更新，尾段分离口径 `uc1_time_tail_audit`）展示本侧 IQ 采样域留出预测残差（中位 `0.129–0.242 ms`）、探测覆盖（未受干预侧 `24/24`，受干预侧 `19/24`）、未知外部参考界下的保守拒绝（定时处理 `0/6`）及真实 BLE/IEEE 单侧断连后的计划内 `1/1` 恢复功能实例（停发尾段 `stale` 单独列报）。与 X-Sync 等文献对照时分别交代参考时基与观测量。

---

## 3. 写作“严禁越界”自查红线（投稿前逐条复核）

- **不写**“首次提出双协议广播 / 首次 BLE–ZigBee 共包 / 首次无网关控制 / 首次单包同步”；
- **不写**“显著领先”或“两者等效”（跨零 `df=2` 区间只报逐区组差值、均值、范围与小样本区间限制）；
- **不写**微秒级跨设备绝对时钟精度、不把本文本侧相对预测残差与 X-Sync 等跨设备同步精度直接排名；
- **不写**“截止期内联合交付”或“全部任务均为 unknown”（统一按 `2,730/3,600 unknown + 870/3,600 not_decoded` 列报，主指标写 `within planned attempts`）；
- **不把** `JC vs LC` 的可靠性差单独归因于协议格式（始终标注 ch3 vs ch39 信道差异与封装+信道配置级口径）；
- **不把**提交波形代理时长（`µs`）或 DMA 完成写成实测 RF 空口时长/能耗，也不宣称商用芯片兼容或物理执行器同步动作。
