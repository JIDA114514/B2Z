"""Synthetic records only: never hardware evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from control_match.n5_config import generate
from control_match.n5_analyze import run_analysis, ratio, recovery_rows


class AnalysisTests(unittest.TestCase):
    def test_empty_capture_retains_all_tasks_and_missing_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            c=generate(2501)
            config=root/'config.json';config.write_text(json.dumps(c))
            tasks=[]; cursor=0
            for t in c['tasks']:
                if cursor<t['first_slot']:
                    tasks.append(dict(command_id=0,first_slot=cursor,repeats=t['first_slot']-cursor))
                tasks.append(dict(t,repeats=t['attempts']))
                cursor=t['first_slot']+t['attempts']
            tasks.append(dict(command_id=0,first_slot=cursor,repeats=300-cursor))
            lines=['CONTROL_PLAN_STATS final=1 state=complete run_id=2501 tasks=13 planned_slots=300 reached_slots=300 generated=300 primary_completed=300 tx_completed=300 deadline_miss=0 dma_timeout=0 period_ms=500 rf_mode=standard_secondary_ch3']
            for entry,t in enumerate(tasks):
                k=t['repeats']
                fields=dict(t,entry=entry,run_id=2501,generated=k,primary_completed=k,tx_completed=k,deadline_miss=0,dma_timeout=0)
                lines.append('CONTROL_PLAN_TASK '+' '.join(f'{k}={v}' for k,v in fields.items()))
                for slot in range(t['first_slot'],t['first_slot']+k):
                    lines.append(f'CONTROL_PLAN_SLOT run_id=2501 slot={slot} entry={entry} command_id={t["command_id"]} generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0')
            board=root/'serial.log';board.write_text('\n'.join(lines))
            paths={}
            for side in ('ble','zigbee'):
                folder=root/side;folder.mkdir()
                paths[side]=folder/'rx.packets.jsonl';paths[side].write_text('')
                (folder/'rx.summary.json').write_text(json.dumps(dict(status='complete',start_utc='2026-11-16T00:00:00+00:00',end_utc='2026-11-16T00:02:30+00:00',counts=dict(samples_processed=150000),config=dict(sample_rate=1000))))
            result=run_analysis(root,config,root/'analysis',paths,board)
            self.assertEqual(result['joint_parsing'],ratio(0,6))
            self.assertEqual(result['live_probe_summary']['ble']['coverage'],ratio(0,24))
            self.assertEqual(len(result['integrity']['tasks']),6)
            self.assertIsNone(ratio(0,0)['value'])
            self.assertTrue((root/'analysis'/'n5.report.md').exists())
            from test_control_engine import wire
            from test_live_control import packet
            for side,target in [('ble',1),('zigbee',2)]:
                raw=wire(70,run=2501,period=500,command=51,target=target,opcode=1,arg=1,
                         execute=40000,valid=39000)
                row=packet(side)
                row.update(sample_start=35000,available_sample=35001)
                if side=='ble':
                    row['extended']['adi']['did']=70
                    row['extended']['ad_structures'][0]['data_hex']=(b'\xff\xff'+raw+bytes(172)).hex()
                else:
                    row['payload_hex']=raw.hex()
                paths[side].write_text(json.dumps(row)+'\n')
            matched=run_analysis(root,config,root/'received',paths,board)
            self.assertEqual(matched['joint_parsing'],ratio(1,6))
            self.assertEqual(matched['joint_first_attempt'],ratio(1,6))


    def test_unrecovered_event_in_denominator(self):
        rows=recovery_rows([dict(event='observation_transition',state='stale',local_sample=10),
                            dict(event='observation_transition',state='reacquiring',local_sample=20)],1000,'ble')
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['recovered_sample'])
        self.assertEqual(rows[0]['censor_reason'],'capture_end_without_recovery')
