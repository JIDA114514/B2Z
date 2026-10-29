# HackRF exadv 接收原型

独立的 LE 1M 扩展广播接收链：`hackrf_transfer → signed int8 IQ → 连续直流抑制 → 数字下变频/FIR抽取 → 差分相位 → 逐采样相位同步搜索 → 包内频偏/极性/小幅时钟误差搜索 → 去白化 → CRC24 → 扩展头/AdvData`。

目标是先稳定恢复一个 secondary 的完整数据。支持固定接收，也支持一个 HackRF 带宽内同时接收多个已指定信道；当前不实现主机定时跳频、LE 2M、LE Coded、周期广播、链式 AdvData 重组或 BLE 控制器/协议栈。

## 依赖与启动

运行环境需要 Python 3、NumPy、SciPy 和 HackRF tools；不依赖 GNU Radio、ZMQ 或旧 `gr_ble.py`。已有系统 Python 安装科学计算库时可直接用 `/usr/bin/python3`。

在项目根目录运行，先查看设备序列号：

```bash
hackrf_info
python3 python/exadv_rx/receive.py --help
```

固定接收 ch39（2480 MHz）的当前板端同频调试路径，只需指定本轮 Run ID：

```bash
python3 python/exadv_rx/receive.py --run-id 10270
```

默认使用 BLE HackRF 序列号 `000000000000000017c467dc2926a0c3`、8 Msps、40 s、LNA=24 dB、VGA=20 dB，保存 IQ 并仅显示简要状态。设备分工与长期配置集中在 [`receiver_defaults.py`](../experiment_tools/receiver_defaults.py)；`--serial`、`--duration`、`--no-save-iq`、`--no-quiet` 可按实验覆盖。

标准 secondary 固定在 BLE data ch3（2410 MHz）时改成 `--channels 3`。必须核实实际 RF 频率和白化信道，不能仅从 AuxPtr 推断板端实际发射配置。两块 HackRF 并用时通过 `--serial <序列号>` 选择设备。

- `--duration 0` 持续接收到 Ctrl-C；离线模式表示读到 EOF。
- 默认启用 `--timing-retry`：原始完整符号窗口通过 CRC 时直接提交，失败时只对最多两个采样候选和三个小幅时钟偏差，用 0.75 符号宽度的中心窗口重判。重试仍须通过完整 BLE CRC24 和扩展头校验，不使用已知 Run ID/Sequence/填充恢复负载，也不翻转弱位来凑 CRC。`--no-timing-retry` 关闭以做同 IQ 对照。
- `--channel-cutoff-hz` 允许在 400000–950000 Hz 范围内显式设置通道 FIR 截止频率，默认仍为 850000 Hz。较窄滤波在不同记录上有得有失，未自动改为新的默认值。
- 默认按主机本地日期和 `--run-id` 归档至 `python/experiments/YYYYMMDD_run<run_id>/`；每次启动新建独立采集子目录。BLE 的 Run ID 只作归档标签，不参与 BLE 负载解码。`--experiment-dir <目录>` 可覆盖默认目录。
- `--output <前缀>` 保持旧前缀语义，已有文件时拒绝覆盖；与 `--experiment-dir` 互斥。
- 回放通过 `--analysis-id <名称>` 指定 `analyses/` 子目录；该参数需要 `--iq-file`，省略则自动生成。
- 默认射频放大器关闭，LNA=24 dB、VGA=20 dB 只是初始设置，不是稳定性保证；根据距离和饱和情况调整。
- `--whitening-channels 39` 可显式设置与 RF 信道不同的白化信道，仅用于诊断或特殊发射配置，结果会保留两者。
- 默认启用 `--dc-block-hz 1000`：在数字下变频和非线性相位解调之前去除 IQ 直流偏置，滤波状态跨块连续。`--dc-block-hz 0` 可关闭以进行同一 IQ 的 A/B 对照。滤波器初始状态需要收敛，开始处的包可能受瞬态影响；滤波对时间估计的影响也需校准。
- 固定 ch39 的 secondary 被标为 `same_channel_auxiliary_diagnostic`，不会当成规范的跨信道跟随事件。

一个 HackRF 同时接收带宽内的 primary/secondary，例如 ch37=2402 MHz、ch0=2404 MHz：

```bash
python3 python/exadv_rx/receive.py \
  --run-id 10270 --channels 37,0 --duration 60
```

中心频率默认取所选信道中点，要求每侧保留 1.2 MHz 边缘余量，越界直接报错。ch39/ch3 相隔 70 MHz，不能由一个 HackRF 同时覆盖；不要对该配置声称已实现 AuxPtr 跟随。宽带接收是同时监听指定频点，不是调谐跟随的验证。

