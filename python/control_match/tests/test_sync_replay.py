"""The two clock fits must use separate past packets and untouched later checks."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_replay import replay


def side(slots, offset, slope, marker_offset=0):
    return {"by_slot": {slot: {"record": {"ref_tick_ms": slot * 200},
                               "sample_start": (offset + slope * slot * .2 + marker_offset) * 8_000_000}
                        for slot in slots}}


class SyncReplayTests(unittest.TestCase):
    def test_disjoint_training_and_future_validation(self):
        ble = side([0, 1, 2, 3, 4, 5, 6], 10, 1.00001)
        zigbee = side([0, 1, 2, 3, 4, 5, 6], 20, .99999, .000472)
        summary, details = replay(ble, zigbee, 8_000_000, 8_000_000, 5, (2, 4))
        disjoint = next(row for row in summary if row["mode"] == "disjoint" and row["packets_per_side"] == 2)
        self.assertEqual(disjoint["train_overlap"], 0)
        self.assertEqual(disjoint["validation_count"], 2)
        self.assertLess(disjoint["max_abs_us"], .001)
        self.assertEqual({row["validation_slot"] for row in details}, {5, 6})
        self.assertEqual(next(row for row in summary if row["mode"] == "disjoint" and row["packets_per_side"] == 4)["status"], "insufficient_training")


if __name__ == "__main__":
    unittest.main()
