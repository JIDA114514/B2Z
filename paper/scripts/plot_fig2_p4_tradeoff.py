#!/usr/bin/env python3
"""Generate Fig. 2 (paper/figures/fig-p4-tradeoff.pdf):
Two-panel confirmatory trade-off figure directly from frozen P5 CSVs:
  (a) Four-way planned-attempt outcome decomposition (/300) + per-block joint
      resolution markers (B1, B2, B3) + run 2743 zero-reassembly callout.
  (b) Submitted waveform proxy cost per jointly resolved task (log scale) with
      per-block run markers, Point A crossover, and Point B fragmentation gap.

Provenance:
  - python/experiments/p5_freeze_20261124/p5_p4_cells.csv
  - python/experiments/p5_freeze_20261124/p5_p4_runs.csv
"""
from __future__ import annotations

import csv
from pathlib import Path
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

mpl.rcParams.update({
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Tinos", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8.0,
    "axes.linewidth": 0.75,
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
})

REPO_ROOT = Path(__file__).resolve().parents[2]
CELLS_CSV = REPO_ROOT / "python" / "experiments" / "p5_freeze_20261124" / "p5_p4_cells.csv"
RUNS_CSV = REPO_ROOT / "python" / "experiments" / "p5_freeze_20261124" / "p5_p4_runs.csv"
OUT_PDF = REPO_ROOT / "paper" / "figures" / "fig-p4-tradeoff.pdf"

CONDS = [
    ("A", "k1",    "A\nK=1"),
    ("A", "q6000", "A\nQ=6 ms"),
    ("B", "k1",    "B\nK=1"),
    ("B", "q6000", "B\nQ=6 ms"),
]
MODES = ["JC", "SC", "LC"]


def load_data():
    cells = {}
    with CELLS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cells[(row["point"], row["strategy"], row["mode"])] = row
    runs = {}
    with RUNS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["point"], row["strategy"], row["mode"])
            runs.setdefault(key, []).append(row)
    for k in runs:
        runs[k].sort(key=lambda r: int(r["block"]))
    return cells, runs


