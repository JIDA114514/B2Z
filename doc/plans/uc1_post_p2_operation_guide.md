# UC1 P3/P4 实机详细操作指导手册

日期：2026-11-20。本手册严格依据 [UC1 冻结后的 P3/P4 实验计划](uc1_post_p2_experiment_plan.md) 编写，对应冻结基线提交 `ef5e237` 及新增串口落盘脚本 [uc1_board_send.py](../../python/control_match/uc1_board_send.py)。全部命令均已在当前仓库实测核对，可直接复制执行。

---

## 0. 开跑前一次性环境准备（每次换天或重启主机时复核）

打开 4 个终端，均切换到仓库根目录 `/home/jida/Desktop/antsdr/B2Z`：
- **终端 A（主控）**：生成配置、查看质量检查、执行联合分析与跨模式比较
- **终端 B（BLE 接收）**：专跑 `python/exadv_rx/receive.py`
- **终端 C（IEEE 接收）**：专跑 `python/zigbee_rx/control_receive.py`
- **终端 D（板端串口）**：专跑 `python/control_match/uc1_board_send.py`

### 0.1 硬件、磁盘与串口核对（在终端 A 执行）

```bash
cd /home/jida/Desktop/antsdr/B2Z

# 1. 核对当前代码提交与工作区状态
git rev-parse --short HEAD && git status --short

# 2. 核对工作盘可用空间（Block 1 每轮开跑前必须 > 7 GiB）
df -h .

# 3. 核对两块 HackRF 序列号（全程固定绑定 BLE/IEEE 及对应天线，严禁互换）
hackrf_info

# 4. 核对板端串口存在且未被 Minicom/CuteCom/Picocom 等其他进程占用
ls -l /dev/ttyUSB1
fuser /dev/ttyUSB1 || echo "/dev/ttyUSB1 空闲可用"
```

> [!IMPORTANT]
> - 运行 `uc1_board_send.py` 前**必须关闭**所有占用 `/dev/ttyUSB1` 的串口助手，否则会出现串口抢占或漏字。
> - 默认串口参数固定为 `/dev/ttyUSB1`、`115200 8N1`（无流控）。若板端串口号变为其他设备（如 `/dev/ttyUSB0`），在执行 `uc1_board_send.py` 时追加 `--port /dev/ttyUSB0`。
> - 若 `hackrf_info` 显示的设备序列号与台架默认顺序不一致，在终端 B/C 运行接收命令时**必须显式附加 `--serial <对应SN>`**，且整个 P3/P4 固定不变。

### 0.2 在终端 A 加载本轮快捷函数（执行一次，当前 Shell 会话持续有效）

