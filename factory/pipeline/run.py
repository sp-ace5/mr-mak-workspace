"""The spine.
  python -m pipeline.run init | build | approve | report | package --pack spec/packs/<id>.yaml
Kill it any time; `build` picks up where it stopped (state lives in factory.db, committed per asset).
`approve` = you listened / looked and you're happy: passed assets are frozen and never rebuilt.
`package` = verifies report exits 0, bundles approved files into dist/<pack>/<pack>.zip ready for itch.io."""

import argparse, hashlib, json, os, pathlib, re, shutil, sqlite3, subprocess, sys, traceback, uuid, zipfile
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = pathlib.Path(os.environ.get("FACTORY_DB") or ROOT / "factory.db")

JSON = False                      # --json: one event object per stdout line instead of human text

def emit(text, event="log", **fields):
    try:
        print(json.dumps({"event": event, "msg": text, **fields}) if JSON else text, flush=True)
    except OSError:          # the desktop service went away mid-job: finish the work, nobody is reading anyway
        pass

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

def merge(base, over):
    """Dicts merge key by key; anything else in `over` replaces."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    return {**base, **{k: merge(base.get(k), v) for k, v in over.items()}}

def global_spec():
    """global.yaml, overlaid with the gitignored global.local.yaml (this machine's tool paths, itch user)."""
    g = yaml.safe_load((ROOT / "spec" / "global.yaml").read_text(encoding="utf-8"))
    local = ROOT / "spec" / "global.local.yaml"
    g = merge(g, yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.exists() else g
    # A relative tool path (one with a folder in it) means "relative to factory/", whatever the caller's cwd.
    # A bare name such as "butler" is left for PATH.
    for name, value in (g.get("tools") or {}).items():
        if isinstance(value, str) and value and re.search(r"[\\/]", value) and not pathlib.Path(value).is_absolute():
            g["tools"][name] = str((ROOT / value).resolve())
    return g

# ---------- producers: (asset row, params, attempt, out_dir) -> (output_path, provenance dict) ----------

def produce_ui_sfx(row, params, attempt, out_dir):
    from generators.sfx_ui import render
    seed = params["seed"] + 1000 * (attempt - 1)          # a retry must not repeat the failed seed
    out = out_dir / f"{row['name']}.wav"
    return out, render(params["recipe"], seed, out)

PROV_KEYS = ("tool_version", "model", "model_version", "seed", "prompt_sha256", "service_plan", "cost_usd",
             "external_ref")

def inbox_fingerprint(pack_id, name):
    src = ROOT / "inbox" / pack_id / f"{name}.glb"
    if not src.exists():
        return None
    h = hashlib.sha256(src.read_bytes())
    side = src.with_suffix(".json")
    if side.exists():
        h.update(side.read_bytes())
    return h.hexdigest()

def produce_inbox_mesh(row, params, attempt, out_dir):
    """Hand-off from any outside tool (3DGenStudio, Tripo/Meshy web app, Blender by hand): drop <name>.glb and
    <name>.json (provenance sidecar) into inbox/<pack_id>/. No GLB yet -> wait. No sidecar -> license 'unknown',
    which global.yaml marks commercial_ok: 0, so the report refuses to ship it."""
    src = ROOT / "inbox" / row["pack_id"] / f"{row['name']}.glb"
    if not src.exists():
        return None, "not delivered yet"
    params["inbox_fp"] = inbox_fingerprint(row["pack_id"], row["name"])
    side = src.with_suffix(".json")
    prov = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    out = out_dir / src.name
    shutil.copy2(src, out)
    return out, {"step": "generate", "tool": prov.get("tool", "unknown"), "license_id": prov.get("license_id", "unknown"),
                 "ai_generated": int(prov.get("ai_generated", 1)), **{k: prov[k] for k in PROV_KEYS if k in prov}}

HARNESS = ROOT / "godot_harness"

def produce_shader(row, params, attempt, out_dir):
    """Shader source lives in shaders/<pack>/<name>.gdshader (drafted with Claude, tuned by you). It is copied
    into the harness at res://addons/<pack>/shaders/, the path it will have in a buyer's project."""
    src = ROOT / "shaders" / row["pack_id"] / f"{row['name']}.gdshader"
    out = HARNESS / "addons" / row["pack_id"] / "shaders" / src.name
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    return out, {"step": "author", "tool": "factory.shader_src", "model": "claude-opus-5-5",
                 "license_id": "own-work", "ai_generated": 1}

PRODUCERS = {"ui_sfx": produce_ui_sfx, "inbox_mesh": produce_inbox_mesh, "shader": produce_shader}
INBOX_KINDS = {"inbox_mesh"}      # made outside the pipeline: retried only when a new export arrives

# ---------- gates: (output_path, pack spec, asset params) -> (results, metrics) ----------

def gate_ui_sfx(path, pack, params):
    from pipeline.gates.audio import check
    return check(path, pack["budgets"]["audio"])

def gate_inbox_mesh(path, pack, params):
    from pipeline.gates.mesh import check
    report_path = pathlib.Path(path).with_suffix(".report.json")
    subprocess.run([global_spec()["tools"]["blender"], "-b", "--factory-startup", "--python",
                    str(ROOT / "blender" / "inspect_glb.py"), "--", str(path), str(report_path)],
                   check=True, capture_output=True, timeout=600)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return check(report, pack["budgets"]["mesh"], lod=params.get("lod", 0)), \
        {"tris": sum(o["tris"] for o in report["objects"])}

def gate_shader(path, pack, params):
    """Headless compile + uniform rules, then a turntable render in every renderer (needs the GPU, opens a window)."""
    from pipeline.gates import godot, preview
    exe = global_spec()["tools"]["godot"]
    res = "res://" + pathlib.Path(path).relative_to(HARNESS).as_posix()
    info, errors = godot.run_harness(exe, str(HARNESS), [res])
    results = godot.check(res, info, errors, pack["budgets"]["shader"])
    pv = pack["budgets"]["preview"]
    for rnd in pv["renderers"]:
        frames = ROOT / "build" / pack["pack_id"] / "preview" / pathlib.Path(path).stem / rnd
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir(parents=True)
        subprocess.run([exe, "--path", str(HARNESS), "--rendering-method", rnd, "--resolution", "512x512",
                        "--write-movie", str(frames / "f.png"), "--fixed-fps", "30", "--quit-after", str(pv["frames"]),
                        "res://preview.tscn", "--", res], capture_output=True, timeout=300)
        results += [(f"{n}_{rnd}", *rest) for n, *rest in preview.check(frames, pv)]
    return results, {"uniforms": len(info.get(res, {}).get("uniforms", []))}

GATES = {"ui_sfx": gate_ui_sfx, "inbox_mesh": gate_inbox_mesh, "shader": gate_shader}

# ---------- commands ----------

def cmd_init(con, pack):
    sync_licenses(con)
    emit(f"db ready: {DB}", "db", path=str(DB))

def sync_licenses(con):
    """Schema plus global.yaml's license table. Build runs it too: the Studio never runs init, and a license
    edit must reach the blocker check (the edit also changes the recipe hash, so publish waits for that build)."""
    con.executescript((ROOT / "pipeline" / "schema.sql").read_text(encoding="utf-8"))
    g = global_spec()
    for lic in g["licenses"]:
        con.execute("INSERT INTO licenses VALUES (:license_id,:commercial_ok,:needs_attribution,:conditions,"
                    ":source_url,:text_sha256,:checked_on) ON CONFLICT(license_id) DO UPDATE SET "
                    "commercial_ok=excluded.commercial_ok, needs_attribution=excluded.needs_attribution, "
                    "conditions=excluded.conditions, source_url=excluded.source_url, "
                    "text_sha256=excluded.text_sha256, checked_on=excluded.checked_on",
                    {"needs_attribution": 0, "conditions": None, "source_url": None, "text_sha256": None, **lic})
    con.commit()

def recipe_hash(spec_path):
    """Spec + generator + gate code. Change any of them and the pack rebuilds (except approved assets)."""
    h = hashlib.sha256(pathlib.Path(spec_path).read_bytes())
    pid = yaml.safe_load(pathlib.Path(spec_path).read_text(encoding="utf-8"))["pack_id"]
    # All pipeline code (run.py, audio_io, gates) and the Godot harness sources decide gate results too.
    # Generated harness folders (.godot, addons, pack) and import caches are skipped.
    # ponytail: the Godot executable's version is not hashed; add it if an engine upgrade ever changes results.
    harness = [p for p in (ROOT / "godot_harness").rglob("*") if p.is_file()
               and not {".godot", "addons", "pack"} & set(p.relative_to(ROOT / "godot_harness").parts)
               and p.suffix not in (".uid", ".import")]
    for f in sorted((ROOT / "generators").glob("*.py")) + sorted((ROOT / "pipeline").rglob("*.py")) \
            + sorted(harness) + sorted((ROOT / "shaders" / pid).glob("*")):
        h.update(f.relative_to(ROOT).as_posix().encode() + b"\0" + f.read_bytes())
    # The license table decides which provenance blocks a sale.
    h.update(json.dumps(global_spec().get("licenses", []), sort_keys=True).encode())
    return h.hexdigest()

def register(con, pack, spec_path):
    h = recipe_hash(spec_path)
    old = con.execute("SELECT spec_hash FROM packs WHERE pack_id=?", (pack["pack_id"],)).fetchone()
    changed = bool(old) and old["spec_hash"] != h
    con.execute("INSERT INTO packs (pack_id, category, spec_path, spec_hash, engine_target) VALUES (?,?,?,?,?) "
                "ON CONFLICT(pack_id) DO UPDATE SET spec_hash=excluded.spec_hash, spec_path=excluded.spec_path, "
                "engine_target=excluded.engine_target",
                (pack["pack_id"], pack["category"], str(spec_path), h, pack.get("engine_target")))
    names = []
    for grp in pack["assets"]:
        for v in range(grp.get("variations", 1)):
            name = grp["name"].format(var=v + 1)
            names.append(name)
            params = {k: val for k, val in grp.items() if k not in ("name", "variations", "kind")}
            params["seed"] = grp.get("seed", 1) + v
            con.execute("INSERT INTO assets (asset_id, pack_id, kind, name, params_json) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(asset_id) DO " + ("UPDATE SET kind=excluded.kind, params_json=excluded.params_json, "
                        "status='pending', attempts=0 WHERE status NOT IN ('approved')" if changed else "NOTHING"),
                        (f"{pack['pack_id']}/{name}", pack["pack_id"], grp["kind"], name, json.dumps(params)))
    # assets dropped from the spec are kept for history but never shipped
    placeholders = ",".join("?" * len(names))
    con.execute(f"UPDATE assets SET status='rejected' WHERE pack_id=? AND name NOT IN ({placeholders})",
                (pack["pack_id"], *names))
    con.commit()

def refresh_inbox(con, pack):
    """A new export (mesh or sidecar) re-opens an inbox asset with fresh attempts, unless you approved it."""
    for r in con.execute("SELECT asset_id, kind, name, status, params_json FROM assets WHERE pack_id=? "
                         "AND status IN ('passed','failed')", (pack["pack_id"],)).fetchall():
        if r["kind"] in INBOX_KINDS:
            fp = inbox_fingerprint(pack["pack_id"], r["name"])
            if fp and fp != json.loads(r["params_json"]).get("inbox_fp"):
                con.execute("UPDATE assets SET status='pending', attempts=0 WHERE asset_id=?", (r["asset_id"],))
    con.commit()

def cmd_build(con, pack, spec_path, max_attempts=3):
    sync_licenses(con)
    register(con, pack, spec_path)
    refresh_inbox(con, pack)
    recipe = recipe_hash(spec_path)
    out_dir = ROOT / "build" / pack["pack_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = con.execute("SELECT * FROM assets WHERE pack_id=? AND status IN ('pending','failed') AND attempts<?",
                       (pack["pack_id"], max_attempts)).fetchall()
    todo = [r for r in rows if r["status"] == "pending" or r["kind"] not in INBOX_KINDS]
    for r in rows:
        if r not in todo:
            emit(f"WAIT  {r['name']}  (failed; fix it where you made it and re-export)", "wait", asset=r["name"])
    known = {r[0] for r in con.execute("SELECT license_id FROM licenses")}
    for row in todo:
        attempt = row["attempts"] + 1
        params = json.loads(row["params_json"])
        try:
            build_one(con, pack, row, params, attempt, out_dir, recipe, known)
        except Exception as e:      # one broken generator or gate fails its own asset, not the whole build
            con.rollback()          # drop this attempt's half-written provenance
            msg = f"{type(e).__name__}: {e}"[:300]
            con.execute("INSERT INTO gate_results (asset_id, attempt, recipe, gate, passed, measured, expected) "
                        "VALUES (?,?,?,?,0,?,?)", (row["asset_id"], attempt, recipe, "gate_error", msg, "no exception"))
            con.execute("UPDATE assets SET status='failed', attempts=?, updated_at=datetime('now') WHERE asset_id=?",
                        (attempt, row["asset_id"]))
            con.commit()
            emit(f"FAIL  {row['name']}  gate_error={msg}", "gate", asset=row["name"], ok=False,
                 failed=[{"gate": "gate_error", "measured": msg, "expected": "no exception"}])
    pack_level_gates(con, pack, recipe)

def build_one(con, pack, row, params, attempt, out_dir, recipe, known):
    """Produce one asset, record its provenance, run its gates and store the verdict."""
    out, prov = PRODUCERS[row["kind"]](row, params, attempt, out_dir)
    if out is None:                                 # nothing new to check; attempt not used up
        emit(f"WAIT  {row['name']}  ({prov})", "wait", asset=row["name"])
        return
    if prov["license_id"] not in known:            # a typo or a license nobody has reviewed: block it
        prov["license_id"] = "unknown"
    out_sha, run_id = sha256(out), uuid.uuid4().hex
    con.execute("INSERT INTO provenance (asset_id, run_id, step, tool, tool_version, model, model_version, seed, "
                "prompt_sha256, service_plan, license_id, ai_generated, cost_usd, external_ref, output_sha256) "
                "VALUES (:a,:run,:step,:tool,:tool_version,:model,:model_version,:seed,:prompt_sha256,"
                ":service_plan,:license_id,:ai_generated,:cost_usd,:external_ref,:sha)",
                {"model": None, "model_version": None, "prompt_sha256": None, "service_plan": None,
                 "cost_usd": 0, "external_ref": None, "tool_version": None, "seed": None,
                 **prov, "a": row["asset_id"], "run": run_id, "sha": out_sha})
    results, metrics = GATES[row["kind"]](out, pack, params)
    con.executemany("INSERT INTO gate_results (asset_id, attempt, recipe, gate, passed, measured, expected) "
                    "VALUES (?,?,?,?,?,?,?)", [(row["asset_id"], attempt, recipe, *res) for res in results])
    ok = all(res[1] for res in results)
    con.execute("UPDATE assets SET status=?, attempts=?, output_path=?, output_sha256=?, run_id=?, "
                "params_json=?, updated_at=datetime('now') WHERE asset_id=?",
                ("passed" if ok else "failed", attempt, str(out), out_sha, run_id,
                 json.dumps({**params, "metrics": metrics}), row["asset_id"]))
    con.commit()                        # commit per asset = resumable
    failed = [{"gate": n, "measured": m, "expected": e} for n, p, m, e in results if not p]
    emit(f"{'PASS' if ok else 'FAIL'}  {row['name']}  " + ", ".join(f"{f['gate']}={f['measured']}" for f in failed),
         "gate", asset=row["name"], ok=ok, failed=failed)

def pack_level_gates(con, pack, recipe):
    """Gates that only make sense across the whole pack (consistency, duplicates)."""
    spread = pack["budgets"].get("audio", {}).get("pack_level_spread_db")
    if not spread:
        return
    from pipeline.gates.audio import pack_consistency
    rows = con.execute("SELECT asset_id, attempts, params_json FROM assets WHERE pack_id=? "
                       "AND status IN ('passed','approved')", (pack["pack_id"],)).fetchall()
    by_recipe = {}
    for r in rows:
        p = json.loads(r["params_json"])
        by_recipe.setdefault(p.get("recipe"), {})[r["asset_id"]] = (p["metrics"]["k_rms_db"], r["attempts"])
    for _name, items in by_recipe.items():
        res = pack_consistency({a: v[0] for a, v in items.items()}, spread)
        for a, (ok, dev) in res.items():
            con.execute("INSERT INTO gate_results (asset_id, attempt, recipe, gate, passed, measured, expected) "
                        "VALUES (?,?,?,?,?,?,?)", (a, items[a][1], recipe, "pack_level_consistency", int(ok),
                                                   f"{dev:+} dB vs median", f"within ±{spread / 2} dB"))
            if not ok:                       # approved assets are frozen; only fresh ones get sent back
                con.execute("UPDATE assets SET status='failed' WHERE asset_id=? AND status='passed'", (a,))
    con.commit()

def cmd_approve(con, pack, spec_path, names=None):
    # "passed" only means something under the current recipe: approving before a rebuild would freeze
    # assets that were never checked against the new budgets, gates or licenses.
    row = con.execute("SELECT spec_hash FROM packs WHERE pack_id=?", (pack["pack_id"],)).fetchone()
    if not row or row["spec_hash"] != recipe_hash(spec_path):
        reason = "spec, generators, gates or licenses changed since the last build: rebuild before approving"
        emit(f"APPROVE REFUSED: {reason}", "refused", reason=reason)
        return 1
    q = "UPDATE assets SET status='approved' WHERE pack_id=? AND status='passed'"
    args = [pack["pack_id"]]
    if names:
        placeholders = ",".join("?" * len(names))
        q += f" AND name IN ({placeholders})"
        args += names
    n = con.execute(q, args).rowcount
    con.commit()
    emit(f"approved {n} asset(s)", "approved", count=n)
    return 0

def cmd_report(con, pack, write=True):
    pid = pack["pack_id"]
    assets = con.execute("SELECT * FROM assets WHERE pack_id=? AND status!='rejected' ORDER BY name", (pid,)).fetchall()
    blockers = con.execute("SELECT b.* FROM v_license_blockers b JOIN assets a USING (asset_id) "
                           "WHERE a.pack_id=?", (pid,)).fetchall()
    prov = con.execute("SELECT p.tool, p.model, p.license_id, MAX(p.ai_generated) ai, COUNT(DISTINCT p.asset_id) n "
                       "FROM provenance p JOIN assets a ON a.asset_id = p.asset_id AND a.run_id = p.run_id "
                       "WHERE a.pack_id=? AND a.status != 'rejected' "
                       "GROUP BY p.tool, p.model, p.license_id", (pid,)).fetchall()
    passed = [a for a in assets if a["status"] in ("passed", "approved")]
    ai_tools = [f"{p['tool']}{' / ' + p['model'] if p['model'] else ''}" for p in prov if p["ai"]]
    lines = [f"# Verify report — {pid}", "",
             f"- Assets: {len(passed)}/{len(assets)} pass every gate",
             f"- License blockers: {len(blockers)} (must be 0 to ship)",
             f"- Engine target: {pack.get('engine_target', 'n/a')}", "", "## Disclosure", "",
             ("Generative AI was used for: " + ", ".join(ai_tools) + ".") if ai_tools
             else "No generative-AI model produced any file in this pack.",
             pack.get("disclosure", {}).get("text", ""), "", "## Per-asset results", "",
             "| Asset | Status | Attempts | Failed gates (last attempt) |", "|---|---|---|---|"]
    for a in assets:
        bad = con.execute("SELECT g.gate, g.measured, g.expected FROM gate_results g JOIN packs p "
                          "ON p.pack_id=? AND g.recipe=p.spec_hash WHERE g.asset_id=? AND g.attempt=? AND g.passed=0",
                          (pid, a["asset_id"], a["attempts"])).fetchall()
        lines.append(f"| {a['name']} | {a['status']} | {a['attempts']} | "
                     + ("; ".join(f"{b['gate']}: {b['measured']} (want {b['expected']})" for b in bad) or "—") + " |")
    ok = 0 if not blockers and len(passed) == len(assets) else 1
    if not write:                    # publish --dry-run: the same verdict, nothing written
        emit(f"report: {len(passed)}/{len(assets)} passed, {len(blockers)} license blockers", "report",
             passed=len(passed), total=len(assets), blockers=len(blockers))
        return ok
    out = ROOT / "dist" / pid
    out.mkdir(parents=True, exist_ok=True)
    (out / "VERIFY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    wiki_raw = global_spec().get("paths", {}).get("wiki_raw")
    if wiki_raw:                     # the LLM wiki ingests this; the database stays the source of truth
        (ROOT / wiki_raw).mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "VERIFY.md", ROOT / wiki_raw / f"{pid}.md")
    manifest = [{"name": a["name"], "kind": a["kind"], "file": pathlib.Path(a["output_path"]).name,
                 "sha256": a["output_sha256"], **json.loads(a["params_json"]).get("metrics", {})} for a in passed]
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    emit(f"wrote {out / 'VERIFY.md'}  ({len(passed)}/{len(assets)} passed, {len(blockers)} license blockers)", "report",
         path=str(out / "VERIFY.md"), passed=len(passed), total=len(assets), blockers=len(blockers))
    return ok

def godot_randomizers(stage_dir, pid):
    """Build AudioStreamRandomizer .tres files in the harness at res://addons/<pid>/, the same path the zip
    unpacks to in a buyer's project, so the .wav references resolve there unchanged."""
    godot = global_spec()["tools"]["godot"]
    proj = ROOT / "godot_harness"
    work = proj / "addons" / pid
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for wav in stage_dir.glob("*.wav"):
        shutil.copy2(wav, work / wav.name)
    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], check=True, capture_output=True, timeout=600)
    p = subprocess.run([godot, "--headless", "--path", str(proj), "--script", "res://make_randomizers.gd", "--",
                        f"res://addons/{pid}"], check=True, capture_output=True, text=True, timeout=600)
    tres = sorted(work.glob("*.tres"))
    if not tres or "err=0" not in p.stdout or any("err=0" not in l for l in p.stdout.splitlines() if "err=" in l):
        raise RuntimeError(f"make_randomizers failed:\n{p.stdout}\n{p.stderr}")
    for t in tres:
        shutil.copy2(t, stage_dir / t.name)
    emit(f"randomizers: {', '.join(t.name for t in tres)}")

