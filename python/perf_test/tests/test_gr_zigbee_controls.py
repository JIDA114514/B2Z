#!/usr/bin/env python3

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


STD_ZIGBEE_DIR = Path(__file__).resolve().parents[2] / "ctc_sim" / "std_zigbee"
sys.path.insert(0, str(STD_ZIGBEE_DIR))

from gr_zigbee import gr_zigbee  # noqa: E402


class FakeSource:
    def __init__(self):
        self.gain = None
        self.if_gain = None
        self.bb_gain = None
        self.center_freq = None

    def set_gain(self, value, channel):
        self.gain = (value, channel)

    def set_if_gain(self, value, channel):
        self.if_gain = (value, channel)

    def set_bb_gain(self, value, channel):
        self.bb_gain = (value, channel)

    def set_center_freq(self, value, channel):
        self.center_freq = (value, channel)


class FakeTranslator:
    def __init__(self):
        self.center_freq = None

    def set_center_freq(self, value):
        self.center_freq = value


class ReceiverControlTests(unittest.TestCase):
    def make_receiver(self):
        return SimpleNamespace(
            rtlsdr_source_0=FakeSource(),
            freq_xlating_fir_filter_lp=FakeTranslator(),
            freq=2_480_000_000,
            freq_offset=100_000,
            cfo_correction=0,
        )

    def test_gain_setters_reach_hardware_source(self):
        receiver = self.make_receiver()

        gr_zigbee.set_rf_gain(receiver, 40)
        gr_zigbee.set_if_gain(receiver, 32)
        gr_zigbee.set_bb_gain(receiver, 24)

        self.assertEqual(receiver.rf_gain, 40)
        self.assertEqual(receiver.if_gain, 32)
        self.assertEqual(receiver.bb_gain, 24)
        self.assertEqual(receiver.rtlsdr_source_0.gain, (40, 0))
        self.assertEqual(receiver.rtlsdr_source_0.if_gain, (32, 0))
        self.assertEqual(receiver.rtlsdr_source_0.bb_gain, (24, 0))

    def test_cfo_correction_is_independent_of_lo_offset(self):
        receiver = self.make_receiver()

        gr_zigbee.set_cfo_correction(receiver, 25_000)
        self.assertEqual(
            receiver.freq_xlating_fir_filter_lp.center_freq,
            -75_000,
        )
        self.assertIsNone(receiver.rtlsdr_source_0.center_freq)

        gr_zigbee.set_freq_offset(receiver, 200_000)
        self.assertEqual(
            receiver.freq_xlating_fir_filter_lp.center_freq,
            -175_000,
        )
        self.assertEqual(
            receiver.rtlsdr_source_0.center_freq,
            (2_480_200_000, 0),
        )


if __name__ == "__main__":
    unittest.main()