```bash
# 填写板上实际烧录的固件标识（例如 Vitis 构建日期或 git commit）
read -r -p '实际烧录固件标识 FW_BUILD: ' FW_BUILD
export FW_BUILD

# 默认接收 VGA=16；若 P3 候选 2 触发饱和复查需统一下调，改设 export RX_VGA=10 或 12
export RX_VGA=16

# 1) 生成单轮冻结 manifest、.board.txt 与 .host.sh（每次只生成即将运行的当前轮）
prepare_uc1() {
  local id=$1 phase=$2 block=$3 point=$4 cond=$5
  local mode tasks stage b policy value iq=--no-save-iq vga=${RX_VGA:-16}
  case "$point" in A) b=0;; B) b=26;; *) echo "点位仅支持 A/B"; return 2;; esac
  case "$cond" in J1|JQ) mode=JC;; S1|SQ) mode=SC;; L1|LQ) mode=LC;; *) echo "条件码错误"; return 2;; esac
  case "$cond" in *1) policy=k; value=1;; *Q) policy=budget; value=6000;; esac
  case "$phase" in
    P3) stage=pilot; tasks=30
        if [[ $block == 1 && $mode == JC ]]; then iq=--save-iq; fi;;
    P4) stage=confirmatory; tasks=100
        if [[ $block == 1 && $point == B && ($cond == JQ || $cond == LQ) ]]; then iq=--save-iq; fi;;
    *) echo "阶段仅支持 P3/P4"; return 2;;
  esac
  local prefix="python/control_match/configs/uc1_${id}"
  local exp_dir="python/experiments/$(date +%Y%m%d)_run${id}"
  python3 python/control_match/uc1_config.py --run-id "$id" \
    --mode "$mode" --profile core --ble-extra "$b" --ieee-extra 0 \
    --tasks "$tasks" --period-ms 500 --policy "$policy" --value "$value" \
    --phase "$phase" --stage "$stage" --block "$block" --rf-condition R1 \
    --sample-rate 4000000 --lna 16 --vga "$vga" "$iq" \
    --firmware-build "${FW_BUILD:?请先设置 FW_BUILD}" \
    --experiment-dir "$exp_dir" \
    --output "$prefix.json" --board-commands "$prefix.board.txt" \
    --host-commands "$prefix.host.sh" || return $?
  echo "========== $prefix.board.txt =========="
  cat "$prefix.board.txt"
  echo "========== $prefix.host.sh =========="
  cat "$prefix.host.sh"
}

# 2) 单轮质量与削波快速核查（输出联合解析四分类、板端完成数、溢出及双侧 clip_ratio）
check_run_qc() {
  local id=$1
  python3 - "$id" <<'PY'
import glob, json, sys
from pathlib import Path
rid = sys.argv[1]
matches = sorted(Path("python/experiments").glob(f"*_run{rid}"))
if len(matches) != 1:
    raise SystemExit(f"目录数量异常: {matches}")
exp = matches[0]
sums = sorted(exp.glob("analyses/uc1_*/uc1.summary.json"))
if not sums:
    raise SystemExit(f"尚未生成 uc1.summary.json: {exp}")
d = json.loads(sums[-1].read_text())
fa = d["first_attempt"]
wp = d["within_planned_attempts"]
wc = d["waveform_cost"]
ub = d.get("uc1_board_stats") or {}
print(f"=== Run {rid} ({d['phase']} block={d['block']} {d['point']} {d['mode']} policy={d['policy']} K={d['k']}) ===")
print(f"  目录: {exp}")
print(f"  首次联合: {fa['joint']['numerator']}/{fa['joint']['denominator']}  四分类={fa['quadrants']}")
print(f"  计划内联合: {wp['joint']['numerator']}/{wp['joint']['denominator']}  四分类={wp['quadrants']}")
print(f"  截止分类: unknown={d['deadline_class']['joint_unknown']['numerator']}/{d['deadline_class']['joint_unknown']['denominator']}")
print(f"  提交波形代理: {wc['submitted_waveform_us']} us | 未用总计: {wc['unused_budget_total_us']} us | 单位成功成本: {wc['per_joint_decoded_task']['value_us']} us")
print(f"  板端统计: completed={ub.get('completed_attempts')}/{ub.get('planned_attempts')} failed={ub.get('failed_attempts')} anomalies={d['anomalies']}")
for side in ("ble", "zigbee"):
    sfiles = sorted((exp / "captures" / side).rglob("rx.summary.json"))
    if not sfiles:
        print(f"  [{side}] 缺少 rx.summary.json")
        continue
    rs = json.loads(sfiles[-1].read_text())
    cnt = rs.get("counts") or {}
    tot = cnt.get("samples_processed") or 0
    cc = cnt.get("clipped_components") or 0
    ratio = (cc / (2 * tot)) if tot else 0.0
    ovf = (rs.get("capture_stats") or {}).get("queue_overflow", 0)
    flag = "OK(<1e-4)" if ratio < 1e-4 else ("复查(1e-4~1e-3)" if ratio < 1e-3 else "显著饱和(>=1e-3)")
    print(f"  [{side}] status={rs.get('status')} queue_overflow={ovf} clipped={cc}/{2*tot} clip_ratio={ratio:.6e} [{flag}]")
PY
}

# 3) P3 候选布局两块（6 轮）一键入选判定（严格按三项规则，不比较模式高低）
check_p3_candidate() {
  if [[ $# -ne 6 ]]; then
    echo "用法: check_p3_candidate <b1_r1> <b1_r2> <b1_r3> <b2_r1> <b2_r2> <b2_r3>"
    return 2
  fi
  python3 - "$@" <<'PY'
import json, sys
from pathlib import Path
rids = sys.argv[1:]
blocks = {1: rids[:3], 2: rids[3:]}
by_block_mode = {1: {}, 2: {}}
all_ok_quality = True
for b, ids in blocks.items():
    total_ok, total_n = 0, 0
    print(f"--- Block {b} ---")
    for rid in ids:
        exp = sorted(Path("python/experiments").glob(f"*_run{rid}"))[-1]
        d = json.loads(sorted(exp.glob("analyses/uc1_*/uc1.summary.json"))[-1].read_text())
        mode = d["mode"]
        num = d["within_planned_attempts"]["joint"]["numerator"]
        den = d["within_planned_attempts"]["joint"]["denominator"]
        by_block_mode[b][mode] = (num, den)
        total_ok += num
        total_n += den
        max_ratio = 0.0
        bad_q = bool(d["anomalies"]["ble"] or d["anomalies"]["zigbee"])
        for side in ("ble", "zigbee"):
            rs = json.loads(sorted((exp / "captures" / side).rglob("rx.summary.json"))[-1].read_text())
            cnt = rs.get("counts") or {}
            tot = cnt.get("samples_processed") or 0
            cc = cnt.get("clipped_components") or 0
            r = (cc / (2 * tot)) if tot else 0.0
            max_ratio = max(max_ratio, r)
            if rs.get("status") != "complete" or (rs.get("capture_stats") or {}).get("queue_overflow", 0):
                bad_q = True
        if max_ratio >= 1e-3 or bad_q:
            all_ok_quality = False
        print(f"  run {rid} ({mode}): {num}/{den}, max_clip_ratio={max_ratio:.6e}, anomalies={bad_q}")
    in_band = 18 <= total_ok <= 76
    print(f"  Block {b} 合并联合成功: {total_ok}/{total_n} -> 区间 [18, 76]: {'PASS' if in_band else 'FAIL'}")

b1_sum = sum(v[0] for v in by_block_mode[1].values())
b2_sum = sum(v[0] for v in by_block_mode[2].values())
cond1 = (18 <= b1_sum <= 76) and (18 <= b2_sum <= 76)
shared_partial = [
    m for m in ("JC", "SC", "LC")
    if m in by_block_mode[1] and m in by_block_mode[2]
    and 1 <= by_block_mode[1][m][0] <= 29
    and 1 <= by_block_mode[2][m][0] <= 29
]
cond2 = len(shared_partial) >= 1
print("=== P3 综合判定 ===")
print(f"  规则1 两块合计数均在 18..76/90: {'PASS' if cond1 else 'FAIL'} (B1={b1_sum}, B2={b2_sum})")
print(f"  规则2 同模式双块均满足 1..29/30: {'PASS' if cond2 else 'FAIL'} (满足模式={shared_partial})")
print(f"  规则3 采集无异常且无 >=1e-3 饱和: {'PASS' if all_ok_quality else 'CHECK/FAIL'}")
print(f"  结论: {'>>> 该布局符合入选条件，可冻结进入 P4 <<<' if (cond1 and cond2 and all_ok_quality) else '>>> 未满足全部条件，按分支规则调整或复查 <<<'}")
PY
}
```