UNIFORM = re.compile(r"^\s*uniform\s+(\w+)\s+(\w+)\s*(?::\s*([^=;]+?))?\s*(?:=\s*([^;]+?))?\s*;", re.M)

def shader_readme(pack, shader_files):
    """README with one uniform table per shader, parsed from the source (header comment = description)."""
    pid = pack["pack_id"]
    rnd = ", ".join(pack["budgets"]["preview"]["renderers"])
    out = [f"# {pid}", "", pack.get("disclosure", {}).get("text", ""), "",
           f"**Verified on Godot {pack.get('engine_target', '').removeprefix('godot-')}:** every shader compiles headless "
           f"and renders without errors in {rnd}. Full gate results: `VERIFY.md`.", "",
           "## Install", "", f"Copy `addons/{pid}/` into your project. Open `demo/demo.tscn` to try every shader "
           "with live sliders. Apply a shader by creating a `ShaderMaterial` and dragging the `.gdshader` onto it.", ""]
    for f in shader_files:
        src = f.read_text(encoding="utf-8")
        desc = " ".join(l.lstrip("/ ").strip() for l in src.splitlines() if l.startswith("//"))
        out += [f"## {f.stem}", "", desc, "", "| Uniform | Type | Range / hint | Default |", "|---|---|---|---|"]
        for typ, name, hint, default in UNIFORM.findall(src):
            m = re.search(r"hint_range\(([^)]*)\)", hint)
            out.append(f"| `{name}` | {typ} | {m.group(1).replace(' ', '') if m else hint.strip() or '—'} | "
                       f"`{default.strip() or '—'}` |")
        out.append("")
    return "\n".join(out)

