#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# GNU Radio Python Flow Graph
# Title: ZigBee OQPSK Receiver (native C++ blocks)
# GNU Radio version: 3.10.9.2

from gnuradio import analog
from gnuradio import blocks
from gnuradio import digital
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio import gr
import sys
import signal
import numpy
import osmosdr
import time
from gnuradio import zeromq


class gr_zigbee(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "ZigBee OQPSK Receiver", catch_exceptions=True)

        ##################################################
        # Variables
        ##################################################
        self.transition_width = transition_width = 300e3
        self.sample_rate = sample_rate = 10000000
        self.chip_rate = chip_rate = 2e6
        self.cutoff_freq = cutoff_freq = 2.5e6
        self.zigbee_channel = zigbee_channel = 11
        self.zigbee_channel_spacing = zigbee_channel_spacing = 5e6
        self.zigbee_base_freq = zigbee_base_freq = 2405e6
        self.squelch_threshold = squelch_threshold = -25
        self.rf_gain = rf_gain = 0
        self.if_gain = if_gain = 16
        self.bb_gain = bb_gain = 16
        self.lowpass_filter = lowpass_filter = firdes.low_pass(1, sample_rate, cutoff_freq, transition_width)
        self.iq_output = iq_output = "/dev/null"
        self.freq_offset = freq_offset = 0
        self.cfo_correction = cfo_correction = 0
        self.freq = freq = zigbee_base_freq + (zigbee_channel_spacing * (zigbee_channel - 11))
        self.demod_sps = demod_sps = int(sample_rate / chip_rate)
        # Each I/Q arm carries every other chip.  Its symbol period and the
        # half-sine pulse therefore span two chip periods.
        self.demod_delay = demod_delay = demod_sps
        self.demod_keep_n = demod_keep_n = 2 * demod_sps
        self.demod_keep_offset = demod_keep_offset = demod_keep_n - 1
        self.phase_keep_offset = phase_keep_offset = 0  # 0-4, phase-diff BlueBee chip sampler

        # Half-sine pulse for OQPSK matched filter
        self.pulse_taps = pulse_taps = [
            numpy.sin(numpy.pi * (n + 0.5) / demod_keep_n)
            for n in range(demod_keep_n)
        ]

        ##################################################
        # Blocks
        ##################################################

        # Formal standard input: one packed 10 Msample/s differential stream.
        # The Python receiver deinterleaves all five 2 Mchip/s timing phases and
        # performs normal IEEE 802.15.4 CHIP_MAP despreading.
        self.zeromq_pub_sink = zeromq.pub_sink(gr.sizeof_char, 1, 'tcp://127.0.0.1:55556', 100, False, (20), '', True, True)
        self.unpacked_to_packed = blocks.unpacked_to_packed_bb(1, gr.GR_LSB_FIRST)
        self.standard_phase_slicer = digital.binary_slicer_fb()

        # Corrected coherent OQPSK reference path.  It is retained on a
        # diagnostic-only endpoint and is no longer the formal BlueBee input.
        self.coherent_zeromq_pub_sink = zeromq.pub_sink(gr.sizeof_char, 1, 'tcp://127.0.0.1:55566', 100, False, (20), '', True, True)
        self.coherent_unpacked_to_packed = blocks.unpacked_to_packed_bb(1, gr.GR_LSB_FIRST)
        self.phase_zeromq_pub_sinks = [
            zeromq.pub_sink(
                gr.sizeof_char, 1, f'tcp://127.0.0.1:{55557 + offset}',
                100, False, (20), '', True, True
            )
            for offset in range(demod_sps)
        ]
        self.phase_unpacked_to_packeds = [
            blocks.unpacked_to_packed_bb(1, gr.GR_LSB_FIRST)
            for _ in range(demod_sps)
        ]

        self.rtlsdr_source_0 = osmosdr.source(
            args="numchan=" + str(1) + " " + "hackrf=0"
        )
        self.rtlsdr_source_0.set_time_now(osmosdr.time_spec_t(time.time()), osmosdr.ALL_MBOARDS)
        self.rtlsdr_source_0.set_sample_rate(sample_rate)
        self.rtlsdr_source_0.set_center_freq((freq + freq_offset), 0)
        self.rtlsdr_source_0.set_freq_corr(0, 0)
        self.rtlsdr_source_0.set_dc_offset_mode(0, 0)
        self.rtlsdr_source_0.set_iq_balance_mode(0, 0)
        self.rtlsdr_source_0.set_gain_mode(False, 0)
        self.rtlsdr_source_0.set_gain(rf_gain, 0)
        self.rtlsdr_source_0.set_if_gain(if_gain, 0)
        self.rtlsdr_source_0.set_bb_gain(bb_gain, 0)
        self.rtlsdr_source_0.set_antenna('', 0)
        self.rtlsdr_source_0.set_bandwidth(0, 0)

        self.freq_xlating_fir_filter_lp = filter.freq_xlating_fir_filter_ccc(1, lowpass_filter, (cfo_correction - freq_offset), sample_rate)

        self.costas_loop = digital.costas_loop_cc(0.02, 4, False)

        # BlueBee phase-difference path: sign(angle(s[n] * conj(s[n-1]))).
        self.phase_delay = blocks.delay(gr.sizeof_gr_complex, 1)
        self.phase_conj = blocks.conjugate_cc()
        self.phase_multiply = blocks.multiply_vcc(1)
        self.phase_arg = blocks.complex_to_arg(1)
        self.phase_keeps = [
            blocks.keep_m_in_n(gr.sizeof_float, 1, demod_sps, offset)
            for offset in range(demod_sps)
        ]
        self.phase_slicers = [
            digital.binary_slicer_fb() for _ in range(demod_sps)
        ]

        # Split I/Q
        self.complex_to_real = blocks.complex_to_real(1)
        self.complex_to_imag = blocks.complex_to_imag(1)

        # I path: delay → FIR matched filter → decimate
        self.i_delay = blocks.delay(gr.sizeof_float, demod_delay)
        self.i_matched = filter.fir_filter_fff(1, pulse_taps)
        self.i_keep = blocks.keep_m_in_n(gr.sizeof_float, 1, demod_keep_n, demod_keep_offset)

        # Q path: FIR matched filter → decimate (Q delay baked into signal)
        self.q_matched = filter.fir_filter_fff(1, pulse_taps)
        self.q_keep = blocks.keep_m_in_n(gr.sizeof_float, 1, demod_keep_n, demod_keep_offset)

        # Interleave I/Q → binary slice → pack
        self.interleave = blocks.interleave(gr.sizeof_float, 1)
        self.binary_slicer = digital.binary_slicer_fb()

        # IQ recording: raw SDR samples, no head (user stops manually)
        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_gr_complex * 1, iq_output, False)
        self.blocks_file_sink_0.set_unbuffered(True)

        ##################################################
        # Connections
        ##################################################
        self.connect((self.rtlsdr_source_0, 0), (self.freq_xlating_fir_filter_lp, 0))
        self.connect((self.freq_xlating_fir_filter_lp, 0), (self.costas_loop, 0))
        self.connect((self.costas_loop, 0), (self.complex_to_real, 0))
        self.connect((self.costas_loop, 0), (self.complex_to_imag, 0))
        self.connect((self.complex_to_real, 0), (self.i_delay, 0))
        self.connect((self.i_delay, 0), (self.i_matched, 0))
        self.connect((self.i_matched, 0), (self.i_keep, 0))
        self.connect((self.i_keep, 0), (self.interleave, 0))

        # Q branch
        self.connect((self.complex_to_imag, 0), (self.q_matched, 0))
        self.connect((self.q_matched, 0), (self.q_keep, 0))
        self.connect((self.q_keep, 0), (self.interleave, 1))

        # Output: skip first 2 garbage samples, then slice → pack → ZMQ
        self.skip_head = blocks.skiphead(gr.sizeof_float, 2)
        self.connect((self.interleave, 0), (self.skip_head, 0))
        self.connect((self.skip_head, 0), (self.binary_slicer, 0))
        self.connect((self.binary_slicer, 0), (self.coherent_unpacked_to_packed, 0))
        self.connect((self.coherent_unpacked_to_packed, 0), (self.coherent_zeromq_pub_sink, 0))

        # Recording: FILTERED IQ (DC offset removed by filter)
        self.connect((self.freq_xlating_fir_filter_lp, 0), (self.blocks_file_sink_0, 0))

        # Phase-difference BlueBee detector path. This does not feed normal ZigBee decoding.
        self.connect((self.freq_xlating_fir_filter_lp, 0), (self.phase_multiply, 0))
        self.connect((self.freq_xlating_fir_filter_lp, 0), (self.phase_delay, 0))
        self.connect((self.phase_delay, 0), (self.phase_conj, 0))
        self.connect((self.phase_conj, 0), (self.phase_multiply, 1))
        self.connect((self.phase_multiply, 0), (self.phase_arg, 0))
        self.connect((self.phase_arg, 0), (self.standard_phase_slicer, 0))
        self.connect((self.standard_phase_slicer, 0), (self.unpacked_to_packed, 0))
        self.connect((self.unpacked_to_packed, 0), (self.zeromq_pub_sink, 0))
        for offset in range(demod_sps):
            self.connect((self.phase_arg, 0), (self.phase_keeps[offset], 0))
            self.connect((self.phase_keeps[offset], 0), (self.phase_slicers[offset], 0))
            self.connect((self.phase_slicers[offset], 0), (self.phase_unpacked_to_packeds[offset], 0))
            self.connect((self.phase_unpacked_to_packeds[offset], 0), (self.phase_zeromq_pub_sinks[offset], 0))

        # Backward-compatible aliases for code that only inspects offset 0.
        self.phase_keep = self.phase_keeps[0]
        self.phase_slicer = self.phase_slicers[0]
        self.phase_unpacked_to_packed = self.phase_unpacked_to_packeds[0]
        self.phase_zeromq_pub_sink = self.phase_zeromq_pub_sinks[0]

    def get_transition_width(self):
        return self.transition_width

    def set_transition_width(self, transition_width):
        self.transition_width = transition_width
        self.set_lowpass_filter(firdes.low_pass(1, self.sample_rate, self.cutoff_freq, self.transition_width))

    def get_sample_rate(self):
        return self.sample_rate

    def set_sample_rate(self, sample_rate):
        self.sample_rate = sample_rate
        self.set_demod_sps(int(self.sample_rate / self.chip_rate))
        self.set_lowpass_filter(firdes.low_pass(1, self.sample_rate, self.cutoff_freq, self.transition_width))
        self.rtlsdr_source_0.set_sample_rate(self.sample_rate)

    def get_chip_rate(self):
        return self.chip_rate

    def set_chip_rate(self, chip_rate):
        self.chip_rate = chip_rate
        self.set_demod_sps(int(self.sample_rate / self.chip_rate))

    def get_cutoff_freq(self):
        return self.cutoff_freq

    def set_cutoff_freq(self, cutoff_freq):
        self.cutoff_freq = cutoff_freq
        self.set_lowpass_filter(firdes.low_pass(1, self.sample_rate, self.cutoff_freq, self.transition_width))

    def get_zigbee_channel(self):
        return self.zigbee_channel

    def set_zigbee_channel(self, zigbee_channel):
        self.zigbee_channel = zigbee_channel
        self.set_freq(self.zigbee_base_freq + (self.zigbee_channel_spacing * (self.zigbee_channel - 11)))

    def get_zigbee_channel_spacing(self):
        return self.zigbee_channel_spacing

    def set_zigbee_channel_spacing(self, zigbee_channel_spacing):
        self.zigbee_channel_spacing = zigbee_channel_spacing
        self.set_freq(self.zigbee_base_freq + (self.zigbee_channel_spacing * (self.zigbee_channel - 11)))

    def get_zigbee_base_freq(self):
        return self.zigbee_base_freq

    def set_zigbee_base_freq(self, zigbee_base_freq):
        self.zigbee_base_freq = zigbee_base_freq
        self.set_freq(self.zigbee_base_freq + (self.zigbee_channel_spacing * (self.zigbee_channel - 11)))

    def get_squelch_threshold(self):
        return self.squelch_threshold

    def set_squelch_threshold(self, squelch_threshold):
        self.squelch_threshold = squelch_threshold
        self.analog_simple_squelch.set_threshold(self.squelch_threshold)

    def get_rf_gain(self):
        return self.rf_gain

    def set_rf_gain(self, rf_gain):
        self.rf_gain = rf_gain
        self.rtlsdr_source_0.set_gain(self.rf_gain, 0)

    def get_if_gain(self):
        return self.if_gain

    def set_if_gain(self, if_gain):
        self.if_gain = if_gain
        self.rtlsdr_source_0.set_if_gain(self.if_gain, 0)

    def get_bb_gain(self):
        return self.bb_gain

    def set_bb_gain(self, bb_gain):
        self.bb_gain = bb_gain
        self.rtlsdr_source_0.set_bb_gain(self.bb_gain, 0)

    def get_lowpass_filter(self):
        return self.lowpass_filter

    def set_lowpass_filter(self, lowpass_filter):
        self.lowpass_filter = lowpass_filter
        self.freq_xlating_fir_filter_lp.set_taps(self.lowpass_filter)

    def get_iq_output(self):
        return self.iq_output

    def set_iq_output(self, iq_output):
        self.iq_output = iq_output
        self.blocks_file_sink_0.open(self.iq_output)

    def get_demod_sps(self):
        return self.demod_sps

    def set_demod_sps(self, demod_sps):
        self.demod_sps = demod_sps
        self.demod_delay = self.demod_sps
        self.demod_keep_n = 2 * self.demod_sps
        self.demod_keep_offset %= self.demod_keep_n
        self.pulse_taps = [
            numpy.sin(numpy.pi * (n + 0.5) / self.demod_keep_n)
            for n in range(self.demod_keep_n)
        ]
        if hasattr(self, 'i_delay'):
            self.i_delay.set_dly(self.demod_delay)
        if hasattr(self, 'i_matched'):
            self.i_matched.set_taps(self.pulse_taps)
        if hasattr(self, 'q_matched'):
            self.q_matched.set_taps(self.pulse_taps)
        if hasattr(self, 'i_keep'):
            self.i_keep.set_n(self.demod_keep_n)
            self.i_keep.set_offset(self.demod_keep_offset)
        if hasattr(self, 'q_keep'):
            self.q_keep.set_n(self.demod_keep_n)
            self.q_keep.set_offset(self.demod_keep_offset)
        if hasattr(self, 'phase_keeps'):
            for keep in self.phase_keeps:
                keep.set_n(self.demod_sps)

    def get_demod_keep_offset(self):
        return self.demod_keep_offset

    def set_demod_keep_offset(self, demod_keep_offset):
        self.demod_keep_offset = int(demod_keep_offset) % self.demod_keep_n
        if hasattr(self, 'i_keep'):
            self.i_keep.set_offset(self.demod_keep_offset)
        if hasattr(self, 'q_keep'):
            self.q_keep.set_offset(self.demod_keep_offset)

    def get_phase_keep_offset(self):
        return self.phase_keep_offset

    def set_phase_keep_offset(self, phase_keep_offset):
        # The diagnostic graph now publishes every fixed phase concurrently;
        # consumers select the corresponding 55557..55561 endpoint.
        self.phase_keep_offset = int(phase_keep_offset) % self.demod_sps

    def get_freq_offset(self):
        return self.freq_offset

    def set_freq_offset(self, freq_offset):
        self.freq_offset = freq_offset
        self.freq_xlating_fir_filter_lp.set_center_freq((self.cfo_correction - self.freq_offset))
        self.rtlsdr_source_0.set_center_freq((self.freq + self.freq_offset), 0)

    def get_cfo_correction(self):
        return self.cfo_correction

    def set_cfo_correction(self, cfo_correction):
        self.cfo_correction = cfo_correction
        self.freq_xlating_fir_filter_lp.set_center_freq((self.cfo_correction - self.freq_offset))

    def get_freq(self):
        return self.freq

    def set_freq(self, freq):
        self.freq = freq
        self.rtlsdr_source_0.set_center_freq((self.freq + self.freq_offset), 0)


def main(top_block_cls=gr_zigbee, options=None):
    tb = top_block_cls()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    tb.start()

    try:
        input('Press Enter to quit: ')
    except EOFError:
        pass
    tb.stop()
    tb.wait()


if __name__ == '__main__':
    main()