---

## 1. 单轮标准操作 SOP（5 步，所有 P3/P4 轮次通用）

每一轮严格按以下 5 步执行，**每轮均重新启动双侧接收端与板端命令**，不连续复用终端进程：

1. **步骤 1（终端 A）：空间检查 + 生成当前轮配置**
   - 若为 P4 Block 1 的 B 点 `JQ`/`LQ`（`2740`、`2742`，每轮需留双侧 IQ 约 5.28 GB），先执行 `df -h .` 确认可用空间 **> 7 GiB**。
   - 执行 `prepare_uc1 <RUN_ID> <P3|P4> <BLOCK> <A|B> <J1|S1|L1|JQ|SQ|LQ>`。
   - 核对打印出来的 `.board.txt` 与 `.host.sh`：确认 `run_id`、`mode`、`tasks`、`K`、`unused_per_task_us`（A 点 `1056/1056/176`、B 点 `432/432/192`）与 `--save-iq / --no-save-iq` 正确。
2. **步骤 2（终端 B & C）：同时启动 BLE 与 IEEE 接收端**
   - 复制 `.host.sh` 第 1 条命令到**终端 B**运行（JC/SC 为 `--channels 3`，LC 为 `--channels 39`）。
   - 复制 `.host.sh` 第 2 条命令到**终端 C**运行（IEEE 恒为 `--channel 12`）。
   - 观察两终端均已进入实时采集流（无报错退出、无设备忙错误）。
