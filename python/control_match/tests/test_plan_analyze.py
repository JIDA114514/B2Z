import tempfile
import unittest
from pathlib import Path

from python.control_match.plan_analyze import read_plan, summarize


def record(slot):
    return {"version": 1, "flags": 1, "run_id": 7, "slot_index": slot,
            "ref_tick_ms": slot * 200, "period_ms": 200, "command_id": 43,
            "execute_at_ms": 3000, "valid_until_ms": 2500}


class PlanAnalysisTests(unittest.TestCase):
    def test_board_log_must_include_each_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "board.board.log"
            header = ("CONTROL_PLAN_STATS final=1 state=complete run_id=7 tasks=1 "
                      "planned_slots=2 reached_slots=2 generated=2 primary_completed=2 "
                      "tx_completed=2 deadline_miss=0 dma_timeout=0\n"
                      "CONTROL_PLAN_TASK run_id=7 entry=0 command_id=43 first_slot=0 "
                      "repeats=2 generated=2 primary_completed=2 tx_completed=2 "
                      "deadline_miss=0 dma_timeout=0\n")
            path.write_text(header +
                            "CONTROL_PLAN_SLOT run_id=7 slot=0 entry=0 command_id=43 "
                            "generated=1 primary_completed=1 tx_completed=1 "
                            "deadline_miss=0 dma_timeout=0\n")
            with self.assertRaisesRegex(ValueError, "complete CONTROL_PLAN_TASK"):
                read_plan(path, 7)
            path.write_text(path.read_text() +
                            "CONTROL_PLAN_SLOT run_id=7 slot=1 entry=0 command_id=43 "
                            "generated=1 primary_completed=1 tx_completed=1 "
                            "deadline_miss=0 dma_timeout=0\n")
            plan = read_plan(path, 7)
            self.assertEqual(list(plan["slots"]), [0, 1])

    def test_different_attempts_still_recover_one_joint_task(self):
        plan = {"stats": {"run_id": "7", "tx_completed": "2"},
                "tasks": [{"command_id": "43", "first_slot": "0", "repeats": "2",
                           "tx_completed": "2"}],
                "slots": {0: {"entry": 0, "command_id": 43, "board_tx_completed": 1},
                          1: {"entry": 0, "command_id": 43, "board_tx_completed": 1}}}
        ble = {"by_slot": {0: {"record": record(0)}}, "live": None}
        zigbee = {"by_slot": {1: {"record": record(1)}}, "live": None}
        summary, slots, tasks = summarize(plan, ble, zigbee)
        self.assertEqual(summary["joint_valid_attempts"], 0)
        self.assertEqual(summary["joint_decoded_tasks"], 1)
        self.assertEqual((summary["ble_only_attempts"], summary["zigbee_only_attempts"]), (1, 1))
        self.assertEqual(tasks[0]["joint_task_decoded"], 1)
        self.assertEqual(len(slots), 2)


if __name__ == "__main__":
    unittest.main()
