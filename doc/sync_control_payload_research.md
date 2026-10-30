# 共包控制与同步负载：既有方案调研

资料核对：2026-10-30。本文整理**原始论文、标准和厂商实例**中可借鉴的机制，供单个 `AUX_ADV_IND` 中 BLE/BlueBee 双协议控制负载设计使用。它是候选方案研究笔记，不是共包协议定义、系统性查新结论或同步性能实测。

## 1. 本项目现状与问题边界

- [现有同 IQ 验证](../python/sync_validation/README.md)只用旧性能帧的 Run ID/Sequence 将独立恢复的 BLE、802.15.4 结果关联；旧帧没有 BLE 独立控制命令或同步字段。它从已解码 PDU 计算包内位置补偿，当前旧布局为 `216 µs`，不是今后任意布局的常数。该结果不能证明两块 HackRF 的时钟同步。
- [BLE 接收器说明](../python/exadv_rx/README.md)明确固定 secondary 接收和同频诊断尚非完整 AuxPtr 跟随；旧生成器的 Aux PHY 值也需按规范修正和重新验证。即使收到 secondary，也不能以此推出跨信道 exadv 兼容。
- 当前无线发送端只有一块 SDR、接收端是两块 HackRF，暂无共享触发或时钟、商用执行器及回传链路。后文的“同步执行”只在测得执行事件后才能使用；现阶段可设计并验证的是时间字段恢复、包参考点估计、软件命令解析和相应的误差边界。

## 2. 文献与业界方案

