"""Wire-format and independent-side matching checks for B2 43 control records."""
import binascii
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze import analyze, control_record, read_board, read_side


BLE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000100010100b80b0000c40900008098")
ZIGBEE = bytes.fromhex(
    "b2430101e9030700000078050000c8002a0000000200010200b80b0000c4090000eae6")


class ControlMatchTests(unittest.TestCase):
    def test_single_task_plan_final_stats_can_supply_dma_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            board_path = Path(temp) / "board.board.log"
            board_path.write_text(
                "CONTROL_PLAN_STATS final=1 state=complete run_id=1703 period_ms=200 "
                "tasks=1 planned_slots=300 reached_slots=300 generated=300 "
                "primary_completed=300 tx_completed=300 deadline_miss=0 dma_timeout=0\n")
            board = read_board(board_path, 1703, 0)
            self.assertEqual((board["scheduled"], board["tx_completed"]), (300, 300))
            self.assertEqual(board["record_type"], "CONTROL_PLAN_STATS")
            self.assertFalse(board["command_id_verified"])
            with self.assertRaisesRegex(ValueError, "single-task plan"):
                board_path.write_text(board_path.read_text().replace("tasks=1", "tasks=2"))
                read_board(board_path, 1703, 0)

    def test_wire_vectors_and_crc_rejection(self):
        ble = control_record(BLE)
        zigbee = control_record(ZIGBEE)
        self.assertEqual((ble["run_id"], ble["slot_index"], ble["ref_tick_ms"],
                          ble["command_id"], ble["target_id"], ble["arg"]),
                         (1001, 7, 1400, 42, 1, 1))
        self.assertEqual((zigbee["target_id"], zigbee["arg"]), (2, 2))
        damaged = bytearray(ZIGBEE)
        damaged[23] ^= 1
        with self.assertRaisesRegex(ValueError, "app_crc16"):
            control_record(bytes(damaged))

    def test_two_independent_records_match_only_for_same_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ble_path = root / "ble.packets.jsonl"
            zigbee_path = root / "zigbee.packets.jsonl"
            ble_data = {"crc_ok": True, "kind": "same_channel_auxiliary_diagnostic",
                        "pdu_length": 224, "packet_no": 1, "sample_start": 100,
                        "extended": {"adi": {"did": 7}, "ad_structures": [
                            {"type": 255, "company_id": 65535,
                             "data_hex": (b"\xff\xff" + BLE + bytes(172)).hex()}]}}
            zigbee_data = {"fcs_ok": True, "packet_no": 1, "sample_start": 200,
                           "payload_hex": ZIGBEE.hex()}
            ble_path.write_text(json.dumps(ble_data) + "\n")
            zigbee_path.write_text(json.dumps(zigbee_data) + "\n" + json.dumps(zigbee_data) + "\n")
            now = datetime.now(timezone.utc)
            summary = {"status": "complete", "start_utc": now.isoformat(),
                       "end_utc": (now + timedelta(seconds=30)).isoformat()}
            for path in (ble_path, zigbee_path):
                path.with_name(path.name.replace(".packets.jsonl", ".summary.json")).write_text(json.dumps(summary))
            board_path = root / "board.board.log"
            board_path.write_text("CONTROL_STATS final=1 state=complete run_id=1001 command_id=42 "
                                  "scheduled=10 generated=10 primary_completed=10 tx_completed=10 "
                                  "deadline_miss=0 dma_timeout=0\n")
            ble = read_side(ble_path, "ble", 1001, 42)
            zigbee = read_side(zigbee_path, "zigbee", 1001, 42)
            board = read_board(board_path, 1001, 42)
            self.assertEqual(zigbee["counts"]["duplicates"], 1)
            unasserted, _ = analyze(ble, zigbee, board, 1001, 42, False)
            self.assertIsNone(unasserted["joint_valid_decode_slots"])
            matched, slots = analyze(ble, zigbee, board, 1001, 42, True)
            self.assertEqual(matched["joint_valid_decode_slots"], 1)
            self.assertEqual(matched["joint_valid_decode_denominator"], 10)
            self.assertTrue(matched["joint_command_recovered"])
            self.assertEqual(slots[7]["shared_fields_match"], 1)
            self.assertEqual(matched["neither_slots"], 9)

            next_slot = bytearray(ZIGBEE)
            next_slot[6:10] = (8).to_bytes(4, "little")
            next_slot[10:14] = (1600).to_bytes(4, "little")
            next_slot[33:35] = binascii.crc_hqx(next_slot[:33], 0xffff).to_bytes(2, "little")
            zigbee_path.write_text(json.dumps({**zigbee_data, "payload_hex": next_slot.hex()}) + "\n")
            zigbee = read_side(zigbee_path, "zigbee", 1001, 42)
            repeated, _ = analyze(ble, zigbee, board, 1001, 42, True)
            self.assertEqual(repeated["joint_valid_decode_slots"], 0)
            self.assertTrue(repeated["joint_command_recovered"])

            different = bytearray(ZIGBEE)
            different[25:29] = (4000).to_bytes(4, "little")
            different[33:35] = binascii.crc_hqx(different[:33], 0xffff).to_bytes(2, "little")
            conflicting_next = bytearray(next_slot)
            conflicting_next[25:29] = (4000).to_bytes(4, "little")
            conflicting_next[33:35] = binascii.crc_hqx(conflicting_next[:33], 0xffff).to_bytes(2, "little")
            zigbee_path.write_text(json.dumps(zigbee_data) + "\n" +
                                   json.dumps({**zigbee_data, "payload_hex": conflicting_next.hex()}) + "\n")
            zigbee = read_side(zigbee_path, "zigbee", 1001, 42)
            with self.assertRaisesRegex(ValueError, "conflicting task fields"):
                analyze(ble, zigbee, board, 1001, 42, True)

            zigbee_path.write_text(json.dumps({**zigbee_data, "payload_hex": different.hex()}) + "\n")
            zigbee = read_side(zigbee_path, "zigbee", 1001, 42)
            mismatched, _ = analyze(ble, zigbee, board, 1001, 42, True)
            self.assertEqual(mismatched["shared_field_mismatches"], 1)
            self.assertEqual(mismatched["joint_valid_decode_slots"], 0)
            self.assertFalse(mismatched["joint_command_recovered"])


if __name__ == "__main__":
    unittest.main()
