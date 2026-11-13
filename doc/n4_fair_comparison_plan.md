# N4 公平对照实施方案

日期：2026-11-12。状态：第一层板端已实现并通过本地生成/语法检查，待用户构建上板；第一层主机接收、单轮分析及跨轮比较已适配，第二层板端C1/JC/LC已实现并通过本地检查，主机C1/legacy重组与分析已适配（见第8–9节），待首轮空口验证。承接 [N4 容量方案](n4_capacity_experiment_plan.md)。2301–2315 已完成首轮 v2 容量扫描，每点联合有效解析 100/100；不能把这些历史轮次直接作为新固件、新基线的同期对照。

## 1. 要回答的问题与最小范围

分两层进行，避免同时改变包组织、字段编码和接收策略：

1. **包组织对照**：相同 v2 字节，共包与分别发送有什么差异？复用 N2 的独立 BlueBee 基线，优先实现。
2. **legacy 对照**：在两边都使用同一种紧凑编码后，exadv 共包和 legacy BLE + 独立 BlueBee 的容量、分片和成本有什么差异？先完成编码测试与预算，再实测代表点。

2316 是 v1 纯时间参考，不承担上述公平对照。超容量板端拒绝实验不是推进前置条件；保留软件边界测试。

设备固定为一个 Pluto 类 SDR 顺序发送、两个 HackRF 独立接收。不增加原生 IEEE 发射、执行器、共享触发或硬件时延测量要求。基线的 IEEE 突发是独立 BlueBee 波形，不称为原生 IEEE O-QPSK 发射，也不代表所有最优分别发送实现。

## 2. 共用应用任务和公平条件

每轮 100 项不同命令，周期 500 ms，K=1，计划持续 50 s。两侧每项具有相同 run_id/command_id，分别使用 BLE target/opcode/arg=1/1/1、IEEE=2/1/2，valid=ref+2000 ms、execute=ref+3000 ms。每轮 run_id 不同，通过 task_index 关联跨轮的等价任务，不能按不同轮次的 run_id 直接合并联合成功。

扩展 b/z 是必须完整恢复的应用 blob。生成器可以使用确定性内容，但接收端只能独立解码后验证；不允许基线用种子替代传输 blob，也不允许另一侧补齐内容。所有模式完整恢复本侧命令、时间语义、blob 和校验后才算本侧成功。

冻结发送功率、接线/衰减、设备序列号、采样率 4 Msps、LNA16/VGA10、amp 关闭、解码版本。每轮两侧录制 80 s，较早启动接收器后 20 s 内发送。变更条件需同时应用于配对组并另建组。

固定频点接收用来隔离格式/成本差异；不将结果称为完整发现/跟随性能。没有校准双端时钟，不比较两进程墙钟差、不计算组执行时差或绝对 RF 完成时延。板端 DMA、波形预算、单接收机 IQ 时间和应用解析事件分列。

## 3. 第一层：v2 共包与 v2 分别发送（优先完成）

|组别|每逻辑尝试的物理发送|接收配置|
|---|---|---|
|J2|ch39 primary → ch3 共包 secondary|BLE 固定 ch3，IEEE 固定 ch12|
|S2|ch39 primary → ch3 BLE-only secondary → 2410 MHz 独立 BlueBee|与 J2 相同|

两组都传输既有 36+b / 36+z 字节记录，不修改 v2 的范围、校验和语义。S2 沿用 N2 的提前准备、主动 DMA 轮询与保护间隔策略；准备阶段、每次提交、结束和失败均记录。保持 primary/AuxPtr 配置一致。各突发不同实际起点不得视作共同 RF epoch；本层验证时间字段交付，不宣称同步精度等价。

按现有生成布局，LE1M 有效波形预算如下，最终以新生成器导出的真实长度交叉核对：

- J2：primary 136 µs + secondary `(239+b+4z)*8` µs。
- S2：primary 136 µs + BLE-only secondary `(63+b)*8` µs + 独立 BlueBee `(176+4z)*8` µs。
- 两组每逻辑尝试合计均为 `2048+8b+32z` µs；J2 两个突发，S2 三个突发。

