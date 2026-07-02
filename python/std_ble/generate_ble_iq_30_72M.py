import numpy as np
import sys
import os

from bsp_string import bsp_string
from bsp_algorithm import bsp_algorithm

def create_ll_payload(mac, adv_data, channel, debug = True):

    ll_payload = [0xAA,0xD6,0xBE,0x89,0x8E] #  preamble + access address
                                            #  PDU-Header   
    flags = bytes.fromhex("020106")     
    # 组装广播 PDU
    pdu_adv = []
    pdu_adv.extend([0x42, (len(adv_data)+9) & 0xFF])    # PDU-Header
    pdu_adv.extend(reversed(mac))                       # PDU-Payload-Adva(实际 MAC 的的反转)
    pdu_adv.extend(flags)
    pdu_adv.extend(adv_data)                            # PDU-Payload-AdvData

    # 生成 CRC(基于PDU)
    crc = bsp_algorithm.bt_crc(pdu_adv, len(pdu_adv))    # CRC 只对 PDU 进行
    
    # 加白(基于PDU+CRC)
    pdu_adv_crc = pdu_adv + crc
    pdu_adv_crc_wt = bsp_algorithm.bt_dewhitening(pdu_adv_crc,channel)

    # 最终组装
    ll_payload.extend(pdu_adv_crc_wt)
    bsp_string.print_data_list_hex("> pre_wt_adv_pdu:", pdu_adv)
    bsp_string.print_data_list_hex("\n> ll data final:", ll_payload)
    bsp_string.print_data_list_hex("\n> crc:", crc)
    # 打印
    if debug:
        # bsp_string.print_data_list_hex("> pre_wt_adv_pdu:", pdu_adv)
        # bsp_string.print_data_list_hex("\n> ll data final:", ll_payload)
        # bsp_string.print_data_list_hex("\n> crc:", crc)
        print(f"pdu_adv: {pdu_adv} \n")

    return ll_payload


def get_gaussian_filter(BT, sps, span=4):
    t = np.arange(-span*sps/2, span*sps/2) / sps
    alpha = np.sqrt(np.log(2) / 2) / BT
    h = (np.sqrt(np.pi) / alpha) * np.exp(- (np.pi * t / alpha)**2)
    return h / np.sum(h)

def generate_ble_iq_30_72M(mac, adv_datas, channel):
    # 1. Generate payload
    ll_datas = create_ll_payload(mac, adv_datas, channel, debug=False)
    
    # 2. Bits to symbols
    bits = bsp_string.bytes_to_bits_lsb(ll_datas)
    symbols = np.array(list(bits), dtype=np.float32) * 2 - 1
    
    # 3. Upsample to 768 Msps
    sps_high = 768
    nrz_high = np.repeat(symbols, sps_high)
    
    # 4. Gaussian filter
    h = get_gaussian_filter(BT=0.5, sps=sps_high, span=4)
    f_sig = np.convolve(nrz_high, h, mode='same')
    
    # 5. Phase integration
    phase_step = np.pi / (2 * sps_high)
    phase = np.cumsum(f_sig * phase_step)
    
    # 6. IQ at 768 Msps
    I_high = np.cos(phase)
    Q_high = np.sin(phase)
    
    # 7. Downsample to 30.72 Msps (decimate by 25)
    I_out = I_high[::25]
    Q_out = Q_high[::25]
    
    # 8. Scale and convert to hex
    I_int = np.round(I_out * 10000).astype(int)
    Q_int = np.round(Q_out * 10000).astype(int)
    
    I_uint16 = I_int & 0xFFFF
    Q_uint16 = Q_int & 0xFFFF
    iq_uint32 = (Q_uint16 << 16) | I_uint16
    
    # 9. 满足 DMA 双通道需求，每个数据重复两遍
    iq_uint32_repeated = np.repeat(iq_uint32, 2)
    
    return iq_uint32_repeated

if __name__ == '__main__':
    mac = [0xFF,0x22,0x33,0x44,0x55,0xFF]
    adv_name = "SDR_BLE"
    adv_datas = [len(adv_name) + 1, 0x09] + [ord(char) for char in adv_name]
    channel = 39
    
    iq_data = generate_ble_iq_30_72M(mac, adv_datas, channel)
    
    output_filename = "ble_waveform_30_72M.h"
    with open(output_filename, "w") as f:
        f.write("// Auto-generated BLE Waveforms\n")
        f.write("// Sample Rate: 30.72 MSPS (Dual Channel Interleaved)\n")
        f.write(f"// Channel: {channel}\n\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"const uint32_t ble_iq_ch{channel}[{len(iq_data)}] __attribute__((aligned(64))) = {{\n")
        
        for i in range(0, len(iq_data), 8):
            chunk = iq_data[i:i+8]
            hex_strs = [f"0x{val:08X}" for val in chunk]
            f.write("    " + ", ".join(hex_strs))
            if i + 8 < len(iq_data):
                f.write(",\n")
            else:
                f.write("\n")
                
        f.write("};\n")
    print(f"Generated {len(iq_data)} samples to {output_filename}")
