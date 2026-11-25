#!/usr/bin/env python3
"""Generate Fig. 1 (paper/figures/fig-uc1-layout-bursts.pdf):
(a) UC1 co-packaged AUX_ADV_IND byte layout, BlueBee 4x[(26+z)+8]=(136+4z) B
    mapping expansion, and deterministic 400 + 8b us offset.
(b) Single-attempt burst structure across JC, SC, and LC at Point B (52/26 B),
    with a spanning bracket identifying the single 1,720 us JC secondary burst.

Provenance:
  - doc/reference/unified_compact_protocol_proposal.md (§2, §4, §5)
  - python/control_match/uc1_config.py (uc1_burst_table, uc1_cost)
"""
from __future__ import annotations

from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

mpl.rcParams.update({
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Tinos", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8.0,
    "axes.linewidth": 0.7,
})

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PDF = REPO_ROOT / "paper" / "figures" / "fig-uc1-layout-bursts.pdf"


def draw_box(ax, x, y, w, h, fc, ec="#2B2B2B", lw=0.72, label="", sublabel="",
             fontsize=8.1, text_color="#111111", radius=0.0):
    if radius > 0:
        patch = FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3
        )
    else:
        patch = Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3)
    ax.add_patch(patch)
    if label and sublabel:
        ax.text(x + w / 2, y + h * 0.65, label, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=text_color, zorder=4)
        ax.text(x + w / 2, y + h * 0.27, sublabel, ha="center", va="center",
                fontsize=fontsize, color=text_color, zorder=4)
    elif label:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color=text_color, zorder=4)


def draw_bracket(ax, x0, x1, y, dy, text, va="bottom", color="#222222", fontsize=8.1, bold=False):
    """Draw a crisp horizontal dimension bracket."""
    ax.plot([x0, x0, x1, x1], [y - dy, y, y, y - dy], color=color, lw=0.72, zorder=5)
    ty = y + (0.04 if va == "bottom" else -0.05)
    ax.text((x0 + x1) / 2, ty, text, ha="center", va=va, fontsize=fontsize,
            fontweight="bold" if bold else "normal", color=color, zorder=5)


