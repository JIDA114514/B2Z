"""Deterministic on-air LE 1M tests, including FIR/chunk boundaries and long PDUs."""
import importlib.util
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from decoder import ChannelDecoder, IQDCBlocker, SYNC_BYTES
from protocol import DiagnosticEventMatcher, EventMatcher, crc24, parse_extended, parse_pdu, whiten
from receive import Capture, main, parse_args


def pdu(payload_length=238, did=17):
    header = bytes([9, 0x09]) + bytes.fromhex("a6a5a4a3a2c1") + (did | (3 << 12)).to_bytes(2, "little")
    data_length = payload_length - len(header)
    data = bytes([data_length - 1, 0xFF]) + bytes((i * 37) & 255 for i in range(data_length - 2))
    return bytes([0x47, payload_length]) + header + data


def waveform(packet, channel=39, fs=8000000, cfo=0, noise=.015, invert=False,
             frequency_offset=0, corrupt=False, ppm=0, seed=123):
    encoded = bytearray(whiten(packet + crc24(packet), channel))
    if corrupt:
        encoded[-1] ^= 4
    raw = SYNC_BYTES + encoded
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little")
    sps = fs // 1000000
    nrz = np.repeat(bits.astype(float) * 2 - 1, sps)
    t = np.arange(-2 * sps, 2 * sps) / sps
    alpha = np.sqrt(np.log(2) / 2) / .5
    taps = np.exp(-(np.pi * t / alpha) ** 2)
    taps /= taps.sum()
    freq = np.convolve(nrz, taps, mode="same") * 250000
    iq = np.exp(1j * np.cumsum(freq * 2 * np.pi / fs))
    if ppm:
        positions = np.arange(0, len(iq) - 1, 1 / (1 + ppm * 1e-6))
        iq = np.interp(positions, np.arange(len(iq)), iq)
    if invert:
        iq = iq.conj()
    iq *= np.exp(2j * np.pi * (cfo + frequency_offset) * np.arange(len(iq)) / fs)
    rng = np.random.default_rng(seed)
    # Noise-only intervals exercise false sync rejection and arbitrary symbol phase.
    iq = np.concatenate((np.zeros(973), iq, np.zeros(4003)))
    iq += noise * (rng.normal(size=len(iq)) + 1j * rng.normal(size=len(iq)))
    return iq.astype(np.complex64)


def decode_chunks(iq, channel=39, center=2480000000, chunk=997, fs=8000000):
    decoder = ChannelDecoder(fs, center, channel)
    packets = []
    for start in range(0, len(iq), chunk):
        packets.extend(decoder.feed(iq[start:start + chunk]))
    packets.extend(decoder.feed([], final=True))
    return decoder, packets