def shader_extras(stage_dir, pack):
    """README + demo scene inside the addon; web demo next to it in dist/<pack>/web_demo."""
    pid = pack["pack_id"]
    godot = global_spec()["tools"]["godot"]
    work = HARNESS / "addons" / pid
    (work / "demo").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HARNESS / "demo" / "demo.gd", work / "demo" / "demo.gd")
    p = subprocess.run([godot, "--headless", "--path", str(HARNESS), "--script", "res://build_demo.gd", "--",
                        f"res://addons/{pid}"], capture_output=True, text=True, timeout=600)
    if "err=0" not in p.stdout:
        raise RuntimeError(f"build_demo failed:\n{p.stdout}\n{p.stderr}")
    shutil.copytree(work / "demo", stage_dir / "demo")
    (stage_dir / "README.md").write_text(shader_readme(pack, sorted((stage_dir / "shaders").glob("*.gdshader"))),
                                         encoding="utf-8")
    web_demo(stage_dir, pack, godot)

def export_template(engine_target):
    """Where the Godot editor installs export templates on this OS, for engine_target 'godot-X.Y'."""
    home = pathlib.Path.home()
    if sys.platform == "win32":
        data = pathlib.Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "Godot"
    elif sys.platform == "darwin":
        data = home / "Library" / "Application Support" / "Godot"
    else:
        data = pathlib.Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "godot"
    ver = engine_target.removeprefix("godot-") + ".stable"
    return data / "export_templates" / ver / "web_nothreads_release.zip"

