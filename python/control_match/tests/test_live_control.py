"""Both receiver adapters produce auditable single-side task events."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_engine import EngineConfig
from live_control import ControlSession


BLE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000100010100b80b0000c40900008098")
ZIGBEE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000200010200b80b0000c4090000eae6")


def packet(side):
    if side == "ble":
        return {"packet_no": 1, "crc_ok": True,
                "kind": "same_channel_auxiliary_diagnostic", "pdu_length": 224,
                "sample_start": 2_400_000, "available_sample": 2_401_000,
                "extended": {"adi": {"did": 7}, "ad_structures": [
                    {"type": 255, "company_id": 65535,
                     "data_hex": (b"\xff\xff" + BLE + bytes(172)).hex()}]}}
    return {"packet_no": 1, "fcs_ok": True, "payload_hex": ZIGBEE.hex(),
            "sample_start": 2_400_472, "available_sample": 2_401_000}


class LiveControlTests(unittest.TestCase):
    def test_each_side_writes_one_task_and_event_log(self):
        for side, target in (("ble", 1), ("zigbee", 2)):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as temp:
                config = EngineConfig(side=side, run_id=1001, sample_rate=1_000_000,
                                      target_ids=frozenset((target,)),
                                      external_reference_bound_ms=1, drift_bound_ppm=0)
                session = ControlSession(Path(temp) / "rx", config, offline=False)
                session.observe_packet(packet(side))
                session.advance(4_005_000)
                result = session.finish("complete")
                self.assertEqual(result["event_counts"]["accepted"], 1)
                self.assertEqual(result["event_counts"]["software_processed"], 1)
                self.assertEqual(result["tasks"][0]["status"], "software_processed")
                self.assertEqual(result["tasks"][0]["processed_sample"], 4_005_000)
                with session.paths["control_tasks"].open(newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(rows[0]["unique_slots"], "1")
                with session.paths["control_events"].open() as handle:
                    events = [json.loads(line) for line in handle]
                self.assertTrue(all("host_monotonic_ns" in event for event in events))
                self.assertTrue(session.paths["control_report"].is_file())

    def test_no_reference_bound_denies_action_and_foreign_run_is_not_task(self):
        with tempfile.TemporaryDirectory() as temp:
            config = EngineConfig(side="ble", run_id=1002, sample_rate=1_000_000,
                                  target_ids=frozenset((1,)))
            session = ControlSession(Path(temp) / "rx", config, offline=True)
            session.observe_packet(packet("ble"))
            session.advance(4_000_000)
            result = session.finish("complete")
            self.assertEqual(result["event_counts"]["foreign_run"], 1)
            self.assertEqual(result["tasks"], [])
            self.assertEqual(result["event_counts"].get("software_processed", 0), 0)

    def test_matching_run_without_bound_rejects_timed_processing(self):
        with tempfile.TemporaryDirectory() as temp:
            config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                                  target_ids=frozenset((1,)))
            session = ControlSession(Path(temp) / "rx", config, offline=True)
            session.observe_packet(packet("ble"))
            session.advance(4_000_000)
            result = session.finish("complete")
            self.assertEqual(result["event_counts"]["decoded"], 1)
            self.assertEqual(result["event_counts"]["rejected"], 1)
            self.assertEqual(result["reasons"]["time_quality_insufficient"], 1)
            self.assertEqual(result["event_counts"].get("software_processed", 0), 0)

    def test_adi_mismatch_is_reported_without_task(self):
        with tempfile.TemporaryDirectory() as temp:
            config = EngineConfig(side="ble", run_id=1001, sample_rate=1_000_000,
                                  target_ids=frozenset((1,)))
            session = ControlSession(Path(temp) / "rx", config, offline=True)
            wrong = packet("ble")
            wrong["extended"]["adi"]["did"] = 8
            session.observe_packet(wrong)
            result = session.finish("complete")
            self.assertEqual(result["event_counts"]["wire_rejected"], 1)
            self.assertEqual(result["tasks"], [])


if __name__ == "__main__":
    unittest.main()
