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
from python.control_match.plan_analyze import read_plan, summarize


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

    def test_board_v2_separate_both_sides_boundary_and_corruption(self):
        fn=self.lib.ble_exadv_secondary_gen_build_capacity_mode
        fn.argtypes=[ctypes.POINTER(Packet),ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint8]
        for b,z in ((0,0),(26,0),(2,6),(8,2)):
            p=Packet(2301,7,3500,500,8,6500,5500,1,1,1,2,1,2)
            self.assertEqual(fn(ctypes.byref(p),b,z,2),0)
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
            args=SimpleNamespace(secondary_channel=3,payload_mode='ble-only',expected_adva='C1:A2:A3:A4:A5:A6',run_id=2301,expected_attempts=100,period_ms=500,command_id=None)
            packet=dict(pdu=pdu,channel=3,crc_ok=True,kind='secondary',ext=parse_ext_adv_payload(list(pdu[2:])))
            self.assertEqual(validate_secondary(packet,args)['control'],record)
            args.payload_mode='joint'
            with self.assertRaisesRegex(ValueError,'secondary_pdu_shape'):
                validate_secondary(packet,args)
            import json
            event=dict(crc_ok=True,kind='auxiliary',pdu_length=pdu[1],
                extended={'adi':{'did':7},'ad_structures':[{'type':255,'company_id':65535,'data_hex':manufacturer.hex()}]})
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'rx.jsonl';path.write_text(json.dumps(event)+'\n')
                side=read_side(path,'ble',2301,8)
                self.assertEqual(side['by_slot'][7]['wire_format'],'ble-only')
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
        text='''CONTROL_PLAN_STATS final=1 state=complete run_id=7 period_ms=500 tasks=1 planned_slots=1 reached_slots=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0 rf_mode=standard_secondary_ch3
CONTROL_PLAN_TASK run_id=7 entry=0 command_id=1 first_slot=0 repeats=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0
CONTROL_PLAN_SLOT run_id=7 slot=0 entry=0 command_id=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0
CAPACITY_CONFIG run_id=7 version=2 ble_extra=2 ieee_extra=6 ble_record_bytes=38 ieee_record_bytes=42 mapped_bytes=200 pdu_payload_bytes=255 k=1 command_rule=slot_plus_one fill=lcg_v2_side_seed
CAPACITY_SLOT run_id=7 slot=0 command_id=1 built=1 ble_record_bytes=38 ieee_record_bytes=42 mapped_bytes=200 pdu_payload_bytes=255
'''
        text += "CONTROL_BURST run_id=7 slot=0 kind=primary generated=1 attempted=1 started=1 completed=1 timeout=0 iq_bytes=35880 air_us=136 pad_us=10 prepared_us=1 submit_before_us=2 submit_after_us=3 finish_us=200\n"
        text += "CONTROL_BURST run_id=7 slot=0 kind=secondary generated=1 attempted=1 started=1 completed=1 timeout=0 iq_bytes=500000 air_us=2120 pad_us=10 prepared_us=1 submit_before_us=300000 submit_after_us=300010 finish_us=303000\n"
        text += "CONTROL_COST_STATS run_id=7 logical_slots=1 ble_tx_completed=1 ieee_tx_completed=1 burst_attempted=2 burst_started=2 burst_completed=2\n"
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'board.log';p.write_text(text)
            plan=read_plan(p,7)
            self.assertEqual(plan['capacity']['ieee_marker_offset_us'],496)
            self.assertEqual(plan['bursts']['planned_waveform_us'],2256)
            separate=text.replace('standard_secondary_ch3','separate_secondary_ch3').replace('pdu_payload_bytes=255','pdu_payload_bytes=55').replace('air_us=2120','air_us=520').replace('burst_attempted=2 burst_started=2 burst_completed=2','burst_attempted=3 burst_started=3 burst_completed=3')
            separate += "CONTROL_BURST run_id=7 slot=0 kind=ieee generated=1 attempted=1 started=1 completed=1 timeout=0 iq_bytes=400000 air_us=1600 pad_us=10 prepared_us=1 submit_before_us=304000 submit_after_us=304010 finish_us=306000\n"
            p.write_text(separate)
            split=read_plan(p,7)
            self.assertIsNone(split['capacity']['ieee_marker_offset_us'])
            self.assertEqual(split['bursts']['planned_waveform_us'],2256)
            self.assertEqual(split['bursts']['counts']['burst_completed'],3)
            fn=self.lib.ble_exadv_secondary_gen_build_capacity_mode
            fn.argtypes=[ctypes.POINTER(Packet),ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint8]
            packet=Packet(7,0,0,500,1,3000,2000,1,1,1,2,1,2)
            self.assertEqual(fn(ctypes.byref(packet),2,6,2),0)
            m=self.lib.ble_exadv_secondary_gen_get_last_meta().contents
            ble={'by_slot':{0:{'record':control_record(read_bytes(m.ble_control_record,38),'ble'),'wire_format':'ble-only'}},'live':None}
            ieee={'by_slot':{0:{'record':control_record(read_bytes(m.zigbee_payload,42),'zigbee')}},'live':None}
            result,_,_=summarize(split,ble,ieee)
            self.assertEqual(result['joint_decoded_tasks'],1)
            self.assertEqual(result['waveform_cost']['per_joint_decoded_task']['value_us'],2256)
            ble['by_slot'][0]['wire_format']='joint'
            with self.assertRaisesRegex(ValueError,'wire format'):summarize(split,ble,ieee)

            p.write_text(separate.replace('air_us=1600','air_us=1376'))
            with self.assertRaisesRegex(ValueError,'waveform budget'):read_plan(p,7)
            p.write_text(separate.replace('pdu_payload_bytes=55','pdu_payload_bytes=255'))
            with self.assertRaisesRegex(ValueError,'capacity budget'):read_plan(p,7)
            p.write_text(text.replace('air_us=2120','air_us=1872'))
            with self.assertRaisesRegex(ValueError,'waveform budget'):read_plan(p,7)
            p.write_text(text.replace('pdu_payload_bytes=255\n','pdu_payload_bytes=254\n'))
            with self.assertRaisesRegex(ValueError,'actual capacity'):read_plan(p,7)
