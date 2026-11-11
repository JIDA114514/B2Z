import copy
import tempfile
import unittest
from pathlib import Path

from python.control_match.n3_holdover import default_config,validate_config,evaluate
from python.control_match.n3_timing import parse_timing


def streams(c):
    return {side:{s:dict(record={'ref_tick_ms':s*c['period_ms']},
                        sample_start=origin+rate*s*c['period_ms']+(1888 if side=='zigbee' else 0),
                        available_sample=int(origin+rate*s*c['period_ms']+8000)) for s in c['slots']}
            for side,origin,rate in [('ble',1e6,4000.04),('zigbee',5e6,3999.96)]}


class HoldoverN3Tests(unittest.TestCase):
    def test_disjoint_holdout_and_affine_recovery(self):
        c=default_config();validate_config(c)
        for p in c['policies']:
            self.assertFalse(set(p['initial']['ble']+p['updates']['ble']) & set(p['initial']['zigbee']+p['updates']['zigbee']))
        rows,stats=evaluate(c,streams(c),dict(ble=4000000,zigbee=4000000))
        self.assertEqual(len(c['probes']),24)
        self.assertTrue(all(abs(r['relative_error_us'])<.001 for r in rows if r['policy']!='offset'))
        self.assertTrue(all(r['n']==24 for r in stats))

    def test_delayed_availability_probe_exclusion_and_missing_side(self):
        c=default_config();s=streams(c)
        _,baseline=evaluate(c,s,dict(ble=4000000,zigbee=4000000))
        delayed=c['policies'][1]['initial']['ble'][-1]
        s['ble'][delayed]['available_sample']=int(s['ble'][69]['sample_start']+1)
        s['zigbee'].pop(79)
        rows,_=evaluate(c,s,dict(ble=4000000,zigbee=4000000))
        r=next(r for r in rows if r['policy']=='freeze_n2' and r['slot']==69)
        self.assertEqual(r['ble_status'],'training_missing_or_unavailable')
        r=next(r for r in rows if r['policy']=='freeze_n4' and r['slot']==79)
        self.assertIsNotNone(r['ble_residual_us']);self.assertIsNone(r['relative_error_us'])
        s=streams(c);before,_=evaluate(c,s,dict(ble=4000000,zigbee=4000000))
        s['ble'][69]['sample_start']+=4000
        after,_=evaluate(c,s,dict(ble=4000000,zigbee=4000000))
        for a,b in zip(before,after):
            self.assertEqual(a['ble_training_slots'],b['ble_training_slots'])
            if a['slot']!=69:self.assertEqual(a['ble_residual_us'],b['ble_residual_us'])
        bad=copy.deepcopy(c);bad['policies'][0]['updates']['ble']=[69]
        with self.assertRaisesRegex(ValueError,'overlap'):validate_config(bad)

    def test_empty_observations_preserve_denominator(self):
        c=default_config(120,500,True)
        rows,summary=evaluate(c,dict(ble={},zigbee={}),dict(ble=4000000,zigbee=4000000))
        self.assertTrue(all(r['n']==0 and r['planned_probes']==6 and r['p99'] is None for r in summary))


def timing_fixture():
    epoch=2**62+2**32-100;hz=1000000
    plan=dict(stats=dict(run_id='7',period_ms='500',aux_offset_us='300000',rf_mode='standard_secondary_ch3'),slots={0:{}})
    lines=[f'CONTROL_TIME_META run_id=7 schema=1 enabled=1 tick_hz={hz} epoch_ticks={epoch:016x} slots_capacity=1024 overflow=0',
           'CONTROL_PLAN_SLOT run_id=7 slot=0 secondary_dma_late_us=80 dma_timeout=0 deadline_miss=0']
    anchor=epoch+100;target=anchor+300000
    lines.append(f'CONTROL_TIME_SLOT run_id=7 slot=0 planned_ticks={epoch:016x} anchor_valid=1 anchor_ticks={anchor:016x} target_ticks={target:016x} frame_us=1 mapping_us=2 gfsk_us=3')
    for kind in (0,1,3):
        start=anchor if kind==0 else target-5 if kind==1 else epoch
        stages={'call':(0,12),'stop_clear':(1,2),'cache_flush':(3,4),'dac_sync':(5,6),'submit_write':(7,8),'poll':(13,20)} if kind!=3 else {'generation':(0,50),'retune_secondary':(200,210),'retune_primary':(400000,400010)}
        for stage,(a,b) in stages.items():
            lines.append(f'CONTROL_TIME_STAGE run_id=7 slot=0 kind={kind} stage={stage} valid=3 before_ticks={start+a:016x} after_ticks={start+b:016x} status=0 remaining_bytes=0')
    lines += ['CONTROL_TIME_LATE run_id=7 slot=0 call_valid=1 submit_valid=1 return_valid=1 pre_call_us=-5 pre_submit_us=2 post_return_us=7',
              'CONTROL_TIME_END run_id=7 slots=1 overflow=0']
    return plan,'\n'.join(lines)+'\n'


