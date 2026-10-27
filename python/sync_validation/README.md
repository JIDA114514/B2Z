# 已保存 IQ 的双协议共同时间参考验证

入口 `validate_saved_iq.py`。逐份原始 IQ 分别启动现有 `exadv_rx/receive.py` 和 `zigbee_rx/receive.py` 的独立离线进程，解码完成后才匹配结果。两个目录中的三份完整录制分别分析，不把不同录制的相对时间戳直接相减。无需连接设备，不修改接收器或板端。

```bash
python3 python/sync_validation/validate_saved_iq.py \
  --output python/sync_validation/results/new_validation
python3 -m unittest discover -s python/sync_validation/tests -v
```

输出目录必须不存在，防止覆盖已有实验。依赖现有两接收器的 NumPy/SciPy 以及绘图用 Matplotlib。默认输入、样本率、中心频率和预先固定的校准划分见 `recordings.config.json`。

## 数据和独立性

- 完整输入：Run 10265（30 B）、10266（40 B）、10267（30 B），各 40 s、8 Msps、640 MB ci8 IQ。
- 排除 `rx_20261027_104243_311380.ci8`：设备启动失败，只有 1733 B，不能当成 IQ 实验。
- ZigBee 接收器独立进行标准 DSSS、PHR、FCS、测试头和完整填充校验，不读取 BLE 帧或蓝蜂精确编码表。
- BLE 接收器先独立通过完整 BLE CRC；后处理在已恢复 PDU 中定位 Manufacturer AD，撤销该区域的白化预补偿，再按已知 BlueBee 编码格式精确反解嵌入帧，验证 FCS 和完整测试填充。这是 BLE 已恢复字节的负载解析，不是第二条 ZigBee IQ 接收链，也不向 ZigBee 解调器提供内容或时刻。
- 对端缺失时不重建负载、不推测时刻。匹配键为同一份 IQ 的 Run ID+Sequence，还要求完整 ZigBee PHY 帧一致；相同标识重复出现时保留计数并排除有歧义的时间配对。

现有帧没有独立 BLE 控制命令及同步字段，因此本实验只利用嵌入的性能帧标识关联同一物理包，不能称为新同步控制协议验证。

## 参考点和校准

BLE 时间戳对应前导码与 AA 同步序列起点；ZigBee 时间戳对应嵌入 PHY 前导码的检测起点。两接收器均补偿自身线性 FIR 群延迟，但差分采样、判决相位、DC 抑制等仍可能有剩余误差。

本工具逐包从已解码的 BLE PDU 解析 BlueBee 区域位置，不通过两侧时间差猜位置：

```text
layout_delta_us = (5 + bluebee_pdu_byte_offset) * 8
raw_delta_us = (zigbee_sample - ble_sample) / input_sample_rate * 1e6
layout_error_us = raw_delta_us - layout_delta_us
```

这里 5 B 为 BLE LE 1M 前导码和 AA，8 us/B。当前扩展头、Flags、Name S、Manufacturer AD 布局的 BlueBee PDU 字节偏移为 22，因此理论包内位置差为 216 us。布局改变时按解析结果重算，不能硬编码 216 us 用于所有未来帧。

校准集合在配置中预先限定为 Run 10265、Sequence <75 的共同有效帧。只估计一个固定量：`bias = median(layout_error_us in calibration)`。所有其他序列和录制都是验证集合，统一使用该固定 bias：

```text
calibrated_error_us = layout_error_us - bias
```

不做逐包对齐，不针对验证集重新拟合均值，不估计并扣除每轮斜率。输出补偿前、仅结构补偿和固定校准后的结果，避免只展示居中后的误差。

## 结果文件

- `validation.manifest.json`：输入配置、原始 IQ SHA-256、原始采集摘要散列、完整重放命令、源码散列及结果文件散列。
- `run_*_{ble,zigbee}.summary.json`：独立重放摘要；完整逐包流和重放控制台日志默认忽略。
- `reference_validation.summary.json`：逐轮四种解码结果、计划分母、条件时间统计和带容差的计划时隙恢复数量。
- `per_sequence.metrics.csv`：包括两侧均缺失的全部 450 个计划时隙；同时标记 calibration/validation、配对状态、结构偏移和误差。
- `reference_validation.png/.pdf`：原始位置差、验证集残差、绝对残差 CDF 和四种解码结果。

`tolerance_results` 的分母为相应轮验证分区的全部计划时隙。分子要求两侧完整校验成功且参考残差在容差内；缺失帧不算通过。该统计是“带参考误差约束的联合解码”，不是同步执行成功率。150 来自接收配置，没有板端发送计数证据时不称为无线 PRR。

时间统计的 n 为双方都成功且完整帧相同、身份不重复的样本数。标准差采用总体口径 `ddof=0`，分位数为 NumPy 默认线性插值，不将缺失赋零；未据单轮相关样本计算独立同分布置信区间。

## 能支持的结论

这是共用同一采样时钟、同一 RF 观测的独立双解码，测量共同包参考时刻的一致性。8 Msps 的 0.125 us 样本间隔、BLE/ZigBee 内部采样网格都不是绝对精度保证。共享的 RF 噪声、滤波、时间轴误差可能相关或相互抵消；原始 IQ 无明显缺块也不能保证硬件/USB 无丢样。

本结果不能证明两块 HackRF 的采集起点一致、独立时钟已同步、漂移得到补偿、真实命令按时执行，或微秒级执行器同步。完整 exadv AuxPtr 跟随也不属于本轮验证。

## 单台/双台接收控制实验

`capture_single_dual.py` 用于目标信号在双设备运行时异常的排查：依次运行 ZigBee 设备单台、两台同时、ZigBee 设备单台。默认每段 30 s，保持设备、天线和 USB 线不移动，只改变接收进程活动状态。保存四份独立 IQ（总计约 1.92 GB）、原始设备日志、逐包结果和阶段摘要。

“单台”只指一个接收进程工作，**两块 HackRF 在所有阶段都必须保持 USB 连接**。脚本在每个阶段开始前通过 `hackrf_info` 核对两个指定序列号；缺少设备时立即停止并保存枚举结果，避免等待第一段结束才发现第二台不可用。子进程故障时会显示 HackRF 原始原因和日志路径，并保留失败阶段的两侧摘要。

先停止已有接收进程，在板端启动持续发送：

```text
bluebee_exadv_perf_start?30 200000 0 10270
```

确认发送已启动后，在项目根目录执行：

```bash
python3 python/sync_validation/capture_single_dual.py \
  --ble-serial 000000000000000017c467dc2926a0c3 \
  --zigbee-serial 000000000000000017c467dc3348a6c3 \
  --run-id 10270
```

可先追加 `--dry-run` 检查命令，不创建文件或访问硬件。实际运行结束后，必须在板端输入 `bluebee_perf_stop?`；脚本不控制板端。程序遇到子接收器失败或阶段超时会停止同阶段接收进程、记录错误，并提示手动停止发送。

连续发送跨越多个录制，Sequence 不从每段零开始，因此脚本不设置 `--expected-packets`，也不自动计算 PRR。必须结合实际发送持续时间、板端计数及 IQ 判断。该脚本已做无硬件回归与 dry-run，真实单/双/单对照尚需用户启动板端后执行。

判读：若两次单台都能恢复而中间双台显著下降，才支持双设备活动相关问题；需交替顺序重复确认，并进一步区分 USB/供电和 RF 耦合。若单台阶段也始终为零，则先检查该设备的天线/连接和目标信号路径，不能继续把问题归因于同时运行。共享 USB hub 本身不是故障证明。
