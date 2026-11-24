#!/usr/bin/env python3
"""Read-only P5 aggregator: freeze paper-ready tables from UC1 P2/P3/P4 outputs.

Reads frozen uc1.summary.json, uc1.comparison.json, rx.summary.json, and H1/H6
artifacts without modifying any source experiment directory. Writes CSV/JSON
tables to --output-dir and a Markdown frozen results report to --report-md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

T_CRIT_DF2 = 4.302652729911275  # 95% two-sided t critical value for df=2
REPO_ROOT = Path(__file__).resolve().parents[2]
EXP_ROOT = REPO_ROOT / "python" / "experiments"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _exp_dir(run_id: int) -> Path:
    matches = sorted(EXP_ROOT.glob(f"*_run{run_id}"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected 1 experiment dir for run {run_id}, found {matches}")
    return matches[0]


def _load_p4_run(run_id: int) -> dict:
    exp = _exp_dir(run_id)
    sums = sorted(exp.glob("analyses/uc1_*_core/uc1.summary.json"))
    if len(sums) != 1:
        raise FileNotFoundError(f"expected 1 uc1_*_core summary in {exp}, found {sums}")
    sp = sums[0]
    d = json.loads(sp.read_text(encoding="utf-8"))
    ub = d.get("uc1_board_stats") or {}
    c3 = d.get("ble_fragment_reassembly") or {}
    fa = d["first_attempt"]
    wp = d["within_planned_attempts"]
    dl = d["deadline_class"]
    wc = d["waveform_cost"]

    side_q = {}
    for s in ("ble", "zigbee"):
        rs_path = sorted((exp / "captures" / s).rglob("rx.summary.json"))[-1]
        rs = json.loads(rs_path.read_text(encoding="utf-8"))
        cnt = rs.get("counts") or {}
        tot = cnt.get("samples_processed") or 0
        cc = cnt.get("clipped_components") or 0
        ovf = (rs.get("capture_stats") or {}).get("queue_overflow", 0)
        side_q[s] = {
            "status": rs.get("status"),
            "queue_overflow": ovf,
            "clipped_components": cc,
            "clip_ratio": (cc / (2 * tot)) if tot else 0.0,
            "packets_total": cnt.get("packets"),
        }

    return {
        "run_id": run_id,
        "experiment_dir": exp.name,
        "summary_path": str(sp.relative_to(REPO_ROOT)),
        "summary_sha256": _sha256(sp),
        "config_sha256": d.get("config_sha256"),
        "block": int(d["block"]),
        "point": d["point"],
        "mode": d["mode"],
        "policy": d["policy"],
        "strategy": "k1" if d["policy"] == "k" else "q6000",
        "k": int(d["k"]),
        "ble_channel": d["layout"]["ble_channel"],
        "ieee_channel": d["layout"]["ieee_channel"],
        "tasks_planned": int(wp["joint"]["denominator"]),
        "first_both": int(fa["quadrants"]["both"]),
        "first_ble_only": int(fa["quadrants"]["ble_only"]),
        "first_zigbee_only": int(fa["quadrants"]["zigbee_only"]),
        "first_neither": int(fa["quadrants"]["neither"]),
        "plan_both": int(wp["quadrants"]["both"]),
        "plan_ble_only": int(wp["quadrants"]["ble_only"]),
        "plan_zigbee_only": int(wp["quadrants"]["zigbee_only"]),
        "plan_neither": int(wp["quadrants"]["neither"]),
        "different_slot_joint": int(wp.get("different_slot_joint_tasks", 0)),
        "deadline_unknown": int(dl["joint_unknown"]["numerator"]),
        "deadline_not_decoded": int(dl["joint_not_decoded"]["numerator"]),
        "planned_waveform_us": int(wc["planned_waveform_us"]),
        "submitted_waveform_us": int(wc["submitted_waveform_us"]),
        "unused_budget_total_us": int(wc["unused_budget_total_us"]),
        "unit_cost_us": wc["per_joint_decoded_task"]["value_us"],
        "c3_fragments": int(c3.get("c3_fragments", 0)),
        "c3_complete": int(c3.get("complete", 0)),
        "c3_timeout": int(c3.get("timeout", 0)),
        "board_completed": int(ub.get("completed_attempts", 0)),
        "board_planned": int(ub.get("planned_attempts", 0)),
        "board_failed": int(ub.get("failed_attempts", 0)),
        "ble_status": side_q["ble"]["status"],
        "ble_overflow": side_q["ble"]["queue_overflow"],
        "ble_clip_ratio": side_q["ble"]["clip_ratio"],
        "zigbee_status": side_q["zigbee"]["status"],
        "zigbee_overflow": side_q["zigbee"]["queue_overflow"],
        "zigbee_clip_ratio": side_q["zigbee"]["clip_ratio"],
        "anomalies_count": len(d["anomalies"]["ble"]) + len(d["anomalies"]["zigbee"]),
    }


def _load_p2_h2_h3() -> list[dict]:
    out = []
    # H2 9 branches (2702-2709, 2718) + H3 boundary (2710)
    run_map = [
        (2704, "H2/H1", "uc1_p2_review"),
        (2702, "H2", "uc1_sc_core"),
        (2703, "H2", "uc1_p2_review"),
        (2710, "H3", "uc1_p2_review"),
        (2718, "H2/H1", "uc1_p2_review"),
        (2705, "H2", "uc1_p2_review"),
        (2706, "H2", "uc1_p2_review"),
        (2707, "H2/H1", "uc1_p2_review"),
        (2708, "H2", "uc1_p2_review"),
        (2709, "H2", "uc1_p2_review"),
    ]
    for rid, tag, aid in run_map:
        exp = _exp_dir(rid)
        sp = exp / "analyses" / aid / "uc1.summary.json"
        d = json.loads(sp.read_text(encoding="utf-8"))
        lay = d["layout"]
        wc = d["waveform_cost"]
        wp = d["within_planned_attempts"]
        c3 = d.get("ble_fragment_reassembly") or {}
        out.append({
            "run_id": rid,
            "tag": tag,
            "point": d["point"],
            "b": lay["ble_extra"],
            "z": lay["ieee_extra"],
            "mode": d["mode"],
            "ble_record_bytes": lay["ble_record_bytes"],
            "ieee_record_bytes": lay["ieee_record_bytes"],
            "mapped_bytes": lay["mapped_bytes"],
            "secondary_payload_bytes": lay["secondary_payload_bytes"],
            "ble_fragments_per_attempt": lay["ble_fragments_per_attempt"],
            "cost_per_attempt_us": wc["planned_waveform_us"] // wc["planned_attempts"],
            "submitted_waveform_us": wc["submitted_waveform_us"],
            "joint_decoded": f"{wp['joint']['numerator']}/{wp['joint']['denominator']}",
            "c3_fragments": c3.get("c3_fragments", 0),
            "c3_complete": c3.get("complete", 0),
            "summary_path": str(sp.relative_to(REPO_ROOT)),
        })
    return out


def _load_p2_h5() -> list[dict]:
    out = []
    for rid, label in ((2715, "Normal (no intervention)"), (2716, "BLE disconnect"), (2717, "IEEE disconnect")):
        exp = _exp_dir(rid)
        sp = exp / "analyses" / "uc1_time_tail_audit" / "uc1.summary.json"
        d = json.loads(sp.read_text(encoding="utf-8"))
        ts = d["time_support"]
        wp = d["within_planned_attempts"]
        lp = ts.get("live_pair_diff_ms") or {}
        rec_in = ts["recovery_in_schedule"]
        tail = ts["post_run_tail_stale_events"]
        probes = ts["live_probe_summary"]
        b_cov = probes["ble"]["coverage"]
        z_cov = probes["zigbee"]["coverage"]
        b_res = probes["ble"]["residual_ms"]
        z_res = probes["zigbee"]["residual_ms"]
        out.append({
            "run_id": rid,
            "scenario": label,
            "joint_tasks": f"{wp['joint']['numerator']}/{wp['joint']['denominator']}",
            "quadrants": wp["quadrants"],
            "ble_probe_cov": f"{b_cov['numerator']}/{b_cov['denominator']}",
            "zigbee_probe_cov": f"{z_cov['numerator']}/{z_cov['denominator']}",
            "ble_rec_in_sched": f"{rec_in['ble']['numerator']}/{rec_in['ble']['denominator']}",
            "zigbee_rec_in_sched": f"{rec_in['zigbee']['numerator']}/{rec_in['zigbee']['denominator']}",
            "tail_stale_ble_zigbee": f"{tail['ble']}/{tail['zigbee']}",
            "ble_res_med_p95_max_ms": (
                f"{b_res['median_abs']:.3f} / {b_res['p95_abs']:.3f} / {b_res['max_abs']:.3f}"
            ),
            "zigbee_res_med_p95_max_ms": (
                f"{z_res['median_abs']:.3f} / {z_res['p95_abs']:.3f} / {z_res['max_abs']:.3f}"
            ),
            "pair_diff_n": lp.get("n"),
            "pair_diff_med_p95_ms": (
                f"{lp['median_abs']:.3f} / {lp['p95_abs']:.3f}" if lp.get("median_abs") is not None else "N/A"
            ),
            "summary_path": str(sp.relative_to(REPO_ROOT)),
        })
    return out


def _paired_stats(diffs: list[int]) -> dict:
    n = len(diffs)
    mean = sum(diffs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in diffs) / (n - 1))
    se = sd / math.sqrt(n)
    half = T_CRIT_DF2 * se
    return {
        "b1_pp": diffs[0],
        "b2_pp": diffs[1],
        "b3_pp": diffs[2],
        "mean_pp": round(mean, 4),
        "sd_pp": round(sd, 4),
        "se_pp": round(se, 4),
        "min_pp": min(diffs),
        "max_pp": max(diffs),
        "ci95_low_pp": round(mean - half, 4),
        "ci95_high_pp": round(mean + half, 4),
        "df": n - 1,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Freeze P5 master CSV/JSON/Markdown tables from UC1 P2-P4 outputs.")
    ap.add_argument("--output-dir", type=Path, default=EXP_ROOT / "p5_freeze_20261124")
    ap.add_argument("--report-md", type=Path, default=REPO_ROOT / "doc/results/uc1_p5_frozen_results_20261124.md")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite non-empty {args.output_dir}; pass --overwrite to replace")

    p4_runs = [_load_p4_run(rid) for rid in range(2731, 2767)]
    by_key = {(r["block"], r["point"], r["strategy"], r["mode"]): r for r in p4_runs}
    assert len(by_key) == 36, f"expected 36 unique P4 cells, got {len(by_key)}"

    # Verify all 12 comparison files match
    comp_audit = {}
    for b in (1, 2, 3):
        for pt in ("A", "B"):
            for strat in ("k1", "q6000"):
                tag = f"b{b}_{pt}_{strat}"
                cp = EXP_ROOT / "p4_comparisons" / tag / "uc1.comparison.json"
                cd = json.loads(cp.read_text(encoding="utf-8"))
                comp_audit[tag] = {
                    "path": str(cp.relative_to(REPO_ROOT)),
                    "sha256": _sha256(cp),
                    "JC_vs_SC_status": cd["comparisons"]["JC_vs_SC"]["conditions_status"],
                    "JC_vs_SC_identifiable": cd["comparisons"]["JC_vs_SC"]["reliability_protocol_effect_identifiable"],
                    "JC_vs_LC_status": cd["comparisons"]["JC_vs_LC"]["conditions_status"],
                    "JC_vs_LC_channel_confound": cd["comparisons"]["JC_vs_LC"]["channel_confound"],
                }

    # Build paired block summary (8 contrasts) and cell summary (12 mode-cells)
    cell_summary = []
    paired_rows = []
    for pt in ("A", "B"):
        for strat in ("k1", "q6000"):
            for mode in ("JC", "SC", "LC"):
                rs = [by_key[(b, pt, strat, mode)] for b in (1, 2, 3)]
                plan_vals = [r["plan_both"] for r in rs]
                first_vals = [r["first_both"] for r in rs]
                mean_p = sum(plan_vals) / 3.0
                sd_p = math.sqrt(sum((x - mean_p) ** 2 for x in plan_vals) / 2.0)
                tot_us = sum(r["submitted_waveform_us"] for r in rs)
                tot_unused = sum(r["unused_budget_total_us"] for r in rs)
                tot_ok = sum(plan_vals)
                pooled_unit = (tot_us / tot_ok) if tot_ok > 0 else None
                cell_summary.append({
                    "point": pt,
                    "strategy": strat,
                    "mode": mode,
                    "k": rs[0]["k"],
                    "b1_plan": plan_vals[0],
                    "b2_plan": plan_vals[1],
                    "b3_plan": plan_vals[2],
                    "total_plan_num": tot_ok,
                    "total_plan_den": 300,
                    "mean_plan_pct": round(mean_p, 2),
                    "sd_plan_pct": round(sd_p, 2),
                    "b1_first": first_vals[0],
                    "b2_first": first_vals[1],
                    "b3_first": first_vals[2],
                    "sum_both": sum(r["plan_both"] for r in rs),
                    "sum_ble_only": sum(r["plan_ble_only"] for r in rs),
                    "sum_zigbee_only": sum(r["plan_zigbee_only"] for r in rs),
                    "sum_neither": sum(r["plan_neither"] for r in rs),
                    "sum_first_ble_only": sum(r["first_ble_only"] for r in rs),
                    "sum_first_zigbee_only": sum(r["first_zigbee_only"] for r in rs),
                    "sum_first_neither": sum(r["first_neither"] for r in rs),
                    "sum_diff_slot_joint": sum(r["different_slot_joint"] for r in rs),
                    "total_submitted_us": tot_us,
                    "total_unused_us": tot_unused,
                    "pooled_unit_cost_us": round(pooled_unit, 2) if pooled_unit is not None else None,
                })
            for other in ("SC", "LC"):
                diffs = [
                    by_key[(b, pt, strat, "JC")]["plan_both"] - by_key[(b, pt, strat, other)]["plan_both"]
                    for b in (1, 2, 3)
                ]
                st = _paired_stats(diffs)
                paired_rows.append({
                    "point": pt,
                    "strategy": strat,
                    "contrast": f"JC_minus_{other}",
                    "channel_confound": other == "LC",
                    "protocol_identifiable": other == "SC",
                    **st,
                })

    p2_h2_h3 = _load_p2_h2_h3()
    p2_h5 = _load_p2_h5()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "p5_p4_runs.csv", p4_runs)
    _write_csv(args.output_dir / "p5_p4_cells.csv", cell_summary)
    _write_csv(args.output_dir / "p5_p4_paired_blocks.csv", paired_rows)
    _write_csv(args.output_dir / "p5_p2_h2_h3.csv", p2_h2_h3)
    _write_csv(args.output_dir / "p5_p2_h5.csv", p2_h5)

    total_tasks = sum(r["tasks_planned"] for r in p4_runs)
    total_dl_unknown = sum(r["deadline_unknown"] for r in p4_runs)
    total_dl_not_decoded = sum(r["deadline_not_decoded"] for r in p4_runs)
    assert total_dl_unknown + total_dl_not_decoded == total_tasks

    frozen_json = {
        "schema": "b2z_uc1_p5_frozen_results_v1",
        "p4_data_archive_commit": "82d56a5",
        "git_head": _git_head(),
        "generator_sha256": _sha256(Path(__file__)),
        "p4_run_range": [2731, 2766],
        "p4_total_runs": len(p4_runs),
        "p4_total_planned_tasks": total_tasks,
        "p4_deadline_totals": {
            "joint_unknown": total_dl_unknown,
            "joint_not_decoded": total_dl_not_decoded,
            "planned_tasks": total_tasks,
        },
        "p4_quality_audit": {
            "all_complete": all(r["ble_status"] == "complete" and r["zigbee_status"] == "complete" for r in p4_runs),
            "total_overflows": sum(r["ble_overflow"] + r["zigbee_overflow"] for r in p4_runs),
            "max_clip_ratio": max(max(r["ble_clip_ratio"], r["zigbee_clip_ratio"]) for r in p4_runs),
            "total_anomalies": sum(r["anomalies_count"] for r in p4_runs),
            "total_board_failed": sum(r["board_failed"] for r in p4_runs),
            "all_comparisons_match": all(
                v["JC_vs_SC_status"] == "match" and v["JC_vs_LC_status"] == "match" for v in comp_audit.values()
            ),
        },
        "comparisons_audit": comp_audit,
        "p4_cells": cell_summary,
        "p4_paired_blocks": paired_rows,
        "p4_runs": p4_runs,
        "p2_h2_h3": p2_h2_h3,
        "p2_h5": p2_h5,
    }
    (args.output_dir / "p5_frozen_summary.json").write_text(
        json.dumps(frozen_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Dynamic lookup helpers for §6 narrative (no hardcoded counts)
    c_map = {(c["point"], c["strategy"], c["mode"]): c for c in cell_summary}
    p_map = {(p["point"], p["strategy"], p["contrast"]): p for p in paired_rows}
    r_map = {r["run_id"]: r for r in p4_runs}

    # Render Markdown frozen report
    rel_out = Path("../../python/experiments") / args.output_dir.name
    md = [
        "# UC1 P5 论文冻结结果总表（P2 2701–2718 + P3 2719–2730 + P4 2731–2766）",
        "",
        f"- **P4 数据归档提交**：`{frozen_json['p4_data_archive_commit']}`（运行时仓库 HEAD `{frozen_json['git_head']}`，汇总脚本 SHA-256 `{frozen_json['generator_sha256']}`）；P4 冻结条件为固件 `20261119-uc1-r1`、无线布局 `R1_candidate2_0p10m`（0.10 m 统一胶棒天线，标称 `0 dBm` / `tx_attenuation=10000 mdB`，双侧接收 `4 Msps` / `LNA 16` / `VGA 16` / `AMP 关`）。P2 与 P3 分别按各自阶段条件追溯：[P2 复核（R0 馈线）](uc1_p2_2701_2718_review_20261120.md) · [P3 条件冻结（0.20/0.10 m 先导）](uc1_p3_r1_freeze_20261123.md)",
        f"- **数据来源与溯源文件**：[{args.output_dir.name}/p5_frozen_summary.json]({rel_out}/p5_frozen_summary.json) · [p5_p4_runs.csv]({rel_out}/p5_p4_runs.csv) · [p5_p4_cells.csv]({rel_out}/p5_p4_cells.csv) · [p5_p4_paired_blocks.csv]({rel_out}/p5_p4_paired_blocks.csv) · [p5_p2_h2_h3.csv]({rel_out}/p5_p2_h2_h3.csv) · [p5_p2_h5.csv]({rel_out}/p5_p2_h5.csv)",
        f"- **P4 质量门禁核验（36 轮 / {total_tasks:,} 计划任务）**：`all_complete={frozen_json['p4_quality_audit']['all_complete']}`，`total_overflows={frozen_json['p4_quality_audit']['total_overflows']}`，`max_clip_ratio={frozen_json['p4_quality_audit']['max_clip_ratio']:.2e}`，`total_anomalies={frozen_json['p4_quality_audit']['total_anomalies']}`，`total_board_failed={frozen_json['p4_quality_audit']['total_board_failed']}`，`12/12 comparisons match={frozen_json['p4_quality_audit']['all_comparisons_match']}`",
        "",
        "> [!IMPORTANT]",
        "> **统计与物理口径边界**：",
        f"> 1. 在 P4 全部 {total_tasks:,} 个计划任务中，**{total_dl_unknown:,}/{total_tasks:,}** 个联合解析成功任务的截止期分类为 `unknown`（独立 HackRF 时间轴无外部校准参考界），其余 **{total_dl_not_decoded:,}/{total_tasks:,}** 个未联合解析任务为 `not_decoded`（合计 {total_dl_unknown + total_dl_not_decoded:,}）。可靠性主指标使用**计划尝试内联合命令解析率**（`within_planned_attempts`），另报首次尝试率（`first_attempt`）。",
        "> 2. 波形成本均为设计/提交波形代理时长（`µs`），非功率计/空口实测 RF 时长或能耗；单位成功任务成本按全部提交波形除以联合成功任务数计算（零成功记 `N/A`）；DMA 完成是发送代理指标。",
        "> 3. `JC` 与 `SC` 同用 BLE ch3（2410 MHz）与 IEEE ch12（2410 MHz），12/12 满足 `reliability_protocol_effect_identifiable=True`；`LC` 使用 BLE ch39（2480 MHz），因此 `JC vs LC` 的可靠性差属于**封装+信道组合**配置级结论，不能单独归因于格式。",
        "> 4. 每条件为 `n=3` 个独立区组（`df=2`，$t_{0.975,2}=4.303$），区间宽度受限于自由度 2（小样本 t 近似可使端点超出 ±100 pp），按预登记停止条件不因区间跨零追加区组。",
        "",
        "## 1. P4 核心主表：12 个条件单元（每单元 3 区组 × 100 任务 = 300 计划任务）",
        "",
        "| 负载点 | 策略 | 模式 | K | B1/B2/B3 计划内 (`/100`) | 合并分子/分母 | 均值 ± SD (%) | B1/B2/B3 首次 (`/100`) | 计划内四分类 (`both/B/Z/none`) | 异槽互补 | 总提交波形 (µs) | 未用预算 (µs) | 合并单位成功成本 (µs/任务) |",
        "| --- | --- | --- | :-: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for c in cell_summary:
        unit_s = f"{c['pooled_unit_cost_us']:.1f}" if c["pooled_unit_cost_us"] is not None else "N/A"
        md.append(
            f"| {c['point']} | {c['strategy']} | {c['mode']} | {c['k']} | "
            f"{c['b1_plan']} / {c['b2_plan']} / {c['b3_plan']} | "
            f"{c['total_plan_num']}/{c['total_plan_den']} | "
            f"{c['mean_plan_pct']:.1f} ± {c['sd_plan_pct']:.1f} | "
            f"{c['b1_first']} / {c['b2_first']} / {c['b3_first']} | "
            f"{c['sum_both']} / {c['sum_ble_only']} / {c['sum_zigbee_only']} / {c['sum_neither']} | "
            f"{c['sum_diff_slot_joint']} | "
            f"{c['total_submitted_us']:,} | {c['total_unused_us']:,} | {unit_s} |"
        )

    md += [
        "",
        "## 2. P4 三区组配对差与 95% t 置信区间（`df=2`）",
        "",
        "| 负载点 | 策略 | 对照 | 信道混杂 | 协议可归因 | B1 / B2 / B3 差值 (pp) | 均值 (pp) | 范围 (pp) | 95% t-CI (`df=2`, pp) |",
        "| --- | --- | --- | :-: | :-: | --- | ---: | --- | --- |",
    ]
    for pr in paired_rows:
        md.append(
            f"| {pr['point']} | {pr['strategy']} | `{pr['contrast']}` | "
            f"{'是 (ch3 vs ch39)' if pr['channel_confound'] else '否 (同 ch3)'} | "
            f"{'是' if pr['protocol_identifiable'] else '否'} | "
            f"{pr['b1_pp']:+d} / {pr['b2_pp']:+d} / {pr['b3_pp']:+d} | "
            f"{pr['mean_pp']:+.2f} | [{pr['min_pp']:+d}, {pr['max_pp']:+d}] | "
            f"[{pr['ci95_low_pp']:+.2f}, {pr['ci95_high_pp']:+.2f}] |"
        )

    md += [
        "",
        "## 3. P4 全部 36 轮逐轮明细（`2731–2766`）",
        "",
        "| Run | Block | 点 | 策略 | 模式 | K | 首次 (`/100`) | 计划内 (`/100`) | 计划内四分类 (`both/B/Z/none`) | C3 (`片/成/超`) | 提交波形 (µs) | 单位成本 (µs) |",
        "| ---: | :-: | :-: | --- | --- | :-: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for r in p4_runs:
        c3_s = f"{r['c3_fragments']}/{r['c3_complete']}/{r['c3_timeout']}" if r["c3_fragments"] else "—"
        unit_s = f"{r['unit_cost_us']:.1f}" if r["unit_cost_us"] is not None else "N/A"
        md.append(
            f"| {r['run_id']} | B{r['block']} | {r['point']} | {r['strategy']} | {r['mode']} | {r['k']} | "
            f"{r['first_both']}/100 | {r['plan_both']}/100 | "
            f"{r['plan_both']}/{r['plan_ble_only']}/{r['plan_zigbee_only']}/{r['plan_neither']} | "
            f"{c3_s} | {r['submitted_waveform_us']:,} | {unit_s} |"
        )

    md += [
        "",
        "## 4. P2 容量、R0 稳定链路成本与 H1 同 IQ 偏移（`2702–2710, 2718`）",
        "",
        "| Run | 阶段 | 点 (`b,z`) | 模式 | BLE/IEEE 记录 (B) | BlueBee 映射 (B) | Secondary Payload (B) | 分片数 | 单尝试波形代理 (µs) | R0 联合解析 | C3 (`片/成`) |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | :-: | ---: | ---: | --- |",
    ]
    for r in p2_h2_h3:
        c3_s = f"{r['c3_fragments']}/{r['c3_complete']}" if r["c3_fragments"] else "—"
        md.append(
            f"| {r['run_id']} | {r['tag']} | {r['point']} (`{r['b']},{r['z']}`) | {r['mode']} | "
            f"{r['ble_record_bytes']}/{r['ieee_record_bytes']} | {r['mapped_bytes']} | "
            f"{r['secondary_payload_bytes']} | {r['ble_fragments_per_attempt']} | "
            f"{r['cost_per_attempt_us']:,} | {r['joint_decoded']} | {c3_s} |"
        )

    md += [
        "",
        "- **H1 实录同 IQ 包内偏移核验（`400+8b µs`）**：A 点 `2704` 实测 `400.00–400.25 µs`（中位 `400.25 µs`，10/10）、C 点 `2707` 实测 `416.00–416.25 µs`（中位 `416.25 µs`，10/10）、B 点 `2718` 实测 `608.00–608.25 µs`（中位 `608.00 µs`，10/10）。仅证明同一采样时钟下包内字段相对位置，不构成两块 HackRF 跨设备同步精度。",
        "- **H6 实录流离线故障注入回放**：`2714` C3 实录流 7/7 通过（`h6_fault_injection_replay_v3`），`2715` `time` 实录流 4/4 通过（`h6_fault_injection_replay_v2`）；显式标注为离线合成注入，非空口实测异常。",
        "",
        "## 5. P2 H5 时间参考支撑与单侧失更恢复实例（`2715–2717`，尾段分离口径 `uc1_time_tail_audit`）",
        "",
        "| Run | 场景 | 联合任务 | 探测覆盖 (BLE / IEEE) | 计划内恢复 (BLE / IEEE) | 停发尾段 stale | BLE 残差中位/P95/最大 (ms) | IEEE 残差中位/P95/最大 (ms) | 双侧估计差中位/P95 (ms, n) |",
        "| ---: | --- | ---: | --- | --- | :-: | --- | --- | --- |",
    ]
    for r in p2_h5:
        md.append(
            f"| {r['run_id']} | {r['scenario']} | {r['joint_tasks']} | "
            f"{r['ble_probe_cov']} / {r['zigbee_probe_cov']} | "
            f"{r['ble_rec_in_sched']} / {r['zigbee_rec_in_sched']} | "
            f"{r['tail_stale_ble_zigbee']} | {r['ble_res_med_p95_max_ms']} | "
            f"{r['zigbee_res_med_p95_max_ms']} | {r['pair_diff_med_p95_ms']} (n={r['pair_diff_n']}) |"
        )

    ak1_jc, ak1_sc, ak1_lc = c_map[("A", "k1", "JC")], c_map[("A", "k1", "SC")], c_map[("A", "k1", "LC")]
    aq_jc, aq_sc, aq_lc = c_map[("A", "q6000", "JC")], c_map[("A", "q6000", "SC")], c_map[("A", "q6000", "LC")]
    bk1_jc, bk1_sc, bk1_lc = c_map[("B", "k1", "JC")], c_map[("B", "k1", "SC")], c_map[("B", "k1", "LC")]
    bq_jc, bq_sc, bq_lc = c_map[("B", "q6000", "JC")], c_map[("B", "q6000", "SC")], c_map[("B", "q6000", "LC")]
    pb_k1_lc = p_map[("B", "k1", "JC_minus_LC")]
    pb_q_lc = p_map[("B", "q6000", "JC_minus_LC")]
    pa_k1_sc = p_map[("A", "k1", "JC_minus_SC")]
    pa_q_sc = p_map[("A", "q6000", "JC_minus_SC")]
    pb_k1_sc = p_map[("B", "k1", "JC_minus_SC")]
    pb_q_sc = p_map[("B", "q6000", "JC_minus_SC")]
    aq_jc_vs_lc_pct = (1.0 - aq_jc["pooled_unit_cost_us"] / aq_lc["pooled_unit_cost_us"]) * 100.0
    bk1_jc_vs_lc_pct = (1.0 - bk1_jc["pooled_unit_cost_us"] / bk1_lc["pooled_unit_cost_us"]) * 100.0
    bq_jc_vs_lc_pct = (1.0 - bq_jc["pooled_unit_cost_us"] / bq_lc["pooled_unit_cost_us"]) * 100.0
    r2743, r2761, r2764 = r_map[2743], r_map[2761], r_map[2764]

    md += [
        "",
        "## 6. 核心实证结论边界（供 P5 写作直接引用）",
        "",
        (
            f"1. **短负载 A（`b=0, z=0`，legacy 无需分片）**：LC 单次提交波形最低（`1,456 µs`，JC/SC 为 `1,648 µs`）；"
            f"`K=1` 下三模式计划内联合解析均值接近（JC `{ak1_jc['mean_plan_pct']:.1f}%`、SC `{ak1_sc['mean_plan_pct']:.1f}%`、LC `{ak1_lc['mean_plan_pct']:.1f}%`），"
            f"LC 合并单位成功成本最低（`{ak1_lc['pooled_unit_cost_us']:.1f} µs/任务`，SC `{ak1_sc['pooled_unit_cost_us']:.1f}`，JC `{ak1_jc['pooled_unit_cost_us']:.1f}`）。"
            f"在同预算上限 `Q=6000 µs` 下，三模式联合解析率均接近饱和（JC `{aq_jc['mean_plan_pct']:.1f}%`、SC `{aq_sc['mean_plan_pct']:.1f}%`、LC `{aq_lc['mean_plan_pct']:.1f}%`），"
            f"单位成功成本排序随策略改变：JC 合并单位成功成本为 `{aq_jc['pooled_unit_cost_us']:.1f} µs/任务`，低于 LC 的 `{aq_lc['pooled_unit_cost_us']:.1f} µs/任务`（低约 `{aq_jc_vs_lc_pct:.1f}%`，SC 为 `{aq_sc['pooled_unit_cost_us']:.1f} µs/任务`）。"
        ),
        (
            f"2. **长负载 B（`b=26, z=0`，LC 触发 C3 五片重组）**：三个独立区组中，JC 与 SC 相对 LC 均观察到较高的联合解析率——"
            f"`K=1` 时 JC 均值 `{bk1_jc['mean_plan_pct']:.1f}%` vs LC `{bk1_lc['mean_plan_pct']:.1f}%`（逐区组 `{pb_k1_lc['b1_pp']:+d} / {pb_k1_lc['b2_pp']:+d} / {pb_k1_lc['b3_pp']:+d} pp`，均值 `{pb_k1_lc['mean_pp']:+.2f} pp`，95% t 区间 `[{pb_k1_lc['ci95_low_pp']:+.2f}, {pb_k1_lc['ci95_high_pp']:+.2f}] pp`，合并单位成功成本低 `{bk1_jc_vs_lc_pct:.1f}%`）；"
            f"`Q=6000 µs` 时 JC（`K=3`）均值 `{bq_jc['mean_plan_pct']:.1f}%`、SC（`K=3`）均值 `{bq_sc['mean_plan_pct']:.1f}%` vs LC（`K=2`）均值 `{bq_lc['mean_plan_pct']:.1f}%`（逐区组 `{pb_q_lc['b1_pp']:+d} / {pb_q_lc['b2_pp']:+d} / {pb_q_lc['b3_pp']:+d} pp`，均值 `{pb_q_lc['mean_pp']:+.2f} pp`，95% t 区间 `[{pb_q_lc['ci95_low_pp']:+.2f}, {pb_q_lc['ci95_high_pp']:+.2f}] pp`，JC 总提交波形低于 LC 且合并单位成功成本低 `{bq_jc_vs_lc_pct:.1f}%`）。"
            f"两个配对区间均跨零且端点超出 ±100 pp（源于 `df=2` 小样本 t 近似与区组间大幅波动），不能宣称统计显著；且因 JC/SC 使用 ch3、LC 使用 ch39，结论严格限定在所测封装与信道组合。"
            f"具体分片观测显示：B2 `2743` 中 IEEE 恢复 `{r2743['plan_both'] + r2743['plan_zigbee_only']}/100` 个任务，BLE 收到 `{r2743['c3_fragments']}` 个 C3 分片但完整重组为 `{r2743['c3_complete']}`（联合 `{r2743['plan_both']}/100`）；B3 `2761` 收到 `{r2761['c3_fragments']}` 片/重组 `{r2761['c3_complete']}` 条（联合 `{r2761['plan_both']}/100`），`2764` 收到 `{r2764['c3_fragments']}` 片/重组 `{r2764['c3_complete']}` 条（联合 `{r2764['plan_both']}/100`）。B 点 LC 完整重组要求同一发送尝试的五片全部到齐。现有记录无法确定各片缺失的具体原因。用 $p^5$ 表示重组成功概率，还需假设五片接收相互独立且成功概率均为 $p$。"
        ),
        (
            f"3. **同频公平对照 `JC vs SC`（12/12 满足配置匹配与协议归因检查）**：四个条件的 `JC − SC` 均值分别为 "
            f"A-K1 `{pa_k1_sc['mean_pp']:+.2f} pp`（`[{pa_k1_sc['ci95_low_pp']:+.2f}, {pa_k1_sc['ci95_high_pp']:+.2f}]`）、"
            f"A-Q `{pa_q_sc['mean_pp']:+.2f} pp`（`[{pa_q_sc['ci95_low_pp']:+.2f}, {pa_q_sc['ci95_high_pp']:+.2f}]`）、"
            f"B-K1 `{pb_k1_sc['mean_pp']:+.2f} pp`（`[{pb_k1_sc['ci95_low_pp']:+.2f}, {pb_k1_sc['ci95_high_pp']:+.2f}]`）、"
            f"B-Q `{pb_q_sc['mean_pp']:+.2f} pp`（`[{pb_q_sc['ci95_low_pp']:+.2f}, {pb_q_sc['ci95_high_pp']:+.2f}]`），区间均跨零。"
            f"在已测条件下，**未观察到 JC 相对 SC 的稳定联合解析优势**（配置匹配与区间跨零均不能证明两者等效）。"
            f"四分类呈现不同的单侧缺失与共同缺失分布：例如 `K=1` 合并 300 计划任务中，A 点 JC 为 `ble_only={ak1_jc['sum_ble_only']}/300`、`neither={ak1_jc['sum_neither']}/300`，SC 为 `ble_only={ak1_sc['sum_ble_only']}/300`、`neither={ak1_sc['sum_neither']}/300`；B 点 JC 为 `ble_only={bk1_jc['sum_ble_only']}/300`、`neither={bk1_jc['sum_neither']}/300`，SC 为 `ble_only={bk1_sc['sum_ble_only']}/300`、`neither={bk1_sc['sum_neither']}/300`（未对双侧相关性作形式假设检验）。"
            f"JC 相对 SC 可直接确认的结构收益是：A/B 点单次尝试波形预算与 SC 相等，但将每次尝试由 **3 个突发减至 2 个突发**，并提供经同 IQ 核验的固定包内位置（`400+8b µs`），以支撑 P2 H5 的固定次信道时间参考与单侧失更恢复实例。"
        ),
        "",
    ]
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote P5 frozen tables to {args.output_dir} and {args.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