因此不能把减少突发数写成减少有效波形时长。padding、间隔和 DMA/调谐耗时单列，禁止把整个发送跨度当成 RF 占用。

首轮只取三个代表点，覆盖零扩展、BLE 最大和 IEEE 最大：

|预留 run_id（先查占用）|组|b,z|计划有效波形/任务|
|---|---|---|---:|
|2401|J2|0,0|2048 µs|
|2402|S2|0,0|2048 µs|
|2403|S2|26,0|2256 µs|
|2404|J2|26,0|2256 µs|
|2405|J2|2,6|2256 µs|
|2406|S2|2,6|2256 µs|

首轮六轮用于功能与成本初验。后续每点至少三轮独立配对重复，交替 J/S 顺序。S2 的 BLE 先发偏置必须披露；若要比较两侧本地到达时间，再增加 IEEE 先发的单独配置并记录其时序，不从当前顺序推导共包同步收益。

### 第一层已实现的板端接口

```text
b2z_capacity_start? <run_id> <period_ms> <attempts> <ble_extra_len> <ieee_extra_len> [rf_mode]
```

省略模式或指定1为J2，指定2为S2；capacity不接受0或其他模式，原控制/plan命令的同频模式不变。原五参数命令兼容，范围仍为b+4z≤26、周期500..65535 ms、1..1024槽且总时长≤600 s。每槽新命令、K=1；共包/分别发送均不读取手工plan草稿。

```text
b2z_capacity_start? 2401 500 100 0 0 1
b2z_capacity_start? 2402 500 100 0 0 2
b2z_capacity_start? 2403 500 100 26 0 2
b2z_capacity_start? 2404 500 100 26 0 1
b2z_capacity_start? 2405 500 100 2 6 1
b2z_capacity_start? 2406 500 100 2 6 2
```

以上为已实现的板端命令清单。配套主机已适配v2分别发送，使用下节接收和分析命令；先完成2401/2402功能核查，再展开余下四轮。

CAPACITY_START/CONFIG报告实际rf_mode；pdu_payload_bytes为真实secondary payload，J2为229+b+4z，S2为53+b。mapped_bytes仍报告176+4z：S2中这部分位于独立IEEE突发，并不在BLE PDU内。CAPACITY_SLOT记录实际构造长度；CONTROL_BURST/COST_STATS沿用N2，S2每槽多一个kind=ieee突发及独立完成计数。tx_completed仍为BLE secondary DMA完成代理，不能当作IEEE也完成；IEEE完成须读逐突发或COST_STATS。

S2沿用BLE完成后至少1 ms的软件保护间隔、主动DMA轮询/超时、恢复primary频率和停止处理。此间隔不是硬件测得的RF静默。两侧数据提前生成，secondary缓存仍在AuxPtr等待前准备。源码已同步SDK实际编译目录；本地三代表点验证了两模式记录逐字节一致、BLE波形解调、IEEE独立波形解码与预算相同，未替代上板验证。

### 第一层主机操作（已适配）

在仓库根目录执行。每轮分别在两个终端设置相同的RUN和LAYOUT；J2用joint，S2用separate。两条命令各启动一次，确认采集后再发送对应板端命令。不要启用control-target-id执行功能，当前是容量/解析对照。

终端A（示例2402分别发送）：

```bash
RUN=2402
LAYOUT=separate
python3 python/exadv_rx/receive.py --run-id "$RUN" --control-layout "$LAYOUT" \
  --channels 3 --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 80 --save-iq --quiet
```

终端B：

```bash
RUN=2402
LAYOUT=separate
python3 python/zigbee_rx/control_receive.py --run-id "$RUN" --control-layout "$LAYOUT" \
  --channel 12 --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 80 \
  --expected-packets 100 --save-iq --quiet
```

2401/2404/2405使用joint；2402/2403/2406使用separate。接收器自动创建日期/run目录，不需要EXP_DIR（跨午夜须统一目录）。负载长度自动从包中解析。两端结束后，等待板端本轮CONTROL_TIME_END及后续输出完成，将完整串口记录放入本轮board.board.log。

每轮分析（日期按实际目录替换）：

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261112_run2402 \
  --run-id 2402 --analysis-id n4_fair
