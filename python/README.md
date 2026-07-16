# python 目录说明

本文件只维护 `python/` 目录的边界、运行约定和过时项更正。当前 BlueBee / BLE extended advertising 波形脚本的功能、参数和可复制命令示例以根目录 `README.md` 为准。

## 目录边界

| 路径 | 维护状态 |
|------|----------|
| `std_ble/` | 当前 BLE 物理层、extended advertising 生成和 BLE/HackRF 接收调试代码。 |
| `ctc_sim/bluebee/` | 当前 BlueBee 论文复现实验、BlueBee/ZigBee 波形生成和接收验证代码。 |
| `ctc_sim/std_zigbee/` | 当前标准 ZigBee 生成、GNU Radio 接收流图和 frame 解析代码。 |
| `ctc_sim/patternbee/` | 历史 PatternBee 实验代码，当前 FreeRTOS/BlueBee 主线不依赖。 |
| `ctc_sim/` 顶层脚本 | 离线分析和旧实验辅助脚本，使用前先查看脚本 `--help` 或源码入口。 |

## 当前入口索引

下列脚本是当前仍会被主线验证流程引用的入口；具体参数不要在本文件重复维护。

| 路径 | 备注 |
|------|------|
| `std_ble/generate_ble_exadv_iq_30_72M.py` | 参数和示例见根目录 `README.md`。 |
| `ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py` | 参数和示例见根目录 `README.md`。 |
| `ctc_sim/bluebee/generate_bluebee_iq_30_72M.py` | 参数和示例见根目录 `README.md`。 |
| `ctc_sim/std_zigbee/zigbee_rx.py` | 标准 ZigBee frame 接收验证入口。 |
| `ctc_sim/bluebee/bluebee_rx.py` | BlueBee 构造 frame 的接收验证入口。 |
| `std_ble/ble_exadv_hackrf_sniffer.py` | BLE extended advertising 捕获和时序调试入口。 |
| `std_ble/ble_packet_detector.py` | BLE packet 检测调试入口。 |
| `ctc_sim/std_zigbee/generate_zigbee_iq_30_72M.py` | 标准 ZigBee 30.72 MSPS 头文件生成辅助入口。 |

查看脚本参数时从仓库根目录执行：

```bash
python3 python/std_ble/generate_ble_exadv_iq_30_72M.py --help
python3 python/ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py --help
python3 python/ctc_sim/bluebee/generate_bluebee_iq_30_72M.py --help
python3 python/ctc_sim/std_zigbee/zigbee_rx.py --help
python3 python/ctc_sim/bluebee/bluebee_rx.py --help
```

## 运行约定

- 默认使用 `python3`。
- 离线生成和分析脚本通常需要 `numpy`；部分频谱/绘图脚本还需要 `scipy`、`matplotlib`。
- 实时接收链路需要 GNU Radio、`osmosdr`、HackRF 驱动和 `pyzmq`。
- 新增脚本应支持 `--help`，并把可复制的主线命令写到根目录 `README.md`，不要在本文件重复参数表。
- 生成的 `.h`、`.iq`、`.c64` 和临时捕获文件容易覆盖已有结果；调试时优先输出到 `/tmp`。
- 面向 AD9363 TX DMA 的 30.72 MSPS C 头文件仍使用当前工程约定：`uint32_t` 中高 16 位为 Q、低 16 位为 I，并按双通道 DMA 格式重复采样。

## BLE 协议概述

BLE（Bluetooth Low Energy）工作在 2.4 GHz ISM 频段，共有 40 个信道（37/38/39 为 advertising channel，0~36 为 data channel），信道间隔 2 MHz。本项目的 cross-technology communication（CTC）方案利用 BLE physical layer 的 GFSK 调制来承载 ZigBee 的 DSSS chip 序列，因此必须从物理层角度理解 BLE 的帧结构、调制方式和数据完整性机制。

BLE 核心规范参考 `doc/BLE_Core_v5.1.pdf`（Vol 6, Part B: Link Layer Specification），标准广播包结构参考 `doc/ble_header.png`。

### 1. BLE 链路层数据帧结构

BLE advertising channel PDU 的标准结构：
![ble_header](../doc/ble_header.png)

