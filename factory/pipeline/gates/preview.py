"""Gates on the PNG frames the preview rig rendered (Godot Movie Maker writes numbered PNGs)."""
import pathlib
import numpy as np
from PIL import Image

def check(frame_dir, spec):
    frames = sorted(pathlib.Path(frame_dir).glob("*.png"))
    r = []
    def g(name, ok, measured, expected):
        r.append((name, bool(ok), str(measured), str(expected)))

    g("frames_written", len(frames) >= spec["min_frames"], len(frames), f">= {spec['min_frames']}")
    if not frames:
        return r
    f = [
        np.asarray(Image.open(p).convert("RGB")).astype(float) / 255.0
        for p in (frames[0], frames[len(frames) // 2], frames[-1])
    ]
    bg = np.array(spec["background_rgb"]) / 255.0
    cover = float(np.mean(np.abs(f[1] - bg).sum(axis=2) > 0.06))          # share of pixels that aren't background
    g("subject_visible", cover >= spec["min_coverage"], round(cover, 3), f">= {spec['min_coverage']}")
    magenta = float(np.mean((f[1][..., 0] > 0.9) & (f[1][..., 1] < 0.1) & (f[1][..., 2] > 0.9)))
    g("no_error_magenta", magenta < 0.01, round(magenta, 4), "< 0.01")    # missing texture / broken material
    if spec.get("animated"):
        motion = float(np.abs(f[0] - f[1]).mean())
        g("animates", motion > 0.002, round(motion, 4), "> 0.002 mean abs diff")
    if spec.get("loops"):
        seam = float(np.abs(f[0] - f[2]).mean())
        g("loop_seam", seam <= spec.get("loop_seam_max", 0.01), round(float(seam), 4), f"<= {spec.get('loop_seam_max', 0.01)}")
    return r