```

验收：100个计划任务；两侧与联合有效解析按实际数量报告，少于100不删失败任务；检查板端primary、BLE及IEEE各自完成数。J2正常为200次突发完成，S2为300次。零扩展两组计划有效波形均204800 µs/轮；两个255 B共包边界点均225600 µs/轮。S2的secondary payload分别为53/79/55 B，独立IEEE映射长度分别为176/176/200 B。任何长度、记录内容、模式、成本不符先定位，不继续批量采集。

跨轮比较继续使用已扩展的compare_n2.py，三对分别为2401/2402、2404/2403、2405/2406。先手工保存conditions.json，两组均填写真实的topology、tx_power（单位明确）、firmware_build（同一固件版本或哈希）和attenuation；不能把未知信息填为“相同”来绕过检查。结构例如：

```json
{
  "joint": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"},
  "separate": {"topology": "TODO", "tx_power": "TODO", "firmware_build": "TODO", "attenuation": "TODO"}
}
```

TODO必须据实替换；信息缺失时工具仍生成描述性报告，但recorded_conditions_match为false，不能当成公平性通过。

```bash
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/20261112_run2401/analyses/n4_fair/plan.summary.json \
  --separate-summary python/experiments/20261112_run2402/analyses/n4_fair/plan.summary.json \
  --conditions python/experiments/20261112_run2402/conditions.json \
  --output-dir python/experiments/20261112_run2402/analyses/n4_compare_2401_2402
