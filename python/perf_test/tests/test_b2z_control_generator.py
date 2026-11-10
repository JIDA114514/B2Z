"""Host checks for the board's v1 dual-protocol packet builder."""

import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest

from python.exadv_rx.protocol import whiten


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "app_FreeRTOS" / "app"


class Packet(ctypes.Structure):
    _fields_ = [
        ("run_id", ctypes.c_uint16),
        ("slot_index", ctypes.c_uint32),
        ("ref_tick_ms", ctypes.c_uint32),
        ("period_ms", ctypes.c_uint16),
        ("command_id", ctypes.c_uint32),
        ("execute_at_ms", ctypes.c_uint32),
        ("valid_until_ms", ctypes.c_uint32),
        ("ble_target", ctypes.c_uint16),
        ("ble_opcode", ctypes.c_uint8),
        ("ble_arg", ctypes.c_uint16),
        ("zigbee_target", ctypes.c_uint16),
        ("zigbee_opcode", ctypes.c_uint8),
        ("zigbee_arg", ctypes.c_uint16),
    ]


class Meta(ctypes.Structure):
    _fields_ = [
        ("zigbee_payload", ctypes.POINTER(ctypes.c_uint8)),
        ("zigbee_payload_len", ctypes.c_uint32),
        ("zigbee_frame", ctypes.POINTER(ctypes.c_uint8)),
        ("zigbee_frame_len", ctypes.c_uint32),
        ("bluebee_bytes", ctypes.POINTER(ctypes.c_uint8)),
        ("bluebee_byte_count", ctypes.c_uint32),
        ("adv_data", ctypes.POINTER(ctypes.c_uint8)),
        ("adv_data_len", ctypes.c_uint32),
        ("pdu", ctypes.POINTER(ctypes.c_uint8)),
        ("pdu_len", ctypes.c_uint32),
        ("crc", ctypes.POINTER(ctypes.c_uint8)),
        ("crc_len", ctypes.c_uint32),
        ("ll_payload", ctypes.POINTER(ctypes.c_uint8)),
        ("ll_payload_len", ctypes.c_uint32),
        ("iq_words", ctypes.POINTER(ctypes.c_uint32)),
        ("iq_word_count", ctypes.c_uint32),
        ("iq_byte_count", ctypes.c_uint32),
        ("air_us", ctypes.c_uint32),
        ("post_pad_us", ctypes.c_uint32),
        ("frame_time_us", ctypes.c_uint32),
        ("mapping_time_us", ctypes.c_uint32),
        ("gfsk_time_us", ctypes.c_uint32),
        ("total_time_us", ctypes.c_uint32),
        ("whitening_channel", ctypes.c_uint32),
        ("tx_lo_hz", ctypes.c_uint64),
        ("ble_control_record", ctypes.POINTER(ctypes.c_uint8)),
        ("primary_iq_words", ctypes.POINTER(ctypes.c_uint32)),
        ("primary_iq_byte_count", ctypes.c_uint32),
        ("primary_air_us", ctypes.c_uint32),
        ("aux_ptr_channel", ctypes.c_uint8),
        ("aux_offset_us", ctypes.c_uint32),
        ("rf_mode", ctypes.c_uint8),
        ("primary_pdu", ctypes.POINTER(ctypes.c_uint8)),
        ("primary_pdu_len", ctypes.c_uint32),
        ("ieee_iq_words", ctypes.POINTER(ctypes.c_uint32)),
        ("ieee_iq_byte_count", ctypes.c_uint32),
        ("ieee_air_us", ctypes.c_uint32),
    ]


def read_bytes(pointer, length):
    return bytes(pointer[i] for i in range(length))


class ControlGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        library = Path(cls.temp.name) / "libb2z_control.so"
        subprocess.run(
            [
                "cc", "-std=c99", "-O0", "-shared", "-fPIC", "-DCONFIG_H_",
                f"-I{APP}", str(APP / "ble_exadv_secondary_gen.c"),
                "-lm", "-o", str(library),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.ble_exadv_secondary_gen_build_control.argtypes = [ctypes.POINTER(Packet)]
        cls.lib.ble_exadv_secondary_gen_build_control.restype = ctypes.c_int32
        cls.lib.ble_exadv_secondary_gen_build_control_mode.argtypes = [
            ctypes.POINTER(Packet), ctypes.c_uint8]
        cls.lib.ble_exadv_secondary_gen_build_control_mode.restype = ctypes.c_int32
        cls.lib.ble_exadv_secondary_gen_build_default.restype = ctypes.c_int32
        cls.lib.ble_exadv_secondary_gen_get_last_meta.restype = ctypes.POINTER(Meta)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_v1_vectors_and_wire_budget(self):
        packet = Packet(
            1001, 7, 1400, 200, 42, 3000, 2500,
            1, 1, 1, 2, 1, 2,
        )
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control(ctypes.byref(packet)), 0)
        meta = self.lib.ble_exadv_secondary_gen_get_last_meta().contents
        ble = read_bytes(meta.ble_control_record, 35)
        zigbee = read_bytes(meta.zigbee_payload, meta.zigbee_payload_len)
        frame = read_bytes(meta.zigbee_frame, meta.zigbee_frame_len)
        pdu = read_bytes(meta.pdu, meta.pdu_len)
        ll = read_bytes(meta.ll_payload, meta.ll_payload_len)
        bluebee = read_bytes(meta.bluebee_bytes, meta.bluebee_byte_count)
        self.assertEqual(
            ble.hex(),
            "b2430101e9030700000078050000c8002a0000000100010100b80b0000c40900008098",
        )
        self.assertEqual(
            zigbee.hex(),
            "b2430101e9030700000078050000c8002a0000000200010200b80b0000c4090000eae6",
        )
        self.assertEqual(frame[:6].hex(), "00000000a725")
        self.assertEqual(frame[-2:].hex(), "973d")
        self.assertEqual((meta.zigbee_frame_len, meta.bluebee_byte_count), (43, 172))
        self.assertEqual((meta.adv_data_len, meta.pdu_len, pdu[1]), (214, 226, 224))
        self.assertEqual(pdu[2:4].hex(), "0909")
        self.assertEqual(pdu[10:12].hex(), "0700")
        self.assertEqual(pdu[12:19].hex(), "020106d2ffffff")
        self.assertEqual(pdu[19:54], ble)
        # The BlueBee region appears unchanged in the on-air byte stream.
        self.assertEqual(ll[59:59 + 172], bluebee)
        self.assertEqual((meta.air_us, meta.primary_air_us), (1872, 136))
        self.assertGreater(meta.primary_iq_byte_count, 0)
        self.assertEqual((meta.rf_mode, meta.whitening_channel, meta.tx_lo_hz,
                          meta.aux_offset_us), (0, 39, 2_480_000_000, 30_000))
        self.assertEqual(read_bytes(meta.primary_pdu, meta.primary_pdu_len)[6:9],
                         bytes.fromhex("03e803"))

    def test_standard_secondary_ch3_updates_auxptr_whitening_and_rf(self):
        packet = Packet(1001, 7, 1400, 500, 42, 3000, 2500,
                        1, 1, 1, 2, 1, 2)
        packet.ref_tick_ms = 3500
        packet.execute_at_ms = 6000
        packet.valid_until_ms = 5000
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control_mode(
            ctypes.byref(packet), 1), 0)
        meta = self.lib.ble_exadv_secondary_gen_get_last_meta().contents
        self.assertEqual((meta.rf_mode, meta.aux_ptr_channel, meta.aux_offset_us),
                         (1, 3, 300_000))
        self.assertEqual((meta.whitening_channel, meta.tx_lo_hz),
                         (3, 2_410_000_000))
        primary = read_bytes(meta.primary_pdu, meta.primary_pdu_len)
        self.assertEqual(primary[6:9], bytes.fromhex("83e803"))
        self.assertEqual(primary[4:6], bytes.fromhex("0700"))
        self.assertEqual((meta.pdu_len, meta.adv_data_len), (226, 214))
        ll = read_bytes(meta.ll_payload, meta.ll_payload_len)
        pdu = read_bytes(meta.pdu, meta.pdu_len)
        bluebee = read_bytes(meta.bluebee_bytes, meta.bluebee_byte_count)
        self.assertEqual(ll[59:59 + 172], bluebee)
        self.assertEqual(whiten(ll[5:5 + len(pdu)], 3), pdu)
        self.assertNotEqual(whiten(ll[5:5 + len(pdu)], 39), pdu)
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control_mode(
            ctypes.byref(packet), 3), -1)

    def test_separate_waveforms_recover_independent_records(self):
        import numpy as np
        from scipy.signal import resample_poly
        from python.perf_test.tests.test_bluebee_gen_waveform import iq_complex, demodulate_center_bits
        from python.zigbee_rx.tests.test_zigbee_receiver import decode
        from python.exadv_rx.protocol import crc24
        from python.control_match.protocol import control_record
        for command, ble_arg, ieee_arg in ((0, 0, 0), (43, 1, 7), (44, 9, 3)):
            packet = Packet(2102, 7, 3500, 500, command, 6000 if command else 0,
                            5000 if command else 0, 1 if command else 0, 1 if command else 0,
                            ble_arg, 2 if command else 0, 2 if command else 0, ieee_arg)
            self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control_mode(ctypes.byref(packet), 2), 0)
            meta = self.lib.ble_exadv_secondary_gen_get_last_meta().contents
            pdu = read_bytes(meta.pdu, meta.pdu_len)
            ll = read_bytes(meta.ll_payload, meta.ll_payload_len)
            self.assertEqual((meta.pdu_len, meta.adv_data_len, meta.air_us, meta.ieee_air_us), (54, 42, 496, 1376))
            self.assertEqual(meta.primary_air_us + meta.air_us + meta.ieee_air_us, 2008)
            self.assertEqual(whiten(ll[5:], 3), pdu + crc24(pdu))
            self.assertEqual(control_record(pdu[19:54])["arg"], ble_arg)
            self.assertEqual(read_bytes(meta.primary_pdu, meta.primary_pdu_len)[6:9], bytes.fromhex("83e803"))
            # DMA buffer duplicates each complex sample for the platform interface.
            ble_iq = iq_complex(np.ctypeslib.as_array(meta.iq_words, shape=(meta.iq_byte_count // 4,))[::2])
            bits = demodulate_center_bits(ble_iq, len(ll) * 8)
            self.assertEqual(np.packbits(bits, bitorder="little").tobytes(), ll)
            ieee_iq = iq_complex(np.ctypeslib.as_array(meta.ieee_iq_words, shape=(meta.ieee_iq_byte_count // 4,))[::2])
            iq4 = resample_poly(ieee_iq, 25, 192).astype(np.complex64)
            _, recovered = decode(np.concatenate((np.zeros(400, np.complex64), iq4, np.zeros(1200, np.complex64))),
                               sample_rate=4_000_000)
            valid = [r for r in recovered if r["fcs_ok"]]
            self.assertEqual(len(valid), 1)
            actual = control_record(bytes.fromhex(valid[0]["payload_hex"]))
            self.assertEqual((actual["run_id"], actual["slot_index"], actual["command_id"], actual["arg"]),
                             (2102, 7, command, ieee_arg))

    def test_sync_only_and_invalid_deadline(self):
        packet = Packet(1001, 1, 200, 200, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control(ctypes.byref(packet)), 0)
        packet.command_id = 42
        packet.ble_target = 1
        packet.zigbee_target = 2
        packet.execute_at_ms = 100
        packet.valid_until_ms = 200
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_control(ctypes.byref(packet)), -1)

    def test_legacy_default_budget_unchanged(self):
        self.assertEqual(self.lib.ble_exadv_secondary_gen_build_default(), 0)
        meta = self.lib.ble_exadv_secondary_gen_get_last_meta().contents
        self.assertEqual(meta.zigbee_payload_len, 46)
        self.assertEqual(meta.zigbee_frame_len, 54)
        self.assertEqual(meta.bluebee_byte_count, 216)
        self.assertEqual((meta.pdu_len, meta.ll_payload_len), (238, 246))
        self.assertFalse(bool(meta.primary_iq_words))


if __name__ == "__main__":
    unittest.main()
