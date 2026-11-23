# UC1 冻结后的 P3/P4 实验计划

本轮沿用已冻结的收发代码、固件和分析口径。P2 归档提交为 `ef5e237`。论文核心结果回答两个问题：代表负载下每次完整发送花多少波形预算，以及在同一预算上限下有多少计划任务能被双方解析。[P2 复核](../results/uc1_p2_2701_2718_review_20261120.md) · [详细操作指导手册](uc1_post_p2_operation_guide.md)

## 哪些证据已经够用

P2 已有 A/B/C 三种布局的同 IQ 位置核验及独立双端解析，容量部分直接引用应用字节、实际 PDU 长度、映射开销和成功样本。R0 稳定链路已覆盖三个布局和三种封装的 K=1 成本。C 点保留作不同 BLE/IEEE 负载分配的实例。H5 三轮用于展示正常、BLE 失更、IEEE 失更各一次的状态轨迹、计划内恢复事件及留出预测残差。论文把时间机制限定为功能实例，无需估计总体恢复率。H4 四轮按已归档的预算校正结果引用。

## P3 先确定一个有部分缺失的无线条件

从固定天线布局、接收增益 LNA 16 / VGA 16 开始。沿用 P2 的发送设置（标称 0 dBm、`tx_attenuation=10000 mdB`），记录实际距离、朝向、增益与设备。用 B 点、core、K=1，每轮 30 任务、500 ms 周期，在两个独立录制块中分别按 JC/SC/LC、LC/SC/JC 采集，共 6 轮。每个块合看三模式共 90 项计划任务，同时满足以下三项即选用该布局（只看区间、复现性与采集质量，不看模式排序）：

1. 两块各自的合并联合成功数均落在 **18–76 / 90**（约 20%–85%，避开天花板/地板效应）；
2. **至少有一个相同模式** $m \in \{\text{JC}, \text{SC}, \text{LC}\}$ 在两块中均同时出现联合成功与联合缺失（$1 \le s_m \le 29$），排除“全收模式 + 全断模式”凑出中间合计数或单块瞬态漂移的假象；
3. 接收日志无队列溢出/截断等采集故障，且无显著饱和（按削波占比 `clip_ratio = clipped_components / (2 * samples_processed)` 判定，不以 `clipped_components > 0` 一票否决：`clip_ratio < 1e-4` 的零星室内环境瞬态照常保留并记录；`clip_ratio >= 1e-3`，或处于 `1e-4`–`1e-3` 且伴随近距高增益/异常丢包时触发饱和复查）。

首个布局未达到条件时，只再试一个候选布局，两块同法复核：优先调整收发距离；若触发上述显著饱和复查，或受限于室内最大距离仍接近全收（>76/90），允许在候选 2 中固定物理摆放，改为**统一增大板端 `tx_attenuation`（如 30000–50000 mdB）或统一下调接收 `VGA`**（三模式与两块严格一致，并如实记录到 manifest 与 `notes.md`）。最多 12 轮；仍未找到可用条件就结束摸底，报告观测范围，暂缓部分缺失条件下的可靠性比较。先导轮始终单列。

## P4 在选定的 R1 完成 36 轮

三种模式为共包 JC、exadv 分别发送 SC、legacy LC。用 A 和 B 同时覆盖 legacy 直接承载和五片重组。每个表格单元跑三种模式，各做三个独立区组，每轮 100 个相同定义的计划任务。

| 负载 (b,z) | K=1，9 轮/点 | 每任务 Q=6000 µs，9 轮/点 |
| --- | --- | --- |
| A (0,0) | 单尝试波形 JC/SC/LC 为 1648/1648/1456 µs | K=3/3/4，检验短负载下 LC 多一次尝试时的结果 |
| B (26,0) | 单尝试波形为 1856/1856/2904 µs | K=3/3/2，检验 legacy 分片后各模式的联合解析 |

JC 和 SC 在同一点的波形预算及 K 相等，突发数为 2 与 3；两者的联合结果直接测量。LC 的 BLE 信道不同，可靠性结论限于所测封装与信道组合。新增矩阵共 3600 个计划任务，按每轮 330 s 约 3 小时 18 分纯采集。R0 及 C 点不追加正式轮，可靠性比较范围相应限定在 R1 的 A/B。