```

输出comparison.json/md，核对格式、两侧扩展长度、任务/截止期、采集与人工RF条件；PDU长度不同属于预期，不要求两组物理布局相同。schema沿用b2z_n2_comparison_v1以兼容旧工具。报告记录的条件一致仅表示所列信息一致，不证明未观测的RF环境完全相同。全部测试为本地验证，仍需新版固件的首轮空口验证。

## 4. 第二层：给双方同样的紧凑编码

不能拿 36 B v2 直接与 31 B legacy AdvData 比较后宣布 legacy 不可用。设计独立实验格式 C1：利用现有协议本来就要求 `ref=slot*period` 的关系，并用相对参考点的时差表达有效期和执行时刻。不依赖事先收到的会话上下文，不省略命令参数或 blob。

以下是待实现的格式草案，不改变现有 v1/v2：

|偏移|长度|字段|
|---|---:|---|
|0|1|格式/封装判别字，区分 C1 完整记录与分片封装|
|1|1|flags|
|2|2|run_id|
|4|4|slot_index|
|8|2|period_ms|
|10|4|command_id|
|14|2|target_id|
|16|1|opcode|
|17|2|arg|
|19|2|valid_delta_ms|
|21|2|execute_delta_ms|
|23|1|extra_len|
|24|n|本侧完整 blob|
|24+n|2|应用 CRC16|

多字节小端，CRC 使用现有 CCITT/init FFFF，覆盖此前全部字节。固定开销 26 B，保留 slot/command/target 的现有宽度。有效期与执行提前量限制在 0..65535 ms；验证 ref 运算溢出、valid<execute 和合法命令，越界拒绝而非截断。当前 N4 的 2 s/3 s 满足范围。恢复 ref/时间值属于本侧已解码字段的定义关系，不是依据另一接收端重构。

该编码减少两个 magic 字节、冗余 ref 字段和绝对时间宽度；必须公开范围限制，不能宣称对任意 v2 任务等价。两个对照组均使用 C1，因此不能把压缩收益归因于 exadv。

### JC：紧凑 exadv 共包

沿用扩展头/Flags/Company ID，分别承载 26+b 与 26+z 字节记录。理论 payload 为 `179+b+4z` B，每任务有效波形为 `1648+8b+32z` µs（含 primary136 µs），仍为两个突发。生成器验证前仅为设计预算。

### LC：紧凑 legacy BLE + 独立 BlueBee

BLE 使用非连接、非扫描响应的 legacy 广播数据路径，不依赖 scan response。AdvData 至多31 B；采用一个厂商 AD，长度/类型/Company ID 共4 B，剩27 B。不额外发送 Flags AD，并将此选择写入格式声明。AdvA、PDU头和 PHY 开销另计。

- C1 长度≤27 B：直接发送完整记录。
- C1 长度>27 B：采用10 B分片头（判别字1、run2、command4、index1、count1、total_length1），每帧最多17 B记录片段。连续分片不填充到固定长度，长度以实际 AD 和 PDU 为准。
- 完整记录的 CRC 覆盖所有分片重组内容；分片逐帧 BLE CRC 均需通过。以 sender/run/command 为重组键；count/total_length 不一致、同片异内容时拒绝任务，重复同内容不重复计成功。每轮清空缓存，设有界条目数和固定 2 s 主机本地重组超时；这是资源清理规则，不是无线有效期精度。
- 只有全部分片、应用 CRC、语义和 blob 校验通过才生成本侧有效任务。缺片、超时、冲突单列。K>1 时仅可合并相同完整记录的片段，变动记录不能沿用同一身份混组。
- IEEE 仍用完整 C1 本侧记录形成独立 IEEE PHY 并经 BlueBee 映射发送；不要求 IEEE 接收机解析 BLE 分片。

首轮 BLE 固定 legacy ch39（2480 MHz），IEEE 仍固定 ch12（2410 MHz）；单板顺序发 BLE全部分片后调谐发 BlueBee。与 JC 的 BLE secondary2410 MHz 不同，是物理信道混杂因素：同接线/功率不能保证等 RF 信道条件。因此本层主要比较格式可实现性和确定性成本；若比较可靠性，只能称各自配置结果，不能归因于包格式本身。首轮只用一个 legacy 广播信道；三信道配置须另算副本和接收观察边界，不可给 legacy 平白乘三成本。

在上述厂商 AD/AdvA 配置下，每个 legacy 帧有效波形=`(20+厂商数据字节数)*8` µs；独立 BlueBee=`(136+4z)*8` µs。预算示例：

|b,z|JC payload|JC µs/任务|LC BLE帧数|LC总突发数|LC µs/任务|
|---|---:|---:|---:|---:|---:|
|0,0|179|1648|1|2|1456|
|26,0|205|1856|4|5|2464|
|2,6|205|1856|2|3|1984|

这些预算允许出现交叉点：小任务 legacy 可能更省，长任务分片可能更贵。不可删掉零扩展点来只展示优势。LC 不等于“单 legacy 包双协议共包”，也不证明这种更强基线不可能；当前 BlueBee 完整命令映射区域已超出31 B，但更紧凑的跨协议分片架构尚未实现，须作为比较范围限制明确说明。

预留首轮：2411 JC(0,0)、2412 LC(0,0)、2413 LC(26,0)、2414 JC(26,0)、2415 JC(2,6)、2416 LC(2,6)。编号须检查占用。六轮均100任务、K=1、同截止期；新增格式接收和成本工具完成之前不可执行。不得拿 JC 的设计预算替代其双端实测。

## 5. 统计、时序与等预算比较

逐任务输出 BLE成功、IEEE成功、联合成功、两侧都失败；另列错误/重复/重组失败。联合率按同轮同命令直接匹配，不相乘。首轮全成功也只报告100/100和样本条件，不宣称普遍100%可靠。

成本输出两套：计划任务格式预算；根据逐突发启动记录核算的实际提交完整有效波形预算。后一套包含失败尝试，提交失败单列，DMA中途失败的实际RF发射比例未知。单位成功联合任务成本除以实际联合解析数，零成功为N/A。同时报告物理突发数、分片数、padding和板端软件提交跨度。

BLE分片重组间隔可用同一个HackRF的首片/末片IQ采样索引测量；不得与另一个HackRF的时间直接相减。逐突发 DMA 日志可衡量板端软件序列跨度，不能叫真实 RF 完成时间。当前 capacity 接收不执行动作，因此不输出执行成功率，也不能仅凭恢复 execute_at 字段宣称按时执行。

先完成同任务 K=1 对照，再开展等有效波形预算的重复策略：所有组相同每任务预算 Q、截止期、周期；K=floor(Q/C)，分片方案的K表示完整分片集合加IEEE的一次尝试。Q至少覆盖最贵方案一次，报告实际使用量与未用预算，不以无意义padding凑齐。比较是“同预算上限”而非精确相等RF占用。每个方案必须在截止期内调度完，否则记录不满足，不悄悄延长期限。实现前冻结Q与重发时序，按任务去重，时间参考/slot/命令重发语义另行明确；不能直接套用当前每槽新命令的capacity接口。

## 6. 软件交付与执行顺序

1. **先实现 S2**：现有 capacity 路径增加显式分别发送配置，保留旧五参数命令兼容；复用N2日志，但按v2实际长度生成和核算。具体串口接口在编码前冻结，不假装已有可运行命令。
2. **适配接收和分析**：BLE严格区分v2 joint/separate封装，IEEE独立解析；分母、突发清单、单侧发送失败均正确统计。跨轮manifest记录配对点、任务语义、功率/接线、代码/固件版本与哈希，配置不等价则拒绝合并性能结论。
3. **本地验证→2401–2406**：真实C生成字节与两侧解析交叉验证，注入长度/CRC/单侧缺失验证统计，不需要额外RF硬件。板端由用户编译上板。
4. **实现 C1/JC/LC**：独立新格式与明确布局，完整记录/分片解析、资源上限、重复/乱序/缺片/冲突测试；验证实际PDU、映射长度与上述预算。确认既有BLE接收器能处理legacy PDU，否则新增显式路径，不能用exadv解析器直接强行放行。
5. **2411–2416**：收发命令随实现补充，再进行首轮。两层合计12轮，不需要重扫15点，也不需要先做2316或硬件时延校准。
6. **汇总→等预算→最终重复**：按当前用户安排，先完成各功能一次有效验证，最终主要点至少3轮独立重复。不能把100个相关包或反复分析同一IQ当成100轮/多轮独立实验。

每轮归档 board.board.log、CAPACITY/任务/逐突发完整记录、两侧IQ和逐包/逐任务文件、summary/report/CSV；跨配置汇总写明哪些为预算、哪些为实测。新增统计必须保持旧N2冻结格式检查，并对新格式采用显式版本预算，避免重复发生“固定N2预算误拒绝v2”的问题。

## 7. 可支持与不可支持的结论

若结果成立，可说明：在给定应用任务、记录范围和SDR拓扑下，共包减少物理突发；在某些blob长度下相较所实现的legacy分片基线降低提交有效波形预算/分片成本，同时保持已观察的联合解析能力。零收益或负收益工作点照实保留。

不能据此声称：全部任务上exadv优于legacy、优于所有最优压缩/原生IEEE方案、真实能耗降低、物理执行同步精度提高、商用设备兼容、任意RF条件下可靠性提升。同步精度证据与本容量/成本对照分别建立。

## 8. 第二层板端实现（2026-11-13）

板端及主机C1/legacy分片接收和分析已实现，操作见第9节；尚待首轮空口验证。用户自行编译上板。独立命令不修改v1/v2命令：

```text
b2z_compact_start? <run_id> <period_ms> <attempts> <ble_extra> <ieee_extra> <mode>
```

严格六个十进制整数，mode=1为JC，mode=2为LC；不省略mode。范围沿用第一层公平任务域b+4z≤26、b≤26、z≤6、周期500..65535 ms、槽数1..1024、计划总时长≤600 s。slot从0递增，command_id=slot+1；每任务K=1，目标/参数及2 s有效期/3 s执行字段沿用第一层，不启动执行器。复用忙状态、停止命令、虚拟任务与有界DMA轮询。接口不承诺更大C1容量，本轮只比较同应用任务。

```text
b2z_compact_start? 2411 500 100 0 0 1
b2z_compact_start? 2412 500 100 0 0 2
b2z_compact_start? 2413 500 100 26 0 2
b2z_compact_start? 2414 500 100 26 0 1
b2z_compact_start? 2415 500 100 2 6 1
b2z_compact_start? 2416 500 100 2 6 2
```

C1完整记录判别字冻结为0xC1，分片头判别字为0xC2，片号从0起。字段布局见第4节。应用CRC16覆盖完整紧凑记录；每个legacy帧独立BLE CRC。legacy ADV_NONCONN_IND使用随机静态地址C1:A2:A3:A4:A5:A6，与exadv地址一致；仅发ch39，无Flags AD、scan response或三信道副本。≤27 B记录直接装载，否则17 B切片，末片不填充。两侧blob沿用v2确定性内容生成规则，保证在同一run/slot下编码转换不改变应用blob。

JC发送primary39和共包secondary3。LC在发射前生成全部legacy分片与独立BlueBee波形，按fragment0..N顺序发送，然后切换到2410 MHz发IEEE，最后恢复2480 MHz。片间和BLE至IEEE之间至少等待1 ms软件保护间隔；不宣称实际RF间隔准确为1 ms。LC不发送primary/AuxPtr或BLE secondary，且不生成它们的无用调制波形。发生停止、提交失败、超时或调谐失败时保留逐突发结果，并尝试恢复primary频率；不追加隐式重发。

日志约定：

- 保留CONTROL_PLAN_START/ENTRY/TASK/SLOT/STATS作为共同任务计划及计数。LC模式名为legacy_separate_ch39，AuxOffset=0；兼容计划日志中的secondary/时间参考字段不适用于LC，不用来评价LC同步。
- COMPACT_CONFIG：format=C1、mode=JC/LC、两侧长度、周期和语义。
- COMPACT_SLOT：逐槽实际记录/映射字节数；JC的secondary_payload_bytes=179+b+4z，LC为0（无secondary），不是丢失长度。
- COMPACT_BURST：JC为primary/secondary；LC为fragment0..fragment3及ieee。每个槽均输出计划突发，包括未提交者；记录生成、提交尝试、启动、完成、超时、IQ字节、有效波形预算、padding和软件调用时刻。
- COMPACT_COST_STATS：累计全部突发；LC的ble_tx_completed仅在全部BLE片均DMA完成后计1，IEEE独立统计。LC的primary完成数为0是预期；tx_started为首BLE片启动任务数，不是所有物理突发数。
- JC保留N3诊断；LC不套用N3 primary/AuxPtr阶段，输出COMPACT_TIME_END，使用COMPACT_BURST的软件时间括号。LC没有实际RF起点、跨设备时差或执行精度测量。

主机必须显式识别上述格式，不能将旧plan_analyze结果作为C1验收。后续主机适配应严格校验COMPACT_CONFIG、逐槽长度和分片数量，独立解析IEEE完整C1，不以BLE重组结果补写IEEE。

本地验证包括：三个代表点的C1语义/应用CRC、JC PDU及BLE CRC、LC实际IQ解调/白化/地址/逐帧CRC与完整分片重组、独立IEEE IQ标准接收链FCS及完整记录、两模式应用内容一致、预算1648/1856/1856与1456/2464/1984 µs，以及超范围提前量拒绝。旧v1/v2生成与虚拟任务测试保持通过。ARM语法检查不等于固件链接成功或空口验证。

## 9. 第二层主机操作（2026-11-13已适配）

接收仍使用exadv_rx/receive.py与zigbee_rx/control_receive.py，联合分析仍用plan_analyze.py。BLE接收器新增legacy ADV_NONCONN_IND路径；C1直接记录和0xC2分片均通过BLE CRC后再处理。LC按AdvA/run/command独立重组，应用CRC与完整内容通过后才计命令；IEEE只解析本侧C1。JSON内version=3/format=C1是主机分派标签，不是将线上0xC1替换为第三字节版本号。

重组缓存上限1024项，超时固定为首片后2秒的**本机IQ采样时间**，与USB/解码处理速度无关（取代第4节草案的主机墙钟超时）。允许片号乱序、相同片重复；冲突片拒绝该身份，离线联合分析遇到冲突会拒绝出具正常结果。已完成或超时身份保留有界记录以避免迟到片重复计数。到采集结束仍不完整者列为incomplete_at_end，跨过2秒者列timeout；丢片不从计划分母中剔除。以上是本地重组规则，不是空口截止精度或执行精度测量。

### 9.1 接收和发送顺序

先做2411/2412，分析通过后再做2413–2416。每轮重新启动两个接收器，较早启动后20秒内发送对应板端命令。以下变量仅简化命令，不需额外EXP_DIR。注意LC的BLE接收必须从ch3改为ch39，IEEE保持ch12。

|run|模式|BLE频道|两侧control-layout|b,z|
|---|---|---:|---|---|
|2411|JC|3|joint|0,0|
|2412|LC|39|separate|0,0|
|2413|LC|39|separate|26,0|
|2414|JC|3|joint|26,0|
|2415|JC|3|joint|2,6|
|2416|LC|39|separate|2,6|

终端A示例2412：

```bash
RUN=2412
BLE_CHANNEL=39
LAYOUT=separate
python3 python/exadv_rx/receive.py --run-id "$RUN" --channels "$BLE_CHANNEL" \
  --control-layout "$LAYOUT" --serial 000000000000000017c467dc2926a0c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 80 --save-iq --quiet
