"""Audio gates. Each returns (gate, passed, measured, expected)."""
import numpy as np
from pipeline.audio_io import read_wav, db, true_peak_db, k_rms_db, integrated_lufs

def check(path, spec):
    sr, x, bits = read_wav(path)
    mono = x.mean(axis=1)
    n = len(mono)
    dur = n / sr
    r = []

    def g(name, ok, measured, expected):
        r.append((name, bool(ok), str(measured), str(expected)))

    g("sample_rate", sr == spec["sample_rate"], sr, spec["sample_rate"])
    g("bit_depth", bits == spec["bit_depth"], bits, spec["bit_depth"])
    g("channels", x.shape[1] == spec["channels"], x.shape[1], spec["channels"])
    lo, hi = spec["duration_s"]
    g("duration", lo <= dur <= hi, round(dur, 3), f"{lo}..{hi}")
    peak = db(np.max(np.abs(x)))
    g("not_silent", peak > -40, round(peak, 2), "> -40 dBFS")
    g("no_clipping", np.max(np.abs(x)) < 0.9999, round(peak, 2), "< 0 dBFS")
    tp = true_peak_db(x)
    g("true_peak", tp <= spec["true_peak_dbtp_max"], round(tp, 2), f"<= {spec['true_peak_dbtp_max']}")
    dc = float(abs(mono.mean()))
    g("dc_offset", dc <= spec["dc_offset_max"], f"{dc:.5f}", f"<= {spec['dc_offset_max']}")
    thresh = 10.0 ** (-60.0 / 20.0)                 # first sample above -60 dBFS
    first = int(np.argmax(np.abs(mono) > thresh))
    lead_ms = 1000.0 * first / sr
    g("lead_silence", lead_ms <= spec["lead_silence_ms_max"], round(lead_ms, 2),
      f"<= {spec['lead_silence_ms_max']} ms")
    tail = mono[-int(0.005 * sr):]                  # last 5 ms must have died away
    tail_db = db(np.max(np.abs(tail[-16:])))        # level of the very last samples
    g("tail_silent", tail_db <= spec["tail_dbfs_max"], round(tail_db, 1), f"<= {spec['tail_dbfs_max']}")
    if spec.get("loop"):                            # ambiences / loops only
        jump = abs(mono[-1] - mono[0])
        g("loop_seam_jump", jump <= spec.get("loop_seam_max", 0.01), round(float(jump), 4),
          f"<= {spec.get('loop_seam_max', 0.01)}")
        lufs = integrated_lufs(x, sr)
        tgt, tol = spec["lufs_target"], spec.get("lufs_tolerance", 1.0)
        g("integrated_lufs", lufs is not None and abs(lufs - tgt) <= tol,
          None if lufs is None else round(lufs, 1), f"{tgt} ± {tol}")
    return r, {"k_rms_db": round(k_rms_db(x), 2), "duration_s": round(dur, 3)}

def pack_consistency(levels, max_spread_db):
    """levels: {asset_id: k_rms_db} for one category. Flags the outliers, not the whole pack."""
    med = float(np.median(list(levels.values())))
    return {a: (abs(v - med) <= max_spread_db / 2.0, round(v - med, 1)) for a, v in levels.items()}
