# 项目概述

## 总目标

本项目以论文 BlueBee 为基础，论文原文位于 `python/ctc_sim/bluebee/`。目标是利用 BLE 的 extended advertising 双包调度外壳，把 BlueBee 负载放入 secondary 包，在尽可能小的系统改动下实现 BLE 到 ZigBee 的跨协议通信，并完成后续性能测量。

## 当前目标

基于bluebee实现BLE和ZigBee异构网络的性能优化。

## 相关路径

- `python/ctc_sim/bluebee/`
  - `generate_bluebee_iq_30_72M.py`：当前主生成脚本
  - `bluebee_phase_analyze.py`、`bluebee_phase_zigbee_rx.py`：BlueBee/ZigBee 分析辅助工具
- `python/ctc_sim/std_zigbee/`
  - `zigbee_rx.py`：当前主接收验证脚本
- `python/std_ble/`
  - `ble_exadv_hackrf_sniffer.py`：仍可用于观察 primary/secondary 存在性
  - `generate_ble_exadv_iq_30_72M.py`：保留旧 BLE exadv 生成逻辑，但不再是当前主线
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/`
  - 裸机发射控制代码

## 注意事项

1. 工作区裸机程序代码未被 git 追踪。
2. 裸机代码修改后，只检查代码逻辑和语法，由用户自行编译和上板。
3. 以实际规范为准，历史注释和旧实验记录可能已过时。
4. `python/ctc_sim/stc_zigbee` 是笔误，实际路径是 `python/ctc_sim/std_zigbee`。
5. `doc/BLE_Core_v5.1.pdf` 可作为 BLE 规范参考，但当前阶段不再以”规范手机跟随 AuxPtr”作为主要成功判据。

## 手机 BLE 检测的负载上限

经实验测定，手机（nRF Connect）能检测到 BLE extended advertising 的 secondary 包存在一个**严格的 PDU payload 阈值**：

| ZigBee payload | BlueBee bytes | PDU payload | 手机检测 |
|------|------|------|------|
| 46 B | 216 | ~238 | ✅ 正常 |
| 47 B | 220 | ~242 | ❌ 检测不到 |
| 48 B | 224 | ~246 | ❌ 检测不到 |
| 49 B | 228 | ~250 | ❌ 检测不到 |

- **阈值**：PDU payload **~238 字节**（216 BlueBee 字节 / 46 字节 ZigBee payload）是手机能检测到的上限。
- **失败原因**：超过此阈值时，手机蓝牙协议栈静默丢弃该包，不显示任何广播。该限制并非 BLE 规范本身的 255 字节硬上限，而是手机厂商实现的内部 buffer 限制。
- **默认配置**：`generate_ble_exadv_iq_30_72M.py` 的 `DEFAULT_ZIGBEE_PAYLOAD` 已设置为 46 字节最大值（`0x00..0x2D`），`--include-flags` + `--name S` 已启用。
- **理论吞吐**：46 字节 / 100ms = **460 B/s**（3680 bps）。
- **接收吞吐瓶颈**：`bluebee_rx.py` 的 `PHASE_DETECT_CONFIRMATIONS` 原为 2，但 `PHASE_MAX_CHIPS=60000`（30ms buffer）远小于 `PHASE_SCAN_PERIOD=50ms` 间隔内产生的 100K 新 chips，导致单个数据包永远无法被连续两次扫描看到，confirmations=2 几乎丢弃了所有命中。
- **修复（2024-06-29）**：`PHASE_DETECT_CONFIRMATIONS=1`，`PHASE_SCAN_PERIOD=0.02`（20ms），`PHASE_MAX_CHIPS=120000`（60ms buffer），保证 ~100% 数据覆盖。
