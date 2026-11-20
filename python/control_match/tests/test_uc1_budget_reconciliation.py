"""Audit a recorded board budget against an immutable explicit-K capture manifest."""
from copy import deepcopy
from pathlib import Path
import unittest

from python.control_match.plan_analyze import read_plan
from python.control_match.uc1_analyze import check_board_matches_manifest
from python.control_match.uc1_config import load


ROOT = Path(__file__).resolve().parents[3]


class BudgetReconciliationTests(unittest.TestCase):
    def test_board_budget_is_explicitly_reconciled_only_when_k_and_remainder_agree(self):
        for run_id, unused in ((2711, 176), (2712, 432), (2713, 432), (2714, 192)):
            with self.subTest(run_id=run_id):
                manifest = load(ROOT / f"python/control_match/configs/uc1_{run_id}.json", run_id)
                folder = next((ROOT / "python/experiments").glob(f"*_run{run_id}"))
                board = read_plan(folder / "board.board.log", run_id)
                with self.assertRaisesRegex(ValueError, "budget_us"):
                    check_board_matches_manifest(manifest, board)
                audit = check_board_matches_manifest(manifest, board, reconcile_board_budget=True)
                self.assertEqual(audit["board_budget_us"], 6000)
                self.assertEqual(audit["board_unused_per_task_us"], unused)
                self.assertFalse(audit["policy_command_proven"])

                inconsistent = deepcopy(board)
                inconsistent["uc1"]["unused_per_task_us"] = str(unused + 1)
                with self.assertRaisesRegex(ValueError, "cannot prove"):
                    check_board_matches_manifest(manifest, inconsistent, reconcile_board_budget=True)

                inconsistent = deepcopy(board)
                inconsistent["uc1"]["budget_us"] = "5000"
                with self.assertRaisesRegex(ValueError, "cannot prove"):
                    check_board_matches_manifest(manifest, inconsistent, reconcile_board_budget=True)


if __name__ == "__main__":
    unittest.main()
