import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'validate_saved_iq.py'
spec=importlib.util.spec_from_file_location('reference_validation',SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def packet():
    # Known fixture is used only to test the post-BLE-CRC byte parser.
    frame=bytes.fromhex('00000000a720b25a010a192800000000b617b605646f44eaa6f95413618e4a89429a56d8125b')
    symbols=[int(bits[i:i+4],2) for byte in frame for bits in [f'{byte:08b}'[::-1]] for i in (0,4)]
    encoded=b''.join(m.WORDS[s].to_bytes(2,'little') for s in symbols)
    adv=bytes.fromhex('020106020953')+bytes([len(encoded)+3,255,255,255])+encoded
    ext=bytes.fromhex('4909a6a5a4a3a2c10000')+adv
    pdu=bytearray(bytes([0x47,len(ext)])+ext)
    mask=m.BLE.whiten(bytes(len(pdu)),39)
    for i in range(22,len(pdu)):
        pdu[i]^=mask[i]
    return {'pdu_hex':pdu.hex(),'crc_hex':m.BLE.crc24(pdu).hex(),'crc_ok':True,
            'whitening_channel':39,'channel':39,'sample_start':8000000.,'decode_method':'hard'},frame


class ValidationTests(unittest.TestCase):
    def test_ble_parser_identity_and_layout_come_from_ble_alone(self):
        p, frame=packet()
        rows=m.ble_identity(p)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['run_id'],rows[0]['sequence']),(10265,0))
        self.assertEqual(rows[0]['frame_hex'],frame.hex())
        self.assertEqual(rows[0]['pdu_byte_offset'],22)
        self.assertEqual(rows[0]['layout_delta_us'],216)
        p['crc_hex']='000000'
        with self.assertRaisesRegex(ValueError,'CRC recomputation'):
            m.ble_identity(p)

    def test_corrupt_embedded_data_rejected_even_with_good_ble_crc(self):
        p,_=packet();data=bytearray.fromhex(p['pdu_hex']);data[-1]^=1
        p.update(pdu_hex=data.hex(),crc_hex=m.BLE.crc24(data).hex())
        with self.assertRaisesRegex(ValueError,'exact mapping/FCS'):
            m.ble_identity(p)

    def test_matching_requires_identity_and_identical_frame(self):
        p,_=packet();a=m.ble_identity(p)[0]
        b=dict(a,sample_start=a['sample_start']+1729,decode_method='hard_dsss')
        rows,_=m.match_sequences([a],[b],10265,3,8000000)
        self.assertEqual(rows[0]['timing_status'],'matched')
        self.assertAlmostEqual(rows[0]['layout_error_us'],.125)
        self.assertEqual(rows[1]['state'],'neither')
        rows,_=m.match_sequences([a],[dict(b,frame_hex='bad')],10265,1,8000000)
        self.assertEqual(rows[0]['timing_status'],'frame_mismatch')
        rows,_=m.match_sequences([a,a],[b],10265,1,8000000)
        self.assertEqual(rows[0]['timing_status'],'ambiguous_repeated_sequence')
        rows,_=m.match_sequences([a],[dict(b,sequence=2)],10265,3,8000000)
        self.assertEqual([r['state'] for r in rows],['ble_only','neither','zigbee_only'])

    def test_calibration_cannot_fit_validation_error_away(self):
        rows=[dict(run_id=1,sequence=0,timing_status='matched',layout_error_us=.25),
              dict(run_id=1,sequence=3,timing_status='matched',layout_error_us=10.),
              dict(run_id=2,sequence=0,timing_status='matched',layout_error_us=20.)]
        result=m.assign_calibration(rows,{'run_id':1,'sequence_lt':1})
        self.assertEqual(result['fixed_bias_us'],.25)
        self.assertEqual(rows[1]['calibrated_error_us'],9.75)
        self.assertEqual(rows[2]['calibrated_error_us'],19.75)
        self.assertEqual(rows[2]['partition'],'validation')


if __name__=='__main__':
    unittest.main()
