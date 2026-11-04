"""Live control classification uses only the independently recovered payload."""
import binascii
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from zigbee_rx.control_receive import ControlTracker


PAYLOAD = bytes.fromhex(
    "b2430101ee0301000000c8000000c8002b000000020001010030750000a861000069b2")


def altered(payload, start, stop, value):
    result = bytearray(payload)
    result[start:stop] = value.to_bytes(stop - start, "little")
    result[33:35] = binascii.crc_hqx(result[:33], 0xffff).to_bytes(2, "little")
    return bytes(result)


class ControlTrackerTests(unittest.TestCase):
    def test_valid_duplicate_foreign_and_corrupt_are_distinct(self):
        tracker = ControlTracker(1006, 43, 100)
        record, disposition, error = tracker.observe(PAYLOAD)
        self.assertEqual((record["run_id"], record["command_id"], record["slot_index"], disposition, error),
                         (1006, 43, 1, "unique", None))
        self.assertEqual(tracker.observe(PAYLOAD)[1], "duplicate")
        self.assertEqual(tracker.observe(altered(PAYLOAD, 4, 6, 1007))[1], "foreign_control")
        damaged = bytearray(PAYLOAD)
        damaged[23] ^= 1
        self.assertEqual(tracker.observe(bytes(damaged))[1:], ("invalid_control", "app_crc16"))
        self.assertEqual(tracker.observe(b"\xb2\x5a" + bytes(8))[1], "non_control")
        self.assertEqual((tracker.counts["unique"], tracker.counts["duplicate"],
                          tracker.counts["foreign_control"], tracker.counts["invalid_control"]),
                         (1, 1, 1, 1))

    def test_out_of_order_and_planned_range(self):
        tracker = ControlTracker(1006, 43, 3)
        self.assertEqual(tracker.observe(PAYLOAD)[1], "unique")
        slot0 = altered(altered(PAYLOAD, 6, 10, 0), 10, 14, 0)
        self.assertEqual(tracker.observe(slot0)[1], "unique")
        self.assertEqual(tracker.counts["out_of_order"], 1)
        self.assertEqual(tracker.longest_loss_burst(), 1)
        slot3 = altered(altered(PAYLOAD, 6, 10, 3), 10, 14, 600)
        self.assertEqual(tracker.observe(slot3)[1], "out_of_range_control")
        self.assertEqual(tracker.counts["unique"], 2)

    def test_unfiltered_run_keeps_distinct_tasks_and_global_slots(self):
        tracker = ControlTracker(1006, None, 4)
        self.assertEqual(tracker.observe(PAYLOAD)[1], "unique")
        second = altered(altered(altered(PAYLOAD, 6, 10, 2), 10, 14, 400),
                         16, 20, 44)
        self.assertEqual(tracker.observe(second)[1], "unique")
        self.assertEqual(tracker.observe(second)[1], "duplicate")
        self.assertEqual(tracker.counts["unique"], 2)
        self.assertEqual(set(tracker.task_keys), {43, 44})
        self.assertEqual(tracker.longest_loss_burst(), 1)
        changed_arg = altered(altered(altered(PAYLOAD, 6, 10, 3), 10, 14, 600),
                              23, 25, 2)
        self.assertEqual(tracker.observe(changed_arg)[1], "conflicting_task_fields")


if __name__ == "__main__":
    unittest.main()