- **Preamble（1 byte）**：固定 `0xAA`（`10101010`），用于接收端时钟恢复和 AGC 锁定。
- **Access Address（4 bytes）**：advertising channel 固定为 `0x8E89BED6`（小端序无线发送）。Preamble 和 Access Address 共 5 bytes 不经过白化，接收端可以据此做 packet detection。
- **PDU Header（2 bytes）**：包含 PDU Type（如 `ADV_EXT_IND = 0x07`）、RFU、TxAdd、RxAdd、Length 字段。Length 指示 PDU Payload 的字节数。
- **PDU Payload（可变长，≤255 bytes for extended advertising）**：对于 extended advertising primary 包（`ADV_EXT_IND`），核心字段是 `ExtHeader` 中的 `AuxPtr`（包含 secondary channel 和 offset）和 `ADI`（Advertising Data Info）。对于 secondary 包（`AUX_ADV_IND`），核心字段是 `AdvA`（6-byte advertiser address）、`ADI` 和 `AdvData`。
- **CRC（3 bytes）**：24-bit CRC，覆盖 PDU Header + Payload 的全部字节。

**Extended Advertising 的 Primary/Secondary 调度**（[generate_ble_exadv_iq_30_72M.py](std_ble/generate_ble_exadv_iq_30_72M.py)）：

```python
# Primary ADV_EXT_IND 的 ExtHeader 核心结构
ext_header = [BLE_EXT_HDR_FLAG_ADI | BLE_EXT_HDR_FLAG_AUX_PTR]
ext_header.extend(adi)      # Advertising Data Info (2 bytes)
ext_header.extend(aux_ptr)  # channel(6bit) + CA + offset_units + offset(13bit) + PHY
```

AuxPtr 字段 3 bytes 编码了 secondary 包的位置：
- Channel：6 bits → 0~36 的 data channel
- Offset：13 bits，单位为 30 µs（小于 245700 µs 时）或 300 µs（大偏移时）。这告诉接收端 secondary 包在 primary 开始后多少微秒发出，称为 **T_MAFS**（Minimum Aux Frame Spacing，最小 300 µs）。

`create_ext_primary_ll_payload()` 构造 primary PDU → CRC → 白化 → 拼接到 Preamble+AA 之后。`create_ext_secondary_ll_payload()` 构造 secondary PDU，在 BlueBee 模式下还会预补偿白化掩码（见下文）。

### 2. 物理层：GFSK 调制

