# 工程备忘录

为了方便之后能快速理解各函数具体功能的实现，在这里记录具体算法实现的思路。

- ad官方的no_OS仓库中仅包含原始例程
- 微相官方实现了command.c，其中主要包含了通过串口读取和控制ad9363的基础功能
- 我在command.c中添加了几个demo用于输出一些状态信息和测试dma发送/接收功能
- 几个蓝牙物理层模拟的函数实现在以下源文件中：
  - ble_rx_adi_glue.c
  - ble_rx.c
  - ble_tx_adv.c
  - ble.c

## BLE相关算法

目前本项目仅支持BLE

### BLE的RX链路

BLE的RX链路是比较简单的，因为GFSK本质上还是FSK,接收方其实依据一般FSK的解调模式实现即可，最多再根据具体参数进行微调。

本项目使用的解调算法为差分正交解调算法实现BLE信号的解调，在非相干差分解调算法中，这是最适合BLE的。相干解调虽然性能确实更好，但是高精度的载波同步对设备性能和算法设计要求很高，并不契合BLE对低成本和低功耗的核心要求。

具体函数处理流程：

- 通过command读取串口命令进入ble_rx_service_start接口
- ble_rx_service_init_once初始化信道参数和rx链路dma，设置rx中心频率
- 之后在主函数的while循环里不断执行ble_rx_service_poll,该函数会依次调用rx所需的各种接口尝试解析出BLE广播数据包，这里为了便于调试，当长时间没有检测到BLE信号后，会尝试翻转比特值或IQ顺序来检查是否是数据格式错误
  - 可以通过注释掉计数器递增命令来关闭这种切换
- 几个接口函数会从dma中读取接收到的IQ数据，并尝试从中分析出BLE数据包，具体执行不再赘述，都是标准流程，主要记录一下符号判决的实现
  - 符号判决实现在ble_rx_port_process_iq_i16中
  - 使用的方法是差分正交解调
  - 需要额外注意，无论是否启用ad936x的2T2R模式，dma中的数据都是双通道的，所以处理的时候要选择正确的数据

符号判决实现：

- 差分正交解调依赖于以下规律：
  - 信号两个相邻采样点的相位差，等于当前IQ数据与前一个IQ数据共轭的乘积结果的虚部，这是因为对于复指数来说，乘以共轭相当于做减法

```c
metric = (float)rx->prev_i * (float)q - (float)rx->prev_q * (float)i;       //通过欧拉公式转换复指数后计算
rx->prev_i = i;
rx->prev_q = q;
if (metric >= 0.0f)                 //累计相位变化
    rx->metric_acc += metric;
else
    rx->metric_acc -= metric;
rx->sym_metric_sum += metric;       //判决指标
rx->phase_acc += 1.0f;              //累计采样数

if (rx->phase_acc >= rx->samples_per_symbol) {      //采样数达到单个符号的长度就进行判决
    bit = (rx->sym_metric_sum >= 0.0f) ? 1u : 0u;   //比特判决
    rx->phase_acc -= (float)rx->samples_per_symbol;
    rx->bit_acc |= (uint8_t)(bit << rx->bit_count); //组装字节
    rx->bit_count++;
    rx->sym_metric_sum = 0.0f;

    if (rx->bit_count == 8u) {
        rx->sym_count += 8u;
        append_byte_and_parse(rx, rx->bit_acc);     //判断是否能够成帧
        rx->bit_acc = 0u;
        rx->bit_count = 0u;
    }
}
```

实验中可以确认这套流程能够检测到BLE信号，但是有效检测数量不稳定，这可能是因为我们采用的是：“固定每符号采样数+硬积分判决”，采样点没有做对齐操作，尝试了gardner和早迟门算法，但是最后发现效果有限，所以单纯增加了一级FIR改善性能。

### BLE的TX链路

TX的核心思路是将生成的IQ数据通过dma传输给ad9363再发射，有几种不同的实现。

#### 直接使用FSK