3. **步骤 3（终端 D）：自动发送板端命令并直接落盘 `board.board.log`**
   - 复制 `.host.sh` 第 3 条命令到**终端 D**运行（等价于 `python3 python/control_match/uc1_board_send.py --run-id <RUN_ID>`）。
   - 确认 10 秒内屏幕出现 `[uc1_board_send] board armed & running: CONTROL_PLAN_START ...`。
   - **等待自动结束**：
     - P3：约 95 s 后 RF 发送结束（终端 B/C 在 120 s 结束），串口继续转储统计约 15–30 s 后自动校验并退出。
     - P4：约 305 s 后 RF 发送结束（终端 B/C 在 330 s 结束），随后板端以 115200 波特率连续转储 610 槽逐突发日志（约 2.2 MB，需额外 **2–3 分钟**）；**切勿提前 Ctrl+C**，等待 `[uc1_board_send] verified .../board.board.log` 打印完成自动退出。
4. **步骤 4（终端 A）：运行联合分析与当轮质量核查**
   - 等终端 B、C、D 全部退出（返回码为 0）后，复制 `.host.sh` 第 4 条 `uc1_analyze.py` 命令到**终端 A**执行。
   - 立即执行 `check_run_qc <RUN_ID>`，核对无队列溢出、无异常、板端完成数正常、`clip_ratio` 正常。
5. **步骤 5（终端 A）：写入本轮 `notes.md`**
   - 执行以下命令写入本轮现场记录（按实际布局编号与备注替换）：
     ```bash
     cat > "python/experiments/$(date +%Y%m%d)_run<RUN_ID>/notes.md" <<'EOF'
     # Run <RUN_ID> 现场记录

     - **目的**：<P3 候选1/2 或 P4 区组X>（<A/B> 点，`JC/SC/LC`，<K=1 或 Q=6000>）。
     - **物理拓扑**：固定天线布局 `<LAYOUT_ID>`（照片 `<PHOTO_ID>`，TX-BLE `<d1> m`，TX-IEEE `<d2> m`，朝向 `<说明>`）。
     - **设备绑定**：BLE HackRF `<BLE_SN>`，IEEE HackRF `<IEEE_SN>`。
     - **板端发射设置**：标称发射功率 `0 dBm`（无功率计实测），板端衰减参数 `tx_attenuation=10000`（mdB）。
     - **人工干预**：无。
     - **现场异常**：未观测到异常（无告警不代表已证明 USB 零丢样）。
     - **关联记录**：[`uc1_<RUN_ID>.json`](../../control_match/configs/uc1_<RUN_ID>.json)、[board.board.log](board.board.log)、[uc1.report.md](analyses/uc1_<jc|sc|lc>_core/uc1.report.md)（设备参数、包数与成本以此为准）。
     - **记录日期**：2026-11-20。
     EOF
     ```

