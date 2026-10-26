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

固定接收 ch39（2480 MHz），适合当前板端同频调试路径：

```bash
python3 python/exadv_rx/receive.py \
  --channels 39 --sample-rate 8000000 --duration 60 \
  --lna 24 --vga 20 --save-iq --quiet
```

标准 secondary 固定在 BLE data ch3（2410 MHz）时改成 `--channels 3`。必须核实实际 RF 频率和白化信道，不能仅从 AuxPtr 推断板端实际发射配置。两块 HackRF 并用时通过 `--serial <序列号>` 选择设备。

- `--duration 0` 持续接收到 Ctrl-C；离线模式表示读到 EOF。
- `--output python/exadv_rx/results/run001` 指定结果前缀，已有文件时拒绝覆盖。
- 默认射频放大器关闭，LNA=24 dB、VGA=20 dB 只是初始设置，不是稳定性保证；根据距离和饱和情况调整。
- `--whitening-channels 39` 可显式设置与 RF 信道不同的白化信道，仅用于诊断或特殊发射配置，结果会保留两者。
- 默认启用 `--dc-block-hz 1000`：在数字下变频和非线性相位解调之前去除 IQ 直流偏置，滤波状态跨块连续。`--dc-block-hz 0` 可关闭以进行同一 IQ 的 A/B 对照。滤波器初始状态需要收敛，开始处的包可能受瞬态影响；滤波对时间估计的影响也需校准。
- 固定 ch39 的 secondary 被标为 `same_channel_auxiliary_diagnostic`，不会当成规范的跨信道跟随事件。

一个 HackRF 同时接收带宽内的 primary/secondary，例如 ch37=2402 MHz、ch0=2404 MHz：

```bash
python3 python/exadv_rx/receive.py \
  --channels 37,0 --sample-rate 8000000 --duration 60 --quiet
```

中心频率默认取所选信道中点，要求每侧保留 1.2 MHz 边缘余量，越界直接报错。ch39/ch3 相隔 70 MHz，不能由一个 HackRF 同时覆盖；不要对该配置声称已实现 AuxPtr 跟随。宽带接收是同时监听指定频点，不是调谐跟随的验证。

## 输出与时间口径

默认保存到本目录 `results/`，每轮生成：

- `.packets.jsonl`：CRC 正确且扩展头可解析的逐包记录，包括完整 PDU/AdvData、AD 字段、AdvA、ADI、AuxPtr、相对采样时刻、频偏和同步评分。
- `.events.jsonl`：同一 IQ 时间线中满足 AuxPtr 信道、PHY、量化偏移窗口以及 ADI/AdvA 身份条件的 primary/auxiliary 匹配。
- `.summary.json`、`.summary.txt`：配置、计数、处理耗时、队列压力和运行状态；JSONL 作为原始结构化数据。
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

## 录制回放与稳定性排查

可以先独立录制，排除实时解码速度的影响：

```bash
hackrf_transfer -r /tmp/exadv.ci8 -f 2480000000 -s 8000000 \
  -l 24 -g 20 -a 0 -p 0 -n 80000000
python3 python/exadv_rx/receive.py \
  --iq-file /tmp/exadv.ci8 --channels 39 --sample-rate 8000000 \
  --duration 0 --quiet
```

`.ci8` 为交错有符号 int8 I/Q；`--format cf32` 读取小端 complex64。外部 IQ 文件必须提供正确采样率、中心频率、信道和白化参数；30.72 Msps 的板端双通道 DMA C 数组不是可直接输入的 IQ 文件，需去交织并正确重采样。

实时采集与解码通过有界队列隔离；队列溢出会明确报错结束，不静默丢块后继续使用假连续时间轴。文件回放允许背压。每 5 秒输出状态；summary 记录处理耗时与队列高水位，实时情况下应检查单块处理时间和样本块时长的关系。2 通道比 1 通道更耗 CPU，主机性能不足时先录制再回放；扩大队列只能吸收短暂抖动，不能解决持续处理不足。

HackRF 原始 IQ 不保证提供可定位每次 USB 丢样的序列号/硬件时间戳；队列无溢出并不能证明采样无缺口。需同时检查原始设备日志与其他独立证据，不能将所有接收损失直接归因无线。`clipped_components` 只是 int8 分量到达量化端点的计数，不是校准 RSSI 或严格 RF 饱和测量。

推荐实测顺序：先发已知短 AdvData，确认 CRC 和字节完全一致；再测 64/238/255 B 长度及实际 BlueBee 共包；每个候选配置至少 3 轮，并与板端或人工发送计数对齐。稳定性目标需由实测确认，不从离线单元测试推断。

## 当前验证与发送端注意事项

当前验证覆盖：CRC/白化与项目旧编码器交叉检查、严格扩展头边界、完整 8 位长度、跨任意数据块、频偏、IQ 反相、小幅采样时钟偏差、坏 CRC、噪声、真实重复包、数字信道平移、同一 IQ 中 primary/secondary 配对、旧 30.72 Msps 生成器 IQ 回归及离线 CLI。

```bash
python3 -m unittest discover -s python/exadv_rx/tests -v
```

初版开发环境未连接设备。2026-10-26 已收到两轮实际 HackRF IQ：4 B 循环 secondary，以及 `bluebee_exadv_perf_start?30 200000 60 10261`。初版缺少直流抑制，导致弱目标大量漏检；同一 IQ 的补偿回放确认能显著恢复短包并恢复部分 30 B 测试包。当前版本默认加入连续 IQ 高通及相关回归测试，原始结果保留，补偿回放使用独立前缀。这是既有硬件录制的离线验证，尚不能代替修复版本的实时长测或声称达到稳定点；详细计数见 `results/experiment_review_20261026.md`。

旧 `python/std_ble/generate_ble_exadv_iq_30_72M.py` 当前把 `BLE_AUX_PHY_LE_1M` 设为 `0x01` 并写入 AuxPtr；规范 Aux PHY 编码是 `0=LE 1M`、`1=LE 2M`、`2=LE Coded`。新接收器按规范解释该字段，不会把声明为 2M 的指针当作已验证的 1M 配对。即使 secondary 的 1M 波形可以独立收到，错误的指针仍会导致配对失败。本次仅新增接收目录，未修改旧发送脚本或板端波形。

参考：[HackRF IQ 格式](https://hackrf.readthedocs.io/en/stable/hackrf_tools.html)、[Bluetooth Link Layer：2.3.4.5 AuxPtr](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/low-energy-controller/link-layer-specification.html)。
