"""Streaming IQ receiver for LE 1M extended advertising, with sample timestamps.

The channel FIR is continuous. Sync acquisition searches every symbol phase;
per-packet CFO, polarity and small clock-rate errors are resolved before CRC.
"""
from __future__ import annotations

from collections import Counter
import math
import numpy as np
from scipy import signal

from protocol import channel_frequency, crc24, parse_pdu, whiten

SYNC_BYTES = bytes.fromhex("aad6be898e")
SYNC_BITS = np.unpackbits(np.frombuffer(SYNC_BYTES, dtype=np.uint8), bitorder="little")
SYNC = SYNC_BITS.astype(np.float32) * 2 - 1
SYNC_CENTERED = SYNC - SYNC.mean()
SYNC_ENERGY = float(SYNC_CENTERED @ SYNC_CENTERED)
OUTPUT_RATE = 2000000
SPS = 2
MAX_PACKET_SAMPLES = (1 + 4 + 2 + 255 + 3) * 8 * SPS


class IQDCBlocker:
    """Continuous first-order IQ high-pass, before frequency translation.

    HackRF LO/DC leakage may be comparable to a weak desired signal. It must
    be removed before nonlinear differential-phase demodulation. State is
    preserved across blocks so the result does not depend on USB chunk sizes.
    """
    def __init__(self, sample_rate: int, cutoff_hz: float = 1000):
        if not math.isfinite(cutoff_hz) or not 0 <= cutoff_hz < sample_rate / 2:
            raise ValueError("DC blocker cutoff must be finite and in [0, Fs/2)")
        self.cutoff_hz = cutoff_hz
        self.alpha = math.exp(-2 * math.pi * cutoff_hz / sample_rate)
        self.state = np.zeros(1, np.complex128)

    def feed(self, iq: np.ndarray) -> np.ndarray:
        if not self.cutoff_hz or not len(iq):
            return iq
        filtered, self.state = signal.lfilter([1., -1.], [1., -self.alpha], iq, zi=self.state)
        return filtered.astype(np.complex64)


