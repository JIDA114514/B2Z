"""N5 task ablation invariants with synthetic records only."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from control_match.control_engine import EngineConfig
from control_match.n5_config import generate
from control_match.n5_task_ablate import (conditions, mutate_v1, ratio, replay_selected,
                                          select_observations, synthetic_rule_cases,
                                          synthetic_wire, task_rows)
from control_match.protocol import control_record


class N5TaskAblationTests(unittest.TestCase):
    def test_k_uses_planned_attempts_and_keeps_sync(self):
        sync = synthetic_wire(68)
        second = synthetic_wire(71, command_id=51, target_id=1, opcode=1, arg=1,
                                execute_at_ms=40000, valid_until_ms=39000)
        rows = [dict(payload=sync, record=control_record(sync), start=1, available=2, line_no=1),
                dict(payload=second, record=control_record(second), start=3, available=4, line_no=2)]
        tasks = {51: dict(command_id=51, first_slot=70, attempts=3)}
        first1 = dict(kind="repeat", value=1)
        kept, counts = select_observations(rows, tasks, first1, 1000, 100)
        self.assertEqual([r["record"]["slot_index"] for r in kept], [68])
        self.assertEqual(counts["filtered_task_observations"], 1)
        kept, counts = select_observations(rows, tasks, dict(kind="repeat", value=3), 1000, 100)
        self.assertEqual([r["record"]["slot_index"] for r in kept], [68, 71])
        self.assertEqual(counts["filtered_task_observations"], 0)

    def test_lead_changes_only_deadlines_and_valid_crc(self):
        original = synthetic_wire(70, command_id=51, target_id=1, opcode=1, arg=1,
                                  execute_at_ms=40000, valid_until_ms=39000)
        changed = mutate_v1(original, execute_at_ms=35500, valid_until_ms=35400)
        self.assertEqual(original[:25], changed[:25])
        self.assertNotEqual(original[25:], changed[25:])
        record = control_record(changed)
        self.assertEqual((record["execute_at_ms"], record["valid_until_ms"]), (35500, 35400))
        self.assertEqual(control_record(original)["execute_at_ms"], 40000)
        with self.assertRaisesRegex(ValueError, "semantics"):
            mutate_v1(original, execute_at_ms=35000, valid_until_ms=35400)

    def test_delay_preserves_packet_marker_and_censors_tail(self):
        sync = synthetic_wire(0)
        rows = [dict(payload=sync, record=control_record(sync), start=100,
                     available=105, line_no=1),
                dict(payload=sync, record=control_record(sync), start=900,
                     available=950, line_no=2)]
        selected, counts = select_observations(rows, {}, dict(kind="delay", value=100),
                                               rate=1000, total=1000)
        self.assertEqual(len(selected), 1)
        self.assertEqual((selected[0]["start"], selected[0]["available"]), (100, 205))
        self.assertEqual(counts["right_censored_observations"], 1)
        self.assertEqual(rows[0]["available"], 105)

    def test_uncalibrated_rejects_and_immediate_does_not_assess_deadline(self):
        payload = synthetic_wire(20, command_id=42, target_id=1, opcode=1, arg=1,
                                 execute_at_ms=13000, valid_until_ms=12000)
        rows = [dict(payload=payload, record=control_record(payload), start=11000,
                     available=11010, line_no=1)]
        config = EngineConfig(side="ble", run_id=9001, sample_rate=1000,
                              target_ids=frozenset({1}))
        scheduled, _ = replay_selected(rows, config, total=15000, step=100)
        self.assertTrue(any(e["event"] == "rejected" and e["reason"] == "time_quality_insufficient"
                            for e in scheduled))
        immediate, _ = replay_selected(rows, config, total=15000, step=100, immediate=True)
        self.assertEqual(sum(e["event"] == "software_processed" for e in immediate), 1)
        self.assertTrue(any(e.get("deadline_status") == "not_evaluated_no_time_reference"
                            for e in immediate))

    def test_all_missing_keeps_six_task_rows_and_zero_denominator(self):
        c = generate(2504, provenance=False)
        plan = {"slots": {slot: {"board_tx_completed": 1} for slot in range(300)}}
        data = {"config": c, "plan": plan, "observations": {"ble": [], "zigbee": []}}
        rows = task_rows(data, dict(name="missing", evidence="synthetic", kind="original"),
                         {"ble": [], "zigbee": []}, {"ble": [], "zigbee": []})
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(r["joint_decoded"] for r in rows), 0)
        self.assertIsNone(ratio(0, 0)["value"])

    def test_rule_matrix_and_conditions_are_complete(self):
        cases = synthetic_rule_cases()
        self.assertEqual(len(cases), 20)
        self.assertTrue(all(r["passed"] for r in cases))
        names = [r["name"] for r in conditions()]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("repeat_all_uncalibrated", names)
        self.assertIn("lead_500ms_synthetic_bound_1ms", names)
        self.assertIn("delay_100ms_synthetic_bound_1ms", names)


if __name__ == "__main__":
    unittest.main()
