# 论文核心宣称查新报告（A/B 节）

- 日期：2026-11-17
- 范围：`doc/next_stage_plan.md` 及 N4/N5 结果中总结出的 A1–A6、B1–B3 核心/条件核心宣称
- 方法：OpenAlex、Crossref、公开网页与 IEEE/ACM 摘要页；按“单包双协议、跨信道跟随、相对时间、单侧失更、成本/容量、K 重发”逐条对照
- 性质：**文献 prior-art 查新，不是教育部查新工作站的正式查新报告**
- 更新：2026-11-17 增补 §1.4（中低档 SCI 定位：是否需要继续提升新颖性）

---

## 1. 结论摘要

### 1.1 总体判断

**A1 + A2 + A4 的“系统组合”有查新空间，可以作为论文核心；A3/A5 只能作为支撑；A6/B1/B2/B3 属于测量与评估，不是新原理。**

本轮未检索到一篇同时覆盖以下四点的完全相同工作：

1. 单个 BLE extended-advertising secondary PDU；
2. 同一 PDU 内同时承载 BLE 控制记录与 BlueBee/IEEE 802.15.4 控制记录；
3. 两侧恢复同一个共同时间参考；
4. BLE 按 AuxPtr 跨信道跟随，IEEE 固定信道独立解码，并在真实单侧解码缺失下进入 holdover/stale、保守拒绝、恢复后重获 tracking。

但“单包双协议可解”“跨协议广播控制”“跨协议时间同步”“单包同步”“单次发射多协议接收”分别已有强前作。**不能把组合写成“首次提出跨协议同步方法”。**

### 1.2 可写 / 不可写

| 类型 | 结论 |
|---|---|
| 可写为核心 | A1 单 PDU 双控制+共同时间；A2 跨信道 BLE 跟随+IEEE 同轮；A4 真实单侧失更状态机 |
| 可写为支撑/评估 | A3 相对时间预测；A5 未校准参考拒绝；A6 共包成本刻画；B1 C1 成本交叉；B2 容量网格；B3 重发试点 |
| 不可写 | “首次跨协议同步”“首次 BLE–802.15.4 同步”“首次单包同步”“首次单次发射多协议接收”“首次跨协议广播控制”“高精度/μs 级”“同步执行”“商用兼容”“能耗下降” |

### 1.3 最强可辩护表述（需完成全文查新后使用）

> To the best of our knowledge, no prior work combines a single BLE extended-advertising secondary PDU carrying both BLE and IEEE 802.15.4 control records plus a shared time reference, cross-channel AuxPtr following, and live single-side loss handling with conservative timed-command rejection.

在此之前，正文用 “we design / we demonstrate / in our prototype”，不要用 “first”。

### 1.4 目标定位：中低档 SCI 下是否需要继续提升新颖性

**结论：不需要为了“新颖性”再发明新机制。** 如果不追求高影响力刊物/会议、只求 SCI 收录，当前 A1+A2+A4 的系统组合已经够用；应把精力放在“贡献写得清、边界守得住、证据闭环”，而不是再做一个新算法。

中低档 SCI 的 novelty 标准通常是：

- 一个新的**系统组合**，而不是新原理；
- 有真实硬件/协议实现；
- 有可复查的测量与对照；
- 声称与证据匹配，不夸大到“首次/高精度/商用”。

当前证据已覆盖这些：

| 证据 | 规模 | 能支撑 |
|---|---|---|
| N1 2001–2003 | 3 轮，3/3 任务，BLE 跟随 276/360 | A2 跨信道跟随 |
| N5 2509–2517 | 9 轮，A/B/C 三组 | A4 单侧失更/重获 |
| N5 2504 等 | 24/24 live probe | A3 相对时间 |
| N2 3 轮 + N4 12 轮 | 240 vs 360 突发 | A6 成本 |
| N4 2411–2416 | 3 个负载点 | B1 成本交叉 |
| 2301–2315 | 15 点，100/100 | B2 容量 |

**真正的风险不是新颖性，而是以下三件事：**