沿用[现有操作手册](uc1_execution_manual.md)的生成、双侧采集及分析命令。P4 用 `--phase P4 --stage confirmatory --rf-condition R1 --profile core --tasks 100`；K=1 用 `--policy k --value 1`，预算用 `--policy budget --value 6000`。按轮更换 run ID、模式、布局和 block，板端执行该轮生成的 .board.txt。正式采集前固定 R1 布局及以下次序。1 表示 K=1，Q 表示预算，J/S/L 表示三种模式。

| 区组 | 负载顺序 | 每个负载内的运行顺序 |
| --- | --- | --- |
| 1 | A、B | J1 S1 L1 JQ SQ LQ |
| 2 | B、A | LQ SQ JQ L1 S1 J1 |
| 3 | A、B | L1 JQ SQ LQ J1 S1 |

每轮重启收发，各区组尽量分布在不同时间段。每轮保存 manifest、板端命令与日志、双侧逐包记录、分析及现场条件。受本地存储限制，P4 采集前指定 Block 1 的 B 点同预算两轮 `2740`（B、JC、Q=6000、K=3）与 `2742`（B、LC、Q=6000、K=2 五片）为双侧 IQ 留样（合计约 10.56 GB / 9.84 GiB）。其余 34 轮用逐包数据复核联合解析和成本；这些轮次无法从原始波形重新解码。

## 汇总与停止条件

按负载、策略和区组，报告首次及计划尝试内的联合解析分子/分母、双方成功/两种单侧成功/双方失败四类。报告全部提交波形成本、未用预算及每个联合成功任务的成本，零成功记 N/A。截止判定沿用冻结分析器的 unknown 和未解析分类。

主比较为同负载、同策略、同区组内 JC 相对 SC、LC 的联合解析率差（百分点）。列出三个区组的差值、均值和范围；给出以区组配对差计算的 t 区间（95%，自由度 2），注明仅三组的精度限制。联合解析的变化与波形成本分别报告。三组完成即结束，差值小、方向不一致或区间跨零时，如实报告未观察到明确优势。配置错误或采集损坏的轮保留记录并以新编号补对应条件；正常无线漏收一律计入分母。

## 实机排程与编号

以下是执行时使用的建议编号。生成器已检查 2719–2766 当前可用。首个布局入选时跳过 2725–2730，P4 仍从 2731 开始。因配置错误或确定采集损坏需要补采时，**补采编号统一从 `2767` 起递增**（避免与主排程表冲突），保留原异常轮记录并在 `notes.md` 标明被替代的 run ID、原条件和区组。

| 阶段 | 布局 | 块 | 点 | 按从左到右执行（编号 / 条件） |
| --- | --- | ---: | --- | --- |
| P3 | 候选 1 | 1 | B | 2719 J1 → 2720 S1 → 2721 L1 |
| P3 | 候选 1 | 2 | B | 2722 L1 → 2723 S1 → 2724 J1 |
| P3 | 候选 2 | 1 | B | 2725 J1 → 2726 S1 → 2727 L1 |
| P3 | 候选 2 | 2 | B | 2728 L1 → 2729 S1 → 2730 J1 |
| P4 | 入选布局 | 1 | A | 2731 J1 → 2732 S1 → 2733 L1 → 2734 JQ → 2735 SQ → 2736 LQ |
| P4 | 入选布局 | 1 | B | 2737 J1 → 2738 S1 → 2739 L1 → 2740 JQ → 2741 SQ → 2742 LQ |
| P4 | 入选布局 | 2 | B | 2743 LQ → 2744 SQ → 2745 JQ → 2746 L1 → 2747 S1 → 2748 J1 |
| P4 | 入选布局 | 2 | A | 2749 LQ → 2750 SQ → 2751 JQ → 2752 L1 → 2753 S1 → 2754 J1 |
| P4 | 入选布局 | 3 | A | 2755 L1 → 2756 JQ → 2757 SQ → 2758 LQ → 2759 J1 → 2760 S1 |
| P4 | 入选布局 | 3 | B | 2761 L1 → 2762 JQ → 2763 SQ → 2764 LQ → 2765 J1 → 2766 S1 |