class ProtocolTests(unittest.TestCase):
    def test_against_existing_encoder(self):
        path = ROOT.parent / "std_ble" / "bsp_algorithm.py"
        spec = importlib.util.spec_from_file_location("reference_ble", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        algorithm = module.bsp_algorithm
        for length in (2, 65, 240, 257):
            data = bytes((i * 29) & 255 for i in range(length))
            self.assertEqual(crc24(data), bytes(algorithm.bt_crc(list(data), len(data))))
            for channel in (0, 3, 11, 36, 37, 38, 39):
                self.assertEqual(whiten(data, channel), bytes(algorithm.bt_dewhitening(list(data), channel)))
                self.assertEqual(whiten(whiten(data, channel), channel), data)

    def test_extended_fields_and_truncation(self):
        # Extended header has ADI and AuxPtr, 30us quantized offset 600us.
        aux = (3 | (20 << 8)).to_bytes(3, "little")
        parsed = parse_extended(bytes([6, 0x18, 0x11, 0x30]) + aux)
        self.assertEqual(parsed["aux_ptr"]["offset_us"], 600)
        self.assertEqual(parsed["adi"], {"sid": 3, "did": 17})
        for bad in (b"", bytes([63]), bytes([1, 1]), bytes([1, 128])):
            with self.assertRaises(ValueError):
                parse_extended(bad)

    def test_full_eight_bit_length(self):
        for length in (64, 238, 255):
            parsed = parse_pdu(pdu(length), 3)
            self.assertEqual(parsed["pdu_length"], length)
            self.assertEqual(len(bytes.fromhex(parsed["extended"]["adv_data_hex"])), length - 10)

    def test_sample_timeline_matching(self):
        matcher = EventMatcher()
        primary = {"packet_no": 1, "kind": "primary", "channel": 39, "sample_time_s": .01,
                   "extended": {"adi": {"sid": 3, "did": 17}, "aux_ptr":
                                {"channel": 3, "phy": 0, "offset_us": 600, "offset_unit_us": 30}}}
        secondary = parse_pdu(pdu(), 3)
        secondary.update(packet_no=2, sample_time_s=.01061)
        self.assertEqual(matcher.feed(primary), [])
        self.assertEqual(len(matcher.feed(secondary)), 1)
        self.assertEqual(matcher.feed(secondary), [])

    def test_outside_band_and_bad_args(self):
        with self.assertRaises(ValueError):
            ChannelDecoder(8000000, 2480000000, 3)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--channels", "39,3"])

    def test_same_channel_diagnostic_is_separate_from_strict_pairs(self):
        primary = {"packet_no": 1, "kind": "primary", "channel": 39, "pdu_length": 7,
                   "sample_time_s": .01, "extended": {"adi": {"sid": 3, "did": 17},
                   "aux_ptr": {"channel": 3, "phy": 1, "offset_us": 30000, "offset_unit_us": 30}}}
        secondary = parse_pdu(pdu(), 39)
        secondary.update(packet_no=2, sample_time_s=.040808)
        strict = EventMatcher()
        strict.feed(primary)
        self.assertEqual(strict.feed(secondary), [])
        matcher = DiagnosticEventMatcher()
        matcher.feed(primary)
        events = matcher.feed(secondary)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["standards_compliant"])
        self.assertFalse(events[0]["channel_matches_aux"])
        self.assertFalse(events[0]["phy_matches_aux"])
        self.assertAlmostEqual(events[0]["error_vs_aux_us"], 808)
        self.assertEqual(matcher.feed(secondary), [])
        secondary["sample_time_s"] = .040808
        for window, mismatch in ((500, False), (2000, True)):
            with self.subTest(window=window, identity_mismatch=mismatch):
                candidate = dict(primary)
                if mismatch:
                    candidate["extended"] = dict(primary["extended"], adi={"sid": 1, "did": 9})
                test_matcher = DiagnosticEventMatcher(window)
                test_matcher.feed(candidate)
                self.assertEqual(test_matcher.feed(secondary), [])

    def test_live_queue_overflow_is_explicit(self):
        args = parse_args(["--queue-blocks", "1", "--block-samples", "1024", "--duration", "0"])
        capture = Capture(args)
        capture.proc = object()  # only the live/offline branch discriminator
        capture.stream = io.BytesIO(b"\x00" * 8192)
        capture._read()
        self.assertTrue(capture.done.is_set())
        self.assertEqual(capture.stats["queue_overflow"], 1)
        self.assertIn("overflow", capture.error)