1. **被看成“BlueBee + X-Sync 的工程拼接”**：应对不是加新算法，而是把“组合为什么非平凡”写清楚——单 PDU 双控制+共同时间、跨信道 AuxPtr 跟随、真实单侧失更状态机，三者共同决定包布局、472 µs 参考点、自包含更新和保守拒绝。
2. **把“同步”写得比证据大**：不要写绝对同步/同步执行/商用兼容；写 relative time reference、software-scheduled prototype、SDR-based receiver。
3. **贡献点太散**：A1–A6、B1–B3 全塞进去会像实验报告；只留 3 条主贡献，其余放评估节。

**最小动作（不需要新实验）：**

- 写一页 gap/prior-art 表（本文第 3 节可直接用）；
- 贡献列表收敛为 A1、A2、A4/A5 三条；
- 加“不声称”段：绝对同步、执行器、商用、能耗、多节点；
- 标题/摘要去“高精度”，用 “single-PDU dual-protocol control and time transport / cross-channel / live loss handling”；
- 主线证据只用强项：N1 3 轮、N5 9 轮、N2 3 轮、N4 12 轮；B1/B2/B3 放补充，B3 等 2521–2529 再升级。

**何时才需要提升新颖性：** 要投 TMC/TON/IoT-J 或顶会，或审稿人明确说 “incremental / combination of existing techniques”。那时再加机制性增量（共享 epoch 的参考点代数、单侧失更自适应更新/保持、共包控制+时间联合可靠性模型），属于“把现有系统做深”，不是从零发明。

---

## 2. 逐条查新

### A1：单 secondary PDU 同时承载双协议控制 + 共同时间字段

**最接近工作**

| 工作 | 已做到 | 与 A1 重叠 | 仍缺 |
|---|---|---|---|
| **BlueBee**（SenSys’17 / ToN’19） | 单个 BLE 包内仿真完整 ZigBee 帧，BLE/ZigBee 双标准可解 | “单包双协议可解” | 只有 ZigBee 负载，没有 BLE 控制记录、没有共同时间字段 |
| **Brunner et al.**（DCOSS’21） | Wi-Fi/BLE/ZigBee 跨协议广播控制，手机无网关控制异构设备 | “跨协议广播控制”用例 | 是否为单个 BLE exadv PDU 同时携带两类控制+时间，需读全文确认 |
| **WiCast**（INFOCOM’23 / TMC’25） | 单个 802.11ax RU 复合信号被 BLE/ZigBee/LoRa 接收 | “一次发射服务多协议接收端” | 面向数据吞吐，不是控制+时间，也不是 BLE exadv |
| **X-Sync / Crocs / TimeBee** | 跨协议时间同步 | “跨协议时间字段” | 没有双协议控制记录；X-Sync 还是多 burst 帧 |

**判断**：A1 是**组合型空白**，novelty 中等。可写“我们设计并验证了单 PDU 双控制+共同时间的系统”，不能写“首次单包双协议”。

---

### A2：ch39→ch3 BLE AuxPtr 跟随 + IEEE ch12 同时独立解码

**最接近工作**

| 工作 | 已做到 | 与 A2 重叠 | 仍缺 |
|---|---|---|---|
| BLE 5 规范 / 商用 exadv | primary→secondary 的 AuxPtr 跟随是标准行为 | “BLE 跟随”本身 | 不是跨协议共包，也没有 IEEE 同轮接收 |
| **BlueBee** | BLE 包内 ZigBee 帧 | 同一 BLE 波形被 IEEE 解 | 不是 exadv primary/secondary，不涉及 AuxPtr 跟随 |
| **WiCast / 并行 CTC** | 单次复合发射到多协议接收 | “同轮多协议接收” | 不是 BLE exadv 跟随，也不是控制+时间 |

**判断**：未检索到“BLE exadv 跨信道跟随 + IEEE 同时解码”的完全相同工作；但“BLE 跟随”是标准机制，“单次发射多协议接收”已被 WiCast 覆盖。A2 是**工程/系统组合**，novelty 中低；价值在实测证据。

**本项目证据**：2001/2002/2003 三轮，IEEE 120/120；BLE 跟随 93/88/95 槽，合计 276/360 = 76.7%；按有效 primary 276/308 = 89.6%；三轮均 3/3 任务。

---

### A3：固定频点相对时间预测中位 0.1–0.3 ms、P95 0.15–0.72 ms

**最接近工作**

