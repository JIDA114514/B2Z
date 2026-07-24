#!/usr/bin/env python3

from contextlib import redirect_stderr
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_DIR = Path(__file__).resolve().parents[1]
STD_ZIGBEE_DIR = MODULE_DIR.parent / "ctc_sim" / "std_zigbee"
sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(STD_ZIGBEE_DIR))

import bluebee_throughput_scan as scan  # noqa: E402
from bluebee_perf_protocol import SequenceTracker, build_test_payload  # noqa: E402
import zigbee_perf_rx  # noqa: E402


class ReceiverArgumentTests(unittest.TestCase):
    def test_bounded_tx_defaults_receiver_to_duration_plus_guard(self):
        argv = [
            "zigbee_perf_rx.py",
            "--payload-len",
            "46",
            "--tx-duration-s",
            "60",
            "--tx-interval-us",
            "100000",
        ]
        with patch.object(sys, "argv", argv):
            args = zigbee_perf_rx.parse_args()

        self.assertEqual(args.duration, 70.0)
        self.assertEqual(args.expected_packets, 600)

    def test_bounded_tx_arguments_must_be_paired(self):
        argv = [
            "zigbee_perf_rx.py",
            "--tx-duration-s",
            "60",
        ]
        with patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                zigbee_perf_rx.parse_args()

    def test_receiver_calibration_and_offset_policy_arguments(self):
        argv = [
            "zigbee_perf_rx.py",
            "--standard-offset-policy",
            "ranked2",
            "--freq-offset",
            "100000",
            "--cfo-correction-hz",
            "-25000",
            "--rf-gain",
            "40",
            "--if-gain",
            "32",
            "--bb-gain",
            "24",
        ]
        with patch.object(sys, "argv", argv):
            args = zigbee_perf_rx.parse_args()

        self.assertEqual(args.standard_offset_policy, "ranked2")
        self.assertEqual(args.freq_offset, 100000)
        self.assertEqual(args.cfo_correction_hz, -25000)
        self.assertEqual(args.rf_gain, 40)
        self.assertEqual(args.if_gain, 32)
        self.assertEqual(args.bb_gain, 24)


class ReceiverSummaryTests(unittest.TestCase):
    @staticmethod
    def make_args(tx_duration_s=None, tx_interval_us=None, expected_packets=None):
        return SimpleNamespace(
            run_id=7,
            payload_len=10,
            tx_duration_s=tx_duration_s,
            tx_interval_us=tx_interval_us,
            expected_packets=expected_packets,
            chip_source="standard",
            chip_zmq="tcp://127.0.0.1:55556",
            standard_keep_offset=None,
            standard_offset_policy="adaptive",
            standard_ambiguity="auto",
            phase_keep_offset=None,
            freq_offset=0.0,
            cfo_correction_hz=0.0,
            rf_gain=50.0,
            if_gain=89.0,
            bb_gain=0.0,
        )

    def make_summary(self, args, sequences):
        tracker = SequenceTracker(expected_run_id=7, expected_payload_len=10)
        for sequence in sequences:
            tracker.observe(build_test_payload(10, 7, sequence))
        return zigbee_perf_rx.build_summary(
            args,
            tracker,
            None,
            100.0,
            120.0,
            len(sequences),
            0,
            0,
            1,
            Path("raw.csv"),
        )

    def test_bounded_summary_uses_planned_range_and_duration(self):
        summary = self.make_summary(
            self.make_args(10, 1_000_000, 10),
            (0, 1, 3, 9, 11),
        )

        self.assertEqual(summary["planned_sequences"]["in_range_unique"], 4)
        self.assertEqual(summary["planned_sequences"]["missing"], 6)
        self.assertEqual(
            summary["planned_sequences"]["out_of_range_sequences"], [11]
        )
        self.assertEqual(
            summary["ratios"]["planned_end_to_end_receive"]["value"], 0.4
        )
        self.assertIsNone(summary["ratios"]["wireless_prr"]["value"])
        self.assertEqual(summary["throughput"]["time_s"], 10)
        self.assertEqual(
            summary["throughput"]["time_basis"], "planned_tx_duration"
        )

    def test_unbounded_summary_leaves_planned_metrics_unavailable(self):
        summary = self.make_summary(self.make_args(), (4, 5))

        self.assertIsNone(summary["planned_sequences"])
        self.assertIsNone(
            summary["ratios"]["planned_end_to_end_receive"]["value"]
        )
        self.assertEqual(
            summary["throughput"]["time_basis"],
            "receiver_observation_duration",
        )


class ScanPlanTests(unittest.TestCase):
    def test_cases_are_unique_and_never_request_board_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(
                test="both",
                mode="both",
                payloads=(10, 46),
                intervals_us=(100000, 50000),
                tx_duration_s=60,
                guard_s=10,
                base_run_id=1000,
            )
            cases = scan.build_cases(args, Path(temp_dir))

        self.assertEqual(len(cases), 16)
        self.assertEqual(len({case["run_id"] for case in cases}), 16)
        for case in cases:
            command = case["receiver_command"]
            self.assertNotIn("--board-stats", command)
            self.assertIn("--standard-offset-policy", command)
            self.assertIn("adaptive", command)
            self.assertIn("--tx-duration-s", command)
            self.assertIn("--tx-interval-us", command)
            self.assertEqual(case["receiver_duration_s"], 70)
            self.assertTrue(
                case["board_command"].startswith(
                    f"bluebee_{case['test']}_perf_start?"
                )
            )

    def test_result_row_uses_only_planned_rate_and_planned_time(self):
        case = {
            "index": 0,
            "test": "pure",
            "mode": "double",
            "payload_len": 46,
            "interval_us": 50000,
            "tx_duration_s": 60,
            "run_id": 9,
            "json_result": "case.json",
        }
        result = {
            "ratios": {
                "planned_end_to_end_receive": {"value": 0.995},
                "wireless_prr": {
                    "value": 1.0,
                    "numerator": 1,
                    "denominator": 1,
                },
            },
            "planned_sequences": {
                "expected_packets": 1200,
                "in_range_unique": 1194,
                "missing": 6,
                "out_of_range_count": 0,
            },
            "throughput": {
                "gross_bit_s": 7323.2,
                "gross_byte_s": 915.4,
                "application_bit_s": 5728.0,
                "application_byte_s": 716.0,
                "time_basis": "planned_tx_duration",
            },
            "receiver": {
                "crc_failure": 0,
                "duplicate": 0,
                "out_of_order": 0,
                "longest_loss_burst": 1,
            },
        }

        row = scan.result_row(case, result)

        self.assertEqual(row["planned_end_to_end_receive"], 0.995)
        self.assertTrue(row["stable_planned_99"])
        self.assertEqual(row["time_basis"], "planned_tx_duration")
        self.assertIsNone(row["wireless_prr"])


if __name__ == "__main__":
    unittest.main()
