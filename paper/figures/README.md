# figures/ — 5 页短论文配图规划（共 2 张核心矢量图）

只放矢量图（PDF 优先）。色板采用色盲友好配色（如 IBM Color Blind Safe / Okabe-Ito），图内最小字号不小于 7–8 pt，线宽不小于 0.8 pt。

## 规划图清单

1. **`fig-uc1-layout-bursts.pdf`**（单栏宽 `3.5 in`，置于 `sections/03-protocol-design.tex`）
   - **(a) `JC` 单 `AUX_ADV_IND` 字节布局**：17 B BLE 扩展头与 AD 头 + `(26+b)` B BLE UC1 记录 + `(136+4z)` B BlueBee 映射区（内含 `(26+z)` B IEEE UC1 记录），标注从 BLE 前导码到映射参考点的确定性偏移 `400 + 8b µs`。
   - **(b) 单次逻辑尝试突发对比**：`JC`（2 突发：primary + ch3/ch12 共包 secondary）vs `SC`（3 突发：primary + ch3 BLE secondary + ch12 独立 IEEE）vs `LC`（`F+1` 突发：ch39 直接承载或 `F=3..5` 片 C3 分片 + ch12 独立 IEEE）。

2. **`fig-p4-tradeoff.pdf`**（双栏宽 `7.16 in`，置于 `sections/05-evaluation.tex`，数据源 `python/experiments/p5_freeze_20261124/`）
   - **(a) 计划尝试内联合解析率与四分类分解**：展示负载点 A `(0,0)` 与 B `(26,0)` 在 `K=1` 和 `Q=6000 µs` 下三模式的合并均值及 **B1/B2/B3 三个独立区组散点**（遵循小样本 `n=3` 必画个体样本点原则），辅以四分类堆叠（`both / ble_only / zigbee_only / neither`）并标注 `2743` 五片 C3 重组悬崖实例。
   - **(b) 单位联合成功任务提交波形代理成本（`µs/task`）**：展示 A 点从 `K=1`（`LC` 最低 `2,141.2`）到 `Q=6000 µs`（`SC 4,960.5 < JC 5,044.9 < LC 5,922.7`）的成本排序反转，以及 B 点分片开销与损失叠加后的显著成本差距。
