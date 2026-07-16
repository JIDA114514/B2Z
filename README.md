# B2Z

主要开发基于 BLE 的跨技术通信（cross technology communication, CTC），具体原理基于 [BlueBee](https://doi.org/10.1145/3131672.3131678)。

当前主线是 FreeRTOS 分支：在 Zynq-7020 / AD9363 上运行 `app_FreeRTOS/`下的代码，使用 BLE extended advertising 的 primary/secondary 双包调度外壳，将 BlueBee 构造的 ZigBee frame 放入 secondary 包。常用工作流有两类：

- Python 端离线生成 IQ/C 头文件，用于分析、SDK 集成或 HackRF/接收链路验证。
- FreeRTOS 串口命令在板端启动 legacy BLE、切换共享 TX DMA 波形，或运行时生成 BlueBee / BLE exadv secondary 波形。

使用的硬件为 MicroPhase 的 e310，上面搭载 Zynq-7020 和 AD9363。

代码来自于 [MicroPhase 官方](https://github.com/MicroPhase/antsdr_standalone)的裸机代码程序，需要注意 hdl 中用于 e310 开发板的 Vivado 项目为 `antsdre310` 而非 `e310v2`。`e310v2` 的代码生成后在下板执行时可能会报错。

## 当前 Python 波形脚本

### BLE extended advertising + BlueBee secondary

`python/std_ble/generate_ble_exadv_iq_30_72M.py` 生成标准 BLE extended advertising 的 primary `ADV_EXT_IND` 和 secondary `AUX_ADV_IND` IQ 波形，并可把 BlueBee/ZigBee 负载追加到 secondary AdvData 中。

常用参数：

| 参数 | 说明 |
|------|------|
| `--channel` | legacy 单 primary 通道参数；默认 37。未设置 `--primary-channels` 时可用它指定 primary。 |
| `--primary-channels` | 一个 advertising event 中的 primary 通道列表，逗号分隔；默认 `39`。 |
| `--primary-spacing-us` | 多 primary PDU 的 start-to-start 间隔；默认 `9000`，需为 30 us 的整数倍。 |
| `--secondary-channel` | AuxPtr 编码的 secondary BLE data channel；默认 `3`。 |
| `--aux-offset-us` | primary 中 AuxPtr 编码的 secondary 偏移；默认 `30000` us。 |
| `--timing-debug-same-channel` | 调试模式：secondary 实际发在 primary 通道上，但 AuxPtr 仍编码为 `--secondary-channel`。当前同频验证常用该模式。 |
| `--diagnostic-profile` | 手机显示诊断 profile：`baseline-nonconn-nonscan`、`connectable-advdata`、`no-flags-name-only`；默认 `connectable-advdata`。 |
| `--include-flags` / `--no-include-flags` | 覆盖 profile 中是否加入 BLE Flags AD structure。 |
| `--no-name` | 省略 Complete Local Name，给 BlueBee 负载留出更多 AdvData 空间。 |
| `--append-bluebee-zigbee` | 在 secondary AdvData 后追加 BlueBee 构造的 ZigBee 内容。 |
| `--zigbee-payload` | BlueBee 模式下的 ZigBee payload，例如 `"0x11 0x22 0x33 0x44"`；默认是 46 字节 `0x00` 到 `0x2D`。 |
| `--bluebee-embed-mode` | `payload` 只映射 payload；`preamble` 映射 `00 00 00 00 A7 00`；`phy-frame` 映射完整 ZigBee PHY frame。默认 `phy-frame`。 |
| `--bluebee-ad-mode` | BlueBee bytes 在 AdvData 中的封装：`manufacturer` 或 `raw`；默认 `manufacturer`。 |
| `--company-id` | manufacturer AD structure 使用的 company ID；默认 `0xFFFF`。 |
| `--map-mode` | BlueBee chip-map：`legacy` 或 `optimized`；默认 `optimized`。 |
| `--phase-polarity` | 相位符号测试：`normal` 或 `inverted`；默认 `normal`。 |
| `--bt` | BLE Gaussian BT；默认 `0.5`。 |
| `--post-pad-us` | 每个 packet 后追加的零 IQ 静默；默认 `10` us。 |
| `--secondary-pre-pad-us` | AUX_ADV_IND 前追加的零 IQ 静默；默认 `0` us。 |
| `--output` | 输出 C 头文件路径；默认 `python/std_ble/ble_exadv_waveform_30_72M.h`。 |
| `--primary-symbol-name` / `--secondary-symbol-name` | 输出 C 数组符号名。 |

当前同频 BlueBee/secondary 验证示例：

```bash
python3 python/std_ble/generate_ble_exadv_iq_30_72M.py \
  --channel 39 \
  --timing-debug-same-channel \
  --append-bluebee-zigbee \
  --bluebee-embed-mode phy-frame \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --aux-offset-us 600 \
  --post-pad-us 10 \
  --output /tmp/ble_exadv_waveform_30_72M.h
```

### 纯 BlueBee ZigBee frame

`python/ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py` 生成纯 BlueBee PHY emulation 的 ZigBee PHY frame IQ，不包 BLE advertising PDU，适合单独验证 BlueBee 到 ZigBee 的投影关系和接收脚本。

常用参数：

| 参数 | 说明 |
|------|------|
| `--zigbee-payload` | ZigBee payload；默认 `"0x11 0x22 0x33 0x44"`。 |
| `--bt` | Gaussian filter BT；默认 `0.5`。 |
| `--post-pad-us` | frame 后静默；默认 `1000` us。 |
| `--map-mode` | `legacy` 或 `optimized`；默认 `optimized`。 |
| `--phase-polarity` | `normal` 或 `inverted`；默认 `normal`。 |
| `--output` | 输出 C 头文件路径；默认 `python/ctc_sim/bluebee/bluebee_zigbee_frame_30_72M.h`。 |
| `--output-iq` | 可选 complex64 IQ 文件，供 HackRF/offline analysis 使用。 |
| `--symbol-name` | 输出 C 数组名；默认 `bluebee_zigbee_frame_iq`。 |
| `--sdk-output` | 同时写出 `zigbee_tx.c/.h` 到 SDK source 目录。 |

示例：

```bash
python3 python/ctc_sim/bluebee/generate_bluebee_zigbee_frame_iq_30_72M.py \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --map-mode optimized \
  --phase-polarity normal \
  --post-pad-us 1000 \
  --output /tmp/bluebee_zigbee_frame_30_72M.h \
  --output-iq /tmp/bluebee_zigbee_frame_30_72M.iq
```

### BlueBee BLE 组合脚本

`python/ctc_sim/bluebee/generate_bluebee_iq_30_72M.py` 是 BlueBee 调试用的组合生成器，支持三种 profile：

| `--profile` | 用途 |
|-------------|------|
| `extended` | 生成 primary `ADV_EXT_IND` + secondary `AUX_ADV_IND`；默认模式。 |
| `ble-visible` | 生成 BLE 可见的单包 advertising 形态，用于手机可见性调试。 |
| `zigbee-frame` | 生成 BlueBee 构造的 ZigBee frame 波形。 |

常用参数包括 `--embed-mode`、`--zigbee-payload`、`--channel`、`--secondary-channel`、`--aux-offset-us`、`--ext-adv-mode`、`--post-pad-us`、`--map-mode`、`--phase-polarity`、`--preamble-repeats`、`--ad-mode`、`--include-flags` / `--no-include-flags`、`--company-id` 和输出符号名参数。默认 `--profile extended`、primary channel `39`、secondary channel `3`、AuxOffset `6990` us、`--post-pad-us 10`、`--map-mode optimized`。

示例：

```bash
python3 python/ctc_sim/bluebee/generate_bluebee_iq_30_72M.py \
  --profile extended \
  --embed-mode phy-frame \
  --zigbee-payload "0x11 0x22 0x33 0x44" \
  --channel 39 \
  --secondary-channel 3 \
  --aux-offset-us 6990 \
  --post-pad-us 10 \
  --output /tmp/bluebee_waveform_30_72M.h
```

## 当前 FreeRTOS 串口命令

FreeRTOS 运行时入口在 `app_FreeRTOS/`。串口 console task 会先处理带原始字符串参数的 BLE/BlueBee 命令，再回落到 AD9361/no-OS 原有命令表。

| 命令 | 作用 |
|------|------|
| `ble_tx_adv_name=<name>` | 设置 Complete Local Name，并启动 legacy advertising，在 ch37/ch38/ch39 轮发。 |
| `ble_tx_stop?` | 停止当前共享 TX DMA advertising 发送并恢复 DDS。 |
| `dma_tx_demo?` | 使用共享 TX DMA 发送内置 BLE ch39 legacy advertising 波形。 |
| `dma_switch?` | 在 `dma_tx_waveforms` 注册的 cyclic DMA 波形之间切换。 |
| `bluebee_gen_demo? [hex payload]` | 运行时构造纯 BlueBee ZigBee frame 并启动 cyclic TX DMA。无 payload 时使用默认 `11 22 33 44`。 |
| `ble_exadv_secondary_gen? [hex ZigBee payload]` | 运行时构造 BLE exadv secondary + BlueBee/ZigBee 波形并启动 cyclic TX DMA。无 payload 时使用默认 46 字节负载。执行时会先输出 `ble_exadv_secondary_gen: generating waveform...`。 |

十六进制 payload 每个 token 最多 1 字节，可使用空格、逗号、冒号或分号分隔，`0x` 前缀可选。当前运行时 BlueBee payload 上限为 46 字节。

串口示例：

```text
ble_tx_adv_name=B2Z
ble_tx_stop?
dma_tx_demo?
dma_switch?
bluebee_gen_demo?
bluebee_gen_demo? 11 22 33 44
bluebee_gen_demo? 0x11,0x22,0x33,0x44
ble_exadv_secondary_gen?
ble_exadv_secondary_gen? 00 01 02 03 04
```

`ble_exadv_secondary_gen?` 默认负载是当前手机可检测阈值内的 46 字节 ZigBee payload；nRF Connect 主要用于确认 ch39 primary 可见，HackRF 或其他接收链路用于确认 secondary/BlueBee 波形在 2480 MHz，`python/ctc_sim/std_zigbee/zigbee_rx.py` 或 BlueBee 接收脚本用于检查 ZigBee frame bytes/FCS。

## Windows下复原vivado工程

### 所需软件

- git (用于从github上下载源码)
- vivado2021.1（用于复原工程）
- vitis 2021.1（用于搭建no-OS测试程序）

### 下载源码

首先需要从github上下载对应的源码。打开**git bash**，然后在mingwin中使用如下命令下载源码。

```bash
git clone --recursive https://github.com/MicroPhase/antsdr_standalone.git
```

![image-20210924190649784](README.assets/image-20210924190649784.png)

注意：在下载源码的时候，使用--recursive会递归的下载子模块当中的文件，只有这样才能保证所需要的版本是一致的。

![image-20221107172649783](README.assets/image-20221107172649783.png)

下载完源码之后，你将会看到有一个**hdl**文件夹。接下来就介绍如何在windows下使用vivado2021.1来复原工程。

### 使用vivado tcl命令行复原工程

关于使用vivado复原工程，可以参考adi官方说明：[ADI HDL Building](https://wiki.analog.com/resources/fpga/docs/build)

打开vivado2019.1，在tcl命令窗口中进入到antsdr工程所在的目录：具体的路径你自己的情况而定。主要是定位到hdl/project/antsdre310或者hdl/project/antsdre200目录下。

![image-20221107172535645](README.assets/image-20221107172535645.png)

然后依次执行如下命令：

```tcl
source ../scripts/adi_make.tcl
adi_make::lib all
source ./system_project.tcl
```

执行上述命令后，vivado将会依次检查所需要的IP，创建所需要的IP，生成Vivado工程并完成bit文件的生成。

![image-20210924191721108](README.assets/image-20210924191721108.png)

Vivado在构建IP和工程的时候，需要等待较长的时间，请耐心等待。

![image-20210924193419017](README.assets/image-20210924193419017.png)

![image-20210924193351690](README.assets/image-20210924193351690.png)

等到整个工程综合完成之后，可以在该工程的 **antsdre310.sdk**或者**antsdre200.sdk**文件夹下找到硬件描述文件，使用这个硬件描述文件，可以用来搭建no-OS工程。

### 搭建no-OS工程

对于Windows用户，为了简单构建no-OS的过程，请直接使用已经提供好的no-OS源码，也就是在git下载下来的源文件下的app_e310或者app_e200文件夹下的代码。

打开vitis软件，定位到**antsdrxxx.sdk**目录下

![image-20230207130507006](README.assets/image-20230207130507006.png)

创建新的工程

![image-20230207130611520](README.assets/image-20230207130611520.png)

首先需要根据导出的.xsa文件,创建一个硬件平台。

![image-20230207130651797](README.assets/image-20230207130651797.png)

![image-20230207130938975](README.assets/image-20230207130938975.png)

![image-20230207131005309](README.assets/image-20230207131005309.png)

创建好硬件平台之后，就可以创建一个新的软件工程了。

![image-20230207131059350](README.assets/image-20230207131059350.png)

在选择模板的时候，选择一个空的工程就可以了。

![image-20230207131141754](README.assets/image-20230207131141754.png)

然后将仓库当中的app_e200或者app_e310拷贝到当前的src文件夹下，然后点击编译，就可以生成可执行程序了。

![image-20230207131326326](README.assets/image-20230207131326326.png)

### 功能测试

接下来就可以连接串口jtag到到电脑上，然后在SDK中生成调试用的elf文件进行调试了。

![image-20210924232424492](README.assets/image-20210924232424492.png)

### NOTE

工程基于ADRV9361,可以支持2R2T,可以通过串口修改本振，采样率，增益，基带信号的频率，幅度等。