---

## 2. 阶段 P3：选定 R1 部分缺失无线条件（6 轮，最多 12 轮）

### 2.1 候选布局 1（2719–2724，全部为 B 点 `b=26, z=0`、30 任务、K=1）

摆放好固定天线布局（拍照留存，记下距离与朝向），先检查 `df -h .` > 3 GiB（2719 留双侧 IQ 约 1.92 GB，其余 5 轮不留 IQ）。按以下顺序**逐轮**执行第 1 节 SOP：

```bash
# --- 候选 1 / Block 1 (顺序: J1 -> S1 -> L1) ---
prepare_uc1 2719 P3 1 B J1   # 留双侧 IQ；跑完后: check_run_qc 2719
prepare_uc1 2720 P3 1 B S1   # 不留 IQ；  跑完后: check_run_qc 2720
prepare_uc1 2721 P3 1 B L1   # 不留 IQ；  跑完后: check_run_qc 2721

# --- 候选 1 / Block 2 (顺序: L1 -> S1 -> J1，可间隔数分钟) ---
prepare_uc1 2722 P3 2 B L1   # 跑完后: check_run_qc 2722
prepare_uc1 2723 P3 2 B S1   # 跑完后: check_run_qc 2723
prepare_uc1 2724 P3 2 B J1   # 跑完后: check_run_qc 2724

# 6 轮完成后，一键评估候选 1 是否入选
check_p3_candidate 2719 2720 2721 2722 2723 2724
```

### 2.2 候选 1 判定与分支处理

- **若 3 条规则全部 `PASS`**：
  - 候选 1 直接入选为 `R1`！**跳过 `2725–2730`**，直接进入第 2.3 节冻结 P3 布局并开始 P4（从 `2731` 起）。
- **若未全部 `PASS`，按原因仅调整一次进入候选 2（2725–2730）**：
  - 合并成功数 `> 76/90`（太好）：增大收发距离；若已到室内极限，固定物理摆放并统一增大板端 `tx_attenuation`（如 `30000`–`50000 mdB`，三模式与两块保持完全一致）。
  - 合并成功数 `< 18/90`（太差）：缩短收发距离或减小遮挡。
  - 出现显著饱和（`clip_ratio >= 1e-3`，或 `1e-4`–`1e-3` 伴随近距高增益/异常丢包）：在终端 A 统一下调接收增益（如 `export RX_VGA=10` 或 `12`）或增大板端 `tx_attenuation`。

```bash
# --- 候选 2 / Block 1 (顺序: J1 -> S1 -> L1) ---
prepare_uc1 2725 P3 1 B J1   # 留双侧 IQ；跑完后: check_run_qc 2725
prepare_uc1 2726 P3 1 B S1   # 跑完后: check_run_qc 2726
prepare_uc1 2727 P3 1 B L1   # 跑完后: check_run_qc 2727

# --- 候选 2 / Block 2 (顺序: L1 -> S1 -> J1) ---
prepare_uc1 2728 P3 2 B L1   # 跑完后: check_run_qc 2728
prepare_uc1 2729 P3 2 B S1   # 跑完后: check_run_qc 2729
prepare_uc1 2730 P3 2 B J1   # 跑完后: check_run_qc 2730

# 6 轮完成后，一键评估候选 2
check_p3_candidate 2725 2726 2727 2728 2729 2730
```

> 若候选 2 仍未满足条件，按计划**立即停止摸底**（不再继续调参），汇总 12 轮观测范围，暂缓有损无线条件比较。

### 2.3 P3 冻结与生成 P4 共享 `conditions.json`

