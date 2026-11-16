import unittest
from control_match.control_engine import EngineConfig
from control_match.n5_config import generate
from control_match.n5_observation import ObservationClock


class N5Tests(unittest.TestCase):
    def clock(self):
        return ObservationClock(EngineConfig(side='ble', run_id=2501, sample_rate=1000000,
                                             target_ids=frozenset({1})), generate(2501))

    def feed(self, c, slot, offset=0):
        sample = slot * 500000 + offset
        c.advance(sample + 1000)
        return c.observe(slot, slot * 500, sample)

    def test_holdout_and_no_packet_timeout(self):
        c = self.clock()
        for slot in range(0,16,2):
            self.feed(c,slot)
        self.assertEqual(c.state,'tracking')
        version = c.version
        c.advance(9000001)
        self.assertEqual(c.state,'holdover')
        c.advance(18000000)
        self.assertEqual(c.state,'stale')
        self.assertEqual(self.feed(c,69),'probe_held_out')
        self.assertEqual(c.version,version)
        self.assertIsNone(c.uncertainty_ms(35000))

    def test_reacquisition_ignores_old_innovation_gate(self):
        c = self.clock()
        for slot in range(0,16,2): self.feed(c,slot)
        c.advance(20000000)
        for slot in range(50,66,2): self.feed(c,slot,100000)
        self.assertEqual(c.state,'tracking')
        self.assertEqual(list(c.points),list(range(50,66,2)))
        c.invalidate()
        self.assertEqual(self.feed(c,66,100000),'timeline_unverified')

    def test_duplicate_and_conflict(self):
        c = self.clock()
        self.feed(c,0)
        self.assertEqual(c.observe(0,0,0),'clock_duplicate')
        self.assertEqual(c.observe(0,0,1),'conflicting_slot')

    def test_probe_uses_model_available_before_marker(self):
        c = self.clock()
        for slot in range(0,16,2): self.feed(c,slot)
        old = c.version
        c.advance(35000000)
        c.observe(68,34000,34000000)
        score = c.score(69,34500000)
        self.assertEqual(score['model_version'],old)
        self.assertLess(score['model_available_sample'],score['sample_start'])
        self.assertEqual(c.observe(69,34500,34500000),'probe_held_out')

    def test_engine_unknown_bound_probe_and_restart(self):
        from control_match.control_engine import SideControlEngine
        from test_control_engine import wire
        engine = SideControlEngine(EngineConfig(side='ble',run_id=2501,sample_rate=1000000,
            target_ids=frozenset({1}),n5_registration=generate(2501)))
        for slot in range(0,68,2):
            engine.observe(wire(slot,run=2501,period=500),slot*500000,slot*500000+1000)
        events=engine.observe(wire(69,run=2501,period=500),34500000,34501000)
        self.assertEqual(next(e for e in events if e['event']=='probe_score')['status'],'scored')
        events=engine.observe(wire(70,run=2501,period=500,command=51,target=1,opcode=1,arg=1,
                                   execute=40000,valid=39000),35000000,35001000)
        self.assertFalse(any(e['event']=='accepted' for e in events))
        self.assertTrue(any(e['event']=='rejected' for e in events))
        engine.timeline_event('synthetic_restart',restart=True)
        self.assertEqual(engine.clock.segment,1)
        self.assertEqual(engine.clock.state,'acquiring')
        self.assertIsNone(engine.clock.uncertainty_ms(40000))
        self.assertEqual(engine.clock.score(79,39500000)['status'],'model_unavailable')

    def test_registration_tamper(self):
        from control_match.n5_config import validate, digest
        c=generate(2501)
        c['probes'].remove(69)
        c['sha256']=digest(c)
        with self.assertRaises(ValueError):validate(c,2501)

    def test_all_tasks_missing_and_progress_recorded(self):
        import tempfile
        from pathlib import Path
        from control_match.live_control import ControlSession
        with tempfile.TemporaryDirectory() as tmp:
            s=ControlSession(Path(tmp)/'rx',EngineConfig(side='ble',run_id=2501,sample_rate=1000000,
                target_ids=frozenset({1}),n5_registration=generate(2501)),offline=True)
            s.progress(100000,3)
            s.timeline_event('synthetic_truncation')
            result=s.finish('error')
            self.assertEqual(len(result['tasks']),6)
            self.assertTrue(all(t['status']=='not_decoded' for t in result['tasks']))
            self.assertEqual(result['event_counts']['sample_progress'],1)
            self.assertEqual(result['engine']['clock']['observation_state'],'timeline_unverified')

    def test_synthetic_crc_opcode_foreign_run_order_and_conflict(self):
        import binascii
        from control_match.control_engine import SideControlEngine
        from test_control_engine import wire
        engine=SideControlEngine(EngineConfig(side='ble',run_id=2501,sample_rate=1000000,
            target_ids=frozenset({1}),n5_registration=generate(2501)))
        def kinds(payload, start, available):
            return engine.observe(payload,start,available)
        invalid=bytearray(wire(0,run=2501,period=500));invalid[-1]^=1
        self.assertEqual(kinds(bytes(invalid),0,1)[-1]['event'],'invalid_record')
        self.assertEqual(kinds(wire(0,run=2502,period=500),0,2)[-1]['event'],'foreign_run')
        cmd=dict(run=2501,period=500,command=51,target=1,opcode=1,arg=1,execute=40000,valid=39000)
        invalid=bytearray(wire(70,**cmd));invalid[22]=255
        invalid[-2:]=binascii.crc_hqx(invalid[:-2],0xffff).to_bytes(2,'little')
        self.assertEqual(kinds(bytes(invalid),35000000,35001000)[-1]['event'],'invalid_record')
        kinds(wire(70,**cmd),35000000,35002000)
        conflict=kinds(wire(71,**dict(cmd,arg=2)),35500000,35501000)
        self.assertEqual(conflict[-1]['reason'],'conflicting_task')
        duplicate=kinds(wire(70,**cmd),35000000,35502000)
        self.assertTrue(any(e['event']=='clock_duplicate' for e in duplicate))
        out_of_order=kinds(wire(68,run=2501,period=500),34000000,35503000)
        self.assertTrue(any(e['event']=='out_of_order_training' for e in out_of_order))
        with self.assertRaises(ValueError):engine.advance(1)

    def test_reacquisition_window_expires_without_packets(self):
        c=self.clock()
        for slot in range(0,16,2):self.feed(c,slot)
        self.feed(c,50,100000)
        self.assertEqual(c.state,'reacquiring')
        c.advance(40000000)
        self.assertEqual(c.state,'stale')
        self.assertIsNone(c.candidate)

    def test_independent_ieee_offset_and_rate(self):
        c=ObservationClock(EngineConfig(side='zigbee',run_id=2501,sample_rate=1000000,
            target_ids=frozenset({2})),generate(2501))
        for slot in range(1,68,2):
            if slot in c.registration['probes']:continue
            start=900000+slot*500000*1.0001+472
            c.advance(int(start)+1000)
            c.observe(slot,slot*500,start)
        start=900000+69*500000*1.0001+472
        c.advance(int(start)+1000)
        result=c.score(69,start)
        self.assertAlmostEqual(result['estimated_ms'],34500,places=6)
        self.assertAlmostEqual(result['residual_ms'],0,places=6)

    def test_explicit_synthetic_bound_freeze_and_timeline_cancel(self):
        from control_match.control_engine import SideControlEngine
        from test_control_engine import wire
        def built():
            engine=SideControlEngine(EngineConfig(side='ble',run_id=2501,sample_rate=1000000,
                target_ids=frozenset({1}),external_reference_bound_ms=1,
                n5_registration=generate(2501)))
            for slot in range(0,70,2):
                engine.observe(wire(slot,run=2501,period=500),slot*500000,slot*500000+1000)
            events=engine.observe(wire(70,run=2501,period=500,command=51,target=1,opcode=1,arg=1,
                execute=40000,valid=39000),35000000,35001000)
            self.assertTrue(any(e['event']=='accepted' for e in events))
            return engine
        engine=built()
        self.assertTrue(any(e['event']=='schedule_frozen' for e in engine.advance(39950000)))
        self.assertTrue(any(e['event']=='software_processed' for e in engine.advance(40000000)))
        engine=built()
        events=engine.timeline_event('synthetic_stream_restart',restart=True)
        self.assertTrue(any(e['event']=='cancelled' for e in events))
        self.assertEqual(engine.current_sample,0)
        engine.observe(wire(72,run=2501,period=500),0,1000)
        self.assertEqual(engine.clock.state,'acquiring')