class ChannelDecoder:
    def __init__(self, sample_rate: int, center_hz: float, channel: int,
                 whitening_channel: int | None = None, sync_threshold: float = .84):
        if sample_rate not in (4000000, 8000000, 12000000, 16000000, 20000000):
            raise ValueError("sample rate must be 4/8/12/16/20 Msps")
        self.channel = channel
        self.whitening_channel = channel if whitening_channel is None else whitening_channel
        self.input_rate = sample_rate
        self.offset_hz = channel_frequency(channel) - center_hz
        if abs(self.offset_hz) + 1200000 >= sample_rate / 2:
            raise ValueError(f"channel {channel} does not fit capture bandwidth (need 1.2 MHz edge margin)")
        self.decimation = sample_rate // OUTPUT_RATE
        self.oscillator = None
        if self.offset_hz and self.offset_hz == int(self.offset_hz):
            period = sample_rate // math.gcd(sample_rate, abs(int(self.offset_hz)))
            if period <= 65536:
                self.oscillator = np.exp(-2j * np.pi * self.offset_hz * np.arange(period) / sample_rate).astype(np.complex64)
        self.taps = signal.firwin(16 * self.decimation + 1, 850000, fs=sample_rate)
        self.history = np.zeros(len(self.taps) - 1, dtype=np.complex64)
        self.input_samples = 0
        self.buffer_base = 0
        self.buffer = np.empty(0, np.complex64)
        self.scan_cursor = 1
        self.last_end = -1
        self.sync_threshold = sync_threshold
        self.stats = Counter()

    def feed(self, iq: np.ndarray, final: bool = False) -> list[dict]:
        iq = np.asarray(iq, dtype=np.complex64)
        count = len(iq)
        if count:
            if self.offset_hz:
                if self.oscillator is not None:
                    indices = (np.arange(count) + self.input_samples) % len(self.oscillator)
                    iq = iq * self.oscillator[indices]
                else:
                    indices = np.arange(count, dtype=np.float64) + self.input_samples
                    iq = iq * np.exp(-2j * np.pi * self.offset_hz * indices / self.input_rate).astype(np.complex64)
            first = (-self.input_samples) % self.decimation
            combined = np.concatenate((self.history, iq))
            filtered = signal.upfirdn(self.taps, combined[first:], down=self.decimation)
            warm = len(self.history) // self.decimation
            available = max(0, (count - first + self.decimation - 1) // self.decimation)
            output = filtered[warm:warm + available].astype(np.complex64)
            self.history = combined[-len(self.history):].copy()
            self.input_samples += count
            self.buffer = np.concatenate((self.buffer, output))
        packets = self._scan(final)
        # Retain precisely the unscanned tail plus one differential-phase sample.
        drop = max(0, self.scan_cursor - self.buffer_base - 1)
        if drop:
            self.buffer = self.buffer[drop:]
            self.buffer_base += drop
        return packets

    def _scan(self, final: bool) -> list[dict]:
        n = len(self.buffer)
        if n < 64 * SPS:
            return []
        limit = n - (64 * SPS if final else MAX_PACKET_SAMPLES)
        if limit < self.scan_cursor - self.buffer_base:
            return []
        phase = np.angle(self.buffer[1:] * np.conj(self.buffer[:-1]))
        phase = phase * OUTPUT_RATE / (2 * np.pi)  # Hz, not calibrated RSSI.
        # phase[k] describes sample interval [k,k+1], centered at k+.5.
        integral = np.concatenate(([0.], np.cumsum(phase, dtype=np.float64)))
        integral_indices = np.arange(len(integral), dtype=np.float64)
        candidates = []
        for offset in range(SPS):
            usable = ((len(phase) - offset) // SPS) * SPS
            if usable < 40 * SPS:
                continue
            symbols = phase[offset:offset + usable].reshape(-1, SPS).mean(axis=1)
            cross = signal.correlate(symbols, SYNC_CENTERED, mode="valid", method="direct")
            running = np.concatenate(([0.], np.cumsum(symbols, dtype=np.float64)))
            sums = running[40:] - running[:-40]
            running_sq = np.concatenate(([0.], np.cumsum(symbols * symbols, dtype=np.float64)))
            squares = running_sq[40:] - running_sq[:-40]
            energy = np.maximum(squares - sums * sums / 40, 1.)
            score = np.abs(cross) / np.sqrt(energy * SYNC_ENERGY)
            hits = np.flatnonzero(score >= self.sync_threshold)
            for hit in hits:
                start = offset + int(hit) * SPS
                absolute = self.buffer_base + start
                if absolute < self.scan_cursor or start > limit or absolute < self.last_end:
                    continue
                amplitude = cross[hit] / SYNC_ENERGY
                cfo = sums[hit] / 40 - amplitude * SYNC.mean()
                if 70000 <= abs(amplitude) <= 400000 and abs(cfo) <= 350000:
                    candidates.append((start, float(score[hit])))
        # Group sample phases belonging to one physical sync word.
        groups = []
        for candidate in sorted(candidates):
            if not groups or candidate[0] - groups[-1][0][0] > SPS * 2:
                groups.append([])
            groups[-1].append(candidate)
        packets = []
        for group in groups:
            if self.buffer_base + group[0][0] < self.last_end:
                continue
            self.stats["sync_candidates"] += 1
            saw_crc_failure = False
            decoded = None
            for start, score in sorted(group, key=lambda item: -item[1]):
                for ppm in (0, -80, 80):
                    decoded, crc_failed = self._decode(integral, integral_indices, start, score, ppm)
                    saw_crc_failure |= crc_failed
                    if decoded is not None:
                        break
                if decoded is not None:
                    break
            if decoded is not None:
                packets.append(decoded)
                self.stats["packets"] += 1
                self.last_end = decoded.pop("_end_sample")
            elif saw_crc_failure:
                self.stats["crc_failure_candidates"] += 1
            else:
                self.stats["rejected_candidates"] += 1
        self.scan_cursor = self.buffer_base + limit + 1
        return packets

    def _decode(self, integral, integral_indices, start, score, ppm):
        step = SPS * (1 + ppm * 1e-6)

        def demod(count):
            edges = start + np.arange(count + 1) * step
            if edges[-1] >= len(integral):
                return None
            values = np.diff(np.interp(edges, integral_indices, integral)) / step
            amplitude = float(values[:40] @ SYNC_CENTERED / SYNC_ENERGY)
            cfo = float(values[:40].mean() - amplitude * SYNC.mean())
            bits = ((values - cfo) * amplitude > 0).astype(np.uint8)
            return bits, cfo, amplitude

        initial = demod(56)
        if initial is None:
            return None, False
        bits, _, _ = initial
        header = whiten(np.packbits(bits[40:56], bitorder="little").tobytes(), self.whitening_channel)
        if header[0] & 15 != 7 or header[1] == 0:
            return None, False
        total_bits = 40 + (2 + header[1] + 3) * 8
        full = demod(total_bits)
        if full is None:
            return None, False
        bits, cfo, amplitude = full
        raw = np.packbits(bits[40:], bitorder="little").tobytes()
        data = whiten(raw, self.whitening_channel)
        if data[-3:] != crc24(data[:-3]):
            return None, True
        try:
            packet = parse_pdu(data[:-3], self.channel)
        except ValueError:
            self.stats["malformed_crc_valid"] += 1
            return None, False
        # FIR group delay is identical per channel and removed from timestamps.
        sample = ((self.buffer_base + start) * self.decimation
                  - (len(self.taps) - 1) / 2)
        packet.update(sample_start=sample, sample_time_s=sample / self.input_rate,
                      whitening_channel=self.whitening_channel, cfo_hz=cfo,
                      polarity=1 if amplitude > 0 else -1, sync_score=score,
                      clock_search_ppm=ppm, crc_hex=data[-3:].hex(),
                      _end_sample=self.buffer_base + start + total_bits * step - SPS)
        return packet, False
