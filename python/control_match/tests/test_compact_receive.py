import ctypes as C
import json
import tempfile
from pathlib import Path
import unittest
import numpy as np
from scipy.signal import resample_poly
from python.perf_test.tests.test_b2z_control_generator import ControlGeneratorTests, Packet
from python.perf_test.tests.test_compact_generator import CompactMeta
from python.perf_test.tests.test_bluebee_gen_waveform import iq_complex
from python.exadv_rx.decoder import ChannelDecoder
from python.zigbee_rx.tests.test_zigbee_receiver import decode
from python.zigbee_rx.control_receive import ControlTracker
from python.control_match.compact import BLEControlExtractor
from python.control_match.protocol import control_record
from python.control_match.analyze import read_side
from python.control_match.plan_analyze import read_plan, summarize


def board(b,z,legacy):
    mode='LC' if legacy else 'JC'
    rf='legacy_separate_ch39' if legacy else 'standard_secondary_ch3'
    primary=0 if legacy else 1
    lines=[f'CONTROL_PLAN_STATS final=1 state=complete run_id=2411 period_ms=500 tasks=1 planned_slots=1 reached_slots=1 generated=1 primary_completed={primary} tx_completed=1 deadline_miss=0 dma_timeout=0 rf_mode={rf}',
           f'CONTROL_PLAN_TASK run_id=2411 entry=0 command_id=1 first_slot=0 repeats=1 generated=1 primary_completed={primary} tx_completed=1 deadline_miss=0 dma_timeout=0',
           f'CONTROL_PLAN_SLOT run_id=2411 slot=0 entry=0 command_id=1 generated=1 primary_completed={primary} tx_completed=1 deadline_miss=0 dma_timeout=0',
           f'COMPACT_CONFIG run_id=2411 format=C1 mode={mode} ble_extra={b} ieee_extra={z} ble_record_bytes={26+b} ieee_record_bytes={26+z} k=1 period_ms=500 valid_lead_ms=2000 execute_lead_ms=3000',
           f'COMPACT_SLOT run_id=2411 slot=0 command_id=1 built=1 ble_record_bytes={26+b} ieee_record_bytes={26+z} mapped_bytes={136+4*z} secondary_payload_bytes={0 if legacy else 179+b+4*z}']
    length=26+b
    sizes=[length] if length<=27 else [10+min(17,length-i) for i in range(0,length,17)]
    kinds=([(f'fragment{i}',(20+n)*8) for i,n in enumerate(sizes)]+[('ieee',(136+4*z)*8)]) if legacy else [('primary',136),('secondary',(189+b+4*z)*8)]
    for i,(kind,air) in enumerate(kinds):
        t=300000+i*5000
        lines.append(f'COMPACT_BURST run_id=2411 slot=0 kind={kind} generated=1 attempted=1 started=1 completed=1 timeout=0 iq_bytes=500000 air_us={air} pad_us=10 prepared_us=1 submit_before_us={t} submit_after_us={t+1} finish_us={t+2000}')
    n=len(kinds)
    lines.append(f'COMPACT_COST_STATS run_id=2411 logical_slots=1 ble_tx_completed=1 ieee_tx_completed=1 burst_attempted={n} burst_started={n} burst_completed={n}')
    return '\n'.join(lines)


