# Run 10265 / 10266 固定数据集诊断

这些脚本保存本轮离线分析方法，不是实时接收入口，不会修改板端或接收器默认配置。从项目根目录运行，依赖现有完整 IQ、逐包记录及相应 `.payload_validation.json`。输入前缀固定为 `rx_20261026_161955_853914` 和 `rx_20261026_162114_151247`；150 个计划时隙是待板端日志确认的分析假设。

- `probe_saved_runs.py`：在 150 个预测时隙各取 12 ms，比较内部 2/4 Msps、700/850 kHz 通道滤波、显式 60 kHz 数字频移、未知数据两电平阈值估计。所有解码接受仍需 BLE CRC；不是用已知测试 payload 恢复数据。片段初始化与抽取起点会影响结果，正式收益以完整 IQ 回放为准。
- `diagnose_missing_frames.py`：对缺失时隙检查同步候选与 CRC 失败，使用已知测试协议生成期望码流做事后错误计数；期望模型先与全部已正确恢复 PDU 逐字节交叉验证。已知 payload 不参与接收解码。
- `measure_burst_energy.py`：100 us 分箱，比较预期包内能量与包前参考。输出是未校准的通道内能量指标，不是 RSSI/SNR 或干扰源识别。有效包使用实际解码时间，缺失包使用对应 primary 或拟合时隙定位，后者存在不确定性。
- `align_errors_and_energy.py`：在包头兼容的 CRC 失败候选上对齐错误位置与能量分箱。能量超过本包分箱中位数两倍的区间记为突增区间；脚本保存逐窗口计数，报告中的汇总对这些计数求和。
- `replay_4m.py`：独立进程改变内部解调采样率，执行完整 IQ 回放；summary 会标记诊断覆盖参数。示例：

```bash
python3 python/exadv_rx/analysis/replay_4m.py \
  --iq-file python/experiments/history_ble_rx_20261026_162114_151247/captures/ble/rx_20261026_162114_151247.ci8 \
  --channels 39 --duration 0 --quiet --output /tmp/assess_10266_full4m
```

前四个脚本通过迁移清单定位固定历史输入，每次在 `python/experiments/` 新建时间命名的分析目录，生成派生 summary、入口报告并更新索引；不覆盖原始 IQ 或已有分析结果。`replay_4m.py` 要求显式 `--output`，继承接收器的输出文件防覆盖规则；输出到归档目录中才自动加入中央索引。

候选诊断通过固定版本接收器方法的源码插入只读记录钩子，依赖 `2026-10-26-window-retry1` 的结构，接收器重构后需重新检查钩子。BlueBee 反解/期望帧仅针对当前板端固定 AdvData、地址及编码表，不能视为通用 BLE/ZigBee 解码器。

结论与限制见 `../../experiments/history_exadv_rx_reviews/analyses/legacy/iq_optimization_feasibility_review.md`。本分析不能仅凭接收 IQ 证明板端 DMA 全部完成，也不能证明某个具体设备或 Wi-Fi 是干扰源。
