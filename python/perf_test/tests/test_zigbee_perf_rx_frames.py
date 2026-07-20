#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest


MODULE_DIR = Path(__file__).resolve().parents[1]
STD_ZIGBEE_DIR = MODULE_DIR.parent / "ctc_sim" / "std_zigbee"
BLUEBEE_DIR = MODULE_DIR.parent / "ctc_sim" / "bluebee"
sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(STD_ZIGBEE_DIR))
sys.path.insert(0, str(BLUEBEE_DIR))

from bluebee_perf_protocol import SequenceTracker, build_test_payload  # noqa: E402
from generate_bluebee_zigbee_frame_iq_30_72M import (  # noqa: E402
    build_bluebee_chip_map,
)
from zigbee_mod import bits_to_chips, bytes_to_bits, crc16_ccitt  # noqa: E402
import zigbee_perf_rx  # noqa: E402


def build_frame(payload):
    fcs = crc16_ccitt(payload)
    return (
        bytes((0x00, 0x00, 0x00, 0x00, 0xA7, len(payload) + 2))
        + payload
        + bytes((fcs & 0xFF, fcs >> 8))
    )


def bluebee_bits_to_chips(bit_string):
    chip_map = build_bluebee_chip_map("optimized")
    return "".join(
        chip_map[int(bit_string[index : index + 4], 2)]
        for index in range(0, len(bit_string), 4)
    )