## 单轮执行

### 1. 准备现场

在仓库根目录执行 `hackrf_info`，核对并固定 BLE 和 IEEE 两块接收机的序列号与对应天线绑定，**整个 P3 和 P4 全程禁止互换两块 HackRF 或其天线**（若本机序列号与脚本默认台架序列号不一致，执行接收命令时必须显式附加 `--serial <SN>`）。使用 P2 冻结版本，填写板上实际固件标识。默认沿用标称 0 dBm、`tx_attenuation=10000 mdB` 与接收端 4 Msps、LNA 16、VGA 16、AMP 关闭（如 P3 候选 2 启用衰减或 VGA 调整，则全组严格一致并如实记录）。记录两条收发距离、天线朝向、照片或示意；每个 run 使用同一布局，整个 P4 保持入选条件不变。

2740 与 2742 的双侧 ci8 每轮约 5.28 GB（4.92 GiB），两轮合计约 10.56 GB（9.84 GiB），留在工作盘。启动这两轮前均需用 `df -h .` 确认余量超过 7 GiB（若空间偏紧，可先将已淘汰候选 1 的 `2719` 原始 IQ 约 1.8 GiB 转存或清理）。P3 为节省空间，预定每个候选布局的第一轮 JC 留双侧 IQ（约 1.92 GB），其余轮保存逐包记录。

### 2. 生成本轮 manifest 和命令

在仓库根目录的 Bash 终端定义以下函数一次。执行 `read -r -p '实际烧录固件标识: ' FW_BUILD` 后（如候选 2 调整接收 VGA，可另设 `export RX_VGA=12`，默认 `16`），按排程表**一次只生成当前轮**。函数参数依次为编号、阶段、块号、负载点、条件码。

```bash
prepare_uc1() {
  local id=$1 phase=$2 block=$3 point=$4 cond=$5
  local mode tasks stage b policy value iq=--no-save-iq vga=${RX_VGA:-16}
  case "$point" in A) b=0;; B) b=26;; *) return 2;; esac
  case "$cond" in J1|JQ) mode=JC;; S1|SQ) mode=SC;; L1|LQ) mode=LC;; *) return 2;; esac
  case "$cond" in *1) policy=k; value=1;; *Q) policy=budget; value=6000;; esac
  case "$phase" in
    P3) stage=pilot; tasks=30
        if [[ $block == 1 && $mode == JC ]]; then iq=--save-iq; fi;;
    P4) stage=confirmatory; tasks=100
        if [[ $block == 1 && $point == B && ($cond == JQ || $cond == LQ) ]]; then iq=--save-iq; fi;;
    *) return 2;;
  esac
  local prefix="python/control_match/configs/uc1_${id}"
  python3 python/control_match/uc1_config.py --run-id "$id" \
    --mode "$mode" --profile core --ble-extra "$b" --ieee-extra 0 \
    --tasks "$tasks" --period-ms 500 --policy "$policy" --value "$value" \
    --phase "$phase" --stage "$stage" --block "$block" --rf-condition R1 \
    --sample-rate 4000000 --lna 16 --vga "$vga" "$iq" \
    --firmware-build "${FW_BUILD:?请先填写实际固件标识}" \
    --experiment-dir "python/experiments/$(date +%Y%m%d)_run${id}" \
    --output "$prefix.json" --board-commands "$prefix.board.txt" \
    --host-commands "$prefix.host.sh"
}
```

首轮示例为 `prepare_uc1 2719 P3 1 B J1`。P4 的首个预算例为 `prepare_uc1 2734 P4 1 A JQ`。打开生成的 `.board.txt` 和 `.host.sh`。核对轮号、模式、块、任务数及 IQ 策略。预算轮的 manifest 应显示 budget、上限 6000；A 点 JC/SC/LC 每任务应余 1056/1056/176 µs，B 点应余 432/432/192 µs。

### 3. 采集、分析和当轮验收