| 来源 | 可靠同步或控制机制 | 对本项目的启示与适用边界 |
|---|---|---|
| [FTSP，Maróti 等，SenSys 2004](https://archive.isis.vanderbilt.edu/sites/default/files/Maroti_M_11_3_2004_The_Floodi.pdf) | 用一条广播消息在发端和收端给同一无线事件打时间戳；在射频/字节边界附近时间戳以减少软件与编码抖动，并用历史样本线性回归估计时钟偏移及频率偏差。论文明确单向消息不能消除传播时延。 | 应定义唯一空口参考点及字段相对该点的位置；接收端使用 IQ 采样索引而非主机到达时刻。重复观察才可估计漂移。文中 Mica2 的微秒级结果不能移植到 HackRF。 |
| [RBS，Elson、Girod、Estrin，OSDI 2002](https://www.usenix.org/events/osdi02/tech/full_papers/elson/elson.pdf) | 共同广播事件让多个接收端记录各自到达时刻，再**交换接收观察值**，消除发送端不确定时延。 | “同一物理包”有利于定义共同观测事件；但没有独立时钟校准和接收端互报，不能直接由两块 HackRF 的相对样本位置求时钟偏移。其接收者互报步骤不属于当前单向共包。 |
| [CheepSync，Sridhar 等，2015](https://arxiv.org/abs/1501.06479) | 在 BLE 4.x 广播中结合底层时间戳和发送/接收误差补偿，给被动扫描端提供时间参考；论文在其硬件与软件配置下报告约 `10 µs` 量级的单跳平均误差。 | 说明 BLE 广播时间同步本身已有先例。可借鉴“时间戳必须与空口事件绑定、分解系统误差”，但其 legacy 广播、nRF24Cheep/Android 实验不能替代本项目 exadv/双协议共包实测。 |
| [BlueSync，IEEE IoT Journal，2022](https://ieeexplore.ieee.org/document/9555832/) | 研究 BLE 非连接广播的时间同步、漂移补偿，以及同步误差与能耗的权衡。 | 周期广播、时钟校正及节能本身已具备期刊先例；本项目应把贡献限定到双协议共包命令与共同时间语义，并提供独立双端证据。 |
| [Crocs，Yu 等，EWSN 2018](https://tns.thss.tsinghua.edu.cn/sun/members/XiuzhenGuo/Crocs_confer.pdf) | 面向 Wi-Fi/ZigBee，把跨技术可识别的时间对齐信号与时间戳传输分开，再估计时钟偏移和频率差。 | 跨技术同步及“先捕获共同事件、再解释时间值”已有直接先例；其 Wi-Fi 信标、跨技术编码和精度不能直接搬到 BLE/BlueBee 的单 secondary。 |
| [X-Sync，Hofmann 等，2021](https://www.carloalbertoboano.com/documents/hofmann21xsync.pdf) | 在现成 BLE 与 IEEE 802.15.4 设备上用跨技术信号传时序信息，通过重复 RSS 采样、帧起点搜索和时钟偏差估计实现跨技术同步；论文支持双向信息交换。 | 这是与本项目协议组合最接近的已知同步工作，不能把 BLE/802.15.4 跨技术校时本身当作新颖性。需要比较其额外信号/双向条件与本项目“同一个 `AUX_ADV_IND` 同时携带两侧控制和共同时间语义”的成本及能力；其精度数字不是本项目目标保证。 |
| [BlueBee，Jiang 等，SenSys 2017](../python/ctc_sim/bluebee/BlueBee.pdf) | 将可被 ZigBee 接收的 PHY 帧映射到 BLE 负载，验证跨协议接收和应用控制等先例。 | 双协议通信与控制能力已有基础；本项目需要证明的是在 exadv 的单个 secondary 中共置两侧命令与时间语义，以及相对分别发送等基线的实测收益。原论文的 BLE 4.2 长帧实验不能视为 exadv AuxPtr 跟随验证。 |
| [TPSN，Ganeriwal 等，SenSys 2003](https://escholarship.org/uc/item/5mh7m01j) | 节点间双向消息交换并估计时钟偏移及传输延迟，网络通过层级同步。 | 可作为双向校准/反馈扩展的对照，不应把单向广播误称为已测得单向传播时延。 |
| [Glossy，Ferrari 等，IPSN 2011](https://nes-lab.org/wordpress/wp-content/uploads/2022/02/ferrari11glossy.pdf) | 严格时序的接收后快速重发、转发计数与槽长用于洪泛及参考时刻推算；论文测得的可靠性/精度依赖并发发送的硬件时序。 | 可以借鉴“重复提升收到至少一次的机会”及“转发/尝试次数和 RF 成本均要计数”。本项目一台发送 SDR 的 K 次重发**不是 Glossy 并发洪泛**，不能引用其性能数值作本系统预期。 |
| [IEEE 802.15.4 TSCH 的 IETF 最小配置 RFC 8180](https://www.rfc-editor.org/rfc/rfc8180.html)、[RFC 7554](https://www.rfc-editor.org/rfc/rfc7554.html) | 增强信标用于入网时取得 ASN 和时间偏移；长期维持需接触时间源，失去联系则失去同步。守护时间与时钟 ppm 共同决定可容忍的同步间隔；RFC 7554 的 `10 ppm × 100 s = 1 ms` 是说明性例子。 | 负载应标识时间域、参考序号和失去更新后的失效规则；执行提前量/容差必须随测得的参考误差及漂移界限设定。ASN/TSCH 不能直接宣称为当前自定义帧已实现。 |
| [Bluetooth Core 6.0，LE Link Layer §2.3.4](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-60/out/en/low-energy-controller/link-layer-specification.html) | `ADV_EXT_IND` 的 AuxPtr 提供后续 auxiliary 包的信道、PHY、量化时间偏移和发送端时钟精度类别；`AUX_ADV_IND` 的 AdvData 空间取决于扩展头长度。SyncInfo 是**周期广播列车**的信息，不能当作任意应用同步字段。链路层还对时间窗随 ppm 增长作 widening。 | 严格分开“扫描何时/何频收到 secondary”与“应用命令何时执行”。单个 PDU 长度须连扩展头、AD 封装、BLE 命令、BlueBee 区域及两侧同步字段一起核算。ZigBee 接收端不会自动理解 AuxPtr/SyncInfo。 |
| [Bluetooth Mesh Model 1.1：Generic OnOff / Time](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/MMDL_v1.1/out/en/index-en.html) | Generic OnOff Set 定义目标状态、事务标识 TID、可选 Transition Time 和 Delay；6 s 内重发保持 TID。Time 状态分别表示时间值、Subsecond、Uncertainty 和 Time Authority。 | 应用命令标识与物理发送尝试分离；区分“目标执行时刻”和“状态过渡持续时间”；时间精度或可信度应显式记录。此处借鉴字段语义，不表示本项目运行 Bluetooth Mesh 或有 TAI/UTC 时间源。 |
| [Bluetooth SIG 智能照明白皮书，§3.4](https://www.bluetooth.com/wp-content/uploads/2020/09/MshWP_Lighting_v1.0.pdf) | 对同一控制命令进行多次发送，并让各次发送携带不同 Delay，指向同一动作时刻，以避免晚收到重发的灯具晚动作。 | “重发＋倒计时共同执行”已有明确工业实例。新方案不能只把 `command_id`、`execute_at`、有效期和去重拼在一起当创新；需要证明双协议同 secondary 的机制和公平基线收益。白皮书示意的成功率计算假设独立丢包，不能直接用于本实验的相关丢包。 |
| [Bluetooth Mesh Protocol 1.1：SEQ、IV Index 与重放保护](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/MshPRT_v1.1/out/en/index-en.html) | 网络 PDU 的单调 SEQ/IV Index 用于重放保护，作用不同于应用层 TID。 | 旧性能协议按计划时隙增长的 Sequence 必须保持原义。新 `command_id` 可在同一命令重发中不变，物理 `attempt_index` 单独变化。CRC/FCS 只检出损坏，不能据此宣称认证或抗恶意重放。 |
| [Bluetooth ESL，Silicon Labs AN1419](https://www.silabs.com/documents/public/application-notes/an1419-ble-electronic-shelf-label.pdf) | 电子价签在同步状态通过 PAwR 接收控制，厂商示例允许按绝对时间或延迟显示图像。 | 说明“广播式时序控制”已有工业先例，应用时间和动作可分开表示；但 PAwR 的周期调度/响应机制与当前单个 `AUX_ADV_IND` 是不同条件，不能借它推断本实验已有确认或多节点执行。 |

另可参考 [Bluetooth Mesh 官方时间格式](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/MMDL_v1.1/out/en/index-en.html)：它规定无法以所需精度确定时间时使用未知值。这提示本项目应区分“未校准”“估计有效”“已过期”，不要用看似精细的时间戳暗示真实精度。

## 3. 对共包字段的候选设计约束（推论，尚未定稿）

以下是从上述来源及项目设备约束**推导**出的设计决策，不是标准规定的字节布局：

1. **共同身份**：BLE 可解析区与 BlueBee/802.15.4 可解析区均携带版本、`run_id`、`command_id` 和必要的目标/组标识；两侧各自完整解码、校验后才按 `(run_id, command_id)` 关联。不同命令或双方内容不一致要显式标记，不能用已知确定性数据代替本侧解码。
2. **命令与重复**：明确命令类型、参数、目标、有效期和不支持命令行为；同一逻辑任务的 K 次广播保持 `command_id`，另记 `attempt_index` 与计划时隙 Sequence。接收端按任务去重，迟到/过期/重复不重复执行。`attempt_index` 如放入空口需计入两侧字节预算；离线统计也需保存实际发送尝试证据。
3. **时间域与参考点**：候选采用本轮实验内单调计数域，而非未经校准的 UTC/TAI。定义 `t_ref` 为 secondary 某个明确 PHY 边界（如 BLE 前导码起点），并规定 ZigBee 字段/前导码相对 `t_ref` 的精确编码偏移。记录时间戳是板端生成、DMA 提交还是经校准的空口发射估计；只有后者可直接作为发射参考，前两者需实测延迟/抖动上界。
4. **执行时刻**：两侧都能解析同一 `target_tick`，或每次重发中相对 `t_ref` 的 `execute_after`（重发时重新计算，但指向同一逻辑目标）。需有 `valid_until`/提前量，不能用“收到后固定等待”暗示接收处理时延和跨端时钟误差已消失。两侧字段语义一致，所占字节分别计入成本。
5. **时间质量**：接收端保留 `last_sync`、拟合样本数、偏移/漂移估计与残差；失去更新后用 `E(t) ≈ E_ref + |δ_ppm|·Δt` 作为待验证的保守误差预算。若 `E(t)` 超过预设容差、时刻已过或参考来源无效，标记不确定/拒绝定时执行；`E_ref` 和 `δ_ppm` 必须来自独立校准，不能仅由 nominal sample rate 推出。
6. **校验与安全**：两侧各自有完整性校验（既有 BLE CRC、802.15.4 FCS 以及必要的应用格式校验）；如果论文要声称防伪/抗重放，则需另设计鉴权及持久化新鲜度状态，不能把 `command_id` 和 CRC 视为安全证明。

字段大小、字节序、单位、环绕规则及命令错误码都应在容量核算后固定为版本化格式。特别是 `AUX_ADV_IND` 的 255 B 是整个 PDU payload 上限，[Core §2.3.4](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-60/out/en/low-energy-controller/link-layer-specification.html)的 AdvData 可用长度还要扣扩展头；原始 ZigBee 命令字节与编码后的 BLE 字节必须同时报告。旧性能帧 46 B 上限是该性能协议/旧配置，不是新共包可用容量。

## 4. 可验证的最小实验路线

1. **先固定语义与字节预算**：给出两侧实际可解码字段表、byte offset、bit/byte order、AD 封装、扩展头、FCS/CRC、总 PDU 长度；同一 IQ 独立双解码比较字段及共同包参考点。每次布局变化均重算包内固定时延。
2. **同 IQ 算法验证**：采样索引补偿已知位置差，预先划分校准/验证数据。比较无补偿、仅固定布局补偿、固定校准偏置、漂移拟合；不得逐包用待测包强制对齐再报告残差。输出条件样本数及丢包/歧义数。
3. **双 HackRF 验证**：先独立标定采集起点、固定射频/处理延迟和采样率偏差；若没有共同硬件时间基准，只能报告各接收链对单播参考的局部误差，不能直接相减两个文件的相对时间。共享时钟和外部触发分别记录。
4. **任务级统计**：以计划任务数为分母，记录两侧成功、单侧成功、都失败、重复、迟到、过期及软件解析事件；对 K 次重发的成本计入所有 primary、secondary、失败与重发。测试更新间隔、连续漏收、执行提前量与漂移；在有执行器观测前只称联合命令解析成功率。

## 5. 仍需查证与决定

- 板端是否可获得与空口 secondary 边界可校准绑定的 TX 时间戳；若不能，先给出 DMA 到空口的不确定度实测上界。
- 每次重发的目标时刻是否保持不变，以及 late/expired 判据与拒绝执行策略；仅单向广播不能保证两侧原子执行。
- 选用相对本轮 epoch 的目标 tick 还是相对每次 `t_ref` 的 offset，分别核算表示范围、量化单位与重复发送下的开销。
- 需要的软件命令只是 IEEE 802.15.4 PHY/MAC 测试负载，还是要进一步实现 NWK/APS/ZCL；未实现栈时不作 ZigBee 商用兼容声明。
- 仍需做针对“exadv 同 secondary 跨协议共包控制+同步”的系统查新与直接基线实验。FTSP、Glossy、CheepSync、Crocs、X-Sync、Mesh/ESL、BlueBee 各已证明部分能力，其论文数值不能替代本项目证据。
