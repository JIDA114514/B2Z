#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest
from unittest import mock


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
    def test_receiver_defaults_use_repeated_best_gain_and_soft_retry(self):
        with mock.patch.object(
            sys,
            "argv",
            ["zigbee_perf_rx.py", "--payload-len", "10"],
        ):
            args = zigbee_perf_rx.parse_args()

        self.assertEqual(args.rf_gain, 0.0)
        self.assertEqual(args.if_gain, 32.0)
        self.assertEqual(args.bb_gain, 40.0)
        self.assertEqual(args.cfo_correction_hz, 0.0)
        self.assertTrue(args.standard_soft_retry)
        self.assertFalse(args.standard_soft_acquire)
        self.assertEqual(args.soft_zmq, zigbee_perf_rx.STANDARD_SOFT_ENDPOINT)

    def test_soft_acquire_is_explicit_and_requires_soft_retry(self):
        with mock.patch.object(
            sys,
            "argv",
            [
                "zigbee_perf_rx.py",
                "--payload-len",
                "10",
                "--standard-soft-acquire",
            ],
        ):
            enabled = zigbee_perf_rx.parse_args()
        self.assertTrue(enabled.standard_soft_retry)
        self.assertTrue(enabled.standard_soft_acquire)

        with mock.patch.object(
            sys,
            "argv",
            [
                "zigbee_perf_rx.py",
                "--payload-len",
                "10",
                "--standard-soft-acquire",
                "--no-standard-soft-retry",
            ],
        ):
            hard_only = zigbee_perf_rx.parse_args()
        self.assertFalse(hard_only.standard_soft_retry)
        self.assertFalse(hard_only.standard_soft_acquire)
        self.assertIsNone(hard_only.soft_zmq)

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

    def test_standard_full_rate_deinterleave_preserves_phase_across_batches(self):
        raw = zigbee_perf_rx.np.asarray(
            [(index * 7 + 3) & 1 for index in range(173)],
            dtype=zigbee_perf_rx.np.uint8,
        )
        outputs = {offset: "" for offset in range(5)}
        stream_phase = 0
        boundaries = (0, 13, 71, 80, 129, len(raw))

        for start, end in zip(boundaries, boundaries[1:]):
            streams, stream_phase = (
                zigbee_perf_rx.deinterleave_standard_phase_values(
                    raw[start:end],
                    stream_phase,
                )
            )
            for offset, chips in streams.items():
                outputs[offset] += chips

        for offset in range(5):
            expected = "".join(str(int(bit)) for bit in raw[offset::5])
            self.assertEqual(outputs[offset], expected)
        self.assertEqual(stream_phase, len(raw) % 5)

    def test_standard_soft_deinterleave_preserves_signed_values(self):
        raw = zigbee_perf_rx.np.asarray(
            [((index * 19) % 251) - 125 for index in range(173)],
            dtype=zigbee_perf_rx.np.int8,
        )
        outputs = {offset: bytearray() for offset in range(5)}
        stream_phase = 0
        boundaries = (0, 13, 71, 80, 129, len(raw))

        for start, end in zip(boundaries, boundaries[1:]):
            streams, stream_phase = (
                zigbee_perf_rx.deinterleave_standard_soft_values(
                    raw[start:end],
                    stream_phase,
                )
            )
            for offset, values in streams.items():
                outputs[offset].extend(values)

        for offset in range(5):
            actual = zigbee_perf_rx.np.frombuffer(
                outputs[offset],
                dtype=zigbee_perf_rx.np.int8,
            )
            zigbee_perf_rx.np.testing.assert_array_equal(
                actual,
                raw[offset::5],
            )
        self.assertEqual(stream_phase, len(raw) % 5)

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

    def test_fast_standard_detector_handles_all_chip_alignments(self):
        for payload_len in (10, 46):
            payload = build_test_payload(payload_len, 0x1234, payload_len)
            frame_chips = bits_to_chips(bytes_to_bits(build_frame(payload)))
            for alignment in range(32):
                with self.subTest(
                    payload_len=payload_len,
                    alignment=alignment,
                ):
                    chips = ("10" * 16)[:alignment] + frame_chips + "0101"
                    candidate = (
                        zigbee_perf_rx.find_standard_frame_candidate_fast(
                            chips,
                            payload_len,
                        )
                    )
                    self.assertIsNotNone(candidate)
                    self.assertEqual(candidate["chip_pos"], alignment)
                    fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                        candidate["frame"]
                    )
                    self.assertTrue(fcs_ok)
                    self.assertEqual(bytes(decoded_payload), payload)

    def test_bluebee_projection_decodes_with_standard_chip_map(self):
        for payload_len in (10, 46):
            with self.subTest(payload_len=payload_len):
                payload = build_test_payload(payload_len, 0x1234, 104)
                projected = bluebee_bits_to_chips(
                    bytes_to_bits(build_frame(payload))
                )
                candidate = (
                    zigbee_perf_rx.find_standard_frame_candidate_fast(
                        projected,
                        payload_len,
                        sample_offset=2,
                    )
                )
                self.assertIsNotNone(candidate)
                fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                    candidate["frame"]
                )
                self.assertTrue(fcs_ok)
                self.assertEqual(bytes(decoded_payload), payload)
                self.assertEqual(candidate["phase_offset"], 2)
                self.assertGreater(candidate["frame_distance"], 0)

    def test_standard_auto_counts_cross_offset_burst_once_and_retransmit(self):
        payload = build_test_payload(10, 0x1234, 105)
        projected = bluebee_bits_to_chips(
            bytes_to_bits(build_frame(payload))
        )
        tracker = SequenceTracker(
            expected_run_id=0x1234,
            expected_payload_len=10,
        )

        for expected_result in ("unique", "duplicate"):
            candidates = [
                zigbee_perf_rx.find_standard_frame_candidate_fast(
                    projected,
                    10,
                    sample_offset=offset,
                )
                for offset in range(5)
            ]
            selected = zigbee_perf_rx.choose_standard_candidate(candidates)
            fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                selected["frame"]
            )
            _, result = tracker.observe(decoded_payload)
            self.assertTrue(fcs_ok)
            self.assertEqual(result, expected_result)

        self.assertEqual(tracker.unique, 1)
        self.assertEqual(tracker.duplicate, 1)

    def test_standard_auto_prefers_valid_fcs_and_handles_inversion(self):
        payload = build_test_payload(10, 0x1234, 106)
        good_frame = build_frame(payload)
        bad_frame = good_frame[:-1] + bytes((good_frame[-1] ^ 0x01,))
        good_inverted = zigbee_perf_rx.invert_chips(
            bluebee_bits_to_chips(bytes_to_bits(good_frame))
        )
        good = zigbee_perf_rx.find_standard_frame_candidate_fast(
            good_inverted,
            10,
            ambiguities=("inverted",),
            sample_offset=4,
        )
        bad = zigbee_perf_rx.find_standard_frame_candidate_fast(
            bluebee_bits_to_chips(bytes_to_bits(bad_frame)),
            10,
            sample_offset=0,
        )

        self.assertFalse(zigbee_perf_rx.validate_frame(bad["frame"])[0])
        selected = zigbee_perf_rx.choose_standard_candidate([bad, good])
        self.assertEqual(selected["phase_offset"], 4)
        self.assertEqual(selected["standard_ambiguity"], "inverted")
        self.assertTrue(zigbee_perf_rx.validate_frame(selected["frame"])[0])

    def test_fast_standard_detector_reports_fcs_failure(self):
        payload = build_test_payload(10, 0x1234, 100)
        frame = build_frame(payload)
        bad_frame = frame[:-1] + bytes((frame[-1] ^ 0x01,))
        candidate = zigbee_perf_rx.find_standard_frame_candidate_fast(
            bits_to_chips(bytes_to_bits(bad_frame)),
            10,
        )

        self.assertIsNotNone(candidate)
        self.assertFalse(zigbee_perf_rx.validate_frame(candidate["frame"])[0])

    def test_fast_standard_detector_resolves_costas_iq_ambiguities(self):
        payload = build_test_payload(10, 0x1234, 103)
        frame_chips = bits_to_chips(bytes_to_bits(build_frame(payload)))

        for ambiguity in zigbee_perf_rx.STANDARD_AMBIGUITIES:
            with self.subTest(ambiguity=ambiguity):
                received = zigbee_perf_rx.transform_standard_chips(
                    frame_chips,
                    ambiguity,
                )
                candidate = (
                    zigbee_perf_rx.find_standard_frame_candidate_fast(
                        received,
                        10,
                        ambiguities=zigbee_perf_rx.STANDARD_AMBIGUITIES,
                    )
                )
                self.assertIsNotNone(candidate)
                fcs_ok, decoded_payload = zigbee_perf_rx.validate_frame(
                    candidate["frame"]
                )
                self.assertTrue(fcs_ok)
                self.assertEqual(bytes(decoded_payload), payload)
                self.assertIn(
                    candidate["standard_ambiguity"],
                    zigbee_perf_rx.STANDARD_AMBIGUITIES,
                )

    def test_fast_standard_detector_keeps_frame_order(self):
        first_payload = build_test_payload(10, 0x1234, 101)
        first_frame = build_frame(first_payload)
        bad_first_frame = first_frame[:-1] + bytes((first_frame[-1] ^ 0x01,))
        second_payload = build_test_payload(10, 0x1234, 102)
        gap = "10" * 20
        chips = (
            bits_to_chips(bytes_to_bits(bad_first_frame))
            + gap
            + bits_to_chips(bytes_to_bits(build_frame(second_payload)))
        )

        candidate = zigbee_perf_rx.find_standard_frame_candidate_fast(
            chips,
            10,
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["chip_pos"], 0)
        self.assertFalse(zigbee_perf_rx.validate_frame(candidate["frame"])[0])

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

    def test_standard_ranked_offsets_decode_runner_up_after_fcs_failure(self):
        payload = build_test_payload(10, 0x1234, 14)
        good_frame = build_frame(payload)
        bad_frame = good_frame[:-1] + bytes((good_frame[-1] ^ 0x01,))
        bad_chips = bits_to_chips(bytes_to_bits(bad_frame))
        good_chips = list(bits_to_chips(bytes_to_bits(good_frame)))
        good_chips[0] = "0" if good_chips[0] == "1" else "1"

        scores = [
            zigbee_perf_rx.score_standard_offset(
                bad_chips,
                10,
                sample_offset=0,
            ),
            zigbee_perf_rx.score_standard_offset(
                "".join(good_chips),
                10,
                sample_offset=1,
            ),
            None,
            None,
            None,
        ]
        selected, decoded, ranked, attempted = (
            zigbee_perf_rx.decode_ranked_standard_offsets(scores, 10)
        )

        self.assertEqual(ranked[0]["sample_offset"], 0)
        self.assertEqual(ranked[1]["sample_offset"], 1)
        self.assertEqual(len(decoded), 2)
        self.assertEqual(attempted, 2)
        self.assertFalse(
            zigbee_perf_rx.validate_frame(decoded[0]["frame"])[0]
        )
        self.assertEqual(selected["phase_offset"], 1)
        self.assertTrue(zigbee_perf_rx.validate_frame(selected["frame"])[0])

    def test_standard_ranked_offsets_stop_after_best_fcs_success(self):
        payload = build_test_payload(46, 0x1234, 15)
        chips = bits_to_chips(bytes_to_bits(build_frame(payload)))
        scores = [
            zigbee_perf_rx.score_standard_offset(
                chips, 46, sample_offset=offset
            )
            for offset in range(5)
        ]
        selected, decoded, ranked, attempted = (
            zigbee_perf_rx.decode_ranked_standard_offsets(scores, 46)
        )
        self.assertEqual(len(ranked), 5)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(attempted, 1)
        self.assertTrue(zigbee_perf_rx.validate_frame(selected["frame"])[0])

    def test_standard_adaptive_recovers_valid_third_rank(self):
        payload = build_test_payload(10, 0x1234, 16)
        good_frame = build_frame(payload)
        bad_frame = good_frame[:-1] + bytes((good_frame[-1] ^ 0x01,))
        best_bad = bits_to_chips(bytes_to_bits(bad_frame))
        second_bad = list(best_bad)
        second_bad[0] = "0" if second_bad[0] == "1" else "1"
        third_good = list(bits_to_chips(bytes_to_bits(good_frame)))
        third_good[0] = "0" if third_good[0] == "1" else "1"
        third_good[1] = "0" if third_good[1] == "1" else "1"
        scores = [
            zigbee_perf_rx.score_standard_offset(
                best_bad, 10, sample_offset=0
            ),
            zigbee_perf_rx.score_standard_offset(
                "".join(second_bad), 10, sample_offset=1
            ),
            zigbee_perf_rx.score_standard_offset(
                "".join(third_good), 10, sample_offset=2
            ),
        ]

        selected, decoded, ranked, attempted = (
            zigbee_perf_rx.decode_ranked_standard_offsets(scores, 10)
        )

        self.assertEqual([score["sample_offset"] for score in ranked], [0, 1, 2])
        self.assertEqual(attempted, 3)
        self.assertEqual(len(decoded), 3)
        self.assertEqual(selected["offset_rank"], 3)
        self.assertTrue(zigbee_perf_rx.validate_frame(selected["frame"])[0])

        limited, _, _, limited_attempted = (
            zigbee_perf_rx.decode_ranked_standard_offsets(
                scores,
                10,
                max_offsets=2,
            )
        )
        self.assertEqual(limited_attempted, 2)
        self.assertFalse(zigbee_perf_rx.validate_frame(limited["frame"])[0])

    def test_soft_retry_recovers_hard_crc_failure_without_new_acquisition(self):
        payload = build_test_payload(10, 0x1234, 17)
        frame = build_frame(payload)
        true_chips = bits_to_chips(bytes_to_bits(frame))
        hard_chips = list(true_chips)
        soft_values = zigbee_perf_rx.np.asarray(
            [80 if chip == "1" else -80 for chip in true_chips],
            dtype=zigbee_perf_rx.np.int8,
        )

        # Make one payload symbol's hard signs favor its nearest competing
        # CHIP_MAP entry.  Give those wrong signs very low confidence so the
        # soft correlation still selects the transmitted symbol.
        symbol_index = 14
        start = symbol_index * 32
        true_symbol = true_chips[start : start + 32]
        alternatives = [
            (
                sum(a != b for a, b in zip(true_symbol, reference)),
                index,
                reference,
            )
            for index, reference in enumerate(zigbee_perf_rx.CHIP_MAP)
            if reference != true_symbol
        ]
        distance, _, alternate = min(alternatives)
        differing = [
            index
            for index, (actual, other) in enumerate(
                zip(true_symbol, alternate)
            )
            if actual != other
        ]
        for chip_index in differing[: distance // 2 + 1]:
            absolute = start + chip_index
            hard_chips[absolute] = alternate[chip_index]
            soft_values[absolute] = (
                1 if alternate[chip_index] == "1" else -1
            )

        candidate = zigbee_perf_rx.find_standard_frame_candidate_fast(
            "".join(hard_chips),
            10,
            sample_offset=2,
        )
        self.assertIsNotNone(candidate)
        self.assertFalse(zigbee_perf_rx.validate_frame(candidate["frame"])[0])

        noise = zigbee_perf_rx.np.asarray(
            [23 if index & 1 else -23 for index in range(137)],
            dtype=zigbee_perf_rx.np.int8,
        )
        soft_buffers = {
            offset: bytearray() for offset in range(5)
        }
        soft_buffers[4].extend(noise.tobytes())
        soft_buffers[4].extend(soft_values.tobytes())
        recovered, attempts, aligned, phase_delta = (
            zigbee_perf_rx.retry_standard_candidates_with_soft(
                [candidate],
                soft_buffers,
                10,
            )
        )

        self.assertEqual(attempts, 1)
        self.assertEqual(aligned, 1)
        self.assertEqual(phase_delta, 2)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["decode_method"], "soft_retry")
        self.assertEqual(recovered["soft_phase_offset"], 4)
        self.assertTrue(zigbee_perf_rx.validate_frame(recovered["frame"])[0])
        self.assertEqual(bytes(recovered["frame"]), frame)

        bad_soft_buffers = {
            offset: bytearray() for offset in range(5)
        }
        bad_soft_values = zigbee_perf_rx.np.asarray(
            [80 if chip == "1" else -80 for chip in hard_chips],
            dtype=zigbee_perf_rx.np.int8,
        )
        bad_soft_buffers[4].extend(bad_soft_values.tobytes())
        failed, _, failed_aligned, unchanged_phase_delta = (
            zigbee_perf_rx.retry_standard_candidates_with_soft(
                [candidate],
                bad_soft_buffers,
                10,
                preferred_phase_delta=4,
            )
        )
        self.assertGreaterEqual(failed_aligned, 1)
        self.assertIsNone(failed)
        self.assertEqual(unchanged_phase_delta, 4)

    def test_scheduled_soft_acquisition_recovers_relaxed_preamble(self):
        run_id = 0x1234
        sequence = 18
        payload = build_test_payload(10, run_id, sequence)
        frame = build_frame(payload)
        true_chips = bits_to_chips(bytes_to_bits(frame))
        hard_chips = list(true_chips)
        soft_values = zigbee_perf_rx.np.asarray(
            [80 if chip == "1" else -80 for chip in true_chips],
            dtype=zigbee_perf_rx.np.int8,
        )

        # Push the hard preamble beyond both the normal distance-80 and relaxed
        # distance-96 gates.  Known Run-ID/Sequence payload segments must now
        # acquire the frame without weakening final validation.
        reference = zigbee_perf_rx.CHIP_MAP[0]
        for symbol_index in range(zigbee_perf_rx.PREAMBLE_SYMBOLS):
            start = symbol_index * 32
            for chip_index in range(13):
                absolute = start + chip_index
                hard_chips[absolute] = (
                    "0" if reference[chip_index] == "1" else "1"
                )
                soft_values[absolute] = (
                    1 if hard_chips[absolute] == "1" else -1
                )

        hard_stream = "".join(hard_chips)
        score = zigbee_perf_rx.score_standard_offset(
            hard_stream,
            10,
            sample_offset=1,
        )
        self.assertEqual(int(score["prefix_distances"][0]), 104)
        self.assertEqual(score["positions"], [])

        soft_buffers = {
            offset: bytearray() for offset in range(5)
        }
        soft_buffers[3].extend(soft_values.tobytes())
        recovered, attempts, aligned, phase_delta, diagnostics = (
            zigbee_perf_rx.acquire_scheduled_standard_frame_with_soft(
                [score],
                soft_buffers,
                10,
                run_id,
                sequence,
            )
        )

        self.assertGreaterEqual(attempts, 1)
        self.assertGreaterEqual(aligned, 1)
        self.assertEqual(phase_delta, 2)
        self.assertGreater(
            diagnostics["attempts_by_source"]["known_payload"],
            0,
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["decode_method"], "soft_acquire")
        self.assertEqual(recovered["soft_acquire_source"], "known_payload")
        self.assertEqual(bytes(recovered["frame"]), frame)

        (
            wrong_recovered,
            _,
            wrong_aligned,
            unchanged_phase_delta,
            _,
        ) = zigbee_perf_rx.acquire_scheduled_standard_frame_with_soft(
            [score],
            soft_buffers,
            10,
            run_id,
            sequence + 1,
            preferred_phase_delta=4,
        )
        self.assertGreaterEqual(wrong_aligned, 1)
        self.assertIsNone(wrong_recovered)
        self.assertEqual(unchanged_phase_delta, 4)

    def test_planned_soft_acquisition_is_limited_to_missing_due_slot(self):
        common = dict(
            anchor_epochs=[1.0],
            interval_s=0.5,
            expected_packets=4,
            attempt_counts={},
            last_attempt_times={},
        )
        self.assertEqual(
            zigbee_perf_rx.planned_soft_acquire_slot(
                1.506,
                received_sequences=set(),
                **common,
            ),
            1,
        )
        self.assertIsNone(
            zigbee_perf_rx.planned_soft_acquire_slot(
                1.506,
                received_sequences={1},
                **common,
            )
        )
        self.assertIsNone(
            zigbee_perf_rx.planned_soft_acquire_slot(
                1.550,
                received_sequences=set(),
                **common,
            )
        )


if __name__ == "__main__":
    unittest.main()