def web_demo(stage_dir, pack, godot):
    """Exports demo.tscn for the browser (gl_compatibility, no threads, so itch.io needs no special headers)."""
    pid = pack["pack_id"]
    tpl = export_template(pack.get("engine_target", "godot-4.5"))
    if not tpl.exists():
        emit(f"SKIP web demo: no export templates at {tpl.parent}", "skip")
        return
    proj = ROOT / "build" / pid / "web"
    if proj.exists():
        shutil.rmtree(proj)
    shutil.copytree(stage_dir, proj / "addons" / pid)
    (proj / "project.godot").write_text(
        f'config_version=5\n\n[application]\nconfig/name="{pid} demo"\n'
        f'run/main_scene="res://addons/{pid}/demo/demo.tscn"\n\n[rendering]\n'
        'renderer/rendering_method="gl_compatibility"\nrenderer/rendering_method.mobile="gl_compatibility"\n',
        encoding="utf-8")
    (proj / "export_presets.cfg").write_text(
        '[preset.0]\n\nname="Web"\nplatform="Web"\nrunnable=true\nexport_filter="all_resources"\n'
        'export_path=""\n\n[preset.0.options]\n\nvariant/thread_support=false\n', encoding="utf-8")
    out = ROOT / "dist" / pid / "web_demo"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, timeout=600)
    p = subprocess.run([godot, "--headless", "--path", str(proj), "--export-release", "Web", str(out / "index.html")],
                       capture_output=True, text=True, timeout=600)
    if not (out / "index.html").exists():
        raise RuntimeError(f"web export failed:\n{p.stdout}\n{p.stderr}")
    zip_path = out.parent / f"{pid}_web.zip"          # itch.io: upload as HTML, "played in the browser"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out.iterdir():
            zf.write(f, f.name)
    emit(f"web demo: {zip_path}", "web_demo", path=str(zip_path))

