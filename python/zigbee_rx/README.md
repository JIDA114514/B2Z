# 独立 HackRF IEEE 802.15.4 / BlueBee 接收器

双独立接收的第二部分：HackRF B 直接采集自己的 IQ，解调 IEEE 802.15.4 2.4 GHz PHY。HackRF A 继续运行 `python/exadv_rx/receive.py`。两个进程没有共享 IQ、BLE 解码结果、无线设备句柄或 ZMQ 端口。

接收路径：`hackrf_transfer → int8 IQ → 连续 DC 抑制 → 数字下变频与 FIR 抽取到 4 Msps → 差分相位 → 所有 chip 采样相位 → 标准 DSSS 解扩 → 动态 PHR → FCS → 可选测试头/填充校验`。

本工具验证 PHY 与负载正确解析，不执行控制动作，也不实现 ZigBee MAC/NWK/APS/ZCL、安全入网或商用芯片兼容性认证。

## 安装与设备选择

需要 Python 3、NumPy、SciPy、HackRF tools，不需要 GNU Radio、osmosdr、ZMQ。项目已有的纯 Python 测试协议 helper `python/perf_test/bluebee_perf_protocol.py` 用于 FCS 解码完成后的 Run ID/Sequence/填充校验；不能仅复制本目录后删除该依赖。

```bash
hackrf_info
python3 python/zigbee_rx/receive.py --help
```

实时模式必须显式提供 `--serial`，避免两个接收进程都选择第一块 HackRF。将下面的 `SERIAL_A` / `SERIAL_B` 替换为两块**不同设备**的完整序列号。

当前板端同频实验位于 2480 MHz：BLE ch39 对应 IEEE 802.15.4 **ch26**，两个协议的信道编号不是同一编号。

终端 A，保持现有 BLE 接收器：

```bash
python3 python/exadv_rx/receive.py --serial SERIAL_A \
  --channels 39 --duration 40 --save-iq --quiet
```

终端 B，针对当前板端 BlueBee 负载：

```bash
python3 python/zigbee_rx/receive.py --serial SERIAL_B \
  --channel 26 --demod phase --symbol-order project \
  --cutoff-hz 700000 --dc-block-hz 1000 \
  --run-id 10267 --payload-len 30 --expected-packets 150 \
  --duration 40 --save-iq --quiet
```

然后在板端输入对应配置，例如：

```text
bluebee_exadv_perf_start?30 200000 30 10267
```

先启动两侧接收，再启动板端。接收时长留出启动和结束余量；`--expected-packets 150` 是显式输入的计划时隙范围，不会因为接收器运行 40 s 而推断 200 个包。

`--run-id` 和 `--payload-len` 仅用于解码后的测量过滤，不会把预期负载、帧长度或 Sequence 注入解调器。新控制包格式尚未定义，暂时解析现有 10 B 性能头；普通 FCS 正确的非测试 PHY 负载也会被输出。

## 两种物理观测与字节顺序

- `--demod phase`：差分相位符号直接按标准 16 项 `CHIP_MAP` 解扩，适用于本项目 BlueBee PHY 仿真。不使用发射端 optimized/emulated 芯片码本。
- `--demod oqpsk`：对真正半正弦 O-QPSK 利用 MSK 等价关系形成差分参考。参考仍从同一标准芯片码本推导，忽略每个符号首个依赖前一符号的差分 chip；不使用 BLE 解码。
- `--demod auto`（默认）：尝试两种观测，按完整 FCS 接受，并将同一物理突发的多采样/多观测结果只提交一次。该模式成本更高；针对当前板端建议固定 `phase`。
- `--symbol-order project`：兼容板端及既有 Python 生成器“每字节 LSB bit 字符串、每四位按字符串解释 symbol”的顺序。
- `--symbol-order ieee`：按低 nibble、再高 nibble 的数值直接映射符号；用于对应格式的标准 O-QPSK 输入。
- `--symbol-order auto`（默认）：根据恢复的 preamble/SFD/PHR 和 FCS 选择，逐包记录最终顺序，不靠已知 payload 猜测。

保留 project/ieee 区分是为了不把项目内表示约定直接等同于外部芯片的完整互操作性。合成 O-QPSK 验证不代替真实 ZigBee 芯片测试。

`--soft-retry` 默认启用：同一候选组的硬判决 FCS 失败后，使用相位差幅度与标准参考相关重判；仍要求 preamble、SFD、PHR 和完整 FCS。`--no-soft-retry` 可关闭。软重试不修补 FCS、不使用测试填充生成数据。真实重复发射的帧仍保留，并由 SequenceTracker 统计 duplicate。

## IQ 回放

可以读取现存的原始 IQ，无需 BLE 逐包文件：

```bash
python3 python/zigbee_rx/receive.py \
  --iq-file python/experiments/history_ble_rx_20261026_161955_853914/captures/ble/rx_20261026_161955_853914.ci8 \
  --channel 26 --demod phase --symbol-order project \
  --run-id 10265 --payload-len 30 --expected-packets 150 \
  --duration 0 --quiet \
  --experiment-dir python/experiments/replay_run10265 --analysis-id phase_v1
```

`.ci8` 为交错有符号 int8 I/Q，`--format cf32` 为小端 complex64。必须提供实际采样率（默认 8 Msps）和录制中心频率（默认所选 ZigBee 信道频率）；`--duration 0` 表示读到 EOF。不要直接读取板端双通道 DMA C 数组。

参数包括 `--center-hz`、`--cutoff-hz`（默认 1.3 MHz）、`--cfo-hz`（默认 0，数字频偏补偿）、`--dc-block-hz`（默认 1 kHz）、LNA/VGA、块大小、有界队列容量及停滞超时。频偏参数不改变时间基准。配置不在采集带宽内时直接拒绝。

