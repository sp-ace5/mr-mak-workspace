"""WAV in/out + loudness helpers. Needs only numpy + scipy."""
import wave
import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter, resample_poly

def write_wav24(path, x, sr=48000):
    """x: float array in [-1, 1], shape (n,) or (n, ch). Writes 24-bit PCM."""
    x = np.atleast_2d(np.asarray(x, dtype=np.float64).T).T
    q = np.clip(np.round(x * 8388607.0), -8388608, 8388607).astype("<i4")
    raw = q.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()  # little-endian low 3 bytes
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(3)
        w.setframerate(sr)
        w.writeframes(raw)

def read_wav(path):
    """Returns (sr, float64 array shape (n, ch), bit_depth)."""
    with wave.open(str(path), "rb") as w:
        bits = w.getsampwidth() * 8
    sr, d = wavfile.read(str(path))   # 24-bit comes back left-justified in int32
    if d.dtype == np.int16:   x = d / 32768.0
    elif d.dtype == np.int32: x = d / 2147483648.0
    elif d.dtype == np.uint8: x = (d.astype(np.float64) - 128.0) / 128.0
    else:                     x = d.astype(np.float64)
    return sr, np.atleast_2d(x.T).T, bits

def db(v):
    return 20.0 * np.log10(max(float(v), 1e-12))

def true_peak_db(x, oversample=4):
    """Inter-sample peak estimate (BS.1770-style 4x oversampling)."""
    return db(np.max(np.abs(resample_poly(x, oversample, 1, axis=0))))

# ITU-R BS.1770 K-weighting coefficients, valid at 48 kHz (the spec requires 48 kHz masters).
_K = [
    ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]),
    ([1.0, -2.0, 1.0],                                       [1.0, -1.99004745483398, 0.99007225036621]),
]

def k_weight(x):
    for b, a in _K:
        x = lfilter(b, a, x, axis=0)
    return x

def k_rms_db(x):
    """Ungated K-weighted level of the whole file. Defined even for 30 ms clicks
    (integrated LUFS needs >= 400 ms). Use it to keep a pack's one-shots consistent."""
    y = k_weight(x)
    return -0.691 + 10.0 * np.log10(max(np.sum(np.mean(y ** 2, axis=0)), 1e-12))

def integrated_lufs(x, sr=48000):
    """Gated integrated loudness (400 ms blocks, 75% overlap, -70 abs / -10 rel gates)."""
    y = k_weight(x)
    blk, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < blk:
        return None
    z = np.array([np.sum(np.mean(y[i:i + blk] ** 2, axis=0)) for i in range(0, len(y) - blk + 1, hop)])
    lk = -0.691 + 10.0 * np.log10(np.maximum(z, 1e-12))
    z = z[lk > -70.0]
    if not len(z):
        return None
    rel = -0.691 + 10.0 * np.log10(np.mean(z)) - 10.0
    z = z[(-0.691 + 10.0 * np.log10(z)) > rel]
    return -0.691 + 10.0 * np.log10(np.mean(z))