class TimingN3Tests(unittest.TestCase):
    def parse(self,text,plan,legacy=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'board.log';p.write_text(text)
            return parse_timing(p,plan,legacy)

    def test_exact_ticks_negative_late_and_missing_stages(self):
        plan,text=timing_fixture();d=self.parse(text,plan)
        self.assertEqual(d['slots'][0]['pre_call_us'],-5)
        self.assertEqual(d['slots'][0]['kind1_submit_write_us'],1)
        line=next(l for l in text.splitlines() if 'kind=1 stage=cache_flush' in l)
        parts=line.split();line2=' '.join('valid=0' if x.startswith('valid=') else x.split('=')[0]+'=0000000000000000' if x.startswith(('before_ticks=','after_ticks=')) else x for x in parts)
        self.assertIsNone(self.parse(text.replace(line,line2),plan)['slots'][0]['kind1_cache_flush_us'])

    def test_prepared_secondary_cache_requires_explicit_phase_and_order(self):
        plan,text=timing_fixture()
        line=next(l for l in text.splitlines() if 'kind=1 stage=cache_flush' in l)
        epoch=2**62+2**32-100
        prepared=' '.join(f'before_ticks={epoch+500:016x}' if x.startswith('before_ticks=')
                          else f'after_ticks={epoch+1500:016x}' if x.startswith('after_ticks=')
                          else x for x in line.split())
        moved=text.replace(line,prepared)
        with self.assertRaisesRegex(ValueError,'outside DMA call'):
            self.parse(moved,plan)
        moved=moved.replace('schema=1','schema=1 secondary_cache=before_aux_wait')
        self.assertEqual(self.parse(moved,plan)['slots'][0]['kind1_cache_flush_us'],1000)
        # Old in-call cache records must not masquerade as prepared buffers.
        with self.assertRaisesRegex(ValueError,'overlaps DMA call'):
            self.parse(text.replace('schema=1','schema=1 secondary_cache=before_aux_wait'),plan)

    def test_trace_must_agree_with_burst_lifecycle(self):
        plan,text=timing_fixture()
        plan['bursts']={'rows':[dict(slot=0,kind=k,attempted=1,started=1,completed=1)
                               for k in ('primary','secondary')]}
        self.assertEqual(self.parse(text,plan)['status'],'complete_software_trace')
        plan['bursts']['rows'][1]['completed']=0
        with self.assertRaisesRegex(ValueError,'poll status'):
            self.parse(text,plan)

    def test_truncated_duplicate_corrupt_and_overflow_rejected(self):
        plan,text=timing_fixture()
        stage=next(l for l in text.splitlines() if l.startswith('CONTROL_TIME_STAGE'))
        for bad in (text.replace(stage+'\n',''),text+stage+'\n',text.replace('overflow=0','overflow=1'),
                    text.replace('pre_call_us=-5','pre_call_us=0'),text.replace('CONTROL_TIME_END','TRUNCATED')):
            with self.assertRaises(ValueError):self.parse(bad,plan,True)
        legacy='CONTROL_PLAN_SLOT run_id=7 slot=0 secondary_dma_late_us=10\n'
        self.assertEqual(self.parse(legacy,plan,True)['status'],'legacy_missing_stages')
        with self.assertRaises(ValueError):self.parse(legacy,plan)
