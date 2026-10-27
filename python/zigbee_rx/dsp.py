"""Local continuous IQ DC suppression, independent of the BLE process."""
import math
import numpy as np
from scipy import signal

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