BLE 1M PHY 使用 **GFSK（Gaussian Frequency Shift Keying）**，调制指数 h=0.5，带宽-符号周期积 BT=0.5。其数学原理（[generate_ble_exadv_iq_30_72M.py:468-490](std_ble/generate_ble_exadv_iq_30_72M.py#L468-L490)）：

**Step 1: NRZ 映射**

每个 BLE bit $b \in \{0, 1\}$ 映射为 NRZ 符号 $s \in \{-1, +1\}$：

$$s[k] = 2 \cdot b[k] - 1 \qquad\Longrightarrow\qquad 0 \rightarrow -1,\; 1 \rightarrow +1$$

**Step 2: 高斯脉冲成形**

GFSK 与普通 FSK 的关键区别在于频率不突变——bit 跳变时，频率经过高斯滤波器平滑过渡。高斯滤波器的冲激响应为：

$$h(t) = \frac{\sqrt{\pi}}{\alpha} \exp\left(-\left(\frac{\pi t}{\alpha}\right)^2\right)$$

$$\text{其中}\quad \alpha = \frac{\sqrt{\ln(2)/2}}{BT}$$

源码中 `get_gaussian_filter(bt=0.5, sps=768, span=4)` 计算此脉冲的离散采样：

```python
t = np.arange(-span * sps / 2, span * sps / 2) / sps
alpha = np.sqrt(np.log(2) / 2) / bt
h = (np.sqrt(np.pi) / alpha) * np.exp(-((np.pi * t / alpha) ** 2))
return h / np.sum(h)
```

NRZ 符号序列先以 768 倍过采，再与高斯滤波器卷积：

```python
nrz_high = np.repeat(symbols, sps_high)
f_sig = np.convolve(nrz_high, h, mode="same")   # f_sig[k] = ∑_m s[m] · h[k - m]
```

**Step 3: 相位积分**

BLE GFSK 的调制指数 $h = 0.5$，每个 bit 贡献 $\pm \pi/2$ 的相位变化。瞬时频率 $f_{sig}[k]$ 决定每采样点的相位增量：

$$\Delta\phi = \frac{\pi}{2 \cdot \text{sps\_high}}, \qquad \phi[k] = \sum_{n=0}^{k} f_{sig}[n] \cdot \Delta\phi$$

```python
phase_step = np.pi / (2 * sps_high)
phase = np.cumsum(f_sig * phase_step)
```

这意味着：
- 连续多个 1：相位单调递增，每个 bit $+\pi/2$，累计形成正频率偏移（约 +250 kHz）
- 连续多个 0：相位单调递减，每个 bit $-\pi/2$，累计形成负频率偏移（约 -250 kHz）

**Step 4: IQ 生成**

```python
i = cos(phase)   # 同相分量
q = sin(phase)   # 正交分量
```

然后抽到目标采样率：30.72 MSPS = 768× 过采 ÷ 25 倍抽取。最终 `uint32_t` 打包为高 16 位 Q、低 16 位 I，每 sample 重复两次满足双通道 DMA 格式。

### 3. CRC 校验：24-bit BLE CRC

BLE 使用 24-bit CRC（[bsp_algorithm.py:39-68](std_ble/bsp_algorithm.py#L39-L68)），生成多项式为：

$$G(x) = x^{24} + x^{10} + x^{9} + x^{6} + x^{5} + x^{4} + x^{3} + x^{2} + x + 1$$

即：`0x5B06_XXXX`（二进制表示中 bit 0、1、2、3、4、5、6、9、10 为 1）。

初始值为 `0x555555`。算法遍历 PDU 的每个字节的每个 bit，LSB-first 处理：

```python
def bt_crc(data, length, init=0x555555):
    ret = [(init >> 16) & 0xff, (init >> 8) & 0xff, init & 0xff]
    for d in data[:length]:
        for v in range(8):
            t = (ret[0] >> 7) & 1           # 最高 bit 移出
            ret[0] <<= 1                     # 24-bit 寄存器左移
            if ret[1] & 0x80: ret[0] |= 1
            ret[1] <<= 1
            if ret[2] & 0x80: ret[1] |= 1
            ret[2] <<= 1
            if d & 1 != t:                   # 输入 bit ≠ 移出 bit → 反馈 XOR
                ret[2] ^= 0x5b
                ret[1] ^= 0x06
            d >>= 1
    # 最终 3 字节各自 bit-reverse
    ret[0] = bt_swap_bits(ret[0] & 0xFF)
    ...
    return ret  # [byte2, byte1, byte0]
```

CRC 计算后追加到 PDU 末尾，然后 **PDU + CRC** 一起进入白化阶段。

### 4. 白化（Data Whitening）

BLE 白化用于避免长串的 0 或 1 导致接收端丢失同步。白化是一个可逆的 XOR 操作——**加密和解密使用相同操作**（[bsp_algorithm.py:11-37](std_ble/bsp_algorithm.py#L11-L37)）。

**原理**：7-bit LFSR（Linear Feedback Shift Register），多项式 $x^{7} + x^{4} + 1$（对应 `0x11`）。

```python
def bt_dewhitening(data, channel):
    lfsr = bt_swap_bits(channel) | 2   # LFSR 种子 = bit_reverse(channel) | 0b10
    for d in data:
        for i in [128, 64, 32, 16, 8, 4, 2, 1]:  # 逐 bit 处理，MSB-first
            if lfsr & 0x80:           # bit7 = 1 → 反馈
                lfsr ^= 0x11          # XOR 多项式（bit4 和 bit0）
                d ^= i                # 白化输出 bit（翻转当前数据 bit）
            lfsr <<= 1
```

LFSR 种子依赖于信道号（`channel` 的 bit-reverse 作为初始值），因此同一 PDU 在不同信道上产生的白化序列不同。这确保了频率分集。

注意：白化只作用于 PDU + CRC，前 5 字节 Preamble + Access Address 不白化，接收端用它们做 packet detection。

**BlueBee 语境下的"反白化"补偿**（[generate_ble_exadv_iq_30_72M.py:431-458](std_ble/generate_ble_exadv_iq_30_72M.py#L431-L458)）：

BlueBee 要求空口上的特定 bit 序列被 ZigBee 接收端看到。但 BLE 发送前会对 PDU 做白化，所以如果直接填入 BlueBee bytes，经过白化后的空口数据会面目全非。解决方案：**在白化前预先对 BlueBee payload 做 XOR 白化掩码**：

```python
mask = whitening_mask(len(pdu) + 3, channel)   # 生成全零数据的白化输出
for i in range(bluebee_len):
    pdu[bluebee_pdu_start + i] ^= mask[bluebee_pdu_start + i]  # 预补偿
```

因为白化是 XOR → 白化后的空口数据 = BlueBee_bytes ⊕ mask ⊕ mask = BlueBee_bytes。这样就保证了 ZigBee 接收端能"看到"设计好的 BlueBee 波形。

---

## ZigBee 协议概述

ZigBee（IEEE 802.15.4）2.4 GHz PHY 使用 **DSSS（Direct Sequence Spread Spectrum）+ O-QPSK**，数据速率 250 kbps，chip 速率 2 Mchip/s。本项目的 BlueBee 方案目标是让 ZigBee 接收机的 DSSS 解扩器将 BLE GFSK 信号"误认"为合法的 ZigBee signal，因此必须深入理解 ZigBee 的帧结构、扩频机制和调制方式。

相关源码主要在 `ctc_sim/std_zigbee/zigbee_mod.py`（发送端）和 `ctc_sim/std_zigbee/zigbee_rx_common.py`（接收端）。

### 1. 802.15.4 PHY 帧结构

标准 ZigBee PHY frame 格式（[zigbee_mod.py:97-105](ctc_sim/std_zigbee/zigbee_mod.py#L97-L105)）：

```
┌──────────────┬─────┬─────┬─────────────┬──────────┐
│   Preamble   │ SFD │ PHR │ MAC Payload │   FCS    │
│   4 bytes    │1 B  │1 B  │  可变长度    │ 2 bytes  │
│   0x00000000 │0xA7 │     │  (≤ 125 B)  │CRC-16    │
└──────────────┴─────┴─────┴─────────────┴──────────┘
```

- **Preamble（4 bytes）**：4 个 `0x00`，经过 DSSS 后对应 8 个 symbol-0（每个 `0x0` → 32-chip 序列 `11011001110000110101001000101110`）。用于接收端 chip-level 同步。
- **SFD（Start-of-Frame Delimiter，1 byte）**：`0xA7`（`10100111`），标志帧开始。
- **PHR（PHY Header，1 byte）**：高 bit 保留为 0，低 7 bit 表示 MAC Payload + FCS 的总字节数（≤ 127）。
- **MAC Payload（可变长）**：应用层数据。
- **FCS（Frame Check Sequence，2 bytes）**：16-bit CRC-CCITT，覆盖 MAC Payload 全部字节。

帧构建源码：

```python
def build_phy_frame(payload_bytes):
    mac_len = len(payload_bytes) + 2     # payload + 2-byte FCS
    fcs = crc16_ccitt(payload_bytes)     # 只对 payload 计算 CRC
    return [0x00]*4 + [SFD, mac_len] + list(payload_bytes) + [fcs&0xFF, (fcs>>8)&0xFF]
```

### 2. DSSS 扩频原理

这是 ZigBee 物理层最核心的设计——**用带宽换鲁棒性**。

**映射规则**：每个 4-bit symbol（0x0 ~ 0xF）映射为一个 32-chip **准正交** PN 序列。16 个序列存在于 `CHIP_MAP` 中（[zigbee_mod.py:9-26](ctc_sim/std_zigbee/zigbee_mod.py#L9-L26)）：

```python
CHIP_MAP = [
    "11011001110000110101001000101110",  # 0x0
    "11101101100111000011010100100010",  # 0x1
    "00101110110110011100001101010010",  # 0x2
    ...
    "11001001011000000111011110111000",  # 0xF
]
```

**扩频的数学本质**：

```
4 bits → 1 symbol → 32 chips → 32 IQ samples (I 路 16 + Q 路 16)
```

- 数据速率：250 kbps → 每 bit 4 µs → 每 4-bit symbol 16 µs
- Chip 速率：2 Mchip/s → 每 chip 0.5 µs → 每 symbol 32 chips
- 处理增益：$10 \cdot \log_{10}(32/4) = 10 \cdot \log_{10}(8) \approx \mathbf{9\text{ dB}}$

这意味着即使接收端信噪比很低，DSSS 解扩后可以将信号能量从 32 chips 集中回 4 bits，获得约 9 dB 的处理增益。

**DSSS 解扩（接收端）**（[zigbee_rx_common.py:78-91](ctc_sim/std_zigbee/zigbee_rx_common.py#L78-L91)）：

```python
def chips_to_symbols(chips):
    for i in range(0, len(chips) - len(chips)%32, 32):
        chunk = chips[i:i+32]
        best_s, best_d = 0, 33
        for s, ref in enumerate(CHIP_MAP):
            d = sum(1 for a, b in zip(chunk, ref) if a != b)  # Hamming distance
            if d < best_d:
                best_d, best_s = d, s
        symbols.append((best_s, best_d))
```

解扩不是"匹配滤波"而是**最小 Hamming distance 判决**：将收到的 32 chips 与 CHIP_MAP 的 16 个参考序列逐一比较，选 Hamming distance 最小的那个 symbol。IEEE 802.15.4 规定符号间最小 Hamming distance ≥ 12，因此接收端最多可以容忍每个 symbol 中有 6 个 chip 错误而仍能正确判决。

### 3. 16-bit CRC-CCITT（FCS）

ZigBee 使用 CRC-16-CCITT（[zigbee_mod.py:85-94](ctc_sim/std_zigbee/zigbee_mod.py#L85-L94)），生成多项式为：

$$G(x) = x^{16} + x^{12} + x^{5} + 1$$

对应的二进制表示：`0x8408`（由于代码中 LSB-first 处理，多项式表示为 `0x8408`，等效于 MSB-first 的 `0x1021`）。

```python
def crc16_ccitt(data, init=0x0000):
    crc = init
    for value in data:
        crc ^= value               # 输入 byte XOR 到 CRC 低 8 位
        for _ in range(8):         # 逐 bit 处理
            if crc & 1:            # LSB = 1 → 反馈
                crc = (crc >> 1) ^ 0x8408  # 右移 + XOR 多项式
            else:
                crc >>= 1
    return crc & 0xFFFF
```

注意：FCS 只覆盖 MAC Payload（不含 Preamble、SFD 和 PHR）。接收端验证时，对收到的 MAC Payload 重新计算 CRC，与收到的 FCS 两字节比较。

**接收端验证**（[zigbee_rx_common.py:140-152](ctc_sim/std_zigbee/zigbee_rx_common.py#L140-L152)）：

```python
def validate_frame(frame):
    phr_len = frame[5]
    payload_len = phr_len - 2
    mac_payload = frame[6:6+payload_len]
    fcs_rx = frame[6+payload_len] | (frame[6+payload_len+1] << 8)
    fcs_calc = crc16_ccitt(mac_payload)
    return fcs_rx == fcs_calc, mac_payload
```

FCS OK 是当前软件侧最强的 ZigBee frame 接收证据——它不仅确认 DSSS 解扩和 byte 还原路径闭合，还确认了整个 payload 的 bit 完整性。

### 4. O-QPSK 物理层调制

ZigBee 2.4 GHz PHY 使用 **O-QPSK（Offset Quadrature Phase Shift Keying）** 将 chip 流映射到 RF 载波。与 standard QPSK 的区别在于：Q 路相对 I 路延迟半个 chip 周期（[zigbee_mod.py:108-134](ctc_sim/std_zigbee/zigbee_mod.py#L108-L134)）。

**调制链**：

```
chip stream (2 Mchip/s)
  ├─ even chips → I 路 (1 Mchip/s)
  └─ odd chips  → Q 路 (1 Mchip/s)，延迟 Tc/2
```

**Step 1: Chip 到 I/Q 分配**

```python
i_chips = chip_bits[0::2]   # 偶数位置 chip → I 路
q_chips = chip_bits[1::2]   # 奇数位置 chip → Q 路
```

每个 chip 为 0 则映射为 -1（相位 180°），为 1 则映射为 +1（相位 0°）。

**Step 2: 半正弦脉冲成形**

与通常的矩形脉冲不同，802.15.4 使用 **half-sine pulse shaping** 来限制频谱带宽：

```python
def half_sine_pulse(samples_per_chip):
    return [math.sin(math.pi * (n + 0.5) / samples_per_chip) for n in range(s_per_chip)]
```

脉冲形状为半个正弦周期（sin(0) → sin(π) ≈ 0 → 0），频谱比矩形脉冲更紧凑。

**Step 3: I/Q 组合与 O-QPSK 延迟**

```python
for c in i_chips:
    i_wave.extend([c * p for p in pulse])     # I 路：偶数 chip × 半正弦
for c in q_chips:
    q_wave.extend([c * p for p in pulse])     # Q 路：奇数 chip × 半正弦

delay = samples_per_chip // 2
q_wave = [0.0] * delay + q_wave               # Q 路延迟半个 chip
```

**O-QPSK 的数学优势**：在标准 QPSK 中，I 和 Q 同时跳变时，信号轨迹穿越原点（零包络），导致较高的峰均比（PAPR）和频谱扩展。O-QPSK 把 Q 路延迟半个 chip，任何时候最多只有一路跳变，轨迹不会过原点，从而降低 PAPR，适合非线性功率放大器。IEEE 802.15.4 选择 O-QPSK + 半正弦脉冲，本质是 **MSK（Minimum Shift Keying）** 的等效形式，具有恒包络特性。

**发送端重采样**（`generate_zigbee_iq_30_72M.py`）：

标准 O-QPSK 在 10 MHz 采样率下生成（2 Mchip/s × 5 samples/chip = 10 MHz，每个 chip 边界落在整数采样点），然后通过 `fft_resample()` 重采样到 30.72 MSPS 以匹配 AD9363 TX 时钟。重采样在 padding 前完成，避免 FFT 把静默 padding 当作周期信号的一部分产生 Gibbs 现象。

---

## 结合源码理解实现

建议按下面顺序读源码：

1. `ctc_sim/std_zigbee/zigbee_mod.py`：先理解标准 ZigBee 的 bit -> chip -> O-QPSK IQ。
2. `std_ble/generate_ble_exadv_iq_30_72M.py`：再理解 BLE PDU -> 白化/CRC -> GFSK IQ，以及 extended advertising 的 primary/secondary 组织。
3. `ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py`：最后看 BlueBee 如何用 BLE GFSK 去模拟 ZigBee chip。
4. `ctc_sim/std_zigbee/zigbee_rx_common.py` 和 `ctc_sim/bluebee/bluebee_rx.py`：从接收端反过来理解检测、解扩和 FCS 验证。

### 1. 统一的数据表示

本仓库脚本里有四层常见数据：

| 层次 | 代码中的表示 | 典型位置 |
|------|--------------|----------|
| byte | Python `list[int]`，每个元素 0..255 | ZigBee payload、BLE PDU、CRC/FCS |
| bit | `"0101..."` 字符串或 `list[int]` | `bytes_to_bits()`、`bits_to_bytes_lsb()` |
| chip | `"0101..."` 字符串，每 32 chip 对应一个 ZigBee 4-bit symbol | `CHIP_MAP`、DSSS 解扩 |
| IQ sample | `numpy` 数组，最后打包为 `uint32_t` | 30.72 MSPS C 头文件 |

注意 bit 序：ZigBee 相关代码默认使用 LSB-first。`ctc_sim/std_zigbee/zigbee_mod.py` 里的 `BIT_ORDER = "lsb"`，`bytes_to_bits()` 按字节低位到高位展开，`bits_to_bytes()` 再按相同约定还原。很多“看起来反了”的字节问题，本质上都要先检查这一层约定。

### 2. 标准 ZigBee 发送链路

标准 ZigBee 发送从 `ctc_sim/std_zigbee/zigbee_mod.py` 开始看：

- `CHIP_MAP` 保存 IEEE 802.15.4 2.4 GHz PHY 的 16 个 4-bit symbol 到 32-chip DSSS 序列的映射。
- `crc16_ccitt()` 计算 MAC payload 的 FCS。
- `build_phy_frame()` 拼出 `4B preamble | SFD | PHR(length) | payload | FCS`。
- `bits_to_chips()` 每 4 bit 查一次 `CHIP_MAP`，把 250 kbps 量级的数据扩成 2 Mchip/s chip 流。
- `oqpsk_modulate()` 把 chip 分到 I/Q 两路，Q 路延迟半个 chip，并使用半正弦脉冲成形。

`ctc_sim/std_zigbee/generate_zigbee_iq_30_72M.py` 是硬件波形版本。它没有改变 PHY 逻辑，而是做工程化处理：

- `generate_zigbee_iq_30_72M()` 先在 10 MHz 下生成 O-QPSK，因为 2 Mchip/s 对应每 chip 5 个采样点，边界是整数采样。
- `fft_resample()` 再把 10 MHz 重采样到 AD9363 TX 常用的 30.72 MSPS。
- 静默 padding 在重采样之后添加，避免 FFT 把 padding 边界当成周期信号的一部分。
- 最后按硬件 DMA 格式打包：高 16 位为 Q，低 16 位为 I，每个 sample 重复两次。

如果学生已经理解 DSSS 和 O-QPSK，可以重点对照 `bits_to_chips()`、`oqpsk_modulate()` 和 `generate_zigbee_iq_30_72M()`，看“理论流程”如何变成“可喂给 DAC DMA 的数组”。

### 3. BLE extended advertising 发送链路

BLE 波形生成主要看 `std_ble/generate_ble_exadv_iq_30_72M.py`。

BLE 链路层包的核心流程在这些函数里：

- `create_ext_primary_ll_payload()` 构造 primary `ADV_EXT_IND`。primary 本身不带完整 AdvData，关键是放 `ADI` 和 `AuxPtr`，告诉接收端 secondary 在哪个 data channel、多久之后出现。
- `build_aux_ptr()` / `decode_aux_ptr()` 负责 AuxPtr 的 30 us / 300 us 单位编码和解码。
- `create_ext_secondary_ll_payload()` 构造 secondary `AUX_ADV_IND`，这里才放 AdvA、ADI 和 AdvData。
- `build_adv_data()` 组 BLE advertising data structure，例如 Flags、Complete Local Name、Manufacturer Specific Data。
- `whiten_ll_pdu()` 对 PDU 追加 BLE CRC，并按信道白化。
- `ble_bits_to_iq_30_72m()` 把 BLE bit 流调成 1M GFSK IQ。

`ble_bits_to_iq_30_72m()` 是理解 BLE GFSK 的核心。它做了四步：

```text
bit 0/1 -> NRZ -1/+1 -> Gaussian filter -> phase integral -> cos/sin IQ
```

源码中先把 bit 映射成 `-1/+1`，再用 `get_gaussian_filter()` 做 BT=0.5 的高斯成形。`phase_step = pi / (2 * sps_high)` 表示 BLE 1M PHY 中每个 bit 近似累积正负 `pi/2` 的相位变化。最后 `i = cos(phase)`、`q = sin(phase)`，并抽取到 30.72 MSPS。

这里要区分两个“信道”概念：

- BLE advertising channel 37/38/39 是 primary 所在频点。
- BLE data channel 0..36 是 AuxPtr 中描述的 secondary channel。

当前同频调试会使用 `--timing-debug-same-channel`，让 secondary 实际也在 primary 频点发射，同时保留 AuxPtr 的编码语义。这个模式主要用于 RF/BlueBee 验证，不等价于让手机严格按规范跟随 AuxPtr。

### 4. BlueBee 的核心映射

BlueBee 的目标不是发一个标准 ZigBee O-QPSK 波形，而是让 ZigBee 接收机“看见”一个足够像 ZigBee DSSS chip 序列的波形。关键源码在 `ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py`，同一套思想也被 `std_ble/generate_ble_exadv_iq_30_72M.py` 复用。

实现逻辑如下：

1. ZigBee 每个 4-bit symbol 对应 32 chip。
2. BLE 1M GFSK 每个 bit 约 1 us；ZigBee 以 2 Mchip/s 观察，相当于每个 BLE bit 会贡献两个相同方向的 chip。
3. 所以 BLE bit 只能稳定模拟 `00` 或 `11` 这种 2-chip pair，无法直接模拟 `01` 或 `10`。
4. `build_bluebee_chip_map()` 为每个 ZigBee symbol 选择一个“pair-constrained”的近似 chip 序列。
5. `zigbee_frame_to_gfsk_bits()` / `zigbee_bytes_to_bluebee_bits()` 再把每个 2-chip pair 转成一个 BLE GFSK bit。

`map-mode=legacy` 的思路是简单按 pair 做多数投票；`map-mode=optimized` 会枚举候选，并用 Hamming distance 打分。优化目标不是让某个 symbol 完全无误，因为很多 pair 本来不可模拟，而是尽量让“正确 symbol 的近似序列”仍然比其他 symbol 更接近标准 `CHIP_MAP`。接收端 DSSS 解扩时本来就按 Hamming distance 选最近 symbol，因此这个优化直接服务于接收机判决。

源码里可以重点看：

- `emulation_candidates()`：枚举一个 symbol 的所有可模拟候选。
- `build_bluebee_chip_map()`：选择 Hamming distance 意义上更稳的候选。
- `zigbee_frame_to_gfsk_bits()`：把 ZigBee frame bytes 转成 BLE GFSK bits。
- `verify_bluebee_roundtrip()`：用标准 ZigBee DSSS 判决反向验证近似 chip 是否还能解回原 frame。

在 extended advertising 组合脚本中还有一个容易忽略的细节：`create_ext_secondary_ll_payload()` 会对 BlueBee bytes 预先异或 whitening mask。原因是 BLE 控制器/波形发送前会对白化后的 bit 上空口；如果想让 ZigBee 侧看到设计好的 BlueBee chip，需要先把要嵌入的 BlueBee bytes 做一次“反白化”补偿，最终经过 BLE whitening 后空口上的对应区域才接近期望的 BlueBee bit 序列。

### 5. 接收链路怎样判断“收到了”

标准 ZigBee 接收和 BlueBee 接收共享一些工具，主要在 `ctc_sim/std_zigbee/zigbee_rx_common.py`：

- `ZMQSubscriber.read_available()` 从 GNU Radio 流图批量取 packed chip bytes，避免 Python 处理慢时积压。
- `unpack_bytes_to_chips()` 把 packed bytes 展开成 chip 字符串。
- `chips_to_symbols()` 每 32 chip 与 `CHIP_MAP` 的 16 个标准序列计算 Hamming distance，选择最近的 symbol。
- `symbols_to_bits()` 和 `bits_to_bytes_lsb()` 把 symbol 还原成 byte。
- `find_preamble()` 查找 `00 00 00 00 A7 length`。
- `validate_frame()` 对 payload 重新计算 FCS，判断 frame 是否真正正确。

BlueBee 接收端 `ctc_sim/bluebee/bluebee_rx.py` 多了两层处理：

- `chips_to_symbols_bluebee()` 不再只用标准 `CHIP_MAP`，而是用 optimized/legacy BlueBee chip map 解 symbol。
- `find_bluebee_detection()` 会遍历 map mode、normal/inverted polarity 和 chip alignment，寻找最可信的 preamble/frame，优先选择 FCS OK 的结果。
- `fast_phase_template_scan()` 用整数滑窗和 `bit_count()` 快速找 BlueBee preamble 模板，降低长缓冲搜索成本。
- `phase_chips_from_iq()` 则体现 BlueBee 论文里的相位差思路：对连续 IQ sample 计算 `angle(s[n] * conj(s[n-1]))`，用相位增量正负切成 chip。

因此本仓库里“检测到 frame”的证据分层如下：

1. 只看到 preamble/SFD：说明同步模式可能出现，但不保证 payload 正确。
2. 能输出完整 frame bytes：说明 DSSS 解扩和 byte 还原路径已经闭合。
3. FCS OK：说明 payload 和 FCS 一致，是当前最强的软件侧证据。