| 工作 | 已做到 | 与 A3 重叠 | 仍缺 |
|---|---|---|---|
| **X-Sync**（LCN’21） | BLE↔802.15.4 直接 CTC 同步，μs 级，MAC 打戳，多 burst 帧 | 同协议对、同时钟问题、同 CTC 思路 | 需要专用多 burst 帧/双向；不是单 PDU 控制+时间 |
| **Crocs**（EWSN’18） | 首个跨协议时钟同步，WiFi–ZigBee，<1 ms | 跨协议时钟同步 | 解耦同步信号与时戳，需要 Barker beacon |
| **TimeBee**（IoT-J’23） | WiFi 辅助 ZigBee，CTC 传时戳 | 跨协议时间同步 | 单侧 WiFi→ZigBee |
| **WizSync**（TMC’14） | WiFi AP 广播授时，ZigBee 节点，0.12 ms | 单向广播授时 | 不是单包双协议 |
| **UAV CTC sync**（Sensors’20） | 广播 CTC，30 节点，99% <30 µs | 广播 CTC 同步 | 只覆盖 ZigBee |
| **AnchorSync**（IEEE Access 2026） | **BLE 单包同步**，<300 ns，处理丢包/重传 | “单包同步”本身 | BLE-only，不是跨协议 |

**判断**：A3 的精度并不占优（X-Sync 约几十 µs、AnchorSync <300 ns，我们中位 0.1–0.3 ms）；“单包同步”也已被 AnchorSync 占住。A3 只能作为“单 PDU 双协议共同时间参考”的**支撑证据**，不能单独作为“高精度同步”贡献。

**本项目证据**：N3 2201/2203 offset 中位 115.8/135.3 µs，P95 151/161 µs；update_1s 中位 137/157 µs，P95 305/326 µs。N5 2504/2509–2517 live probe 24/24，中位绝对 0.19–0.34 ms，P95 0.42–0.72 ms。

---

### A4：真实单侧失更 → holdover/stale/reacquiring + 保守拒绝

**最接近工作**

| 工作 | 已做到 | 与 A4 重叠 | 仍缺 |
|---|---|---|---|
| PTP/NTP 时钟状态 | holdover、clockClass、validity、root distance | “失更/质量状态”是标准 | 不是跨协议单包广播 |
| **WizSync** | 预测 skew、自适应睡眠 | 单向广播下的保持 | 不是在线单侧失更/重获状态机 |
| **AnchorSync** | 监控接收时戳、处理丢包/重传、重同步 | 丢包/重传下的同步鲁棒性 | BLE-only，连接型；不是跨协议广播 |
| **X-Sync** | 双向 CTC 同步 | 跨协议同步的误差处理 | 不是“单侧解码缺失 + 保守拒绝 + 重获”状态机 |

**判断**：状态机原理本身不新；但“跨协议单包广播 + 真实单侧解码缺失 + 在线保守拒绝 + 重获”的组合未检索到完全相同工作。A4 是目前**最像系统贡献**的一条，novelty 中等；必须写成“系统机制 + 实测状态路径”，不能写成“新时钟算法”。

**本项目证据**：2509–2517 九轮，A 组 3×6/6；B 组 5/4/5/6；C 组 4/5/4/6；受影响侧 probe 16–20/24；六轮受影响侧均走过 `tracking→holdover→stale→reacquiring→tracking`。2511/2515 操作偏差保留标注，不作严格同条件效应量。

---

### A5：未校准参考下拒绝定时处理，immediate 仍 6/6

| 工作 | 已做到 | 与 A5 重叠 | 仍缺 |
|---|---|---|---|
| PTP/NTP | 参考质量未知/失效时拒绝授时或标记不可用 | “质量不足不执行”是标准安全策略 | 不是跨协议软件调度 |
| **AnchorSync / X-Sync** | 处理丢包、重传、重同步 | 鲁棒性 | 没有“未校准参考界 → 拒绝定时执行”的显式策略 |

**判断**：A5 是安全策略/工程边界，不是新原理。可作为“不在未校准条件下伪造同步执行”的方法学贡献，但不应作为核心 novelty。

**本项目证据**：2504/2507/2508 真实未校准定时处理 0/6；immediate 6/6；合成 1 ms 参考界只验证状态机；2504 每侧 18 次 `time_quality_insufficient`。

---