候选布局入选后，**严禁再移动天线或改变功率/衰减/增益**，在终端 A 创建本次 P4 共用的 `conditions.json`（按实际入选布局信息替换尖括号内容）：

```bash
mkdir -p python/experiments/p4_comparisons
cat > python/experiments/p4_comparisons/r1_conditions.json <<EOF
{
  "JC": {
    "topology": "<R1_LAYOUT_ID_AND_DISTANCE>",
    "tx_power": "0 dBm nominal",
    "attenuation": "<10000_OR_SELECTED_ATTEN> mdB",
    "firmware_build": "${FW_BUILD}"
  },
  "SC": {
    "topology": "<R1_LAYOUT_ID_AND_DISTANCE>",
    "tx_power": "0 dBm nominal",
    "attenuation": "<10000_OR_SELECTED_ATTEN> mdB",
    "firmware_build": "${FW_BUILD}"
  },
  "LC": {
    "topology": "<R1_LAYOUT_ID_AND_DISTANCE>",
    "tx_power": "0 dBm nominal",
    "attenuation": "<10000_OR_SELECTED_ATTEN> mdB",
    "firmware_build": "${FW_BUILD}"
  }
}
EOF
```

再定义一个跨模式比较快捷函数（每完成一个区组内某负载点的 6 轮后调用，自动定位当轮目录、生成 12 份对比）：

```bash
compare_p4_trio() {
  local tag=$1 r_jc=$2 r_sc=$3 r_lc=$4
  local s_jc s_sc s_lc
  s_jc=$(echo python/experiments/*_run${r_jc}/analyses/uc1_jc_core/uc1.summary.json)
  s_sc=$(echo python/experiments/*_run${r_sc}/analyses/uc1_sc_core/uc1.summary.json)
  s_lc=$(echo python/experiments/*_run${r_lc}/analyses/uc1_lc_core/uc1.summary.json)
  python3 python/control_match/uc1_analyze.py \
    --compare-jc "$s_jc" --compare-sc "$s_sc" --compare-lc "$s_lc" \
    --conditions python/experiments/p4_comparisons/r1_conditions.json \
    --output-dir "python/experiments/p4_comparisons/${tag}"
}
```

---

## 3. 阶段 P4：正式 36 轮确认性重复（2731–2766）

每轮 100 任务、500 ms 周期、610 槽（RF 305 s + 接收 330 s + 板端串口转储约 2–3 分钟）。三个区组尽量安排在**不同时间段**，每个区组 12 轮。

### 3.1 Block 1（2731–2742，仅 2740 `JQ` 与 2742 `LQ` 留双侧 IQ）

2740 与 2742 开跑前均用 `df -h .` 核对可用空间超过 7 GiB（两轮双侧 IQ 合计约 10.56 GB / 9.84 GiB，保存在本地实验目录；若当前磁盘 12 GiB 略紧，开跑 `2742` 前可先转存/清理淘汰候选 1 的 `2719` 原始 IQ 约 1.8 GiB）。全部 36 轮均归档双侧逐包记录、配置、串口日志与分析。

**Block 1 — 负载 A（`2731–2736`，顺序 `J1 → S1 → L1 → JQ → SQ → LQ`）**：

```bash
df -h . && prepare_uc1 2731 P4 1 A J1   # SOP 2~5 + check_run_qc 2731
df -h . && prepare_uc1 2732 P4 1 A S1   # SOP 2~5 + check_run_qc 2732

df -h . && prepare_uc1 2733 P4 1 A L1   # SOP 2~5 + check_run_qc 2733
df -h . && prepare_uc1 2734 P4 1 A JQ   # SOP 2~5 + check_run_qc 2734

df -h . && prepare_uc1 2735 P4 1 A SQ   # SOP 2~5 + check_run_qc 2735
df -h . && prepare_uc1 2736 P4 1 A LQ   # SOP 2~5 + check_run_qc 2736

# Block 1 负载 A 三模式对比（2 份）
compare_p4_trio b1_A_k1    2731 2732 2733
compare_p4_trio b1_A_q6000 2734 2735 2736
```