1. 将 `.host.sh` 中的 BLE、IEEE 两条接收命令分别复制到两个终端运行（必要时附加固定的 `--serial`）。JC/SC 的 BLE 信道为 3，LC 为 39，IEEE 均为 12。两端均开始收流后，在第三个终端运行 `.host.sh` 中的板端串口自动发送与落盘命令（也可直接执行 `python3 python/control_match/uc1_board_send.py --run-id <RUN_ID>`，默认 `/dev/ttyUSB1`、`115200 8N1`，需先关闭其他占用 `/dev/ttyUSB1` 的串口工具）。P3 板端 RF 发送约 95 s、接收 120 s；P4 分别为 305 s、330 s（注意 P4 结束后板端还会以 115200 波特率连续转储约 2–3 分钟的逐槽/突发统计，脚本会一直写盘直到收到 `CONTROL_TIME_END` / `COMPACT_TIME_END` 并自动校验后退出，中途请勿中断）。
2. `uc1_board_send.py` 退出时会自动将完整日志保存到本轮目录的 `board.board.log` 并调用 `read_plan()` 核对 `UC1_CONFIG`、`CONTROL_PLAN_*`、逐突发日志和 `UC1_STATS final=1`。两端接收与串口转储均完成后，运行该轮 `.host.sh` 的最后一条联合分析命令。在 `notes.md` 记实际布局或照片编号、HackRF 序列号、块号、时间、标称功率/衰减及任何移动或异常。
3. 核对两侧 capture 完成状态、溢出/截断告警、双侧 `clipped_components` 与 `clip_ratio = clipped_components / (2 * samples_processed)`（零星 `< 1e-4` 仅记录不否决；`>= 1e-3` 或 `1e-4`–`1e-3` 伴随近距高增益/异常丢包触发饱和复查）、板端完成次数与失败次数、分析报告的计划分母。保留失败尝试与所有无线缺失。有配置错误或确定的采集损坏时记录原因，并从 `2767` 起分配替代 run ID 补采。
4. P3 每个块三轮共 90 项计划任务。两块各自的合并联合成功数均落在 **18–76 / 90**、**至少有一个相同模式**在两块中均满足 $1 \le s_m \le 29$，且采集质量可用（无队列溢出/截断及显著饱和），即登记该布局、三轮各自分子分母、`clip_ratio` 与入选日期，然后进入 P4。若首布局偏高（>76/90）可增大距离或在室内极限时统一增大 `tx_attenuation`，偏低（<18/90）可缩短距离，触发显著饱和复查时统一下调 `VGA` 或增大 `tx_attenuation`。完成 P3 后写定 P4 布局与排程。
5. P4 每完成一个负载在一个区组内的六轮，分别对 `1`（K=1）和 `Q`（6000 µs）做一次 JC/SC/LC 比较，输出目录按 `python/experiments/p4_comparisons/b<block>_<point>_<k1|q6000>/` 归档（三组共 12 份）。传入 `--conditions` 的 JSON 必须为三模式均填齐 `topology`、`tx_power`、`attenuation`、`firmware_build` 四个非空字段（缺任一项会被比较器判为 `unknown`）：

```json
{
  "JC": {
    "topology": "R1_selected_layout_id",
    "tx_power": "0 dBm nominal",
    "attenuation": "10000 mdB",
    "firmware_build": "<FW_BUILD>"
  },
  "SC": {
    "topology": "R1_selected_layout_id",
    "tx_power": "0 dBm nominal",
    "attenuation": "10000 mdB",
    "firmware_build": "<FW_BUILD>"
  },
  "LC": {
    "topology": "R1_selected_layout_id",
    "tx_power": "0 dBm nominal",
    "attenuation": "10000 mdB",
    "firmware_build": "<FW_BUILD>"
  }
}
```

按[跨模式比较命令](uc1_execution_manual.md#步骤-6运行单轮联合分析与跨模式对比)传入三份同点、同策略的 summary 与上述 `conditions.json`。三组结束时共得到 12 个三模式比较，再依上节计算配对差与区间。

## 交付与工时

P3 留下一份候选布局及选定理由记录；P4 留下 36 份逐轮报告、一张逐区组联合解析与成本表，以及 A/B 两个负载的模式比较。每个 P4 区组 12 轮，纯采集 66 分钟。首布局入选时全程 42 轮、3 小时 30 分；第二布局入选时 48 轮、3 小时 42 分。另留布置、重启、分析与转存时间。
