#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest


MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from bluebee_perf_protocol import (  # noqa: E402
    SequenceTracker,
    build_test_payload,
    parse_board_stats_text,
    parse_test_payload,
    ratio,
)


class PayloadTests(unittest.TestCase):
    def test_known_46_byte_vector(self):
        payload = build_test_payload(46, 0x1234, 0x89ABCDEF)
        self.assertEqual(
            payload.hex(),
            "b25a010a3412efcdab89e77dbe2c6dc1919154b5408e12bce6ffa02e71b87dcd"
            "32b8f3c0e3bb15a6400a44d6a69b",
        )
        self.assertTrue(parse_test_payload(payload, 0x1234, 46).valid)

    def test_fill_corruption_is_rejected(self):
        payload = bytearray(build_test_payload(16, 7, 9))
        payload[-1] ^= 0x01
        parsed = parse_test_payload(payload, 7, 16)
        self.assertFalse(parsed.valid)
        self.assertEqual(parsed.reason, "fill")


class SequenceTests(unittest.TestCase):
    def test_duplicate_order_and_loss(self):
        tracker = SequenceTracker(expected_run_id=0x1234, expected_payload_len=10)
        results = []
        for sequence in (0, 1, 4, 4, 3, 7):
            _, result = tracker.observe(build_test_payload(10, 0x1234, sequence))
            results.append(result)
        self.assertEqual(
            results,
            ["unique", "unique", "unique", "duplicate", "out_of_order", "unique"],
        )
        self.assertEqual(tracker.unique, 5)
        self.assertEqual(tracker.duplicate, 1)
        self.assertEqual(tracker.out_of_order, 1)
        self.assertEqual(tracker.longest_loss_burst(scheduled=9), 2)


class BoardStatsTests(unittest.TestCase):
    def test_last_matching_final_line(self):
        text = "\n".join(
            (
                "PERF_STATS final=0 test=pure state=running run_id=5 scheduled=1",
                "PERF_STATS final=1 test=pure state=complete run_id=6 scheduled=9 tx_completed=8",
                "PERF_STATS final=1 test=pure state=complete run_id=5 scheduled=10 tx_completed=9",
            )
        )
        stats = parse_board_stats_text(text, expected_run_id=5)
        self.assertEqual(stats["scheduled"], 10)
        self.assertEqual(stats["tx_completed"], 9)
        self.assertEqual(
            ratio(8, 10),
            {"numerator": 8, "denominator": 10, "value": 0.8},
        )
        self.assertIsNone(ratio(0, 0)["value"])


if __name__ == "__main__":
    unittest.main()