第一种调制方式实现在build_adv_iq_words,由于BLE使用的GFSK本质上也是FSK,所以直接使用FSK生成IQ数据也是能被其他BLE设备识别的。

具体实现原理为利用复数旋转生成特定的频率偏移：

```c
ni = (i * c - q * rot_s) >> 15;
nq = (i * rot_s - q * c) >> 15;
```

c和rot_s为每次旋转的角度对应的cos和sin值，比特1对应正向旋转，比特0对应负向旋转，具体的角度来自于采样率和和频偏大小，本项目硬件采样率30.72MHz,频偏250kHz,对应弧度：

$$
\theta = 2\pi * 250000 / 30720000 \approx 0.05115
$$

对应角度2.93度，为了对应16位硬件，进行缩放，得到的正弦值：32768 * sin(0.05115) = 1675；得到余弦值：32768 * cos(0.05115) = 32724

为了保证精度，先使用32位数运算，再截取高位。每次依据符号率和采样率关系计算出每个符号所需的采样点，旋转足够次数后，切换下一个采样地进行新的旋转。最后按照双通道dma的形式存储到数组中即可。

#### 引入高斯滤波

直接使用FSK生成BLE信号是可以被商用设备识别的，但是其信号质量会比较差，这是因为符号跳变太过剧烈，这引入了额外的高频分量，使得信号频谱变宽；通过高斯滤波，使得信号的能量集中在目标频率附近，减少了相邻信道间的干扰，也提高了频谱利用率。代码实现为：build_adv_iq_words_gfsk函数

c语言的具体实现其实是对python脚本的移植，其原理是完全一致的，具体参考python代码的说明。为了保证卷积时窗口没有超出数组范围，代码里利用了有符号数和无符号数的的转换：

```c
for (uint32_t n_out = 0u; n_out < out_samples; n_out++) {
  uint32_t n = n_out * BLE_GFSK_DECIM;
  float acc = 0.0f;
  int32_t start = (int32_t)n - (int32_t)(BLE_GFSK_TAPS / 2u);

  for (uint32_t k = 0u; k < BLE_GFSK_TAPS; k++) {
      int32_t idx = start + (int32_t)k;
      //由于start可能为负，为了避免越界，此处将有符号数强制转换为无符号数，如果索引为负，则一定大于high_count
      if ((uint32_t)idx < high_count) {
          uint32_t bit_idx = (uint32_t)idx / BLE_GFSK_SPS_HIGH;
          uint8_t bit = get_bit_lsb_first(pkt, bit_idx);
          float sym = bit ? 1.0f : -1.0f;
          acc += ble_gfsk_taps[k] * sym;
        }
    }
  phase += acc * phase_step_decim;
}
```

但此处有一个额外需要考虑的问题，为了匹配ad9363的30.72MHz的采样率，我们要将原本1MHz符号率下的比特流先上采样768倍，滤波处理后再降采样25倍。对于zynq7020搭载的arm A9处理器而言，这种运算量太过巨大了，单个数据包可能需要将近10秒的时间来生成全部波形。

为了简化计算，我们没有计算全部的点，而是只计算抽样的点，最后累加得到相位增量。优化后性能提升还是比较显著的，大概只需要3秒左右的时间就能生成一个BLE包。但总体上来说性能并不够用。

#### 引入相位增量表

高斯滤波器具有记忆性，当前时刻的输出不仅取决于当前值，也受前后比特的影响。具体受几个比特的影响取决于滤波器的SPAN参数设置，一般在3-8,SPAN的值越大，滤波效果越好，但计算开销越大。本代码设置为3.

实际实现中，主要通过init_ble_gfsk_phase_lut生成lut,不同于上一般依次计算每一个比特之间的相位变化，以3个比特为一组，计算出所有的可能后存入lut,在生成波形时每次直接查表处理3个比特，不再重复计算，节省大量时间。此时实际执行时，初始化完成后，新波形生成速度可以控制在1秒左右，且只需要初始化一次，之后可复用lut.