### A6：共包减少 33.3% 突发/提交，但有效波形预算不变

| 工作 | 已做到 | 与 A6 重叠 | 仍缺 |
|---|---|---|---|
| **BlueBee** | 单 BLE 包承载 ZigBee，减少跨协议转发 | 单包承载、减少发送 | 不是“共包 vs 分别发送”的同预算对照 |
| **WiCast / 并行 CTC** | 单次复合发射减少多协议串行发送 | 减少发射次数 | 不是 BLE+ZigBee 控制/时间成本核算 |
| **Waves**（ToN’23） | WiFi 广播到多 ZigBee 节点 | 广播减少提交 | 不是双协议共包 |

**判断**：A6 是测量/成本刻画，不是新机制；“减少突发、有效波形不变”是打包的自然结果。可作为系统评估的一节，不能当核心 novelty。

**本项目证据**：N2 三轮 2101/2102、2104/2105、2107/2108：各 3/3 任务；240 vs 360 突发；双方 240,960 µs。N4 第一层三对：100/100；200 vs 300 突发；204,800/225,600 µs 相等。

---

### B1：C1 紧凑格式成本交叉

| 工作 | 已做到 | 与 B1 重叠 | 仍缺 |
|---|---|---|---|
| BLE 5 legacy vs extended advertising | 负载/分片/容量的标准权衡 | “legacy 分片 vs 扩展广播” | 不是跨协议共包 + 时间字段 |
| 6LoWPAN/头部压缩 | 紧凑编码 | 紧凑编码本身 | 不是 BLE/ZigBee 双协议 |
| **BlueBee** | 高码率跨协议载荷 | 载荷效率 | 不是 C1/legacy 成本交叉 |

**判断**：B1 是针对当前实现的测量，novelty 低；且存在 JC ch3 vs LC ch39 的 BLE 信道混杂，必须先消除才能作为公平对照。

**本项目证据**：N4 2411–2416：0 B +13.19%；26 B −24.68%；2/6 B −6.45%；2413 收 400 分片、2416 收 200 分片，均完整重组 100/100。

---

### B2：2301–2315 十五点、229–255 B、全部 100/100

**判断**：255 B 是 BLE 5 规范上限；“15 点全通过”是容量扫描结果，不是新机制。可作为“当前实现容量边界未触顶”的证据，但不能写“容量上限”或“普遍可靠”。

**本项目证据**：2301–2315 共 15 点，PDU 229–255 B，每点 100/100。

---

### B3：实际重发挽回首发失败任务；K 可靠性未确认

| 工作 | 已做到 | 与 B3 重叠 | 仍缺 |
|---|---|---|---|
| 标准 ARQ/重复广播 | 重发提高成功率 | 重复发送 | 不是跨协议 K 对照 |
| **Waves / X-Cast / RCTC** | 广播/CTC 的可靠性与重复 | 跨协议广播可靠性 | 不是 BLE+IEEE 双协议 K 物理对照 |

**判断**：B3 目前只是 3 轮试采，不能作为核心宣称；等 2521–2529 三组各三轮完成后，才能升级为“uniform-K 物理可靠性收益”的测量贡献。

**本项目证据**：2518–2520 试采 K=5/3/1，全 K 6/6、6/6、4/6；首发 4/6、5/6、4/6；实际重发挽回了 3 个首发失败任务。

---

## 3. 最接近工作总表

| 工作 | 年份/ venue | 与本文最接近的点 | 不能覆盖的点 |
|---|---|---|---|
| **BlueBee** | SenSys’17 / ToN’19 | 单 BLE PDU 承载 ZigBee 帧 | 无 BLE 控制记录、无共同时间 |
| **Crocs** | EWSN’18 | 首个跨协议时钟同步 | WiFi–ZigBee，解耦 beacon，<1 ms |
| **X-Sync** | LCN’21 | BLE↔802.15.4 CTC 同步，μs 级 | 多 burst 专用帧，非单 PDU 控制+时间 |
| **TimeBee** | IoT-J’23 | CTC 时间同步 | WiFi 辅助 ZigBee，单侧 |
| **WizSync** | TMC’14 | 单向广播授时，0.12 ms | 非单包双协议 |
| **UAV CTC sync** | Sensors’20 | 广播 CTC 同步，30 节点 | 仅 ZigBee |
| **AnchorSync** | IEEE Access 2026 | 单包 BLE 同步，<300 ns | BLE-only，连接型 |
| **WiCast** | INFOCOM’23 / TMC’25 | 单次复合发射到多协议接收 | 数据吞吐，非控制+时间 |
| **Brunner et al.** | DCOSS’21 | 跨协议广播控制，无网关 | 是否单 PDU、是否含时间待全文 |
| **X-Cast** | DCOSS-IoT’25 | 跨协议广播协调 | 频谱利用，非时间/控制 |
| **Waves** | ToN’23 | WiFi 广播到 ZigBee 节点 | 非双协议共包 |