def main() -> None:
    cells, runs = load_data()

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(7.1, 3.1), dpi=300,
        gridspec_kw={"width_ratios": [1.16, 1.00], "wspace": 0.24}
    )

    x_groups = np.arange(len(CONDS))
    bar_w = 0.255
    offsets = [-bar_w, 0.0, bar_w]

    # ------------------------------------------------------------------
    # Panel (a): Stacked 4-way outcomes + B1/B2/B3 block joint markers
    # ------------------------------------------------------------------
    c_both = "#0072B2"    # Okabe-Ito blue
    c_ble  = "#56B4E9"    # sky blue
    c_ieee = "#E69F00"    # orange
    c_none = "#555555"    # dark gray
    block_markers = {1: "o", 2: "s", 3: "^"}
    block_jitters = {1: -0.055, 2: 0.0, 3: 0.055}

    for gi, (pt, st, _) in enumerate(CONDS):
        for mi, mode in enumerate(MODES):
            row = cells[(pt, st, mode)]
            x = x_groups[gi] + offsets[mi]
            den = float(row["total_plan_den"])
            p_both = float(row["sum_both"]) / den * 100.0
            p_ble  = float(row["sum_ble_only"]) / den * 100.0
            p_ieee = float(row["sum_zigbee_only"]) / den * 100.0
            p_none = float(row["sum_neither"]) / den * 100.0

            ax1.bar(x, p_both, width=bar_w * 0.90, color=c_both, edgecolor="white", lw=0.4, zorder=2)
            ax1.bar(x, p_ble,  width=bar_w * 0.90, bottom=p_both, color=c_ble, edgecolor="white", lw=0.4, zorder=2)
            ax1.bar(x, p_ieee, width=bar_w * 0.90, bottom=p_both + p_ble, color=c_ieee, edgecolor="white", lw=0.4, zorder=2)
            ax1.bar(x, p_none, width=bar_w * 0.90, bottom=p_both + p_ble + p_ieee, color=c_none, edgecolor="white", lw=0.4, zorder=2)

            mlbl = r"LC$^{\mathrm{a}}$" if mode == "LC" else mode
            ax1.text(x, -3.5, mlbl, ha="center", va="top", fontsize=8.1, color="#222222")

            for b_idx, col in [(1, "b1_plan"), (2, "b2_plan"), (3, "b3_plan")]:
                val = float(row[col])
                ax1.scatter(
                    x + block_jitters[b_idx], val,
                    marker=block_markers[b_idx], s=17,
                    facecolor="white", edgecolor="#111111", linewidth=0.72, zorder=5
                )

    # Annotate Run 2743 zero-reassembly cliff (B, q6000, LC, B2 = 0%)
    x_2743 = x_groups[3] + offsets[2]
    ax1.annotate(
        "Run 2743: 0/100 joint\n210 fragments, 0 complete",
        xy=(x_2743, 1.5), xytext=(x_2743 - 1.15, 24.5),
        ha="center", va="center", fontsize=8.1, color="#7F1D1D",
        bbox=dict(boxstyle="round,pad=0.22", fc="#FEF2F2", ec="#B91C1C", lw=0.7, alpha=0.96),
        arrowprops=dict(arrowstyle="->", color="#B91C1C", lw=0.85, connectionstyle="arc3,rad=0.18"),
        zorder=6
    )

    ax1.set_ylim(0, 114)
    ax1.set_yticks([0, 20, 40, 60, 80, 100])
    ax1.set_xlim(-0.52, 3.52)
    ax1.set_xticks(x_groups)
    ax1.set_xticklabels([c[2] for c in CONDS], fontsize=8.1)
    ax1.tick_params(axis="x", pad=11, length=0)
    ax1.set_ylabel("Planned Tasks (%)", fontsize=8.1)
    ax1.set_title("(a) Task outcomes and block joint resolution", fontsize=8.1, fontweight="bold", pad=32)
    ax1.yaxis.grid(True, linestyle=":", alpha=0.5, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    leg_a = [
        Patch(fc=c_both, ec="white", label="Both (joint)"),
        Patch(fc=c_ble,  ec="white", label="BLE-only"),
        Patch(fc=c_ieee, ec="white", label="IEEE-only"),
        Patch(fc=c_none, ec="white", label="Neither"),
        Line2D([0], [0], marker="o", color="none", mfc="white", mec="#111111", ms=4.0, label="B1"),
        Line2D([0], [0], marker="s", color="none", mfc="white", mec="#111111", ms=3.8, label="B2"),
        Line2D([0], [0], marker="^", color="none", mfc="white", mec="#111111", ms=4.2, label="B3"),
    ]
    ax1.legend(
        handles=leg_a, loc="upper center", bbox_to_anchor=(0.50, 1.21),
        ncol=4, frameon=False, fontsize=8.1, handlelength=1.0,
        columnspacing=0.55, handletextpad=0.35
    )

    # ------------------------------------------------------------------
    # Panel (b): Pooled & Per-Block Unit Submitted Waveform Proxy Cost
    # ------------------------------------------------------------------
    mode_colors = {"JC": "#0072B2", "SC": "#009E73", "LC": "#D55E00"}

    for gi, (pt, st, _) in enumerate(CONDS):
        for mi, mode in enumerate(MODES):
            row = cells[(pt, st, mode)]
            x = x_groups[gi] + offsets[mi]
            pooled_u = float(row["pooled_unit_cost_us"])

            ax2.bar(
                x, pooled_u, width=bar_w * 0.88,
                color=mode_colors[mode], edgecolor="#222222", lw=0.5, alpha=0.90, zorder=2
            )

            for r in runs[(pt, st, mode)]:
                b_idx = int(r["block"])
                u_str = r["unit_cost_us"].strip()
                if u_str:
                    ax2.scatter(
                        x + block_jitters[b_idx], float(u_str),
                        marker=block_markers[b_idx], s=15,
                        facecolor="white", edgecolor="#111111", linewidth=0.7, zorder=5
                    )

            # Clean non-overlapping pooled cost annotations on key LC* bars
            if (pt, st) == ("A", "k1") and mode == "LC":
                ax2.text(x, 3300, "2.14k", ha="center", va="bottom",
                         fontsize=8.1, fontweight="bold", color="#9A3412", zorder=6)
            elif (pt, st) == ("A", "q6000") and mode == "LC":
                ax2.text(x, 6900, "5.92k", ha="center", va="bottom",
                         fontsize=8.1, fontweight="bold", color="#9A3412", zorder=6)
            elif (pt, st) == ("B", "k1") and mode == "LC":
                ax2.text(x, 11400, "10.1k", ha="center", va="bottom",
                         fontsize=8.1, fontweight="bold", color="#9A3412", zorder=6)
            elif (pt, st) == ("B", "q6000") and mode == "LC":
                ax2.text(x, 21000, "18.7k", ha="center", va="bottom",
                         fontsize=8.1, fontweight="bold", color="#9A3412", zorder=6)

    # Annotate Point A strategy-dependent crossover and Run 2743 N/A
    ax2.annotate(
        "Point A, Q=6 ms:\nJC costs 14.8% less than LC",
        xy=(x_groups[1] + offsets[0], 5450),
        xytext=(0.56, 26500),
        ha="center", va="center", fontsize=8.1, color="#1E3A5F",
        bbox=dict(boxstyle="round,pad=0.22", fc="#EFF6FF", ec="#2563EB", lw=0.65),
        arrowprops=dict(arrowstyle="->", color="#2563EB", lw=0.8, connectionstyle="arc3,rad=-0.12"),
        zorder=6
    )

    ax2.text(
        x_groups[3] + offsets[2], 45500,
        "B2: N/A\n(0/100)",
        ha="center", va="bottom", fontsize=8.1, fontweight="bold", color="#9B2C2C", zorder=6
    )

    ax2.set_yscale("log")
    ax2.set_ylim(1200, 82000)
    ax2.set_xlim(-0.52, 3.52)
    ax2.set_xticks(x_groups)
    ax2.set_xticklabels([c[2] for c in CONDS], fontsize=8.1)
    ax2.set_ylabel("Waveform cost (µs per joint task)", fontsize=8.1)
    ax2.set_title("(b) Unit waveform cost (log scale)", fontsize=8.1, fontweight="bold", pad=32)
    ax2.yaxis.grid(True, which="major", linestyle=":", alpha=0.55, zorder=0)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    leg_b = [
        Patch(fc=mode_colors["JC"], ec="#222222", lw=0.5, label="JC (ch3)"),
        Patch(fc=mode_colors["SC"], ec="#222222", lw=0.5, label="SC (ch3)"),
        Patch(fc=mode_colors["LC"], ec="#222222", lw=0.5, label=r"LC$^{\mathrm{a}}$ (ch39)"),
    ]
    ax2.legend(
        handles=leg_b, loc="upper center", bbox_to_anchor=(0.50, 1.11),
        ncol=3, frameon=False, fontsize=8.1, handlelength=1.05, columnspacing=0.85
    )

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.072, right=0.985, top=0.76, bottom=0.17)
    fig.savefig(OUT_PDF, format="pdf")
    plt.close(fig)
    print(f"Wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