class CompactReceiverTests(unittest.TestCase):
    setUpClass=classmethod(ControlGeneratorTests.setUpClass.__func__)
    tearDownClass=classmethod(ControlGeneratorTests.tearDownClass.__func__)

    def packets(self,b,z,legacy):
        fn=self.lib.b2z_compact_build
        fn.argtypes=[C.POINTER(Packet),C.c_uint32,C.c_uint32,C.c_uint8]
        self.lib.b2z_compact_get_meta.restype=C.POINTER(CompactMeta)
        p=Packet(2411,0,0,500,1,3000,2000,1,1,1,2,1,2)
        self.assertEqual(fn(C.byref(p),b,z,legacy),0)
        m=self.lib.ble_exadv_secondary_gen_get_last_meta().contents
        lc=self.lib.b2z_compact_get_meta().contents
        chunks=[np.zeros(4000,np.complex64)]
        buffers=[(lc.iq[k],lc.iq_bytes[k]) for k in range(lc.ble_count)] if legacy else [(m.iq_words,m.iq_byte_count)]
        for ptr,size in buffers:
            iq=iq_complex(np.ctypeslib.as_array(ptr,shape=(size//4,))[::2])
            chunks.extend([resample_poly(iq,25,192).astype(np.complex64),np.zeros(8000,np.complex64)])
        iq=np.concatenate(chunks)
        self.ble_iq=iq.copy()
        decoder=ChannelDecoder(4000000,2480000000 if legacy else 2410000000,39 if legacy else 3)
        packets=decoder.feed(iq,final=True)
        self.assertEqual(len(packets),len(buffers))
        for p in packets:p['available_sample']=len(iq)
        if legacy:
            ieee=iq_complex(np.ctypeslib.as_array(m.ieee_iq_words,shape=(m.ieee_iq_byte_count//4,))[::2])
            iq=np.concatenate((np.zeros(400,np.complex64),resample_poly(ieee,25,192),np.zeros(1200,np.complex64))).astype(np.complex64)
        _,received=decode(iq,sample_rate=4000000)
        valid=[r for r in received if r['fcs_ok']]
        self.assertEqual(len(valid),1)
        return packets,valid[0]

    def test_real_waveforms_to_joint_summary(self):
        for b,z in [(0,0),(26,0),(2,6)]:
            for legacy in [0,1]:
                packets,ieee=self.packets(b,z,legacy)
                record,status,error=ControlTracker(2411,None,1).observe(bytes.fromhex(ieee['payload_hex']))
                self.assertEqual(status,'unique');self.assertIsNone(error)
                with tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);log=root/'board.log';log.write_text(board(b,z,legacy))
                    plan=read_plan(log,2411)
                    f=root/'ble.jsonl';f.write_text(''.join(json.dumps(p)+'\n' for p in packets))
                    ble=read_side(f,'ble',2411,1);ble['live']=None
                    result,_,_=summarize(plan,ble,{'by_slot':{0:{'record':record}},'live':None})
                    self.assertEqual(result['joint_decoded_tasks'],1)
                    expected=(1456 if b==0 else 2464 if b==26 else 1984) if legacy else (1648 if b==0 else 1856)
                    self.assertEqual(result['waveform_cost']['submitted_waveform_us'],expected)
                    log.write_text(board(b,z,legacy).replace('mapped_bytes=', 'missing_mapped_bytes='))
                    with self.assertRaises((ValueError,KeyError)):read_plan(log,2411)

    def test_cli_reports_compact_and_missing_fragment(self):
        import subprocess,sys
        root_repo=Path(__file__).resolve().parents[3]
        packets,ieee=self.packets(26,0,1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'board.board.log').write_text(board(26,0,1))
            for side,rows in [('ble',packets),('zigbee',[ieee])]:
                folder=root/'captures'/side/'test';folder.mkdir(parents=True)
                (folder/'rx.packets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
                (folder/'rx.summary.json').write_text(json.dumps(dict(status='complete',start_utc='2026-11-13T00:00:00+00:00',end_utc='2026-11-13T00:01:00+00:00',config={})))
            for name,expected in [('complete',1),('missing',0)]:
                if not expected:
                    (root/'captures/ble/test/rx.packets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in packets[:-1]))
                result=subprocess.run([sys.executable,str(root_repo/'python/control_match/plan_analyze.py'),
                    '--experiment-dir',str(root),'--run-id','2411','--analysis-id',name],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                report=json.loads((root/'analyses'/name/'plan.summary.json').read_text())
                self.assertEqual(report['joint_decoded_tasks'],expected)
                if not expected:
                    self.assertEqual(report['zigbee_only_attempts'],1)
                    self.assertEqual(report['ble_fragment_reassembly']['incomplete_at_end'],1)
                    self.assertIsNone(report['waveform_cost']['per_joint_decoded_task']['value_us'])

    def test_receive_cli_on_legacy_iq(self):
        import subprocess,sys
        self.packets(26,0,1)
        root_repo=Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);iq=root/'input.cf32';self.ble_iq.astype('<c8').tofile(iq)
            r=subprocess.run([sys.executable,str(root_repo/'python/exadv_rx/receive.py'),
                '--iq-file',str(iq),'--format','cf32','--sample-rate','4000000',
                '--channels','39','--control-layout','separate','--run-id','2411',
                '--duration','0','--output',str(root/'rx'),'--quiet'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            d=json.loads((root/'rx.summary.json').read_text())
            self.assertEqual(d['status'],'complete')
            self.assertEqual(d['counts']['legacy'],4)
            self.assertEqual(d['counts']['matching_control_records'],1)
            self.assertEqual(d['counts']['compact_complete'],1)

    def test_compact_compare_marks_channel_confound(self):
        from python.control_match.compare_n2 import compare
        from copy import deepcopy
        summaries=[]
        for legacy in (0,1):
            packets,ieee=self.packets(0,0,legacy)
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);log=p/'board';log.write_text(board(0,0,legacy))
                plan=read_plan(log,2411)
                ex=BLEControlExtractor();raw=ex(packets[0])
                ble={'by_slot':{0:{'record':control_record(raw,'ble'),'wire_format':'legacy' if legacy else 'joint'}},'live':None}
                zig={'by_slot':{0:{'record':control_record(bytes.fromhex(ieee['payload_hex']),'zigbee')}},'live':None}
                result,_,_=summarize(plan,ble,zig);summaries.append(result)
        result=compare(*summaries,{})
        self.assertEqual(result['comparison_scope'],'compact_cost_with_RF_channel_confound')
        self.assertFalse(result['reliability_protocol_effect_identifiable'])
        self.assertEqual(result['joint_minus_separate_submitted_waveform_us'],192)
        bad=deepcopy(summaries[1]);bad['compact']['ble_extra']='2'
        self.assertIn('compact.ble_extra',compare(summaries[0],bad,{})['unresolved_or_different_conditions'])

    def test_fragment_faults(self):
        from copy import deepcopy
        packets,_=self.packets(26,0,1)
        # Out-of-order fragment indices, monotonically increasing local observations.
        ordered=list(reversed(deepcopy(packets)))
        for i,p in enumerate(ordered):p['sample_time_s']=i*.01
        ex=BLEControlExtractor();out=[ex(p) for p in ordered]
        self.assertEqual(sum(v is not None for v in out),1)
        self.assertEqual(control_record(out[-1],'ble')['extra_len'],26)
        ex=BLEControlExtractor();self.assertIsNone(ex(packets[0]));self.assertIsNone(ex(packets[0]))
        ex.expire(3);self.assertEqual(ex.counts['timeout'],1)
        self.assertTrue(all(ex(p) is None for p in packets[1:]))
        ex=BLEControlExtractor();ex(packets[0]);ex.finish();self.assertEqual(ex.counts['incomplete_at_end'],1)
        ex=BLEControlExtractor();ex(packets[0]);bad=deepcopy(packets[0])
        ad=bad['extended']['ad_structures'][0];raw=bytearray.fromhex(ad['data_hex']);raw[-1]^=1;ad['data_hex']=raw.hex()
        with self.assertRaisesRegex(ValueError,'conflict'):ex(bad)