class IQTests(unittest.TestCase):
    def test_recorded_packet_recovered_by_window_retry(self):
        with np.load(ROOT / "tests" / "fixtures" / "run10264_seq24.npz", allow_pickle=False) as fixture:
            values = fixture["iq_ci8"].astype(np.float32)
            iq = (values[:, 0] + 1j * values[:, 1]) / 128
            expected = str(fixture["expected_pdu_hex"])
        for enabled in (False, True):
            with self.subTest(timing_retry=enabled):
                decoder = ChannelDecoder(8000000, 2480000000, 39, timing_retry=enabled)
                dc = IQDCBlocker(8000000)
                packets = []
                for start in range(0, len(iq), 997):
                    packets.extend(decoder.feed(dc.feed(iq[start:start + 997])))
                packets.extend(decoder.feed([], final=True))
                target = [packet for packet in packets if packet["extended"].get("adva") == "C1:A2:A3:A4:A5:A6"]
                self.assertEqual(len(target), int(enabled))
                if enabled:
                    self.assertEqual(target[0]["pdu_hex"], expected)
                    self.assertEqual(target[0]["decode_method"], "narrow_window_retry")
                    self.assertEqual(decoder.stats["timing_retry_recovered"], 1)

    def test_dc_filter_is_independent_of_chunk_boundaries(self):
        iq = waveform(pdu()) + np.complex64(.5 + .9j)
        expected = IQDCBlocker(8000000).feed(iq)
        blocker = IQDCBlocker(8000000)
        actual = np.concatenate([blocker.feed(iq[i:i + 997]) for i in range(0, len(iq), 997)])
        np.testing.assert_allclose(actual, expected, atol=1e-7)
        np.testing.assert_array_equal(IQDCBlocker(8000000, 0).feed(iq), iq)

    def test_weak_packet_under_strong_dc_leakage(self):
        packet = pdu(238)
        # Allow the continuous receiver's DC estimate to settle before the burst.
        iq = np.concatenate((np.zeros(32000, np.complex64),
                             .04 * waveform(packet, noise=.01))) + np.complex64(.07 + .12j)
        _, uncorrected = decode_chunks(iq)
        self.assertEqual(uncorrected, [])
        corrected = IQDCBlocker(8000000).feed(iq)
        _, packets = decode_chunks(corrected)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["pdu_hex"], packet.hex())

    def test_long_packet_chunk_boundaries_cfo_and_polarity(self):
        for length, cfo, invert, ppm in ((64, 0, False, 0), (238, 175000, False, 65),
                                       (255, -160000, True, -65)):
            with self.subTest(length=length):
                packet = pdu(length)
                _, packets = decode_chunks(waveform(packet, cfo=cfo, invert=invert, ppm=ppm))
                self.assertEqual(len(packets), 1)
                self.assertEqual(packets[0]["pdu_hex"], packet.hex())
                self.assertAlmostEqual(packets[0]["cfo_hz"], cfo, delta=20000)
                self.assertAlmostEqual(packets[0]["sample_start"], 973, delta=8)

    def test_crc_corruption_and_noise(self):
        decoder, packets = decode_chunks(waveform(pdu(), corrupt=True))
        self.assertEqual(packets, [])
        self.assertGreater(decoder.stats["crc_failure_candidates"], 0)
        rng = np.random.default_rng(53)
        _, packets = decode_chunks((rng.normal(size=100000) + 1j * rng.normal(size=100000)).astype(np.complex64))
        self.assertEqual(packets, [])

    def test_channel_translation_and_repeated_packets(self):
        packet = pdu()
        iq = waveform(packet, channel=3, frequency_offset=1000000)
        _, packets = decode_chunks(np.concatenate([iq, iq, iq]), channel=3, center=2409000000)
        self.assertEqual(len(packets), 3)  # genuine RF repeats are never deduplicated
        self.assertEqual([p["pdu_hex"] for p in packets], [packet.hex()] * 3)
        self.assertGreater(packets[1]["sample_start"], packets[0]["sample_start"])

    def test_primary_secondary_one_iq_timeline(self):
        fs = 8000000
        aux = (0 | (66 << 8)).to_bytes(3, "little")  # ch0, LE1M, 1980us
        primary = bytes([7, 7, 6, 0x18, 0x11, 0x30]) + aux
        secondary = pdu(238)
        a = waveform(primary, channel=37, frequency_offset=-1000000, noise=0)
        b = waveform(secondary, channel=0, frequency_offset=1000000, noise=0)
        delay = int(1980e-6 * fs)
        iq = np.zeros(max(len(a), len(b) + delay), np.complex64)
        iq[:len(a)] += a
        iq[delay:delay + len(b)] += b
        rng = np.random.default_rng(98)
        iq += (.015 * (rng.normal(size=len(iq)) + 1j * rng.normal(size=len(iq)))).astype(np.complex64)
        packets = []
        for channel in (37, 0):
            _, found = decode_chunks(iq, channel=channel, center=2403000000)
            packets.extend(found)
        self.assertEqual(len(packets), 2)
        matcher = EventMatcher()
        matches = []
        for number, packet in enumerate(sorted(packets, key=lambda p: p["sample_start"]), 1):
            packet["packet_no"] = number
            matches.extend(matcher.feed(packet))
        self.assertEqual(len(matches), 1)
        self.assertAlmostEqual(matches[0]["delta_us"], 1980, delta=2)

    def test_existing_30_72m_generator_waveform(self):
        directory = ROOT.parent / "std_ble"
        sys.path.insert(0, str(directory))
        try:
            import generate_ble_exadv_iq_30_72M as generator
            ll, packet, _, _, _ = generator.create_ext_secondary_ll_payload(
                generator.parse_mac("C1:A2:A3:A4:A5:A6"), list(range(220)), 39, 3, 17, 0)
            bits = "".join(f"{byte:08b}"[::-1] for byte in ll)
            packed = generator.ble_bits_to_iq_30_72m(bits, pre_pad_us=100, post_pad_us=100)[::2]
            i = (packed & 65535).astype(np.uint16).view(np.int16).astype(np.float32)
            q = (packed >> 16).astype(np.uint16).view(np.int16).astype(np.float32)
            iq = signal.resample_poly((i + 1j * q) / 15000, 25, 96).astype(np.complex64)
            _, found = decode_chunks(iq)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["pdu_hex"], bytes(packet).hex())
        finally:
            sys.path.remove(str(directory))

    def test_offline_cli_ci8(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iq = waveform(pdu(255)) * .6
            values = np.column_stack([iq.real, iq.imag])
            np.clip(np.round(values * 127), -128, 127).astype(np.int8).tofile(root / "input.ci8")
            result = main(["--iq-file", str(root / "input.ci8"), "--duration", "0",
                           "--block-samples", "1027", "--output", str(root / "rx"), "--quiet"])
            self.assertEqual(result, 0)
            summary = json.loads((root / "rx.summary.json").read_text())
            self.assertEqual(summary["counts"]["packets"], 1)
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(len((root / "rx.packets.jsonl").read_text().splitlines()), 1)

    def test_truncated_iq_is_reported(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.ci8").write_bytes(b"\x01\x02\x03")
            with contextlib.redirect_stdout(io.StringIO()):
                result = main(["--iq-file", str(root / "bad.ci8"), "--duration", "0",
                               "--output", str(root / "rx"), "--quiet"])
            self.assertEqual(result, 1)
            summary = json.loads((root / "rx.summary.json").read_text())
            self.assertIn("truncated IQ", summary["error"])


if __name__ == "__main__":
    unittest.main()
