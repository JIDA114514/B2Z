# figures/ — 5 页短论文矢量图（已生成并接入正文）

色板采用色盲友好配色（Okabe-Ito），Type-42 字体嵌入 PDF，全部由 `paper/scripts/` 下的可复现脚本直接生成。

## 已生成矢量图清单

1. **`fig-uc1-layout-bursts.pdf`**（单栏宽 `3.50 in`，脚本 `paper/scripts/plot_fig1_layout.py`，接入 `sections/03-protocol-design.tex`）
   - **(a) `JC` 单 `AUX_ADV_IND` 字节布局**：`5 B` Pre+AA + `2 B` PDU Hdr + `17 B` Ext.+AD + `(26+b) B` BLE UC1 记录 + `(136+4z) B` BlueBee 映射区 + `3 B` CRC，标注确定性偏移 `400 + 8b µs` 及 H1 同 IQ 三点实测中位数（A `400.25`、B `608.00`、C `416.25 µs`）。
   - **(b) B 点（`52/26 B`）单次逻辑尝试突发对比**：`JC`（2 突发，`1,856 µs`）vs `SC`（3 突发，`1,856 µs`）vs `LC (C3)`（6 突发，`2,904 µs`），底部注明 A 点 `F=1` 直接承载边界。

2. **`fig-p4-tradeoff.pdf`**（双栏宽 `7.16 in`，脚本 `paper/scripts/plot_fig2_p4_tradeoff.py`，直接读取 `python/experiments/p5_freeze_20261124/{p5_p4_cells.csv, p5_p4_runs.csv}`，接入 `sections/05-evaluation.tex`）
   - **(a) 四分类结果分布与 B1/B2/B3 逐区组联合解析散点**：展示 A/B 两点在 `K=1` 和 `Q=6000 µs` 下三模式的四分类堆叠（`both / ble_only / zigbee_only / neither`）与全部区组个体散点，并标注 B2 `2743` 五片 C3 零重组实例（`210` 片 / `0` 重组 / `98` 仅 IEEE）。
   - **(b) 单位联合成功任务提交波形代理成本（对数坐标）**：展示 A 点 `K=1`（`LC*` 最低 `2.14k`）到 `Q=6000 µs`（`JC` 比 `LC*` 低 `14.8%`）的排序反转，以及 B 点分片成本放大与 `2743` 轮 `N/A` 标注。

## 重新生成命令

```bash
python3 paper/scripts/plot_fig1_layout.py
python3 paper/scripts/plot_fig2_p4_tradeoff.py
```