上例显式使用 `--cutoff-hz 700000 --dc-block-hz 1000`，用于保留 Run 10268 中已验证的离线改善配置：两份完整 IQ 在原 1.3 MHz 截止频率下均恢复 0 个 ZigBee 有效包，改为 700 kHz 后分别恢复 81 和 68 包。但后续 Run 10269 实时实验已正确采用该参数，ZigBee 设备仍为 0 包；相同程序回放旧 IQ 仍恢复 68 包，新 BLE 设备 IQ 则能恢复 70 包。因此 700 kHz 尚不是稳定解决方案，应优先做单台/双台接收对照，定位目标信号的接收路径。通用默认值 1.3 MHz 保留，历史结果不覆盖，也不能将收窄带宽视为对所有原生 O-QPSK 输入都最优。参见 `../experiments/history_sync_dual_run10269_diagnostic/analyses/legacy/review.md`。

## 输出与统计

默认在 `python/experiments/` 新建 UTC 时间命名的实验目录，实时结果为 `captures/zigbee/rx.*`，回放为 `analyses/<analysis_id>/zigbee/rx.*`。两端传入相同 `--experiment-dir <目录>` 可合并归档；回放可加 `--analysis-id <名称>`，省略则自动命名。原 `--output <前缀>` 仍可使用，与 `--experiment-dir` 互斥，拒绝覆盖已有结果。

完整结构、联合归档示例和索引命令见[顶层 README](../../README.md#接收结果与实验归档)，历史入口见[实验索引](../experiments/index.md)。

- `.packets.jsonl`：所有 FCS 正确的 PHY 帧、完整 payload、采样时间、观测方式、符号顺序、硬/软判决方法、Run ID、Sequence、测试校验及 disposition。
- `.summary.json`：完整接收和解码计数、序列缺口、计划范围、处理时延、队列、吞吐、版本与源码 SHA-256。`.summary.txt` 为简短文本，`.report.md` 为可读接收报告；顶层 `report.md` 汇总本轮结果。
- `.hackrf.log`：设备采集原始输出。
- `--save-iq`：保存原始输入字节及对应 summary 配置。完整 IQ 和逐包流默认不进入 Git，小型摘要/报告可提交。

unique 只统计指定/锁定 Run ID、通过完整确定性填充校验的首次 Sequence；duplicate 和 out_of_order 单独计数。未指定 Run ID 时锁定第一份有效测试 payload；多轮实验建议分别启动并显式设置 Run ID。非测试帧只计 FCS 有效和 non_test，不冒充性能测试成功包。

`--expected-packets N` 输出明确范围 `0..N-1` 的缺失区间及最长缺失；省略时最长缺失仅覆盖已收到的最小到最大 Sequence，不包含未知首尾。`fcs_failure_candidates` 是候选组 FCS 失败数，不是唯一物理坏包数，也不是无线 PER。

吞吐分母为所有已处理 IQ 的标称采样时长（包括实验前后余量）。gross 为有效唯一测试 payload 的字节数，application 扣除每包 10 B 测试头；同时报告 bit/s 与 byte/s。

如有板端最终串口日志，可以提供 `--board-log path/to/run.board.log`。只有明确确认接收覆盖完整板端实验并设置 `--full-run-covered`、计数和 Run ID 一致且采集正常完成，才合并计算无线 PRR、调度完成率和端到端接收率。不能对“30 s 接收覆盖 60 s 发送”的情况设置该标志。无发送证据时 PRR 为 N/A。

## 独立双接收的测量边界

新进程不读取 BLE PDU、白化字节或 BLE 接收结果。读取同一份旧 IQ 只是离线算法验证；真正双独立接收要使用两块不同序列号的 HackRF，同时各自录制。

两个独立采集的 `sample_time_s` 起点不同，不能直接相减作为同步误差。共同接收率可在解码完成后按 Run ID+Sequence 或未来 command_id 合并；同步精度还需独立校准。

去掉 `--quiet` 可逐包打印时间戳。`t=...s` 显示到小数点后 9 位，`sample=...` 是补偿 FIR 延迟后的输入采样位置，`ref=zigbee_preamble` 标明包内参考点。BLE 脚本对应 `ref=ble_preamble`。二者都是各自采集的相对标称采样时间，不是打印时刻或 UTC；显示位数不代表测量精度。比较必须匹配同一 Run ID+Sequence，不能使用终端中的 `#` 包计数配对。相同 IQ 可按包布局补偿位置差；不同 HackRF 需先校准起点、采样率偏差和固定延迟。

队列溢出明确报错，不静默丢块；文件回放允许背压。没有队列溢出不保证 USB/硬件完全无丢样。两块高采样率 SDR 共用主机时应分别检查队列和设备日志；当前不能承诺实时长测稳定点。

## 验证

```bash
python3 -m unittest discover -s python/zigbee_rx/tests -v
```

覆盖标准码本/FCS与旧项目交叉验证、BlueBee 10/30/40/46 B、两种符号顺序的原生半正弦 O-QPSK、最大 127 B PSDU、频偏、反相、跨块、噪声/坏 FCS 拒绝、真实重复包、离线 CLI、计划缺口及板端统计合并。

真实 IQ 回放结果见 `../experiments/history_zigbee_rx_reviews/analyses/legacy/validation_review.md`。开发时只检测到一块已连接 HackRF，双设备同时接收尚需用户连接第二块并明确序列号后验证。

参考：[HackRF 原始 IQ 格式](https://hackrf.readthedocs.io/en/stable/hackrf_tools.html)。码本与项目 `python/ctc_sim/std_zigbee/zigbee_mod.py` 逐项回归；本实现不依赖历史 GNU Radio/ZMQ 接收脚本。
