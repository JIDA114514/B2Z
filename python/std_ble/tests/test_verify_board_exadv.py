"""Integration checks for the board v1 BLE flow verifier and long exadv PDU."""
import ctypes
import json
import numpy as np
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from python.exadv_rx.protocol import crc24, whiten
from python.perf_test.tests.test_b2z_control_generator import (
    ControlGeneratorTests, Packet, read_bytes,
)
from python.std_ble.ble_exadv_hackrf_sniffer import BleStreamParser
from python.std_ble.verify_board_exadv import main, validate_primary, validate_secondary


class BoardBleFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ControlGeneratorTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        ControlGeneratorTests.tearDownClass()

    def board_pdus(self, slot):
        packet = Packet(1904, slot, slot * 500, 500, 43, 5000, 4500,
                        1, 1, 1, 2, 1, 1)
        library = ControlGeneratorTests.lib
        self.assertEqual(library.ble_exadv_secondary_gen_build_control_mode(
            ctypes.byref(packet), 1), 0)
        meta = library.ble_exadv_secondary_gen_get_last_meta().contents
        return (read_bytes(meta.primary_pdu, meta.primary_pdu_len),
                read_bytes(meta.pdu, meta.pdu_len))

    def test_std_ble_stream_parser_accepts_long_board_secondary(self):
        primary, secondary = self.board_pdus(0)
        args = SimpleNamespace(run_id=1904, command_id=43, expected_attempts=2,
                               period_ms=500, primary_channel=39, secondary_channel=3,
                               aux_offset_us=300000, expected_adva="C1:A2:A3:A4:A5:A6")
        for channel, pdu, validator in ((39, primary, validate_primary),
                                        (3, secondary, validate_secondary)):
            parser = BleStreamParser(channel)
            on_air = bytes.fromhex("aad6be898e") + whiten(pdu + crc24(pdu), channel)
            parser.insert_data(on_air[:8])
            self.assertEqual(parser.poll(), [])
            parser.insert_data(on_air[8:])
            decoded = parser.poll()
            self.assertEqual(len(decoded), 1)
            self.assertEqual(parser.crc_errors, 0)
            self.assertEqual(validator(decoded[0], args)["did"], 0)
        self.assertEqual(len(secondary), 226)

    def test_stream_parser_recovers_crc_valid_frame_with_preamble_errors_and_bit_shift(self):
        _, secondary = self.board_pdus(0)
        on_air = bytearray(bytes.fromhex("aad6be898e") + whiten(secondary + crc24(secondary), 3))
        on_air[0] ^= 0x09  # Two damaged preamble bits; access address and PDU remain intact.
        bits = np.unpackbits(np.frombuffer(on_air, dtype=np.uint8), bitorder="little")
        shifted = np.packbits(np.concatenate((np.array([1, 0, 1], dtype=np.uint8), bits)),
                              bitorder="little").tobytes()
        parser = BleStreamParser(3)
        for start in range(0, len(shifted), 19):
            parser.insert_data(shifted[start:start + 19])
            packets = parser.poll()
            if packets:
                self.assertEqual(len(packets), 1)
                self.assertTrue(packets[0]["crc_ok"])
                self.assertEqual(packets[0]["preamble_errors"], 2)
                self.assertEqual(packets[0]["bit_alignment"], 3)
                self.assertEqual(packets[0]["length"], 224)
                break
        else:
            self.fail("shifted secondary was not recovered")

    def test_same_run_files_correlate_identity_without_claiming_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "20261110_run1904" / "captures" / "ble"
            paths = [root / side / "rx.packets.jsonl" for side in ("primary", "secondary")]
            rows = [[], []]
            for slot in range(2):
                for index, (channel, pdu) in enumerate(zip((39, 3), self.board_pdus(slot))):
                    rows[index].append({"channel": channel, "pdu_hex": pdu.hex(),
                                        "crc_hex": crc24(pdu).hex(), "crc_ok": True,
                                        "sample_time_s": 1 + slot * .5 + index * .3})
            for path, records in zip(paths, rows):
                path.parent.mkdir(parents=True)
                path.write_text("".join(json.dumps(record) + "\n" for record in records))
                path.with_name("rx.summary.json").write_text(json.dumps({
                    "status": "complete", "start_utc": "2026-11-10T00:00:00+00:00",
                    "end_utc": "2026-11-10T00:00:10+00:00"}))
            output = Path(temporary) / "result"
            self.assertEqual(main(["--run-id", "1904", "--command-id", "43",
                                   "--expected-attempts", "2", "--primary-packets", str(paths[0]),
                                   "--secondary-packets", str(paths[1]),
                                   "--output-dir", str(output)]), 0)
            result = json.loads((output / "flow.summary.json").read_text())
            self.assertEqual(result["paired_dids"], [0, 1])
            self.assertFalse(result["follow_observed"])
            self.assertFalse(result["aux_air_timing_verified"])
            self.assertFalse(result["full_standard_exadv_verified"])

    def test_corrupt_packet_is_reported_without_aborting_file_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "20261110_run1904" / "captures" / "ble"
            paths = [root / side / "rx.packets.jsonl" for side in ("primary", "secondary")]
            primary, secondary = self.board_pdus(0)
            for path, channel, pdu in zip(paths, (39, 3), (primary, secondary)):
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"channel": channel, "pdu_hex": pdu.hex(),
                                            "crc_hex": crc24(pdu).hex(), "crc_ok": True}) + "\n")
                path.with_name("rx.summary.json").write_text(json.dumps({
                    "status": "complete", "start_utc": "2026-11-10T00:00:00+00:00",
                    "end_utc": "2026-11-10T00:00:10+00:00"}))
            paths[1].write_text(paths[1].read_text().replace('"crc_ok": true', '"crc_ok": false'))
            output = Path(temporary) / "result"
            self.assertEqual(main(["--run-id", "1904", "--expected-attempts", "1",
                                   "--primary-packets", str(paths[0]),
                                   "--secondary-packets", str(paths[1]),
                                   "--output-dir", str(output)]), 2)
            result = json.loads((output / "flow.summary.json").read_text())
            self.assertEqual(result["counts"]["secondary_invalid"], 1)
            self.assertEqual(result["assessment"], "incomplete_same_run_content_observation")


if __name__ == "__main__":
    unittest.main()
