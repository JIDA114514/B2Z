"""Receiver checks against bytes from the real C v2 packet generator (not RF)."""
import binascii
import ctypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from python.perf_test.tests.test_b2z_control_generator import ControlGeneratorTests, Packet, read_bytes
from python.control_match.protocol import control_record, ble_manufacturer_record
from python.control_match.analyze import extract_ble, read_side
from python.zigbee_rx.control_receive import ControlTracker
from python.std_ble.verify_board_exadv import validate_secondary
from python.std_ble.ble_exadv_hackrf_sniffer import parse_ext_adv_payload
from python.control_match.plan_analyze import read_plan


class CapacityReceiverTests(unittest.TestCase):
    setUpClass=classmethod(ControlGeneratorTests.setUpClass.__func__)
    tearDownClass=classmethod(ControlGeneratorTests.tearDownClass.__func__)

    def test_board_v2_both_sides_boundary_and_corruption(self):
        fn=self.lib.ble_exadv_secondary_gen_build_capacity
        fn.argtypes=[ctypes.POINTER(Packet),ctypes.c_uint32,ctypes.c_uint32]
        for b,z in ((0,0),(26,0),(2,6),(8,2)):
            p=Packet(2301,7,3500,500,8,6500,5500,1,1,1,2,1,2)
            self.assertEqual(fn(ctypes.byref(p),b,z),0)
            m=self.lib.ble_exadv_secondary_gen_get_last_meta().contents
            pdu=read_bytes(m.pdu,m.pdu_len)
            manufacturer=pdu[17:]
            raw=ble_manufacturer_record(manufacturer,pdu[1])
            extracted=extract_ble(dict(crc_ok=True,kind='auxiliary',pdu_length=pdu[1],
                extended={'ad_structures':[{'type':255,'company_id':65535,'data_hex':manufacturer.hex()}]}))
            self.assertEqual(extracted,raw)
            record=control_record(raw,'ble')
            self.assertEqual(record['extra_len'],b)
            self.assertEqual(record['ieee_marker_offset_us'],480+8*b)
            ieee=read_bytes(m.zigbee_payload,m.zigbee_payload_len)
            parsed,disposition,error=ControlTracker(2301,None,100).observe(ieee)
            self.assertEqual(disposition,'unique');self.assertIsNone(error)
            self.assertEqual(parsed['extra_len'],z)
            self.assertIsNone(parsed['ieee_marker_offset_us'])
            args=SimpleNamespace(secondary_channel=3,payload_mode='joint',expected_adva='C1:A2:A3:A4:A5:A6',run_id=2301,expected_attempts=100,period_ms=500,command_id=None)
            packet=dict(pdu=pdu,channel=3,crc_ok=True,kind='secondary',ext=parse_ext_adv_payload(list(pdu[2:])))
            self.assertEqual(validate_secondary(packet,args)['control'],record)
            for data,side in ((raw,'ble'),(ieee,'zigbee')):
                with self.assertRaises(ValueError):control_record(data[:-1],side)
                damaged=bytearray(data);damaged[-1]^=1
                with self.assertRaisesRegex(ValueError,'app_crc16'):control_record(bytes(damaged),side)
                if data[33]:
                    damaged=bytearray(data);damaged[34]^=1
                    damaged[-2:]=binascii.crc_hqx(damaged[:-2],0xffff).to_bytes(2,'little')
                    with self.assertRaisesRegex(ValueError,'capacity_content'):control_record(bytes(damaged),side)
            with self.assertRaises(ValueError):ble_manufacturer_record(manufacturer+b'\0',pdu[1]+1)

    def test_capacity_manifest_budget_and_actual_lengths(self):
        text='''CONTROL_PLAN_STATS final=1 state=complete run_id=7 tasks=1 planned_slots=1 reached_slots=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0 rf_mode=standard_secondary_ch3
CONTROL_PLAN_TASK run_id=7 entry=0 command_id=1 first_slot=0 repeats=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0
CONTROL_PLAN_SLOT run_id=7 slot=0 entry=0 command_id=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0
CAPACITY_CONFIG run_id=7 version=2 ble_extra=2 ieee_extra=6 ble_record_bytes=38 ieee_record_bytes=42 mapped_bytes=200 pdu_payload_bytes=255 k=1 command_rule=slot_plus_one fill=lcg_v2_side_seed
CAPACITY_SLOT run_id=7 slot=0 command_id=1 built=1 ble_record_bytes=38 ieee_record_bytes=42 mapped_bytes=200 pdu_payload_bytes=255
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'board.log';p.write_text(text)
            self.assertEqual(read_plan(p,7)['capacity']['ieee_marker_offset_us'],496)
            p.write_text(text.replace('pdu_payload_bytes=255\n','pdu_payload_bytes=254\n'))
            with self.assertRaisesRegex(ValueError,'actual capacity'):read_plan(p,7)