class VariableFrameTests(unittest.TestCase):
    def test_vectorized_message_unpack_matches_scalar_lsb_order(self):
        messages = [
            bytes((0x00, 0x01, 0x80, 0xFF)),
            b"",
            bytes((0xA5, 0x5A)),
        ]
        expected = "".join(
            zigbee_perf_rx.unpack_bytes_to_chips(message)
            for message in messages
        )
        self.assertEqual(
            zigbee_perf_rx.unpack_messages_to_chips(messages),
            expected,
        )

    def test_minimum_and_maximum_payload(self):
        for payload_len in (10, 16, 46):
            with self.subTest(payload_len=payload_len):
                payload = build_test_payload(payload_len, 0x1234, 99)
                frame = build_frame(payload)
                chips = "10101" + bits_to_chips(bytes_to_bits(frame)) + "0101"
                decoded, position, _, _ = zigbee_perf_rx.find_frame_window(chips)
                fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(decoded)
                self.assertEqual(position, 5)
                self.assertTrue(fcs_ok)
                self.assertEqual(bytes(decoded_payload), payload)

    def test_bluebee_approximate_chips_with_errors(self):
        payload = build_test_payload(10, 0x1234, 7)
        frame = build_frame(payload)
        emulated = list(bluebee_bits_to_chips(bytes_to_bits(frame)))
        for index in range(10, len(emulated), 97):
            emulated[index] = "0" if emulated[index] == "1" else "1"
        chips = "10101" + "".join(emulated) + "0101"

        decoded, position, _, _ = zigbee_perf_rx.find_frame_window(chips)
        fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(decoded)

        self.assertEqual(position, 5)
        self.assertTrue(fcs_ok)
        self.assertEqual(bytes(decoded_payload), payload)

    def test_phase_decoder_uses_bluebee_map_and_inverted_polarity(self):
        payload = build_test_payload(10, 0x1234, 8)
        frame = build_frame(payload)
        emulated = bluebee_bits_to_chips(bytes_to_bits(frame))
        inverted = zigbee_perf_rx.invert_chips(emulated)
        chips = "10101" + inverted + "0101"

        decoded, position, _, _ = zigbee_perf_rx.find_frame_window(
            chips, "phase"
        )
        fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(decoded)

        self.assertEqual(position, 5)
        self.assertTrue(fcs_ok)
        self.assertEqual(bytes(decoded_payload), payload)

    def test_phase_auto_covers_all_offsets_and_counts_one_burst_once(self):
        payload = build_test_payload(10, 0x1234, 9)
        frame = build_frame(payload)
        emulated = bluebee_bits_to_chips(bytes_to_bits(frame))
        candidates = []

        self.assertEqual(
            list(zigbee_perf_rx.PHASE_ENDPOINTS.values()),
            [
                "tcp://127.0.0.1:55557",
                "tcp://127.0.0.1:55558",
                "tcp://127.0.0.1:55559",
                "tcp://127.0.0.1:55560",
                "tcp://127.0.0.1:55561",
            ],
        )
        for offset in range(5):
            chips = ("10" * offset) + emulated + "0101"
            candidate = zigbee_perf_rx.find_frame_candidate(
                chips, "phase", phase_offset=offset
            )
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["phase_offset"], offset)
            candidates.append(candidate)

        selected = zigbee_perf_rx.choose_phase_candidate(candidates)
        fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
            selected["frame"]
        )
        tracker = SequenceTracker(expected_run_id=0x1234, expected_payload_len=10)
        _, result = tracker.observe(decoded_payload)

        self.assertTrue(fcs_ok)
        self.assertEqual(result, "unique")
        self.assertEqual(tracker.unique, 1)
        self.assertEqual(tracker.duplicate, 0)

    def test_later_retransmission_remains_a_real_duplicate(self):
        payload = build_test_payload(10, 0x1234, 10)
        frame = build_frame(payload)
        chips = bluebee_bits_to_chips(bytes_to_bits(frame))
        tracker = SequenceTracker(expected_run_id=0x1234, expected_payload_len=10)

        for expected_result in ("unique", "duplicate"):
            candidates = [
                zigbee_perf_rx.find_frame_candidate(
                    chips, "phase", phase_offset=offset
                )
                for offset in range(5)
            ]
            selected = zigbee_perf_rx.choose_phase_candidate(candidates)
            fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                selected["frame"]
            )
            _, result = tracker.observe(decoded_payload)
            self.assertTrue(fcs_ok)
            self.assertEqual(result, expected_result)

        self.assertEqual(tracker.unique, 1)
        self.assertEqual(tracker.duplicate, 1)

    def test_phase_auto_prefers_valid_fcs_and_reports_failure(self):
        payload = build_test_payload(10, 0x1234, 11)
        good_frame = build_frame(payload)
        bad_frame = good_frame[:-1] + bytes((good_frame[-1] ^ 0x01,))
        good = zigbee_perf_rx.find_frame_candidate(
            bluebee_bits_to_chips(bytes_to_bits(good_frame)),
            "phase",
            phase_offset=4,
        )
        bad = zigbee_perf_rx.find_frame_candidate(
            bluebee_bits_to_chips(bytes_to_bits(bad_frame)),
            "phase",
            phase_offset=0,
        )

        self.assertFalse(zigbee_perf_rx.validate_frame(bad["frame"])[0])
        selected = zigbee_perf_rx.choose_phase_candidate([bad, good])
        self.assertEqual(selected["phase_offset"], 4)
        self.assertTrue(zigbee_perf_rx.validate_frame(selected["frame"])[0])

    def test_phase_diagnostic_tolerates_one_preamble_symbol_error(self):
        payload = build_test_payload(10, 0x1234, 12)
        frame = build_frame(payload)
        chips = bluebee_bits_to_chips(bytes_to_bits(frame))
        corrupted = zigbee_perf_rx.BLUEBEE_OPTIMIZED_MAP[1] + chips[32:]

        self.assertIsNone(
            zigbee_perf_rx.find_frame_candidate(corrupted, "phase")
        )
        candidate = zigbee_perf_rx.find_frame_candidate(
            corrupted,
            "phase",
            phase_offset=2,
            expected_payload_len=10,
        )
        fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
            candidate["frame"]
        )

        self.assertEqual(candidate["prefix_symbol_errors"], 1)
        self.assertTrue(fcs_ok)
        self.assertEqual(bytes(decoded_payload), payload)

    def test_fast_phase_detector_handles_offsets_and_inversion(self):
        payload = build_test_payload(10, 0x1234, 13)
        frame = build_frame(payload)
        emulated = bluebee_bits_to_chips(bytes_to_bits(frame))

        for offset in range(5):
            with self.subTest(offset=offset):
                prefix = "10" * (offset + 1)
                chips = prefix + emulated + "01" * 20
                if offset & 1:
                    chips = zigbee_perf_rx.invert_chips(chips)
                candidate = zigbee_perf_rx.find_phase_frame_candidate_fast(
                    chips, 10, phase_offset=offset
                )
                fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                    candidate["frame"]
                )
                self.assertTrue(fcs_ok)
                self.assertEqual(bytes(decoded_payload), payload)


if __name__ == "__main__":
    unittest.main()
