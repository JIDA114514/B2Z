"""N2 costs retain sync updates, repeats and partial transmissions."""
import tempfile
from pathlib import Path
import unittest

from python.control_match.burst_cost import cost_summary
from python.control_match.plan_analyze import read_plan, summarize


def board_log(separate=True, fail_ieee=False):
    mode = "separate_secondary_ch3" if separate else "standard_secondary_ch3"
    n = 3
    failed = int(fail_ieee)
    lines = [f"CONTROL_PLAN_STATS final=1 state=complete run_id=7 period_ms=500 tasks=2 planned_slots={n} reached_slots={n} generated={n} primary_completed={n} tx_completed={n} deadline_miss=0 dma_timeout={failed} rf_mode={mode}",
             "CONTROL_PLAN_TASK run_id=7 entry=0 command_id=0 first_slot=0 repeats=1 generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout=0",
             f"CONTROL_PLAN_TASK run_id=7 entry=1 command_id=43 first_slot=1 repeats=2 generated=2 primary_completed=2 tx_completed=2 deadline_miss=0 dma_timeout={failed}"]
    for slot in range(n):
        timeout = int(fail_ieee and slot == 2)
        lines.append(f"CONTROL_PLAN_SLOT run_id=7 slot={slot} entry={int(slot > 0)} command_id={43 if slot else 0} generated=1 primary_completed=1 tx_completed=1 deadline_miss=0 dma_timeout={timeout}")
        kinds = [("primary", 136), ("secondary", 496 if separate else 1872)]
        if separate:
            kinds.append(("ieee", 1376))
        for i, (kind, air) in enumerate(kinds):
            start = slot * 500000 + 100 + i * 10000
            t = int(timeout and kind == "ieee")
            lines.append(f"CONTROL_BURST run_id=7 slot={slot} kind={kind} generated=1 attempted=1 started=1 completed={1-t} timeout={t} iq_bytes=4096 air_us={air} pad_us=10 prepared_us={slot * 500000} submit_before_us={start} submit_after_us={start+10} finish_us={start+air+100}")
    bursts = n * (3 if separate else 2)
    lines.append(f"CONTROL_COST_STATS run_id=7 logical_slots={n} ble_tx_completed={n} ieee_tx_completed={n-failed} burst_attempted={bursts} burst_started={bursts} burst_completed={bursts-failed}")
    return "\n".join(lines) + "\n"


def load(text):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "board.log"
        path.write_text(text)
        return read_plan(path, 7)


def side(slot, wire=None):
    record = {"version": 1, "flags": 1, "run_id": 7, "slot_index": slot,
              "ref_tick_ms": slot * 500, "period_ms": 500, "command_id": 43,
              "execute_at_ms": 3000, "valid_until_ms": 2500,
              "target_id": 1 if wire else 2, "opcode": 1, "arg": 7}
    return {"by_slot": {slot: {"record": record, "wire_format": wire}}, "live": None}


class BurstCostTests(unittest.TestCase):
    def test_equal_air_budget_different_bursts_and_repetition_dedup(self):
        for separate in (True, False):
            plan = load(board_log(separate))
            ble = side(1, "ble-only" if separate else "joint")
            zigbee = side(2)
            result, slots, tasks = summarize(plan, ble, zigbee)
            self.assertEqual(result["joint_decoded_tasks"], 1)
            self.assertEqual(result["joint_valid_attempts"], 0)
            cost = result["waveform_cost"]
            self.assertEqual(cost["submitted_waveform_us"], 6024)
            self.assertEqual(cost["burst_completed"], 9 if separate else 6)
            self.assertEqual(cost["per_joint_decoded_task"]["value_us"], 6024)
            self.assertEqual(tasks[0]["board_ieee_tx_completed"], 2)
            self.assertEqual(len(slots), 3)

    def test_ieee_timeout_does_not_erase_ble_or_discount_attempt(self):
        plan = load(board_log(fail_ieee=True))
        self.assertEqual(plan["slots"][2]["board_ble_tx_completed"], 1)
        self.assertEqual(plan["slots"][2]["board_ieee_tx_completed"], 0)
        cost = cost_summary(plan["bursts"], 0)
        self.assertEqual(cost["submitted_waveform_us"], 6024)
        self.assertEqual(cost["uncertain_bursts"], 1)
        self.assertIsNone(cost["per_joint_decoded_task"]["value_us"])
        self.assertIsNone(cost["actual_rf_airtime_us"])

    def test_failed_submission_retains_attempted_budget(self):
        text = board_log(fail_ieee=True)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("CONTROL_BURST ") and "slot=2 kind=ieee" in line:
                values = dict(part.split("=", 1) for part in line.split()[1:])
                values.update(started="0", timeout="0", finish_us="0")
                lines[index] = "CONTROL_BURST " + " ".join(f"{k}={v}" for k, v in values.items())
        text = "\n".join(lines).replace("dma_timeout=1", "dma_timeout=0").replace("burst_started=9", "burst_started=8")
        plan = load(text)
        cost = cost_summary(plan["bursts"], 0)
        self.assertEqual(cost["submitted_waveform_us"], 6024 - 1376)
        self.assertEqual(cost["attempted_waveform_budget_us"], 6024)
        self.assertEqual(cost["uncertain_bursts"], 1)
        self.assertEqual(plan["slots"][2]["board_ble_tx_completed"], 1)

    def test_duplicate_missing_and_wrong_budget_rejected(self):
        text = board_log()
        burst = next(line for line in text.splitlines() if line.startswith("CONTROL_BURST "))
        for bad in (text + burst + "\n", text.replace(burst + "\n", ""),
                    text.replace("air_us=496", "air_us=1872"),
                    text.replace("burst_completed=9", "burst_completed=8")):
            with self.subTest(bad=bad[-80:]), self.assertRaises(ValueError):
                load(bad)

    def test_receiver_format_must_match_board_mode(self):
        with self.assertRaisesRegex(ValueError, "wire format"):
            summarize(load(board_log()), side(1, "joint"), side(2))

    def test_separate_cannot_silently_use_old_board_counter(self):
        text = "\n".join(line for line in board_log().splitlines()
                         if not line.startswith(("CONTROL_BURST", "CONTROL_COST_STATS")))
        with self.assertRaisesRegex(ValueError, "CONTROL_COST_STATS"):
            load(text)


class ComparisonTests(unittest.TestCase):
    def test_unrecorded_conditions_are_not_a_fairness_pass(self):
        from python.control_match.compare_n2 import compare
        joint, _, _ = summarize(load(board_log(False)), side(1, "joint"), side(2))
        separate, _, _ = summarize(load(board_log(True)), side(1, "ble-only"), side(2))
        result = compare(joint, separate, {})
        self.assertFalse(result["recorded_conditions_match"])
        self.assertIn("conditions.topology", result["unresolved_or_different_conditions"])
        self.assertEqual(result["joint_minus_separate_submitted_waveform_us"], 0)
        joint["ble_follow"] = {}
        with self.assertRaisesRegex(ValueError, "fixed-frequency"):
            compare(joint, separate, {})
