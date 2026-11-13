"""C1/legacy generated waveform validation; no RF measurements."""
import binascii
import ctypes as C
import unittest
import numpy as np
from scipy.signal import resample_poly
from python.perf_test.tests.test_b2z_control_generator import ControlGeneratorTests, Packet, read_bytes
from python.perf_test.tests.test_bluebee_gen_waveform import iq_complex, demodulate_center_bits
from python.zigbee_rx.tests.test_zigbee_receiver import decode
from python.exadv_rx.protocol import whiten, crc24

class CompactMeta(C.Structure):
    _fields_=[('ble_count',C.c_uint32),('iq',C.POINTER(C.c_uint32)*4),
              ('iq_bytes',C.c_uint32*4),('air_us',C.c_uint32*4)]

class CompactTests(unittest.TestCase):
    setUpClass=classmethod(ControlGeneratorTests.setUpClass.__func__)
    tearDownClass=classmethod(ControlGeneratorTests.tearDownClass.__func__)

    def test_compact_modes_and_fragment_waveforms(self):
        fn=self.lib.b2z_compact_build
        fn.argtypes=[C.POINTER(Packet),C.c_uint32,C.c_uint32,C.c_uint8]
        self.lib.b2z_compact_get_meta.restype=C.POINTER(CompactMeta)
        p=Packet(2411,7,3500,500,8,6500,5500,1,1,1,2,1,2)
        for b,z,jcost,lcost in [(0,0,1648,1456),(26,0,1856,2464),(2,6,1856,1984)]:
            self.assertEqual(fn(C.byref(p),b,z,0),0)
            m=self.lib.ble_exadv_secondary_gen_get_last_meta().contents
            ble=read_bytes(m.ble_control_record,26+b)
            ieee=read_bytes(m.zigbee_payload,26+z)
            for n,data in [(b,ble),(z,ieee)]:
                self.assertEqual(data[0],0xc1)
                self.assertEqual(data[23],n)
                self.assertEqual(int.from_bytes(data[-2:],'little'),binascii.crc_hqx(data[:-2],0xffff))
                self.assertEqual(int.from_bytes(data[4:8],'little')*int.from_bytes(data[8:10],'little'),3500)
                self.assertEqual(int.from_bytes(data[19:21],'little'),2000)
                self.assertEqual(int.from_bytes(data[21:23],'little'),3000)
            self.assertEqual(m.primary_air_us+m.air_us,jcost)
            self.assertEqual(m.pdu_len,181+b+4*z)
            ll=read_bytes(m.ll_payload,m.ll_payload_len)
            self.assertEqual(whiten(ll[5:],3),read_bytes(m.pdu,m.pdu_len)+crc24(read_bytes(m.pdu,m.pdu_len)))
            self.assertEqual(fn(C.byref(p),b,z,1),0)
            m=self.lib.ble_exadv_secondary_gen_get_last_meta().contents
            lc=self.lib.b2z_compact_get_meta().contents
            self.assertEqual(read_bytes(m.ble_control_record,26+b),ble)
            self.assertEqual(sum(lc.air_us[:lc.ble_count])+m.ieee_air_us,lcost)
            chunks=[]
            for k in range(lc.ble_count):
                iq=iq_complex(np.ctypeslib.as_array(lc.iq[k],shape=(lc.iq_bytes[k]//4,))[::2])
                bits=demodulate_center_bits(iq,lc.air_us[k])
                ll=np.packbits(bits,bitorder='little').tobytes()
                self.assertEqual(ll[:5],bytes.fromhex('aad6be898e'))
                raw=whiten(ll[5:],39);pdu=raw[:-3]
                self.assertEqual(raw[-3:],crc24(pdu))
                self.assertEqual(pdu[0],0x42)
                self.assertEqual(pdu[1],len(pdu)-2)
                self.assertEqual(pdu[2:8],bytes.fromhex('a6a5a4a3a2c1'))
                self.assertLessEqual(len(pdu)-8,31)
                data=pdu[12:]
                if lc.ble_count==1:chunks.append(data)
                else:
                    self.assertEqual((data[0],data[7],data[8],data[9]),(0xc2,k,lc.ble_count,len(ble)))
                    self.assertEqual(int.from_bytes(data[1:3],'little'),p.run_id)
                    self.assertEqual(int.from_bytes(data[3:7],'little'),p.command_id)
                    chunks.append(data[10:])
            self.assertEqual(b''.join(chunks),ble)
            iq=iq_complex(np.ctypeslib.as_array(m.ieee_iq_words,shape=(m.ieee_iq_byte_count//4,))[::2])
            iq4=resample_poly(iq,25,192).astype(np.complex64)
            _,records=decode(np.concatenate((np.zeros(400,np.complex64),iq4,np.zeros(1200,np.complex64))),sample_rate=4000000)
            valid=[r for r in records if r['fcs_ok']]
            self.assertEqual(len(valid),1)
            self.assertEqual(bytes.fromhex(valid[0]['payload_hex']),ieee)
        self.assertEqual(fn(C.byref(p),27,0,0),-1)
        p.execute_at_ms=p.ref_tick_ms+65536
        self.assertEqual(fn(C.byref(p),0,0,0),-1)

if __name__=='__main__':unittest.main()