**Block 1 — 负载 B（`2737–2742`，顺序 `J1 → S1 → L1 → JQ → SQ → LQ`）**：

```bash
df -h . && prepare_uc1 2737 P4 1 B J1   # SOP 2~5 + check_run_qc 2737
df -h . && prepare_uc1 2738 P4 1 B S1   # SOP 2~5 + check_run_qc 2738

df -h . && prepare_uc1 2739 P4 1 B L1   # SOP 2~5 + check_run_qc 2739
df -h . && prepare_uc1 2740 P4 1 B JQ   # SOP 2~5 + check_run_qc 2740

df -h . && prepare_uc1 2741 P4 1 B SQ   # SOP 2~5 + check_run_qc 2741
df -h . && prepare_uc1 2742 P4 1 B LQ   # SOP 2~5 + check_run_qc 2742

# Block 1 负载 B 三模式对比（2 份）
compare_p4_trio b1_B_k1    2737 2738 2739
compare_p4_trio b1_B_q6000 2740 2741 2742
```

### 3.2 Block 2（2743–2754，不留 IQ，先 B 后 A，顺序 `LQ → SQ → JQ → L1 → S1 → J1`）

```bash
# --- Block 2 / 负载 B ---
prepare_uc1 2743 P4 2 B LQ   # SOP 2~5 + check_run_qc 2743
prepare_uc1 2744 P4 2 B SQ   # SOP 2~5 + check_run_qc 2744
prepare_uc1 2745 P4 2 B JQ   # SOP 2~5 + check_run_qc 2745
prepare_uc1 2746 P4 2 B L1   # SOP 2~5 + check_run_qc 2746
prepare_uc1 2747 P4 2 B S1   # SOP 2~5 + check_run_qc 2747
prepare_uc1 2748 P4 2 B J1   # SOP 2~5 + check_run_qc 2748

# Block 2 负载 B 三模式对比（注意参数顺序始终为 JC SC LC）
compare_p4_trio b2_B_k1    2748 2747 2746
compare_p4_trio b2_B_q6000 2745 2744 2743

# --- Block 2 / 负载 A ---
prepare_uc1 2749 P4 2 A LQ   # SOP 2~5 + check_run_qc 2749
prepare_uc1 2750 P4 2 A SQ   # SOP 2~5 + check_run_qc 2750
prepare_uc1 2751 P4 2 A JQ   # SOP 2~5 + check_run_qc 2751
prepare_uc1 2752 P4 2 A L1   # SOP 2~5 + check_run_qc 2752
prepare_uc1 2753 P4 2 A S1   # SOP 2~5 + check_run_qc 2753
prepare_uc1 2754 P4 2 A J1   # SOP 2~5 + check_run_qc 2754

# Block 2 负载 A 三模式对比（JC SC LC）
compare_p4_trio b2_A_k1    2754 2753 2752
compare_p4_trio b2_A_q6000 2751 2750 2749
```

### 3.3 Block 3（2755–2766，不留 IQ，先 A 后 B，顺序 `L1 → JQ → SQ → LQ → J1 → S1`）

