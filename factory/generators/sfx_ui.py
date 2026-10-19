"""Procedural UI sound generator. Written once (by you + Claude), reviewed once,
then run forever: same recipe + same seed = same file. No model, no license question."""
import numpy as np
from scipy.signal import butter, sosfilt
from pipeline.audio_io import write_wav24, true_peak_db

SR = 48000

def _env(n, attack_ms, decay_ms):
    t = np.arange(n) / SR
    a = max(attack_ms / 1000.0, 1e-4)
    return np.minimum(t / a, 1.0) * np.exp(-np.maximum(t - a, 0.0) / (decay_ms / 1000.0))

def _fade_out(x, ms):
    n = int(ms / 1000.0 * SR)
    x[-n:] *= np.cos(np.linspace(0.0, np.pi / 2.0, n)) ** 2   # smooth to exactly zero
    return x

def _seg(x, ms=3):
    return _fade_out(x, ms)                               # every segment ends at zero: no click at joins

def _tone(f0, f1, dur, rng, shape="sine"):
    n = int(dur * SR)
    f = np.geomspace(f0, f1, n)                           # exponential pitch glide
    ph = 2.0 * np.pi * np.cumsum(f) / SR + rng.uniform(0.0, 2.0 * np.pi)
    if shape == "sine":
        return np.sin(ph)
    return np.tanh(3.0 * np.sin(ph)) / np.tanh(3.0)       # soft square

RECIPES = {
    # name: function(rng) -> mono float signal
    "click": lambda r: sosfilt(
        butter(4, r.uniform(2500, 4000), "hp", fs=SR, output="sos"),
        r.standard_normal(int(0.04 * SR))
    ) * _env(int(0.04 * SR), 0.3, r.uniform(4, 8)),

    "hover": lambda r: _tone(
        r.uniform(1800, 2200), r.uniform(2300, 2600), 0.06, r
    ) * _env(int(0.06 * SR), 2, 15),

    "confirm": lambda r: np.concatenate([
        _seg(_tone(f, f * 1.01, 0.09, r) * _env(int(0.09 * SR), 2, 40))
        for f in (r.uniform(640, 700), r.uniform(950, 1050))
    ]),

    "error": lambda r: np.concatenate([
        _seg(_tone(f, f * 0.97, 0.12, r, "square") * _env(int(0.12 * SR), 2, 50))
        for f in (r.uniform(330, 360), r.uniform(220, 240))
    ]),
}

def render(recipe, seed, out_path, tp_target_db=-1.0):
    rng = np.random.default_rng(seed)
    x = RECIPES[recipe](rng)
    x = sosfilt(butter(2, 20, "hp", fs=SR, output="sos"), x)          # DC blocker
    x = np.concatenate([_fade_out(x, 8), np.zeros(int(0.002 * SR))])  # 8 ms fade + 2 ms digital silence
    x *= 10.0 ** ((tp_target_db - true_peak_db(x)) / 20.0)            # normalize to true peak, not sample peak
    write_wav24(out_path, x, SR)
    return {
        "tool": "factory.sfx_ui",
        "tool_version": "1",
        "seed": seed,
        "license_id": "own-work",
        "ai_generated": 0,
        "step": "synth",
    }
