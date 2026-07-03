# 项目概述

## 总目标

本项目以论文 BlueBee 为基础，论文原文位于 `python/ctc_sim/bluebee/`。目标是利用 BLE 的 extended advertising 双包调度外壳，把 BlueBee 负载放入 secondary 包，在尽可能小的系统改动下实现 BLE 到 ZigBee 的跨协议通信，并完成后续性能测量。

## 当前目标

不追求完美实现BLE拓展广播功能，而是借助辅助包的更大可携带数据量，将bluebee生成的完整zigbee帧装入辅助包中，目标是同时实现手机显示BLE完整包，zigbee_rx.py脚本能检测到完整zigbee帧。

## 阶段结论

- 旧阶段的“手机显示完整 BLE extended advertising secondary 数据”路线已暂停，不再作为当前主线目标。
- 当前主线改为利用 BLE exadv 的双包调度外壳，在 `ch39 / 2480 MHz` 上发 primary，并在同频发 BlueBee secondary。
- 裸机 `ble_exadv_tx?` 现阶段只保留 `aux_delay_us interval_us` 两个参数，默认推荐命令形态为 `ble_exadv_tx? 600 10000`。
- 裸机调度以生成头文件中的 primary/secondary IQ、频点和 AuxOffset 元数据为准；不再保留 lead sweep、secondary test、timing debug 路径。

## 验收标准

- 手机 nRF Connect 能看到 `ch39` 上的 primary 广播
- HackRF 或其他接收链路能够确认 secondary/BlueBee 波形确实在 `2480 MHz`
- `python/ctc_sim/std_zigbee/zigbee_rx.py` 能检测到完整 ZigBee frame
- 优先接受标准：
  - 能输出完整 frame bytes 供比对
  - 若同时 FCS OK，则视为更强证据

## 相关路径

- `python/ctc_sim/bluebee/`
  - `bluebee_zigbee_frame_iq_30_72M.py`：生成纯bluebee构造的完整zigbee帧
  - `bluebee_phase_analyze.py`、`bluebee_phase_zigbee_rx.py`：BlueBee/ZigBee 分析辅助工具
- `python/ctc_sim/std_zigbee/`
  - `bluebee_rx.py`：当前主接收验证脚本，用于解调bluebee构造的zigbee帧
  - `zigbee_rx.py`：标准zigbee解调脚本
- `python/std_ble/`
  - `generate_ble_exadv_iq_30_72M.py`：将bluebee负载嵌入到BLE广播包中，为了方便调试，使用参数--timing-debug-same-channel --channel 39 --append-bluebee-zigbee --aux-offset-us 600 --post-pad-us 10
- `hdl/projects/antsdre310/antsdre310.sdk/app/src/`
  - 裸机发射控制代码

## 注意事项

1. 工作区裸机程序代码未被 git 追踪。
2. 裸机代码修改后，只检查代码逻辑和语法，由用户自行编译和上板。
3. 以实际规范为准，历史注释和旧实验记录可能已过时。
4. `python/ctc_sim/stc_zigbee` 是笔误，实际路径是 `python/ctc_sim/std_zigbee`。
5. `doc/BLE_Core_v5.1.pdf` 可作为 BLE 规范参考，但当前阶段不再以“规范手机跟随 AuxPtr”作为主要成功判据。
