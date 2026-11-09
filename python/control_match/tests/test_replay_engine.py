"""One-side replay preserves packet availability and never borrows the other side."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_engine import EngineConfig
from replay_engine import main, replay_records


BLE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000100010100b80b0000c40900008098")
ZIGBEE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000200010200b80b0000c4090000eae6")


def packet(side, *, available=True):
    start = 2_400_000 if side == "ble" else 2_400_472
    common = {"sample_start": start}
    if available:
        common["available_sample"] = 2_401_000
    if side == "ble":
        return {**common, "crc_ok": True, "kind": "same_channel_auxiliary_diagnostic",
                "pdu_length": 224, "extended": {"adi": {"did": 7}, "ad_structures": [
                    {"type": 255, "company_id": 65535,
                     "data_hex": (b"\xff\xff" + BLE + bytes(172)).hex()}]}}
    return {**common, "fcs_ok": True, "payload_hex": ZIGBEE.hex()}


class ReplayEngineTests(unittest.TestCase):
    def test_both_sides_process_own_record_at_own_target(self):
        for side, target, value in (("ble", 1, 1), ("zigbee", 2, 2)):
            with self.subTest(side=side):
                config = EngineConfig(side=side, run_id=1001, sample_rate=1_000_000,
                                      target_ids=frozenset((target,)),
                                      external_reference_bound_ms=1, drift_bound_ppm=0)
                events, summary = replay_records([packet(side)], config, 4_000_000)
                self.assertEqual(summary["events"]["accepted"], 1)
                self.assertEqual(summary["events"]["software_processed"], 1)
                self.assertEqual(summary["engine"]["software_state"], {target: value})
                processed = next(event for event in events if event["event"] == "software_processed")
                self.assertEqual(processed["target_sample"], 4_000_000)
                self.assertEqual(processed["local_sample"], 4_000_000)

    def test_missing_availability_refuses_old_packet_logs(self):
        config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                              target_ids=frozenset((1,)))
        with self.assertRaisesRegex(ValueError, "missing available_sample"):
            replay_records([packet("ble", available=False)], config, 4_000_000)

    def test_ble_adi_must_match_independently_recovered_slot(self):
        config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                              target_ids=frozenset((1,)))
        wrong = packet("ble")
        wrong["extended"]["adi"]["did"] = 8
        with self.assertRaisesRegex(ValueError, "ADI/slot mismatch"):
            replay_records([wrong], config, 4_000_000)

    def test_progress_continues_after_last_packet_before_capture_end(self):
        config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                              target_ids=frozenset((1,)),
                              external_reference_bound_ms=1, drift_bound_ppm=0)
        events, summary = replay_records([packet("ble")], config, 5_000_000,
                                         progress_step_samples=10_000)
        self.assertEqual(summary["events"].get("cancelled", 0), 0)
        processed = next(event for event in events if event["event"] == "software_processed")
        self.assertEqual(processed["local_sample"], 4_000_000)

    def test_command_line_writes_events_and_explicit_assumption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packets = root / "rx.packets.jsonl"
            packets.write_text(json.dumps(packet("ble")) + "\n")
            (root / "rx.summary.json").write_text(json.dumps({
                "status": "complete", "counts": {"samples_processed": 4_000_000},
                "config": {"sample_rate": 1_000_000}}))
            output = root / "analysis"
            self.assertEqual(main(["--packets", str(packets), "--side", "ble",
                                   "--run-id", "1001", "--target-id", "1",
                                   "--assumed-reference-bound-ms", "1",
                                   "--output-dir", str(output)]), 0)
            summary = json.loads((output / "control.summary.json").read_text())
            self.assertEqual(summary["events"]["software_processed"], 1)
            self.assertIn("not a measured bound", summary["assumption_status"])
            self.assertTrue((output / "control.events.jsonl").is_file())

    def test_command_line_rejects_archive_run_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packets = root / "rx.packets.jsonl"
            packets.write_text(json.dumps(packet("ble")) + "\n")
            (root / "rx.summary.json").write_text(json.dumps({
                "status": "complete", "counts": {"samples_processed": 4_000_000},
                "config": {"sample_rate": 1_000_000}}))
            output = root / "analysis"
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as raised:
                main(["--packets", str(packets), "--side", "ble", "--run-id", "1002",
                      "--target-id", "1", "--output-dir", str(output)])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("packet contents have run IDs [1001]", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_immediate_baseline_uses_availability_and_deduplicates(self):
        for side, target, value in (("ble", 1, 1), ("zigbee", 2, 2)):
            with self.subTest(side=side):
                config = EngineConfig(side=side, run_id=1001, sample_rate=1_000_000,
                                      target_ids=frozenset((target,)))
                first = packet(side)
                second = packet(side)
                second["sample_start"] += 1_000
                second["available_sample"] += 1_000
                events, summary = replay_records([first, second], config, 4_000_000,
                                                 policy="immediate")
                self.assertEqual(summary["events"].get("software_processed"), 1)
                self.assertEqual(summary["events"].get("duplicate"), 1)
                self.assertEqual(summary["engine"]["software_state"], {target: value})
                processed = next(e for e in events if e["event"] == "software_processed")
                self.assertEqual(processed["local_sample"], first["available_sample"])
                self.assertEqual(processed["deadline_status"],
                                 "not_evaluated_no_time_reference")

    def test_immediate_baseline_keeps_target_check(self):
        config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                              target_ids=frozenset((2,)))
        events, summary = replay_records([packet("ble")], config, 4_000_000,
                                         policy="immediate")
        self.assertEqual(summary["events"].get("software_processed", 0), 0)
        self.assertEqual(next(e for e in events if e["event"] == "rejected")["reason"],
                         "wrong_target")

    def test_immediate_command_line_labels_policy_and_rejects_reference_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packets = root / "rx.packets.jsonl"
            packets.write_text(json.dumps(packet("ble")) + "\n")
            (root / "rx.summary.json").write_text(json.dumps({
                "status": "complete", "counts": {"samples_processed": 4_000_000},
                "config": {"sample_rate": 1_000_000}}))
            output = root / "immediate"
            args = ["--packets", str(packets), "--side", "ble", "--run-id", "1001",
                    "--target-id", "1", "--policy", "immediate", "--output-dir", str(output)]
            self.assertEqual(main(args), 0)
            summary = json.loads((output / "control.summary.json").read_text())
            self.assertEqual(summary["schema"], "b2z_immediate_baseline_replay_v1")
            self.assertEqual(summary["events"]["software_processed"], 1)
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit):
                main(args + ["--assumed-reference-bound-ms", "1"])
            self.assertIn("does not use a reference bound", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