---

## 4. 论文定位与措辞

### 4.1 建议贡献点（中低档 SCI 定位）

1. **Single-PDU dual-protocol transport**：一个 v1 secondary PDU 同时携带 BLE 与 IEEE 802.15.4 控制记录及共同时间字段；两条独立 SDR 链恢复并联合解析（A1）。
2. **Cross-channel follow + coexistence**：ch39→ch3 的 BLE AuxPtr 跟随与 IEEE ch12 独立解码在同一轮完成；三轮 3/3 任务（A2）。
3. **Live loss handling**：真实单侧缺失下在线 `holdover/stale`、保守拒绝和 `reacquiring→tracking`；不把离线掩码当现场证据（A4/A5）。

**A3** 作为“相对时间参考”的支撑节，不单独作为“高精度同步”贡献；**A6/B1/B2/B3 不放进贡献列表**，放“成本/容量评估”节；**B3** 等 2521–2529 完成后再升级。

### 4.2 禁用/替换

| 禁用/高风险 | 改为 |
|---|---|
| 首次提出 / first | “we propose / we design”；确有全文查新后再写 “to the best of our knowledge” |
| 高精度 / 微秒级 | 写实测中位/P95 与样本数；当前约 0.1–0.3 ms 中位 |
| 单包同步（单独） | “单 PDU 双协议控制+共同时间” |
| 同步执行 / 执行成功 | “联合解析 / 软件调度原型” |
| 商用兼容 | “SDR-based receiver prototype” |
| 能耗下降 / 空口时长下降 | “减少突发/提交次数；提交波形预算不变” |

### 4.3 标题/摘要建议

- 标题强调“single-PDU dual-protocol control and time transport / cross-channel / live loss handling”，不要强调“new synchronization method”。
- 摘要先写系统问题与设计，再写“relative time reference”；不要先写“高精度同步”。
- 贡献列表用 “we design, implement, and measure”，避免 “first”。

---

## 5. 仍需补的查新

1. **IEEE Xplore / ACM DL 全文**：重点查 BlueBee、X-Sync、AnchorSync、Brunner、WiCast 的全文和引用网络；确认 Brunner 是否单帧、AnchorSync 是否涉及跨协议。
2. **CNKI/万方**：中文“跨协议 时间同步 单包”“BLE 扩展广播 ZigBee”检索；目前未覆盖。
3. **专利**：Google Patents/Espacenet 检索 “single packet cross-protocol timestamp”“BLE extended advertising synchronization”。
4. **BLE exadv 研究**：目前 OpenAlex 上 “extended advertising + ZigBee” 命中很少；需要 IEEE 全文确认是否已有“exadv 作为跨协议载体”的工作。
5. **正式查新报告**：如果学校要求教育部查新工作站盖章，DSH 的检索不能替代。

---

## 6. 参考文献（已核 DOI/出版信息）