```bash
# --- Block 3 / 负载 A ---
prepare_uc1 2755 P4 3 A L1   # SOP 2~5 + check_run_qc 2755
prepare_uc1 2756 P4 3 A JQ   # SOP 2~5 + check_run_qc 2756
prepare_uc1 2757 P4 3 A SQ   # SOP 2~5 + check_run_qc 2757
prepare_uc1 2758 P4 3 A LQ   # SOP 2~5 + check_run_qc 2758
prepare_uc1 2759 P4 3 A J1   # SOP 2~5 + check_run_qc 2759
prepare_uc1 2760 P4 3 A S1   # SOP 2~5 + check_run_qc 2760

# Block 3 负载 A 三模式对比（JC SC LC）
compare_p4_trio b3_A_k1    2759 2760 2755
compare_p4_trio b3_A_q6000 2756 2757 2758

# --- Block 3 / 负载 B ---
prepare_uc1 2761 P4 3 B L1   # SOP 2~5 + check_run_qc 2761
prepare_uc1 2762 P4 3 B JQ   # SOP 2~5 + check_run_qc 2762
prepare_uc1 2763 P4 3 B SQ   # SOP 2~5 + check_run_qc 2763
prepare_uc1 2764 P4 3 B LQ   # SOP 2~5 + check_run_qc 2764
prepare_uc1 2765 P4 3 B J1   # SOP 2~5 + check_run_qc 2765
prepare_uc1 2766 P4 3 B S1   # SOP 2~5 + check_run_qc 2766

# Block 3 负载 B 三模式对比（JC SC LC）
compare_p4_trio b3_B_k1    2765 2766 2761
compare_p4_trio b3_B_q6000 2762 2763 2764
```

---

## 4. 异常处置与补采规则（`2767+`）

| 现象 | 是否补采 | 操作方式 |
| --- | --- | --- |
| 正常无线漏收（含某轮解析率偏低或全失） | **否（严禁重跑剔除）** | 照常保留并计入分母 |
| 零星低比例削波（`clip_ratio < 1e-4`） | **否** | 仅在 `notes.md` 与质量表披露 |
| `queue_overflow > 0` / 接收崩溃 / 满盘截断 | **是** | 原目录保留并在 `notes.md` 注明原因；分配 `2767+` 补采 |
| 串口被抢占 / `board.board.log` 校验失败 / 发错参数 | **是** | 原目录保留并在 `notes.md` 注明原因；分配 `2767+` 补采 |
| 采集期间人员误碰天线或明显改变遮挡 | **是** | 原目录保留并在 `notes.md` 注明原因；分配 `2767+` 补采 |

补采示例（假设 `2738`（P4 Block 1 B点 S1）发生 USB 队列溢出，用 `2767` 补采）：

```bash
prepare_uc1 2767 P4 1 B S1
# 按 SOP 2~5 完成 2767 采集与分析；在 2738 和 2767 的 notes.md 中双向注明“2767 替代因 queue_overflow 作废的 2738”
# 后续 compare_p4_trio 时把 2738 替换为 2767：
compare_p4_trio b1_B_k1 2737 2767 2739
```

---

## 5. 全部 36 轮完成后的索引刷新与收尾核查

全部 P3/P4 轮次及 12 份跨模式对比完成后，在终端 A 执行：

```bash
# 1. 核对 12 份跨模式对比已全部生成且 conditions_status 均为 match
python3 - <<'PY'
import json
from pathlib import Path
files = sorted(Path("python/experiments/p4_comparisons").glob("*/uc1.comparison.json"))
print(f"Found {len(files)}/12 comparison files:")
for f in files:
    d = json.loads(f.read_text())
    st = {k: (v["conditions_status"], v["jc_minus_other_within_planned_rate"]) for k, v in d["comparisons"].items()}
    print(f"  {f.parent.name}: {st}")
PY

# 2. 重建全仓库实验索引（index.md / index.csv / runs.csv / artifacts.csv）
python3 -c 'from pathlib import Path; from python.experiment_tools.reporting import rebuild_index; rebuild_index(Path("python/experiments")); print("rebuild_index OK")'

# 3. 核对工作区改动（确认无原始 .ci8 IQ 被误跟踪）
git status --short
```

完成后即可进入 P5：基于 12 份 `uc1.comparison.json` 与 36 份 `uc1.summary.json` 计算三区组配对差、均值、范围及自由度 2 的 95% t 区间，冻结最终论文图表与结论。