## 输出与时间口径

默认保存到 `python/experiments/YYYYMMDD_run<run_id>/captures/ble/<启动时间_唯一后缀>/rx.*`；回放保存到同轮 `analyses/<analysis_id>/ble/rx.*`。组织方式、两设备示例和历史迁移说明见[顶层 README](../../README.md#接收结果与实验归档)，历史入口见[实验索引](../experiments/index.md)。每次生成：

- `.packets.jsonl`：CRC 正确且扩展头可解析的逐包记录，包括完整 PDU/AdvData、AD 字段、AdvA、ADI、AuxPtr、相对采样时刻、频偏和同步评分。
- `.events.jsonl`：通过 `match_type` 区分严格 AuxPtr 匹配和同频诊断匹配，不能将两类事件合并为规范符合的事件数。
- `.summary.json`：完整配置、计数、处理耗时、队列压力和运行状态；`.summary.txt` 为简短文本，`.report.md` 为可读接收报告。本轮顶层 `report.md` 汇总各接收记录；JSONL 保留原始逐包数据。
- `.hackrf.log`：`hackrf_transfer` 原始 stderr，保留设备错误和可能的传输异常。
- 开启 `--save-iq` 时输出 `.ci8`（或离线输入对应的 `.cf32`），录制参数在 summary 中。

注意：

1. 长度使用完整 8 位，支持最大 255 B PDU payload；不沿用旧接收器的 `length & 0x3f`。所有采样相位参与同步搜索，不依赖任意 bit 流恰好字节对齐。
2. CRC 错包不提交为有效接收；`crc_failure_candidates` 只是同步候选 CRC 失败数，不能当成唯一物理坏包数。通过 CRC 但扩展头非法的候选另计。
3. 真正重复发射的包逐个保留，不因 PDU 内容相同而丢弃；同一采样位置的多相位检测内部只提交一次。ADI/DID 不是逐包 Sequence。
4. `sample_start` 为输入 IQ 的相对采样位置，已补偿 FIR 群延迟；`sample_time_s` 用标称采样率换算，不是硬件绝对时间或 UTC。接收选择相位、频偏和滤波仍有估计误差，不作为已校准同步精度。
5. 仅在同一连续 IQ 采集中按采样时间配对；不使用 USB 到达时间、进程墙钟或实验周期折叠伪造配对。不跨设备 summary 直接比较相对时间。
6. AuxPtr 的偏移表示量化窗口，不是无误差的精确执行时刻；当前配对还允许配置的测量容差。多个 primary 指向同一个 secondary 时可产生多个指针匹配，不等于多个独立控制任务。
7. `auxiliary` 不凭 type 7 或 ADI 猜测 AUX_ADV_IND/AUX_CHAIN_IND 等具体子类型；当前不重组链式数据，也不执行应用控制命令。
8. 未合并发送端有效计数与一致观察窗口时 PRR 为 N/A。新脚本不会从接收数量推测板端发送数。

### `pairs` 与 `diagnostic_pairs`

状态行同时显示两种计数：

```text
status samples=... packets=... pairs=0 diagnostic_pairs=... queue=...
```

- `pairs` / summary 的 `matched_events`：严格 AuxPtr 配对，要求信道、LE 1M PHY、身份与声明的量化偏移窗口一致，原有口径未放宽。
- `diagnostic_pairs`：默认启用的同频调试配对，仅处理 `same_channel_auxiliary_diagnostic`。要求同一实际 RF 信道、相同 ADI，以及存在时一致的 AdvA；只在声明偏移的 ±2000 us 内做一对一匹配，不按实验周期折叠时间。窗口由 `--diagnostic-pair-window-us` 显式配置，最高 10000 us，`--no-diagnostic-pairs` 可关闭。
- 诊断事件标为 `match_type=same_channel_diagnostic`、`standards_compliant=false`，保留实际间隔、对 AuxPtr 的误差、信道/PHY 是否一致。不是硬件时间同步精度，也不是控制任务执行成功率。
- 当前板端同频 ch39、AuxPtr 声明 ch3/PHY=1/30000us，而实测偏移约 30800us，因此严格 `pairs` 仍应为 0，诊断计数可以增加。

逐包 `decode_method` 区分 `hard` 和 `narrow_window_retry`。通道统计中的 `hard_crc_failure_candidates` 包括随后被重试恢复的候选，`crc_failure_candidates` 为最终仍失败的候选，`timing_retry_attempts` / `timing_retry_recovered` 报告额外开销与恢复数。候选计数不能当成独立物理坏包数。

## 录制回放与稳定性排查

可以先独立录制，排除实时解码速度的影响：

```bash
hackrf_transfer -r /tmp/exadv.ci8 -f 2480000000 -s 8000000 \
  -l 24 -g 20 -a 0 -p 0 -n 80000000
python3 python/exadv_rx/receive.py \
  --iq-file /tmp/exadv.ci8 --run-id 10270
```

`.ci8` 为交错有符号 int8 I/Q；`--format cf32` 读取小端 complex64。外部 IQ 文件必须提供正确采样率、中心频率、信道和白化参数；30.72 Msps 的板端双通道 DMA C 数组不是可直接输入的 IQ 文件，需去交织并正确重采样。

实时采集与解码通过有界队列隔离；队列溢出会明确报错结束，不静默丢块后继续使用假连续时间轴。文件回放允许背压。每 5 秒输出状态；summary 记录处理耗时与队列高水位，实时情况下应检查单块处理时间和样本块时长的关系。2 通道比 1 通道更耗 CPU，主机性能不足时先录制再回放；扩大队列只能吸收短暂抖动，不能解决持续处理不足。

HackRF 原始 IQ 不保证提供可定位每次 USB 丢样的序列号/硬件时间戳；队列无溢出并不能证明采样无缺口。需同时检查原始设备日志与其他独立证据，不能将所有接收损失直接归因无线。`clipped_components` 只是 int8 分量到达量化端点的计数，不是校准 RSSI 或严格 RF 饱和测量。

去掉 `--quiet` 可逐包打印 `t=...s`（小数点后 9 位）、补偿 FIR 延迟后的输入采样位置 `sample=...` 和 `ref=ble_preamble`。这些是该录制的相对标称采样时间，不是 USB 到达/打印时刻或 UTC；显示位数不代表精度。与 ZigBee 比较时需匹配同一 Run ID+Sequence，并补偿包内位置差。两个独立 HackRF 的采集起点和采样时钟未经校准时，不能直接相减验证同步。终端中的 `#` 是各接收器自己的包计数，不是共同标识。

推荐实测顺序：先发已知短 AdvData，确认 CRC 和字节完全一致；再测 64/238/255 B 长度及实际 BlueBee 共包；每个候选配置至少 3 轮，并与板端或人工发送计数对齐。稳定性目标需由实测确认，不从离线单元测试推断。

## 当前验证与发送端注意事项

当前验证覆盖：CRC/白化与项目旧编码器交叉检查、严格扩展头边界、完整 8 位长度、跨任意数据块、频偏、IQ 反相、小幅采样时钟偏差、坏 CRC、噪声、真实重复包、数字信道平移、同一 IQ 中 primary/secondary 配对、旧 30.72 Msps 生成器 IQ 回归及离线 CLI。

窗口重试另有一个约 19 KB 的真实 IQ 回归片段，验证完整窗口失败、窄窗口成功且 CRC 条件不变；同频诊断匹配覆盖身份不符、窗口超限、重复提交和严格/诊断计数隔离。完整 IQ 对照结果保存在 `../experiments/history_exadv_rx_reviews/analyses/legacy/window_retry_comparison.summary.json`，不以分段窗口探针的收益代替连续回放结果。

```bash
python3 -m unittest discover -s python/exadv_rx/tests -v
```

初版开发环境未连接设备。2026-10-26 已收到两轮实际 HackRF IQ：4 B 循环 secondary，以及 `bluebee_exadv_perf_start?30 200000 60 10261`。初版缺少直流抑制，导致弱目标大量漏检；同一 IQ 的补偿回放确认能显著恢复短包并恢复部分 30 B 测试包。当前版本默认加入连续 IQ 高通及相关回归测试，原始结果保留，补偿回放使用独立前缀。这是既有硬件录制的离线验证，尚不能代替修复版本的实时长测或声称达到稳定点；详细计数见 `../experiments/history_exadv_rx_reviews/analyses/legacy/experiment_review_20261026.md`。

旧 `python/std_ble/generate_ble_exadv_iq_30_72M.py` 当前把 `BLE_AUX_PHY_LE_1M` 设为 `0x01` 并写入 AuxPtr；规范 Aux PHY 编码是 `0=LE 1M`、`1=LE 2M`、`2=LE Coded`。新接收器按规范解释该字段，不会把声明为 2M 的指针当作已验证的 1M 配对。即使 secondary 的 1M 波形可以独立收到，错误的指针仍会导致配对失败。本次仅新增接收目录，未修改旧发送脚本或板端波形。

参考：[HackRF IQ 格式](https://hackrf.readthedocs.io/en/stable/hackrf_tools.html)、[Bluetooth Link Layer：2.3.4.5 AuxPtr](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/low-energy-controller/link-layer-specification.html)。
