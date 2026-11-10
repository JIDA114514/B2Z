import binascii
import subprocess
import sys
import ctypes
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from python.perf_test.tests.test_b2z_control_generator import ControlGeneratorTests, Packet, read_bytes
from python.exadv_rx.protocol import crc24
from python.std_ble.verify_board_exadv import file_packet, validate_secondary
from python.control_match.flow_input import load_flow
from python.control_match.plan_analyze import summarize


class FlowInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ControlGeneratorTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        ControlGeneratorTests.tearDownClass()

    def fixture(self, root):
        args = SimpleNamespace(run_id=2001, command_id=None, expected_attempts=6,
                               period_ms=500, secondary_channel=3, expected_adva='C1:A2:A3:A4:A5:A6')
        events = []
        for slot, command in [(0,43),(3,44)]:
            packet = Packet(2001,slot,slot*500,500,command,5000,4500,1,1,command-42,2,1,3)
            lib = ControlGeneratorTests.lib
            self.assertEqual(lib.ble_exadv_secondary_gen_build_control_mode(ctypes.byref(packet),1),0)
            m = lib.ble_exadv_secondary_gen_get_last_meta().contents
            for kind, channel, pdu in [('primary_valid',39,read_bytes(m.primary_pdu,m.primary_pdu_len)),
                                       ('secondary_valid',3,read_bytes(m.pdu,m.pdu_len))]:
                row = dict(event=kind,channel=channel,did=slot,pdu_hex=pdu.hex(),crc_hex=crc24(pdu).hex(),crc_ok=True)
                if kind == 'secondary_valid':
                    row['control'] = validate_secondary(file_packet(row),args)['control']
                events.append(row)
            events.append(dict(event='followed_event',did=slot))
        p = root/'flow.events.jsonl'
        p.write_text(''.join(json.dumps(x)+'\n' for x in events))
        (root/'flow.summary.json').write_text(json.dumps(dict(
            schema='board_std_ble_flow_v1',mode='live_hop',status='complete',interrupted=False,
            run_id=2001,command_id=None,expected_attempts=6,period_ms=500,primary_channel=39,
            secondary_channel=3,advertised_aux_offset_us=300000,primary_dids=[0,3],
            secondary_dids=[0,3],paired_dids=[0,3],start_utc='2026-11-10T00:00:00+00:00',
            end_utc='2026-11-10T00:01:00+00:00')))
        return p,events

    def test_multitask_cross_attempt_and_missing_software_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p,_ = self.fixture(Path(d)); ble=load_flow(p,2001)
            zigbee={'by_slot':{},'live':None}
            for slot,e in ble['by_slot'].items():
                r=dict(e['record'],slot_index=slot+1,ref_tick_ms=(slot+1)*500,target_id=2,arg=3)
                zigbee['by_slot'][slot+1]={'record':r}
            plan={'stats':dict(run_id='2001',tx_completed='6',period_ms='500'),
                  'tasks':[dict(command_id=str(c),first_slot=str(i*3),repeats='3',tx_completed='3')
                           for i,c in enumerate([43,44])],
                  'slots':{i:dict(entry=i//3,command_id=43+i//3,board_tx_completed=1) for i in range(6)}}
            summary,slots,tasks=summarize(plan,ble,zigbee)
            self.assertEqual(summary['joint_decoded_tasks'],2)
            self.assertEqual(summary['joint_valid_attempts'],0)
            self.assertEqual(summary['neither_attempts'],2)
            self.assertEqual(summary['ble_follow']['joint_tasks_with_follow']['numerator'],2)
            self.assertEqual(summary['ble_follow']['per_planned_slot']['denominator'],6)
            self.assertEqual(summary['ble_follow']['per_valid_primary']['value'],1)
            self.assertIsNone(summary['joint_software_processed_tasks'])
            self.assertEqual(tasks[0]['ble_live_status'],'not_measured')
            self.assertIsNone(ble['by_slot'][0]['sample_start'])
            self.assertEqual(ble['counts']['crc_recomputed'],4)

    def test_cli_writes_joint_report_with_flow_source(self):
        from python.std_ble.ble_exadv_hackrf_sniffer import parse_ad_structures
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); flow,events=self.fixture(root)
            zdir=root/'zigbee'; zdir.mkdir()
            rows=[]
            for event in events:
                if event['event'] != 'secondary_valid': continue
                ad=parse_ad_structures(file_packet(event)['ext']['adv_data'])
                data=bytearray(ad[1][1][2:37])
                slot=event['did']+1
                data[6:10]=slot.to_bytes(4,'little')
                data[10:14]=(slot*500).to_bytes(4,'little')
                data[20:22]=(2).to_bytes(2,'little')
                data[33:35]=binascii.crc_hqx(data[:33],0xffff).to_bytes(2,'little')
                rows.append(dict(fcs_ok=True,payload_hex=data.hex()))
            zp=zdir/'rx.packets.jsonl'; zp.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            (zdir/'rx.summary.json').write_text(json.dumps(dict(status='complete',
                start_utc='2026-11-10T00:00:00+00:00',end_utc='2026-11-10T00:01:00+00:00')))
            lines=['CONTROL_PLAN_STATS final=1 state=complete run_id=2001 tasks=2 period_ms=500 planned_slots=6 reached_slots=6 generated=6 primary_completed=6 tx_completed=6 deadline_miss=0 dma_timeout=0']
            for entry in range(2):
                lines.append(f'CONTROL_PLAN_TASK run_id=2001 entry={entry} command_id={43+entry} first_slot={entry*3} repeats=3 generated=3 primary_completed=3 tx_completed=3 deadline_miss=0 dma_timeout=0')
            for slot in range(6):
                lines.append(f'CONTROL_PLAN_SLOT run_id=2001 slot={slot} entry={slot//3} command_id={43+slot//3} generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0')
            (root/'board.board.log').write_text('\n'.join(lines))
            script=Path(__file__).resolve().parents[1]/'plan_analyze.py'
            result=subprocess.run([sys.executable,str(script),'--experiment-dir',str(root),
                '--run-id','2001','--ble-flow',str(flow),'--zigbee-packets',str(zp)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            summary=json.loads((root/'analyses/plan_match/plan.summary.json').read_text())
            self.assertEqual(summary['joint_decoded_tasks'],2)
            self.assertIsNone(summary['joint_software_processed_tasks'])
            self.assertEqual(summary['ble_follow']['joint_tasks_with_follow']['numerator'],2)

    def test_tampered_crc_and_orphan_follow_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p,events=self.fixture(Path(d))
            events[1]['crc_hex']='000000'
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            with self.assertRaisesRegex(ValueError,'CRC mismatch'):load_flow(p,2001)
            p,events=self.fixture(Path(d))
            events.insert(0,dict(event='followed_event',did=0))
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            with self.assertRaisesRegex(ValueError,'preceding'):load_flow(p,2001)