def cmd_package(con, pack):
    """Verifies report is 0, then packages all approved/passed files + VERIFY.md + manifest.json into dist/<id>/<id>.zip."""
    if cmd_report(con, pack) != 0:
        emit("PACKAGE ABORTED: report has failing assets or license blockers.", "refused",
             reason="report has failing assets or license blockers")
        return 1
    pid = pack["pack_id"]
    dist_dir = ROOT / "dist" / pid
    stage_dir = dist_dir / "addons" / pid
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    shutil.rmtree(dist_dir / "web_demo", ignore_errors=True)    # only this run's export may be published
    (dist_dir / f"{pid}_web.zip").unlink(missing_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    assets = con.execute("SELECT * FROM assets WHERE pack_id=? AND status IN ('passed','approved') ORDER BY name", (pid,)).fetchall()
    for a in assets:
        src = pathlib.Path(a["output_path"])
        if not src.exists() or sha256(src) != a["output_sha256"]:   # the file changed after its gates ran
            reason = f"{a['name']}: {src.name} changed or vanished since it was gated: rebuild it"
            emit(f"PACKAGE REFUSED: {reason}", "refused", reason=reason)
            return 1
        dst = stage_dir / ("shaders" if a["kind"] == "shader" else "") / src.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(src, dst)
    if any(a["kind"] == "ui_sfx" for a in assets):
        godot_randomizers(stage_dir, pid)
    if any(a["kind"] == "shader" for a in assets):
        shader_extras(stage_dir, pack)
    shutil.copy2(dist_dir / "VERIFY.md", stage_dir / "VERIFY.md")
    shutil.copy2(dist_dir / "manifest.json", stage_dir / "manifest.json")
    zip_path = dist_dir / f"{pid}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in stage_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(dist_dir))
    emit(f"packaged: {zip_path} ({len(assets)} assets)", "packaged", path=str(zip_path), assets=len(assets))
    return 0

TEMPLATES = {
    "ui_sfx": """pack_id: PACK_ID
category: audio
engine_target: godot-4.5
# title: Shown on itch.io      description: one-line pitch      price_usd: 4.99

disclosure:
  itch_ai_tags: [code]
  text: >-
    Say truthfully which files, if any, a generative model produced, and where AI assisted.

budgets:
  audio:
    sample_rate: 48000
    bit_depth: 24
    channels: 1
    duration_s: [0.02, 1.5]
    true_peak_dbtp_max: -0.9
    dc_offset_max: 0.002
    lead_silence_ms_max: 5
    tail_dbfs_max: -60
    pack_level_spread_db: 8

# recipe: a generator in generators/sfx_ui.py (click, hover, confirm, error)
assets:
  - {kind: ui_sfx, recipe: click, name: 'UIClick_Button{var:02d}', variations: 2, seed: 100}
""",
    "shader": """pack_id: PACK_ID
category: shader
engine_target: godot-4.5
# title: Shown on itch.io      description: one-line pitch      price_usd: 4.99

disclosure:
  itch_ai_tags: [code]
  text: >-
    Say truthfully which files, if any, a generative model produced, and where AI assisted.

budgets:
  shader:
    max_uniforms: 12
    uniform_name_regex: '[a-z][a-z0-9_]*'
  preview:
    renderers: [forward_plus, mobile, gl_compatibility]
    frames: 90
    min_frames: 90
    background_rgb: [20, 23, 28]
    min_coverage: 0.05
    animated: true

# Each name is shaders/PACK_ID/<name>.gdshader
assets:
  - {kind: shader, name: my_shader}
""",
    "inbox_mesh": """pack_id: PACK_ID
category: mesh
engine_target: godot-4.5
# title: Shown on itch.io      description: one-line pitch      price_usd: 4.99

disclosure:
  itch_ai_tags: [3d]
  text: >-
    Say truthfully which files, if any, a generative model produced, and where AI assisted.

budgets:
  mesh: {}          # mesh gate code is not in this repo yet

# Drop inbox/PACK_ID/<name>.glb plus <name>.json (provenance sidecar)
assets:
  - {kind: inbox_mesh, name: my_mesh}
""",
}
PACK_ID = re.compile(r"[a-z][a-z0-9_]*")

def cmd_new(kind, pack_id):
    """Writes spec/packs/<pack_id>.yaml from a template. Never overwrites."""
    if not PACK_ID.fullmatch(pack_id or ""):
        emit(f"REFUSED: pack id {pack_id!r} must match [a-z][a-z0-9_]*", "refused", reason="bad pack id")
        return 1
    out = ROOT / "spec" / "packs" / f"{pack_id}.yaml"
    if out.exists():
        emit(f"REFUSED: {out} already exists", "refused", reason="spec exists")
        return 1
    with out.open("x", encoding="utf-8", newline="\n") as f:
        f.write(TEMPLATES[kind].replace("PACK_ID", pack_id))
    emit(f"created {out}", "created", path=str(out))
    return 0

def cmd_listing(con, pack):
    """dist/<pack>/listing.md: a draft to paste into the itch.io page editor (there is no API for it)."""
    pid = pack["pack_id"]
    cmd_report(con, pack)                             # fresh VERIFY.md
    dist = ROOT / "dist" / pid
    verify = [l for l in (dist / "VERIFY.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    readme = dist / "addons" / pid / "README.md"
    body = readme.read_text(encoding="utf-8").splitlines() if readme.exists() else []
    if body and body[0].startswith("# "):
        body = body[1:]
    zip_path = dist / f"{pid}.zip"
    files = []
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            files = zf.namelist()
    ver = pack.get("engine_target", "").removeprefix("godot-")
    price = pack.get("price_usd")
    if price is not None:
        try:
            price = float(price)                      # YAML reads a quoted "4.99" as text
        except (TypeError, ValueError):
            emit(f"LISTING REFUSED: price_usd must be a number, got {price!r}", "refused",
                 reason=f"price_usd must be a number, got {price!r}")
            return 1
    disc = pack.get("disclosure", {})
    lines = [f"# {pack.get('title', pid)}", "",
             pack.get("description", f"{pack['category'].capitalize()} pack for Godot {ver}."), "",
             f"Suggested price: {f'${price:.2f}' if price is not None else 'none'}", "",
             "## Description", "", "\n".join(body).strip() or disc.get("text", ""), "",
             "## Verification", "", *verify, "",
             "## AI disclosure (itch.io)", "",
             f"Categories: {', '.join(disc.get('itch_ai_tags', [])) or 'none'}", "", disc.get("text", ""), "",
             "## Files", "", *([f"- {f}" for f in files] or ["(not packaged yet)"]), ""]
    out = dist / "listing.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    emit(f"wrote {out}", "listing", path=str(out))
    return 0

def dir_sha256(d):
    """Hash of a directory's files (relative path + bytes, sorted), for channels pushed as a folder."""
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(f.relative_to(d).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()

def cmd_publish(con, pack, spec_path, dry_run=False, expect=None):
    """Uploads the addon zip (and web_demo if present) to itch.io with butler. Refuses unless the pack is
    shippable: report exits 0, every live asset is approved, the zip exists, and nothing changed since the build."""
    pid = pack["pack_id"]
    g = global_spec()
    user = (g.get("itch") or {}).get("user")
    butler = g.get("tools", {}).get("butler")
    if not dry_run:                                   # a dry run writes nothing, not even the schema
        con.executescript((ROOT / "pipeline" / "schema.sql").read_text(encoding="utf-8"))   # adds releases to old DBs
    dist = ROOT / "dist" / pid
    zip_path = dist / f"{pid}.zip"
    row = con.execute("SELECT spec_hash FROM packs WHERE pack_id=?", (pid,)).fetchone()
    def refuse(reason):
        emit(f"PUBLISH REFUSED: {reason}", "refused", reason=reason)
        return 1
    if not user:
        return refuse("itch.user is not set (put it in spec/global.local.yaml)")
    butler = butler and (butler if pathlib.Path(butler).exists() else shutil.which(butler))   # a bare name: PATH
    if not butler:
        return refuse(f"butler not found at {g.get('tools', {}).get('butler')!r} (set tools.butler in spec/global.local.yaml)")
    if not row:
        return refuse("pack was never built")
    if recipe_hash(spec_path) != row["spec_hash"]:
        return refuse("spec, generators or gates changed since the last build: rebuild first")
    if cmd_report(con, pack, write=not dry_run) != 0:
        return refuse("report has failing assets or license blockers")
    pending = [r["name"] for r in con.execute("SELECT name FROM assets WHERE pack_id=? AND status NOT IN "
                                              "('approved','rejected') ORDER BY name", (pid,))]
    if pending:
        return refuse(f"not approved: {', '.join(pending)}")
    if not con.execute("SELECT 1 FROM assets WHERE pack_id=? AND status='approved'", (pid,)).fetchone():
        return refuse("no approved assets: nothing to publish")
    if not zip_path.exists():
        return refuse(f"addon zip missing: {zip_path} (run package)")
    approved = {r["name"]: r["output_sha256"] for r in con.execute(
        "SELECT name, output_sha256 FROM assets WHERE pack_id=? AND status='approved'", (pid,))}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            shipped = {m["name"]: m["sha256"] for m in json.loads(zf.read(f"addons/{pid}/manifest.json"))}
    except (KeyError, ValueError, zipfile.BadZipFile):
        shipped = None
    if shipped != approved:                           # zip built from older outputs, or not by package
        return refuse("zip does not match the approved assets: run package again")
    pushes = [("godot-addon", zip_path, sha256(zip_path))]
    if (dist / "web_demo").is_dir():
        pushes.append(("html5", dist / "web_demo", dir_sha256(dist / "web_demo")))
    # --expect: the channel:sha256 pairs the user saw in the dry run and confirmed. Anything else was not confirmed.
    if expect is not None and sorted(f"{c}:{h}" for c, _, h in pushes) != sorted(expect):
        return refuse("files changed since the preview: open Publish again to see what would be uploaded")
    for channel, path, file_sha in pushes:
        target = f"{user}/{pid}:{channel}"
        cmd = [str(butler), "push", str(path), target]
        emit(f"{'DRY RUN  ' if dry_run else ''}{subprocess.list2cmdline(cmd)}", "push",
             channel=channel, target=target, cmd=cmd, dry_run=dry_run, sha256=file_sha)
        if dry_run:
            continue
        try:                                          # no stdin: a login prompt fails instead of hanging
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired:
            emit(f"butler push timed out after 1 h for {target}", "error", message="butler did not finish within an hour",
                 channel=channel)
            return 1
        if p.returncode != 0:
            tail = "\n".join((p.stdout + p.stderr).splitlines()[-40:])
            print(tail, file=sys.stderr)
            emit(f"butler push failed ({p.returncode}) for {target}", "error", message=tail, channel=channel)
            return 1
        # ponytail: butler_build stays NULL until step 5 pins butler's output format
        con.execute("INSERT INTO releases (pack_id, channel, target, file_sha256, spec_hash) VALUES (?,?,?,?,?)",
                    (pid, channel, target, file_sha, row["spec_hash"]))
        con.commit()                                  # one row per push that really happened
        emit(f"pushed {target}", "pushed", channel=channel, target=target)
    return 0

PLAYGROUND = ROOT.parent / "playground"

def cmd_playground(con, open_after=False):
    """Copies every approved, packaged pack into playground/addons (tools/sync_packs.gd), checks the scene loads
    headless with zero errors, and with --open then launches Godot on it, detached."""
    con.executescript((ROOT / "pipeline" / "schema.sql").read_text(encoding="utf-8"))   # a fresh DB is fine
    godot = global_spec()["tools"]["godot"]
    approved = {}
    for r in con.execute("SELECT pack_id, name, status FROM assets ORDER BY pack_id"):
        names = approved.setdefault(r["pack_id"], set())
        if names is None or r["status"] == "rejected":
            continue
        if r["status"] == "approved":
            names.add(r["name"])
        else:
            approved[r["pack_id"]] = None                 # something still pending, failed or only passed
    def packaged(pid):
        """The staged addon holds exactly today's approved assets (it may predate a later rejection)."""
        try:
            manifest = json.loads((ROOT / "dist" / pid / "addons" / pid / "manifest.json").read_text(encoding="utf-8"))
            return {m["name"] for m in manifest} == approved[pid]
        except (OSError, ValueError, KeyError, TypeError):
            return False
    ready = sorted(p for p, names in approved.items() if names and packaged(p))
    dirs = [ROOT / "dist" / p / "addons" / p for p in ready]
    emit(f"playground: {len(dirs)} approved, packaged pack(s)", "playground", packs=[d.name for d in dirs])
    def headless(*args):
        return subprocess.run([godot, "--headless", "--path", str(PLAYGROUND), *args],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    sync = headless("--script", "res://tools/sync_packs.gd", "--", *map(str, dirs))
    for line in sync.stdout.splitlines():
        if line.startswith(("synced ", "removed ")):
            word, pid = line.split(" ", 1)
            emit(line, word, pack=pid)
    if sync.returncode != 0 or "err=0" not in sync.stdout:
        detail = "\n".join((sync.stdout + sync.stderr).splitlines()[-40:])
        emit(f"playground sync failed:\n{detail}", "error", message=detail)
        return 1
    headless("--import")
    check = headless("--script", "res://tools/check.gd")
    counts = next((json.loads(l) for l in check.stdout.splitlines() if l.startswith("{")), None)
    errors = [l for l in check.stderr.splitlines() if "ERROR" in l]
    if counts is None or errors or check.returncode != 0:
        detail = "\n".join((errors or check.stderr.splitlines() or [f"exit {check.returncode}"])[-40:])
        emit(f"playground did not load cleanly:\n{detail}", "error", message=detail)
        return 1
    emit(f"playground loads: {counts['shaders']} shaders, {counts['sounds']} sounds", "check", **counts)
    if open_after:
        detached = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} \
            if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([godot, "--path", str(PLAYGROUND)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detached)
        emit(f"opened {PLAYGROUND}", "opened", path=str(PLAYGROUND))
    return 0

def run(a):
    if a.cmd == "new":
        return cmd_new(a.kind, a.id)
    if a.cmd == "playground":
        return cmd_playground(connect(), a.open)
    spec_path = ROOT / a.pack
    pack = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    pid = pack.get("pack_id") if isinstance(pack, dict) else None
    # The file name is what the Studio locks on and what the publish confirmation names. A pack_id that differs
    # (a copied spec) would rewrite another pack's approvals or upload under the other name; an odd one is a path.
    if not (isinstance(pid, str) and re.fullmatch(r"[a-z][a-z0-9_]*", pid) and pid == spec_path.stem):
        reason = f"pack_id {pid!r} must be a lowercase id equal to the spec file name {spec_path.stem!r}"
        emit(f"REFUSED: {reason}", "refused", reason=reason)
        return 1
    if a.cmd == "publish" and a.dry_run and not DB.exists():   # a preview never creates the database
        emit("PUBLISH REFUSED: pack was never built", "refused", reason="pack was never built")
        return 1
    con = connect()
    if a.cmd == "init":    cmd_init(con, pack)
    if a.cmd == "build":   cmd_build(con, pack, spec_path)
    if a.cmd == "approve": return cmd_approve(con, pack, spec_path, a.only)
    if a.cmd == "report":  return cmd_report(con, pack)
    if a.cmd == "package": return cmd_package(con, pack)
    if a.cmd == "listing": return cmd_listing(con, pack)
    if a.cmd == "publish": return cmd_publish(con, pack, spec_path, a.dry_run, a.expect)
    return 0

def main():
    global JSON
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["new", "init", "build", "approve", "report", "package", "listing", "publish",
                                    "playground"])
    ap.add_argument("--pack", help="spec/packs/<id>.yaml (every command except new and playground)")
    ap.add_argument("--kind", choices=sorted(TEMPLATES), help="new: pack template")
    ap.add_argument("--id", help="new: pack id")
    ap.add_argument("--only", nargs="*", help="approve: just these asset names")
    ap.add_argument("--dry-run", action="store_true", help="publish: print the butler commands, push nothing")
    ap.add_argument("--open", action="store_true", help="playground: launch Godot on it after a clean load")
    ap.add_argument("--expect", nargs="*", help="publish: the channel:sha256 pairs the dry run showed; refuse on any change")
    ap.add_argument("--json", action="store_true", help="one JSON event per stdout line")
    a = ap.parse_args()
    if a.cmd == "new" and not a.kind:
        ap.error("new needs --kind and --id")
    if a.cmd not in ("new", "playground") and not a.pack:
        ap.error(f"{a.cmd} needs --pack")
    JSON = a.json
    try:
        code = run(a)
    except Exception as e:
        traceback.print_exc()                       # human mode: the traceback is the whole report
        code = 1
        if JSON:
            emit(str(e), "error", message=str(e))
    if JSON:
        try:
            print(json.dumps({"event": "done", "cmd": a.cmd, "exit": code}), flush=True)
        except OSError:      # nobody left to tell (see emit)
            pass
    return code

if __name__ == "__main__":
    sys.exit(main())
