"""Shader + VFX-scene gates via the headless Godot harness (no GPU needed for these)."""
import json, re, subprocess

TYPE_INT, TYPE_FLOAT = 2, 3            # Variant.Type
HINT_RANGE = 1                         # PropertyHint
USAGE_GROUPING = 64 | 128 | 256        # group / category / subgroup entries, not real uniforms

def run_harness(godot_exe, harness_dir, res_paths, timeout=120):
    p = subprocess.run(
        [godot_exe, "--headless", "--path", harness_dir, "--script", "res://check.gd", "--", *res_paths],
        capture_output=True, text=True, timeout=timeout
    )
    info = {}
    for line in p.stdout.splitlines():
        if line.startswith("{"):
            d = json.loads(line)
            info[d["path"]] = d
    errors = {}
    for m in re.finditer(r"@@BEGIN (\S+)\n(.*?)@@END \1", p.stderr, re.S):
        errors[m.group(1)] = [
            l.strip() for l in m.group(2).splitlines()
            if "SHADER ERROR" in l or l.startswith("ERROR")
        ]
    return info, errors

def check(res_path, info, errors, spec):
    r = []
    def g(name, ok, measured, expected):
        r.append((name, bool(ok), str(measured), str(expected)))

    errs = errors.get(res_path, [])
    g("compiles", res_path in info and not errs, errs[:2] or "clean", "no SHADER ERROR / ERROR")
    d = info.get(res_path, {})
    if res_path.endswith(".gdshader"):
        u = [x for x in d.get("uniforms", []) if not (x.get("usage", 0) & USAGE_GROUPING)]
        scalars = [x for x in u if x["type"] in (TYPE_INT, TYPE_FLOAT)]
        unhinted = [x["name"] for x in scalars if x["hint"] != HINT_RANGE]
        g("scalar_uniforms_have_range", not unhinted, unhinted or "all hinted", "hint_range on every int/float")
        g("uniform_count", len(u) <= spec["max_uniforms"], len(u), f"<= {spec['max_uniforms']}")
        bad = [x["name"] for x in u if not re.fullmatch(spec["uniform_name_regex"], x["name"])]
        g("uniform_naming", not bad, bad or "ok", spec["uniform_name_regex"])
    if res_path.endswith(".tscn"):
        g("scene_loads", d.get("loaded", False), d.get("loaded"), True)
        g("particle_budget", d.get("particles_total", 0) <= spec["max_particles"],
          d.get("particles_total"), f"<= {spec['max_particles']}")
        g("emitter_budget", d.get("emitters", 0) <= spec["max_emitters"], d.get("emitters"), f"<= {spec['max_emitters']}")
    return r