```

终端B示例2412：

```bash
RUN=2412
LAYOUT=separate
python3 python/zigbee_rx/control_receive.py --run-id "$RUN" --channel 12 \
  --control-layout "$LAYOUT" --serial 000000000000000017c467dc3348a6c3 \
  --sample-rate 4000000 --lna 16 --vga 10 --duration 80 \
  --expected-packets 100 --save-iq --quiet
```

然后发送第8节相应板端命令。保持发送功率、接线和增益一致，不启用control-target-id。LC没有primary/AuxPtr，所以严格配对计数为0是预期；本层也不要求JC固定频点接收观察primary。LC分片数不等于任务数：26 B BLE扩展时每任务4个BLE帧，但只有重组后才算1条有效记录。

### 9.2 单轮分析

等待板端全部逐槽/突发打印完成：JC含CONTROL_TIME_END；LC含COMPACT_TIME_END。保存完整日志到自动创建的本轮目录下board.board.log。日期以真实目录为准：

```bash
python3 python/control_match/plan_analyze.py \
  --experiment-dir python/experiments/20261113_run2412 \
  --run-id 2412 --analysis-id n4_compact
```

输出plan.summary.json/report.md及任务/槽/突发CSV。校验COMPACT_CONFIG/SLOT、模式与实际BLE封装、记录长度、时间语义、各物理突发预算、独立BLE/IEEE完成数。LC不套用JC布局偏移；两侧软件执行计数无观测时为N/A。解析率必须包含全部100个计划任务；未收齐片段计失败，不用确定性内容补齐。

全发送且全解析时的预期预算（非实测RF占用）：

|run|BLE帧/任务（不含JC primary）|每轮总突发|有效波形µs/轮|
|---|---:|---:|---:|
|2411|1|200|164800|
|2412|1|200|145600|
|2413|4|500|246400|
|2414|1|200|185600|
|2415|1|200|185600|
|2416|2|300|198400|

这不是预设100%解析的验收门槛。实际少收时保留四象限与重组异常，先排查录制边界、固件异常和配置；不要把预算结果当成无线实测精度。

### 9.3 配对比较

三对分别是2411/2412、2414/2413、2415/2416。沿用第3节conditions.json结构，joint字段填写JC、separate字段填写LC；均记录真实功率配置、接线、固件版本和外接衰减。无功率计校准时不要把配置值称为实际输出功率。

```bash
python3 python/control_match/compare_n2.py \
  --joint-summary python/experiments/20261113_run2411/analyses/n4_compact/plan.summary.json \
  --separate-summary python/experiments/20261113_run2412/analyses/n4_compact/plan.summary.json \
  --conditions python/experiments/20261113_run2412/conditions.json \
  --output-dir python/experiments/20261113_run2412/analyses/n4_compact_compare_2411_2412
```

工具自动识别JC/LC。比较相同扩展长度、命令清单、周期、有效期、设备/增益与人工条件；仅允许预期的BLE ch3/2410 MHz与ch39/2480 MHz差异。报告comparison_scope=compact_cost_with_RF_channel_confound，reliability_protocol_effect_identifiable=false：即使recorded_conditions_match=true，也不能把可靠性差异归因于协议格式。单轮结果不替代独立重复。

本地验证采用真实C生成器IQ，经BLE接收器、IEEE标准解码链、分片重组和联合分析完成三个工作点JC/LC六种组合；额外覆盖缺片、重复、乱序、冲突、超时、CLI离线接收及报告生成。它们属于软件/回放验证，不增加物理实验次数。
