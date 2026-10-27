"""Continuous IQ -> differential chips -> standard DSSS -> PHR/FCS.

Supports direct phase-chip observation (BlueBee) and MSK-equivalent O-QPSK
observation. Both despread only references derived from standard CHIP_MAP.
"""
from __future__ import annotations
from collections import Counter
import math
import numpy as np
from scipy import signal

from zigbee_protocol import REFERENCE_PROFILES, frame_payload, symbols_to_bytes

OUTPUT_RATE = 4000000
CHIP_RATE = 2000000
SPS = OUTPUT_RATE // CHIP_RATE
MAX_FRAME_CHIPS = (6 + 127) * 64


class ZigBeeDecoder:
    def __init__(self, sample_rate=8000000, center_hz=2480000000,
                 frequency_hz=2480000000, demod="auto", symbol_order="auto",
                 cutoff_hz=1300000, cfo_hz=0, soft_retry=True,
                 preamble_max_distance=80):
        if sample_rate not in (4000000, 8000000, 12000000, 16000000, 20000000):
            raise ValueError("sample rate must be 4/8/12/16/20 Msps")
        if demod not in ("auto", "phase", "oqpsk") or symbol_order not in ("auto", "project", "ieee"):
            raise ValueError("invalid demodulation or symbol order")
        if not math.isfinite(cutoff_hz) or not 700000 <= cutoff_hz <= 1600000:
            raise ValueError("channel cutoff must be 700000..1600000 Hz")
        if abs(frequency_hz - center_hz) + cutoff_hz + 200000 >= sample_rate / 2:
            raise ValueError("requested channel does not fit capture bandwidth")
        if not math.isfinite(cfo_hz) or abs(cfo_hz) > 300000:
            raise ValueError("CFO correction must be within +/-300000 Hz")
        self.input_rate = sample_rate
        self.offset_hz = frequency_hz - center_hz + cfo_hz
        self.cfo_hz = cfo_hz
        self.decimation = sample_rate // OUTPUT_RATE
        self.taps = signal.firwin(16 * self.decimation + 1, cutoff_hz, fs=sample_rate)
        self.history = np.zeros(len(self.taps) - 1, np.complex64)
        self.input_samples = 0
        self.buffer_base = 0
        self.buffer = np.empty(0, np.complex64)
        self.cursor = 1
        self.last_end = -1
        self.profiles = list(REFERENCE_PROFILES) if demod == "auto" else [demod]
        self.orders = ["project", "ieee"] if symbol_order == "auto" else [symbol_order]
        self.soft_retry = soft_retry
        self.max_distance = preamble_max_distance
        self.stats = Counter()
        self.oscillator = None
        if self.offset_hz and self.offset_hz == int(self.offset_hz):
            period = sample_rate // math.gcd(sample_rate, abs(int(self.offset_hz)))
            if period <= 65536:
                self.oscillator = np.exp(-2j * np.pi * self.offset_hz * np.arange(period) / sample_rate).astype(np.complex64)

    def feed(self, iq, final=False):
        iq = np.asarray(iq, np.complex64)
        count = len(iq)
        if count:
            if self.offset_hz:
                positions = np.arange(count) + self.input_samples
                oscillator = (self.oscillator[positions % len(self.oscillator)] if self.oscillator is not None
                              else np.exp(-2j * np.pi * self.offset_hz * positions / self.input_rate))
                iq = iq * oscillator
            first = (-self.input_samples) % self.decimation
            combined = np.concatenate((self.history, iq))
            filtered = signal.upfirdn(self.taps, combined[first:], down=self.decimation)
            warm = len(self.history) // self.decimation
            available = max(0, (count - first + self.decimation - 1) // self.decimation)
            self.buffer = np.concatenate((self.buffer, filtered[warm:warm + available].astype(np.complex64)))
            self.history = combined[-len(self.history):].copy()
            self.input_samples += count
        packets = self._scan(final)
        drop = max(0, self.cursor - self.buffer_base - 1)
        if drop:
            self.buffer = self.buffer[drop:]
            self.buffer_base += drop
        return packets

    def _scan(self, final):
        n = len(self.buffer)
        limit = n - ((8 * 64 if final else MAX_FRAME_CHIPS) * SPS)
        if limit < self.cursor - self.buffer_base:
            return []
        phase = np.angle(self.buffer[1:] * self.buffer[:-1].conj()) * OUTPUT_RATE / (2 * np.pi)
        indices = np.arange(len(phase), dtype=float)
        candidates = []
        for offset in range(SPS):
            values = phase[offset::SPS]
            hard = np.where(values >= 0, 1., -1.).astype(np.float32)
            for profile in self.profiles:
                refs = REFERENCE_PROFILES[profile]
                if len(hard) < 256:
                    continue
                corr = signal.correlate(hard, refs[0], mode="valid", method="direct")
                size = len(hard) - 256 + 1
                total = sum(corr[32 * i:32 * i + size] for i in range(8))
                effective = int(np.count_nonzero(refs[0])) * 8
                distance = (effective - np.abs(total)) / 2
                for hit in np.flatnonzero(distance <= self.max_distance):
                    start = offset + int(hit) * SPS
                    absolute = self.buffer_base + start
                    if absolute < self.cursor or start > limit or absolute < self.last_end:
                        continue
                    polarity = 1 if total[hit] >= 0 else -1
                    candidates.append((start, float(distance[hit]), profile, polarity))
        # Group timing/profile hypotheses of one physical preamble.
        groups = []
        for candidate in sorted(candidates):
            if not groups or candidate[0] - groups[-1][0][0] > 2 * SPS:
                groups.append([])
            groups[-1].append(candidate)
        packets = []
        for group in groups:
            if self.buffer_base + group[0][0] < self.last_end:
                continue
            self.stats["preamble_candidates"] += 1
            ranked = sorted(group, key=lambda item: item[1])
            result = None
            saw_fcs_failure = False
            for soft in ([False, True] if self.soft_retry else [False]):
                if soft and not saw_fcs_failure:
                    break
                for start, distance, profile, polarity in ranked:
                    for ppm in (0, -80, 80):
                        packet, fcs_failed = self._decode(phase, indices, start, profile, polarity,
                                                          ppm, soft, distance)
                        saw_fcs_failure |= fcs_failed
                        if packet is not None:
                            result = packet
                            break
                    if result is not None:
                        break
                if result is not None:
                    break
            if result is None:
                self.stats["fcs_failure_candidates" if saw_fcs_failure else "rejected_candidates"] += 1
                continue
            self.last_end = result.pop("_end_sample")
            packets.append(result)
            self.stats["fcs_valid_packets"] += 1
            self.stats[result["decode_method"] + "_packets"] += 1
        self.cursor = self.buffer_base + limit + 1
        return packets

    def _decode(self, phase, indices, start, profile, polarity, ppm, soft, preamble_distance):
        step = SPS * (1 + ppm * 1e-6)
        refs = REFERENCE_PROFILES[profile]
        prefix = np.tile(refs[0], 8) * polarity

        def symbols(count):
            positions = start + np.arange(count * 32) * step
            if positions[-1] >= len(phase):
                return None
            values = np.interp(positions, indices, phase)
            # Balanced direct chips / linear fit of the known OQPSK preamble.
            mask = prefix != 0
            a = prefix[mask]
            b = values[:256][mask]
            slope = np.dot(a - a.mean(), b - b.mean()) / max(np.sum((a - a.mean()) ** 2), 1)
            bias = b.mean() - slope * a.mean()
            corrected = (values - bias) * polarity
            chips = corrected if soft else np.where(corrected >= 0, 1., -1.)
            scores = chips.reshape(-1, 32).astype(np.float32) @ refs.T
            return np.argmax(scores, axis=1), corrected, float(bias), scores

        header = symbols(12)
        if header is None:
            return None, False
        for order in self.orders:
            frame_header = symbols_to_bytes(header[0], order)
            if frame_header[:5] != bytes.fromhex("00000000a7") or not 2 <= frame_header[5] <= 127:
                continue
            frame_bytes = 6 + frame_header[5]
            result = symbols(frame_bytes * 2)
            if result is None:
                return None, False
            decoded_symbols, values, bias, scores = result
            frame = symbols_to_bytes(decoded_symbols, order)
            try:
                payload = frame_payload(frame)
            except ValueError:
                return None, True
            sample = (self.buffer_base + start) * self.decimation - (len(self.taps) - 1) / 2
            selected = refs[decoded_symbols]
            distances = np.count_nonzero((values.reshape(-1, 32) >= 0) != (selected > 0), axis=1)
            if profile == "oqpsk":
                distances -= (values.reshape(-1, 32)[:, 0] >= 0) != (selected[:, 0] > 0)
            return {"frame_hex": frame.hex(), "payload_hex": payload.hex(), "payload_len": len(payload),
                    "phr_length": frame[5], "fcs_hex": frame[-2:].hex(), "fcs_ok": True,
                    "sample_start": sample, "sample_time_s": sample / self.input_rate,
                    "phy_observation": profile, "dsss_codebook": "IEEE802.15.4_standard",
                    "symbol_order": order, "polarity": polarity, "clock_search_ppm": ppm,
                    "decode_method": "soft_dsss" if soft else "hard_dsss",
                    "preamble_distance": preamble_distance, "mean_chip_distance": float(distances.mean()),
                    "estimated_cfo_hz": bias + self.cfo_hz,
                    "_end_sample": self.buffer_base + start + frame_bytes * 64 * step - SPS}, False
        return None, False
