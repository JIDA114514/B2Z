import math

def generate_iq_lut(N=1000, M=266, amplitude=9830, i_high_q_low=False):
    """
    生成用于 DMA 发送的 IQ 查找表
    N: 数组总长度 (点数)
    M: 在这 N 个点中包含的完整正弦波周期数 (必须是整数！)
       基带频率偏移 = (M / N) * tx_sampling_freq
    amplitude: 幅度。满量程是 32767，建议留一点裕量(如30000)避免DAC数字滤波器溢出
    i_high_q_low: 决定 32-bit 中 I 和 Q 的高低位顺序
    """
    lut = []
    for k in range(N):
        # 计算当前点的相位 (使用复指数 e^(j*wt) = cos(wt) + j*sin(wt))
        theta = 2.0 * math.pi * M * k / N
        
        # I 路为余弦，Q 路为正弦 (构成标准单音)
        i_val = int(round(amplitude * math.cos(theta)))
        q_val = int(round(amplitude * math.sin(theta)))
        
        # 限制在 16-bit 有符号整数范围内
        i_val = max(-32768, min(32767, i_val))
        q_val = max(-32768, min(32767, q_val))
        
        # 转换为无符号 16-bit 十六进制 (处理负数的二补码)
        i_hex = i_val & 0xFFFF
        q_hex = q_val & 0xFFFF
        
        # 打包成 32-bit (根据你的 HDL 链路，通常 ADI 的 DMA 期望低 16 位是 I，高 16 位是 Q)
        if i_high_q_low:
            word = (i_hex << 16) | q_hex
        else:
            word = (q_hex << 16) | i_hex 
            
        lut.append(word)
        lut.append(word)
    return lut

# ================= 配置区 =================
N_SAMPLES = 768
CYCLES = 25  # 必须是整数！比如设为1，如果采样率是4MHz，则基带频偏为 (1/1024)*4M ≈ 3.9kHz
AMP = 9830 # 留点裕量

# 生成数据
vals = generate_iq_lut(N=N_SAMPLES, M=CYCLES, amplitude=AMP, i_high_q_low=False)

# ================= 打印输出 =================
print(f"// CYCLES={CYCLES}, N={N_SAMPLES}, AMPLITUDE={AMP}")
print(f"const uint32_t custom_iq_lut[{N_SAMPLES} * 2] __attribute__((aligned)) = {{")
for i in range(0, len(vals), 8):
    chunk = vals[i:i+8]
    # 格式化为 8 位的十六进制并以逗号分割
    line = ", ".join([f"0x{v:08X}" for v in chunk])
    if i + 8 < len(vals):
        line += ","
    print("    " + line)
print("};")