def main() -> None:
    fig = plt.figure(figsize=(3.45, 3.55), dpi=300)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.05, 1.32], hspace=0.22)

    # Colorblind-safe Okabe-Ito inspired tones
    c_phy = "#E5E7EB"       # light gray: BLE PHY/CRC framing
    c_hdr = "#D6E4F0"       # pale blue: Ext Hdr + AD
    c_ble = "#7EB0D5"       # medium steel blue: BLE UC1 record
    c_ieee = "#F4A261"      # warm orange: BlueBee-mapped IEEE 802.15.4
    c_prim = "#D1D5DB"      # gray: primary ADV_EXT_IND
    c_c3 = "#CC79A7"        # muted magenta/purple: C3 fragments

    # ------------------------------------------------------------------
    # Panel (a): JC Secondary AUX_ADV_IND Byte Layout
    # ------------------------------------------------------------------
    ax1 = fig.add_subplot(gs[0])
    ax1.set_xlim(0.0, 10.0)
    ax1.set_ylim(-0.84, 1.38)
    ax1.axis("off")

    ax1.text(0.05, 1.26, "(a) JC secondary layout (LE 1M, channel 3)",
             ha="left", va="center", fontsize=8.6, fontweight="bold", color="#111111")

    segments = [
        (0.05, 1.25, c_phy,  "Pre/AA",       "5 B"),
        (1.30, 0.80, c_phy,  "Hdr",          "2 B"),
        (2.10, 1.50, c_hdr,  "Ext.+AD",      "17 B"),
        (3.60, 2.35, c_ble,  "BLE UC1", "26 + b B"),
        (5.95, 3.15, c_ieee, "Mapped IEEE", "136 + 4z B"),
        (9.10, 0.85, c_phy,  "CRC",          "3 B"),
    ]
    y0, bh = 0.08, 0.56
    for x, w, fc, lbl, sub in segments:
        draw_box(ax1, x, y0, w, bh, fc, label=lbl, sublabel=sub, fontsize=8.1)

    draw_bracket(
        ax1, 2.10, 9.10, y0 + bh + 0.15, 0.07,
        r"Payload: $179 + b + 4z$ B (tested: 179, 205 B)",
        va="bottom", fontsize=8.1
    )

    arrow_y = -0.17
    ax1.annotate(
        "", xy=(5.95, arrow_y), xytext=(0.05, arrow_y),
        arrowprops=dict(arrowstyle="<->", color="#9B2C2C", lw=0.85, shrinkA=0, shrinkB=0),
        zorder=5
    )
    ax1.plot([0.05, 0.05], [y0, arrow_y - 0.04], color="#9B2C2C", lw=0.6, ls=":", zorder=4)
    ax1.plot([5.95, 5.95], [y0, arrow_y - 0.04], color="#9B2C2C", lw=0.6, ls=":", zorder=4)
    ax1.text(
        2.95, arrow_y - 0.08,
        r"Marker offset: (400 + 8b) µs",
        ha="center", va="top", fontsize=8.1, fontweight="bold", color="#9B2C2C"
    )
    ax1.text(
        0.05, arrow_y - 0.55,
        "Median (µs): A 400.25, B 608.00, C 416.25 (n=10 each)",
        ha="left", va="top", fontsize=8.1, color="#444444"
    )

    # Explicit BlueBee expansion formula under orange block
    ax1.text(
        7.95, arrow_y - 0.03,
        "4 × [(26 + z) + 8] B",
        ha="center", va="top", fontsize=8.1, color="#7A3E00"
    )

    # ------------------------------------------------------------------
    # Panel (b): Single-Attempt Burst Structure (Point B: b=26, z=0)
    # ------------------------------------------------------------------
    ax2 = fig.add_subplot(gs[1])
    ax2.set_xlim(0.0, 10.0)
    ax2.set_ylim(-0.38, 3.68)
    ax2.axis("off")

    ax2.text(0.05, 3.55, "(b) Bursts per attempt at point B (52/26 B)",
             ha="left", va="center", fontsize=8.6, fontweight="bold", color="#111111")

    row_h = 0.56
    x_label = 0.05
    x_start = 1.72

    # Row 1: JC (2 bursts, 1,856 us) with spanning bracket over blue+orange secondary
    y_jc = 2.26
    ax2.text(x_label, y_jc + row_h / 2, "JC\n(2 bursts)", ha="left", va="center",
             fontsize=8.1, fontweight="bold", color="#005B8F")
    draw_box(ax2, x_start, y_jc, 1.05, row_h, c_prim, label="Pri.", sublabel="136 µs", fontsize=8.1, radius=0.05)
    ax2.annotate("", xy=(x_start + 1.38, y_jc + row_h / 2), xytext=(x_start + 1.07, y_jc + row_h / 2),
                 arrowprops=dict(arrowstyle="->", color="#555555", lw=0.72))
    sec_x = x_start + 1.40
    sec_w_ble = 1.95
    sec_w_ieee = 3.15
    draw_box(ax2, sec_x, y_jc, sec_w_ble, row_h, c_ble, label="BLE 52 B", sublabel="ch3", fontsize=8.1)
    draw_box(ax2, sec_x + sec_w_ble, y_jc, sec_w_ieee, row_h, c_ieee, label="IEEE 26 B", sublabel="ch12", fontsize=8.1)
    draw_bracket(
        ax2, sec_x, sec_x + sec_w_ble + sec_w_ieee, y_jc + row_h + 0.16, 0.09,
        "One secondary: 1,720 µs at 2410 MHz",
        va="bottom", color="#005B8F", fontsize=8.1, bold=True
    )
    ax2.text(9.95, y_jc + row_h / 2, "1,856 µs", ha="right", va="center",
             fontsize=8.1, fontweight="bold", color="#005B8F")

    # Row 2: SC (3 bursts, 1,856 us)
    y_sc = 1.30
    ax2.text(x_label, y_sc + row_h / 2, "SC\n(3 bursts)", ha="left", va="center",
             fontsize=8.1, fontweight="bold", color="#007A59")
    draw_box(ax2, x_start, y_sc, 1.05, row_h, c_prim, label="Pri.", sublabel="136 µs", fontsize=8.1, radius=0.05)
    ax2.annotate("", xy=(x_start + 1.38, y_sc + row_h / 2), xytext=(x_start + 1.07, y_sc + row_h / 2),
                 arrowprops=dict(arrowstyle="->", color="#555555", lw=0.72))
    draw_box(ax2, x_start + 1.40, y_sc, 1.95, row_h, c_ble, label="BLE Sec.", sublabel="632 µs", fontsize=8.1, radius=0.05)
    ax2.annotate("", xy=(x_start + 3.68, y_sc + row_h / 2), xytext=(x_start + 3.37, y_sc + row_h / 2),
                 arrowprops=dict(arrowstyle="->", color="#555555", lw=0.72))
    draw_box(ax2, x_start + 3.70, y_sc, 2.80, row_h, c_ieee, label="IEEE Burst", sublabel="1,088 µs", fontsize=8.1, radius=0.05)
    ax2.text(9.95, y_sc + row_h / 2, "1,856 µs", ha="right", va="center",
             fontsize=8.1, fontweight="bold", color="#007A59")

    # Row 3: LC (6 bursts, 2,904 us)
    y_lc = 0.34
    ax2.text(x_label, y_lc + row_h / 2, "LC (C3)\n(6 bursts)", ha="left", va="center",
             fontsize=8.1, fontweight="bold", color="#A33B00")
    fx = x_start
    fw = 0.70
    gap = 0.06
    for i in range(5):
        draw_box(ax2, fx, y_lc, fw, row_h, c_c3, label=f"f{i}",
                 fontsize=8.1, text_color="#FFFFFF", radius=0.04)
        fx += fw + gap
    ax2.annotate("", xy=(fx + 0.28, y_lc + row_h / 2), xytext=(fx - 0.03, y_lc + row_h / 2),
                 arrowprops=dict(arrowstyle="->", color="#555555", lw=0.72))
    draw_box(ax2, fx + 0.30, y_lc, 2.40, row_h, c_ieee, label="IEEE Burst", sublabel="1,088 µs", fontsize=8.1, radius=0.05)
    ax2.text(9.95, y_lc + row_h / 2, "2,904 µs", ha="right", va="center",
             fontsize=8.1, fontweight="bold", color="#A33B00")

    ax2.text(
        0.05, -0.06,
        "LC: five fragments on ch39, 1,816 µs in total.\n"
        "At point A, LC uses two bursts (1,456 µs).",
        ha="left", va="top", fontsize=8.1, color="#444444"
    )

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.96, bottom=0.05)
    fig.savefig(OUT_PDF, format="pdf")
    plt.close(fig)
    print(f"Wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
