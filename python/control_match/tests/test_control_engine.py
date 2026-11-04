"""Command decisions use local IQ progress and independently parsed v1 bytes."""
import binascii
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_engine import EngineConfig, SideControlEngine


def wire(slot, *, run=1001, command=0, target=0, opcode=0, arg=0,
         execute=0, valid=0, period=200):
    raw = bytearray(35)
    raw[:2] = b"\xb2\x43"
    raw[2] = 1
    raw[3] = int(command != 0)
    for offset, width, value in ((4, 2, run), (6, 4, slot), (10, 4, slot * period),
                                 (14, 2, period), (16, 4, command), (20, 2, target),
                                 (23, 2, arg), (25, 4, execute), (29, 4, valid)):
        raw[offset:offset + width] = value.to_bytes(width, "little")
    raw[22] = opcode
    raw[33:35] = binascii.crc_hqx(raw[:33], 0xffff).to_bytes(2, "little")
    return bytes(raw)


def config(**changes):
    values = dict(side="ble", run_id=1001, sample_rate=1000,
                  target_ids=frozenset((1,)), external_reference_bound_ms=1,
                  drift_bound_ppm=0)
    values.update(changes)
    return EngineConfig(**values)


def kinds(events):
    return [event["event"] for event in events]


class ControlEngineTests(unittest.TestCase):
    def test_nonadjacent_updates_repeat_and_one_software_action(self):
        engine = SideControlEngine(config())
        self.assertIn("clock_updated", kinds(engine.observe(wire(0), 1000, 1010)))
        self.assertIn("clock_updated", kinds(engine.observe(wire(10), 3000, 3010)))
        self.assertTrue(engine.clock.rate_fitted)
        command = dict(command=42, target=1, opcode=1, arg=7, execute=6000, valid=5500)
        events = engine.observe(wire(20, **command), 5000, 5010)
        self.assertIn("accepted", kinds(events))
        self.assertEqual(next(e for e in events if e["event"] == "scheduled")["target_sample"], 7000)
        self.assertIn("duplicate", kinds(engine.observe(wire(21, **command), 5200, 5210)))
        self.assertNotIn("software_processed", kinds(engine.advance(6999)))
        self.assertEqual(kinds(engine.advance(7000)).count("software_processed"), 1)
        self.assertEqual(engine.state, {1: 7})
        self.assertEqual(engine.snapshot()["task_status"], {"42": "processed"})
        self.assertNotIn("software_processed", kinds(engine.advance(7100)))

    def test_zigbee_marker_and_out_of_order_time_updates(self):
        engine = SideControlEngine(config(side="zigbee", sample_rate=1_000_000))
        engine.observe(wire(0), 1_000_472, 1_002_000)
        self.assertEqual(engine.clock.predict_sample(0), 1_000_000)
        engine.observe(wire(10), 3_000_472, 3_002_000)
        events = engine.observe(wire(5), 2_000_472, 3_003_000)
        self.assertIn("clock_updated", kinds(events))
        self.assertEqual(engine.clock.latest_ref_ms, 2000)
        self.assertEqual(engine.clock.details()["training_packets"], 3)

    def test_invalid_foreign_target_and_unsupported_do_not_process(self):
        engine = SideControlEngine(config(supported_opcodes=frozenset((0, 1))))
        damaged = bytearray(wire(0))
        damaged[10] ^= 1
        self.assertIn("invalid_record", kinds(engine.observe(bytes(damaged), 1000, 1010)))
        self.assertEqual(engine.clock.version, 0)
        self.assertIn("foreign_run", kinds(engine.observe(wire(0, run=1002), 1000, 1010)))
        self.assertEqual(engine.clock.version, 0)
        engine.observe(wire(0), 1000, 1010)
        wrong = engine.observe(wire(1, command=41, target=2, opcode=1,
                                    execute=3000, valid=2500), 1200, 1210)
        self.assertEqual(wrong[-1]["reason"], "wrong_target")
        unsupported = engine.observe(wire(2, command=42, target=1, opcode=2,
                                          execute=3000, valid=2500), 1400, 1410)
        self.assertEqual(unsupported[-1]["reason"], "unsupported")
        self.assertEqual(engine.tasks, {})

    def test_availability_not_packet_start_controls_expiry_and_lateness(self):
        engine = SideControlEngine(config())
        engine.observe(wire(0), 1000, 1010)
        expired = engine.observe(wire(10, command=1, target=1, opcode=1,
                                      execute=2300, valid=2010), 3000, 3020)
        self.assertEqual(expired[-1]["reason"], "expired")
        late = engine.observe(wire(11, command=2, target=1, opcode=1,
                                   execute=2225, valid=2223), 3200, 3220)
        self.assertEqual(late[-1]["reason"], "late")

    def test_uncalibrated_reference_denies_timed_action(self):
        engine = SideControlEngine(config(external_reference_bound_ms=None))
        events = engine.observe(wire(0, command=42, target=1, opcode=1,
                                     execute=3000, valid=2500), 1000, 1010)
        self.assertEqual(events[-1]["reason"], "time_quality_insufficient")
        self.assertEqual(engine.tasks, {})

    def test_clock_updates_retime_before_freeze_and_processing_late_cancels(self):
        engine = SideControlEngine(config(max_rate_ppm=2000))
        engine.observe(wire(0, command=42, target=1, opcode=2, arg=9,
                            execute=4000, valid=3500), 1000, 1010)
        old_target = engine.tasks[42].target_sample
        events = engine.observe(wire(10), 3001, 3010)
        self.assertIn("rescheduled", kinds(events))
        self.assertGreater(engine.tasks[42].target_sample, old_target)
        target = engine.tasks[42].target_sample
        cancelled = engine.advance(target + 60)
        self.assertEqual(next(e for e in cancelled if e["event"] == "cancelled")["reason"],
                         "processing_late")
        self.assertEqual(engine.triggers, [])

    def test_rejected_attempt_can_be_accepted_later_but_conflict_cannot(self):
        engine = SideControlEngine(config())
        engine.observe(wire(0), 1000, 1010)
        command = dict(command=42, target=1, opcode=1, arg=1,
                       execute=3000, valid=2500)
        # Delayed first attempt is outside the validity window.
        self.assertEqual(engine.observe(wire(1, **command), 1200, 3800)[-1]["reason"],
                         "expired")
        with self.assertRaisesRegex(ValueError, "monotonically"):
            engine.advance(1410)
        # A separate engine demonstrates a recoverable time-quality rejection.
        retry = SideControlEngine(config(max_uncertainty_ms=1.9, drift_bound_ppm=1000))
        retry.observe(wire(0), 1000, 1010)
        first = retry.observe(wire(10, **command), 3000, 3010)
        self.assertEqual(first[-1]["reason"], "time_quality_insufficient")
        retry.observe(wire(11), 3200, 3210)
        second = retry.observe(wire(12, **command), 3400, 3410)
        self.assertIn("accepted", kinds(second))
        conflict = retry.observe(wire(12, **{**command, "arg": 2}), 3400, 3610)
        self.assertEqual(conflict[-1]["reason"], "conflicting_task")
        self.assertEqual(retry.clock.version, 4)

    def test_clock_outlier_cannot_schedule_command(self):
        engine = SideControlEngine(config())
        engine.observe(wire(0), 1000, 1010)
        events = engine.observe(wire(10, command=42, target=1, opcode=1,
                                     execute=3000, valid=2500), 3051, 3060)
        self.assertIn("clock_outlier", kinds(events))
        self.assertEqual(events[-1]["reason"], "time_quality_insufficient")
        self.assertEqual(engine.clock.version, 1)

    def test_freeze_prevents_retiming_and_trigger_fires_once(self):
        engine = SideControlEngine(config())
        command = dict(command=42, target=1, opcode=2, arg=9,
                       execute=4000, valid=3500)
        engine.observe(wire(0, **command), 1000, 1010)
        target = engine.tasks[42].target_sample
        self.assertIn("schedule_frozen", kinds(engine.advance(4900)))
        events = engine.observe(wire(19), 4801, 4900)
        self.assertNotIn("rescheduled", kinds(events))
        self.assertEqual(engine.tasks[42].target_sample, target)
        self.assertEqual(kinds(engine.advance(target)).count("software_processed"), 1)
        self.assertEqual(engine.triggers, [{"target_id": 1, "arg": 9, "local_sample": target}])
        self.assertIn("duplicate", kinds(engine.observe(wire(17, **command), 4400, 5010)))
        self.assertEqual(len(engine.triggers), 1)


if __name__ == "__main__":
    unittest.main()
