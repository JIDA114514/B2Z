import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dsp import IQDCBlocker
from zigbee_decoder import ZigBeeDecoder
from zigbee_protocol import (CHIP_MAP, channel_frequency, fcs16, frame_payload,
                             symbols_to_bytes, _measurement)

spec = importlib.util.spec_from_file_location("zigbee_receive_cli", ROOT / "receive.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def frame(payload):
    return bytes.fromhex("00000000a7") + bytes([len(payload) + 2]) + payload + fcs16(payload).to_bytes(2, "little")


def frame_symbols(data, order):
    if order == "ieee":
        return [s for byte in data for s in (byte & 15, byte >> 4)]
    return [int(bits[i:i+4], 2) for byte in data for bits in [f"{byte:08b}"[::-1]] for i in (0, 4)]


def modulate(payload, kind="bluebee", order="project", cfo=0, invert=False, bad_fcs=False,
             noise=.008, seed=12):
    fs = 8000000
    data = bytearray(frame(payload))
    if bad_fcs:
        data[-1] ^= 1
    symbols = frame_symbols(data, order)
    if kind == "bluebee":
        # TX-only fixture. The receiver must never use this emulation map.
        words = [0x419F, 0x0E77, 0x999E, 0x667A, 0x9DC3, 0x770E, 0xDC39, 0x70E7,
                 0xBCF5, 0xB3D7, 0xCD5F, 0x357F, 0xD5FC, 0x57F3, 0x5BCF, 0x6F3D]
        bits = np.array([(words[s] >> k) & 1 for s in symbols for k in range(16)])
        nrz = np.repeat(bits * 2. - 1, 8)
        t = np.arange(-16, 16) / 8
        taps = np.exp(-(np.pi * t / (np.sqrt(np.log(2)/2)/.5))**2)
        taps /= taps.sum()
        freq = np.convolve(nrz, taps, mode="same") * 250000
        iq = np.exp(1j * np.cumsum(freq * 2 * np.pi / fs))
    else:
        chips = np.array([int(bit) * 2 - 1 for s in symbols for bit in CHIP_MAP[s]])
        pulse = np.sin(np.pi * (np.arange(8) + .5) / 8)
        i = np.repeat(chips[::2], 8) * np.tile(pulse, len(chips)//2)
        q = np.repeat(chips[1::2], 8) * np.tile(pulse, len(chips)//2)
        iq = np.pad(i, (0, 4)) + 1j * np.pad(q, (4, 0))
    if invert:
        iq = iq.conj()
    iq *= np.exp(2j*np.pi*cfo*np.arange(len(iq))/fs)
    iq = np.r_[np.zeros(7993), iq, np.zeros(16000)]
    rng = np.random.default_rng(seed)
    iq += noise * (rng.normal(size=len(iq)) + 1j*rng.normal(size=len(iq)))
    return iq.astype(np.complex64)


def decode(iq, chunk=997, **kwargs):
    decoder = ZigBeeDecoder(**kwargs)
    dc = IQDCBlocker(8000000)
    packets = []
    for start in range(0, len(iq), chunk):
        packets.extend(decoder.feed(dc.feed(iq[start:start+chunk])))
    packets.extend(decoder.feed([], final=True))
    return decoder, packets


class ReceiverTests(unittest.TestCase):
    def test_standard_map_and_crc_match_project(self):
        spec = importlib.util.spec_from_file_location("zigbee_ref", ROOT.parent / "ctc_sim/std_zigbee/zigbee_mod.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(list(CHIP_MAP), mod.CHIP_MAP)
        for size in (0, 10, 46, 125):
            payload = bytes(range(size))
            self.assertEqual(fcs16(payload), mod.crc16_ccitt(payload))
            self.assertEqual(frame_payload(frame(payload)), payload)

    def test_bit_order_roundtrip(self):
        for order in ("project", "ieee"):
            data = bytes(range(256))
            self.assertEqual(symbols_to_bytes(frame_symbols(data, order), order), data)

    def test_bluebee_10_30_40_46_and_frequency_polarity(self):
        for size, cfo, invert in ((10, 0, False), (30, 60000, False), (40, -70000, True), (46, 30000, False)):
            with self.subTest(size=size):
                payload = _measurement.build_test_payload(size, 10270, 19)
                _, packets = decode(modulate(payload, cfo=cfo, invert=invert))
                self.assertEqual(len(packets), 1)
                self.assertEqual(packets[0]["payload_hex"], payload.hex())
                self.assertEqual(packets[0]["dsss_codebook"], "IEEE802.15.4_standard")
                self.assertEqual(packets[0]["phy_observation"], "phase")

    def test_native_oqpsk_both_symbol_orders(self):
        for order, cfo, inverse in (("ieee", 50000, False), ("project", -40000, True)):
            with self.subTest(order=order):
                payload = bytes(range(32))
                _, packets = decode(modulate(payload, kind="oqpsk", order=order, cfo=cfo, invert=inverse))
                self.assertEqual(len(packets), 1)
                self.assertEqual(packets[0]["payload_hex"], payload.hex())
                self.assertEqual(packets[0]["phy_observation"], "oqpsk")
                self.assertEqual(packets[0]["symbol_order"], order)

    def test_fcs_and_noise_rejected(self):
        _, packets = decode(modulate(bytes(range(30)), bad_fcs=True))
        self.assertEqual(packets, [])
        rng = np.random.default_rng(9)
        _, packets = decode((rng.normal(size=100000)+1j*rng.normal(size=100000)).astype(np.complex64))
        self.assertEqual(packets, [])

    def test_repeated_physical_packets_preserved(self):
        payload = _measurement.build_test_payload(30, 10270, 19)
        burst = modulate(payload)
        _, packets = decode(np.r_[burst, burst, burst], chunk=65536)
        self.assertEqual(len(packets), 3)
        self.assertEqual([p["payload_hex"] for p in packets], [payload.hex()]*3)

    def test_recorded_iq_soft_retry_requires_valid_fcs(self):
        with np.load(ROOT / 'tests/fixtures/run10265_soft_frame.npz') as fixture:
            raw = fixture['iq_ci8'].astype(np.float32)
            iq = (raw[:, 0] + 1j * raw[:, 1]) / 128
            expected = str(fixture['expected_frame_hex'])
        _, hard = decode(iq, chunk=65536, demod='phase', symbol_order='project', soft_retry=False)
        _, soft = decode(iq, chunk=65536, demod='phase', symbol_order='project', soft_retry=True)
        self.assertEqual(hard, [])
        self.assertEqual(len(soft), 1)
        self.assertEqual(soft[0]['frame_hex'], expected)
        self.assertEqual(soft[0]['decode_method'], 'soft_dsss')
        self.assertEqual(frame_payload(bytes.fromhex(expected)).hex(), soft[0]['payload_hex'])

    def test_native_maximum_phy_frame(self):
        payload = bytes(range(125))
        _, packets = decode(modulate(payload, kind="oqpsk", order="ieee"), chunk=32771)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["payload_hex"], payload.hex())

    def test_cli_offline_sequence_and_board_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p1 = _measurement.build_test_payload(30, 10270, 0)
            p2 = _measurement.build_test_payload(30, 10270, 2)
            iq = np.r_[modulate(p1), modulate(p2), modulate(p2)] * .6
            values = np.column_stack((iq.real, iq.imag))
            np.clip(np.round(values*127), -128, 127).astype(np.int8).tofile(root/'input.ci8')
            (root/'board.log').write_text('PERF_STATS final=1 run_id=10270 scheduled=3 tx_completed=3\n')
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli.main(['--iq-file',str(root/'input.ci8'),'--duration','0','--run-id','10270',
                                   '--expected-packets','3','--board-log',str(root/'board.log'),
                                   '--full-run-covered','--output',str(root/'rx'),'--quiet'])
            self.assertEqual(result, 0)
            summary = json.loads((root/'rx.summary.json').read_text())
            self.assertEqual(summary['receiver']['unique'], 2)
            self.assertEqual(summary['receiver']['duplicate'], 1)
            self.assertEqual(summary['receiver']['longest_loss_burst'], 1)
            self.assertAlmostEqual(summary['ratios']['wireless_prr']['value'], 2/3)
            packets = [json.loads(line) for line in (root/'rx.packets.jsonl').read_text().splitlines()]
            self.assertEqual([p['sequence'] for p in packets], [0, 2, 2])
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--iq-file',str(root/'input.ci8'),'--duration','0','--run-id','10270',
                          '--board-log',str(root/'board.log'),'--output',str(root/'partial'),'--quiet'])
            partial = json.loads((root/'partial.summary.json').read_text())
            self.assertIsNone(partial['ratios']['wireless_prr']['value'])
            (root/'missing_id.log').write_text('PERF_STATS final=1 scheduled=3 tx_completed=3\n')
            with self.assertRaisesRegex(ValueError, 'valid run_id'):
                cli.main(['--iq-file',str(root/'input.ci8'),'--board-log',str(root/'missing_id.log')])

    def test_cli_invalid_and_partial_iq(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args([])  # no accidental first-HackRF selection
        with self.assertRaises(ValueError):
            channel_frequency(27)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);(root/'bad.ci8').write_bytes(b'\x01\x02\x03')
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli.main(['--iq-file',str(root/'bad.ci8'),'--duration','0','--output',str(root/'rx'),'--quiet'])
            self.assertEqual(result, 1)
            self.assertIn('truncated IQ', json.loads((root/'rx.summary.json').read_text())['error'])


if __name__ == '__main__':
    unittest.main()
