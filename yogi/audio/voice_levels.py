"""Band energy for the orb, matching the browser analyser in orb.html.

Magnitudes are mapped onto the AnalyserNode default range of -100..-30 dB
and scaled to 0..1, the same range getByteFrequencyData produced.
"""

import threading
import time

import numpy as np

# Same edges as audioLook.bands in orb.html.
BANDS = ((80.0, 300.0), (300.0, 1500.0), (1500.0, 5000.0))
MIN_DB = -100.0
MAX_DB = -30.0
EMIT_INTERVAL_S = 1.0 / 30.0
# AnalyserNode bin width at its default 48 kHz capture and fftSize 1024.
BROWSER_BIN_HZ = 48000.0 / 1024.0

_lock = threading.Lock()
_listener = None
_last_emit = 0.0


def set_level_listener(fn):
    """Register the single consumer of emitted levels. None clears it."""
    global _listener
    with _lock:
        _listener = fn


def _window_levels(samples, sample_rate):
    count = samples.size
    window = np.blackman(count)
    window_sum = float(window.sum())
    if window_sum <= 0.0:
        return 0.0, 0.0, 0.0

    # One-sided magnitude, scaled so a full-scale sine peaks near 1.0.
    magnitude = np.abs(np.fft.rfft(samples * window)) * 2.0 / window_sum
    magnitude[0] *= 0.5
    if count % 2 == 0 and magnitude.size > 1:
        magnitude[-1] *= 0.5

    decibels = 20.0 * np.log10(np.maximum(magnitude, 1e-10))
    level = np.clip((decibels - MIN_DB) / (MAX_DB - MIN_DB), 0.0, 1.0)

    hz_per_bin = sample_rate / count
    bands = []
    for lo_hz, hi_hz in BANDS:
        start = max(0, int(np.floor(lo_hz / hz_per_bin)))
        end = min(level.size, int(np.ceil(hi_hz / hz_per_bin)))
        if end <= start:
            bands.append(0.0)
        else:
            bands.append(float(level[start:end].mean()))
    return tuple(bands)


def band_levels(samples, sample_rate):
    """Return (low, mid, high) in 0..1 for one block of mono float audio.

    Windows are sized so each bin is about as wide as the browser analyser,
    otherwise a single tone is averaged down to nothing across a fine FFT.
    """
    samples = np.asarray(samples, dtype=np.float64).reshape(-1)
    if samples.size < 16 or sample_rate <= 0:
        return 0.0, 0.0, 0.0

    width = max(32, int(round(sample_rate / BROWSER_BIN_HZ)))
    if samples.size <= width:
        return _window_levels(samples, sample_rate)

    starts = range(0, samples.size - width + 1, width)
    starts = list(starts)[-8:]
    total = np.zeros(3)
    for start in starts:
        total += _window_levels(samples[start:start + width], sample_rate)
    return tuple((total / len(starts)).tolist())


def emit_levels(samples, sample_rate):
    """Notify the listener at about 30 Hz. Safe to call from an audio callback."""
    global _last_emit
    now = time.perf_counter()
    with _lock:
        listener = _listener
        if listener is None or now - _last_emit < EMIT_INTERVAL_S:
            return
        _last_emit = now

    low, mid, high = band_levels(samples, sample_rate)
    listener(low, mid, high)