1. W. Jiang, Z. Yin, R. Liu, Z. Li, S. M. Kim, T. He, “Boosting the Bitrate of Cross-Technology Communication on Commodity IoT Devices,” *IEEE/ACM Trans. Netw.*, vol. 27, no. 3, pp. 1069–1083, 2019. DOI: [10.1109/TNET.2019.2913980](https://doi.org/10.1109/TNET.2019.2913980)
2. R. Hofmann, D. Grubmair, C. A. Boano, K. Römer, “X-Sync: Cross-Technology Clock Synchronization Among Off-the-Shelf Wireless IoT Devices,” *Proc. IEEE LCN*, pp. 115–122, 2021. DOI: [10.1109/LCN52139.2021.9524940](https://doi.org/10.1109/LCN52139.2021.9524940)
3. Z. Yu, C. Jiang, Y. He, X. Zheng, X. Guo, “Crocs: Cross-Technology Clock Synchronization for WiFi and ZigBee,” *Proc. EWSN*, pp. 135–144, 2018; arXiv: [2209.15407](https://arxiv.org/abs/2209.15407)
4. D. Gao, Y. Liu, B. Hu, L. Wang, W. Chen, Y. Chen, T. He, “Time Synchronization Based on Cross-Technology Communication for IoT Networks,” *IEEE Internet Things J.*, vol. 10, no. 22, pp. 19753–19764, 2023. DOI: [10.1109/JIOT.2023.3282202](https://doi.org/10.1109/JIOT.2023.3282202)
5. T. Hao, R. Zhou, G. Xing, M. W. Mutka, J. Chen, “WizSync: Exploiting Wi-Fi Infrastructure for Clock Synchronization in Wireless Sensor Networks,” *IEEE Trans. Mobile Comput.*, vol. 13, no. 6, pp. 1379–1392, 2014. DOI: [10.1109/TMC.2013.43](https://doi.org/10.1109/TMC.2013.43)
6. Z. Tan, X. Yang, M. Pang, S. Gao, M. Li, P. Chen, “UAV-Assisted Low-Consumption Time Synchronization Utilizing Cross-Technology Communication,” *Sensors*, vol. 20, no. 18, 5134, 2020. DOI: [10.3390/s20185134](https://doi.org/10.3390/s20185134)
7. S. Domadenik, M. Jankovec, M. Topič, “AnchorSync: A Robust High-Accuracy Low-Overhead Synchronization Method for BLE Connected Devices,” *IEEE Access*, vol. 14, pp. 129488–129498, 2026. DOI: [10.1109/ACCESS.2026.3725297](https://doi.org/10.1109/ACCESS.2026.3725297)
8. D. Xia, X. Zheng, L. Liu, S. Huang, H. Ma, “WiCast: Parallel Cross-Technology Transmission for Connecting Heterogeneous IoT Devices,” *IEEE Trans. Mobile Comput.*, vol. 24, no. 10, pp. 9506–9523, 2025. DOI: [10.1109/TMC.2025.3564340](https://doi.org/10.1109/TMC.2025.3564340)
9. H. Brunner, R. Hofmann, M. Schuß, J. Link, M. Hollick, C. A. Boano, K. Römer, “Leveraging Cross-Technology Broadcast Communication to build Gateway-Free Smart Homes,” *Proc. DCOSS*, 2021. DOI: [10.1109/DCOSS52077.2021.00014](https://doi.org/10.1109/DCOSS52077.2021.00014)
10. “X-Cast: Cross-Technology Broadcasts for Enhanced Spectrum Utilization in Low-Power Networks,” *Proc. DCOSS-IoT*, 2025. DOI: [10.1109/DCOSS-IoT65416.2025.00018](https://doi.org/10.1109/DCOSS-IoT65416.2025.00018)
11. W. Wang et al., “Simultaneous Data Dissemination Among WiFi and ZigBee Devices,” *IEEE/ACM Trans. Netw.*, 2023. DOI: [10.1109/TNET.2023.3243070](https://doi.org/10.1109/TNET.2023.3243070)
12. “Cross-Technology Communication for the Internet of Things: A Survey,” *ACM Comput. Surv.*, 2022. DOI: [10.1145/3530049](https://doi.org/10.1145/3530049)

---

## 附录 A：本轮主要检索式

```text
"cross-technology" "time synchronization" BLE 802.15.4
"single packet" BLE ZigBee synchronization timestamp
"extended advertising" ZigBee cross-technology
"cross-technology" broadcast control BLE ZigBee
"BlueBee" ZigBee BLE follow-up
"single packet" "cross-technology" synchronization
"cross-technology" retransmission reliability
AnchorSync BLE synchronization
```

**检索限制**：OpenAlex/Crossref/web 为主；X-Sync、AnchorSync、Brunner、WiCast 只读摘要/部分全文；IEEE/ACM/CNKI 全文未系统覆盖；“未检索到”不等于“不存在”，正式投稿前需补全文级查新并记录检索日期/数据库/检索式。
