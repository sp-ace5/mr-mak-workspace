"""The asset playground (playground/): sync, headless load check, and the `playground` command.
Godot runs only headless here; nothing is launched on screen and nothing is pushed anywhere."""
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys

import pytest

from conftest import REPO, cli
from test_cli import events

IGNORE = shutil.ignore_patterns(".godot", "addons", "*.uid")


def real_godot():
    sys.path.insert(0, str(REPO / "factory"))
    from pipeline.run import global_spec
    exe = global_spec()["tools"]["godot"]
    return exe if pathlib.Path(exe).exists() else None


def godot(exe, proj, *args):
    return subprocess.run([exe, "--headless", "--path", str(proj), *args],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)


@pytest.fixture
def playground(tmp_path):
    dst = tmp_path / "playground"
    shutil.copytree(REPO / "playground", dst, ignore=IGNORE)
    return dst


def fx_addon(root):
    """A packaged-looking addon with one spatial shader."""
    addon = root / "fx_pack"
    (addon / "shaders").mkdir(parents=True)
    (addon / "shaders" / "glow.gdshader").write_text(
        "shader_type spatial;\nuniform vec4 c : source_color = vec4(1.0);\nvoid fragment() { ALBEDO = c.rgb; }\n",
        encoding="utf-8")
    (addon / "manifest.json").write_text(json.dumps([{"name": "glow", "kind": "shader"}]), encoding="utf-8")
    return addon


@pytest.mark.skipif(not real_godot(), reason="Godot not installed at tools.godot")
def test_playground_loads_synced_addons(playground, tmp_path):
    exe = real_godot()
    godot(exe, playground, "--import")
    empty = godot(exe, playground, "--script", "res://tools/check.gd")    # nothing synced, no addons/ yet
    assert '{"shaders":0,"sounds":0}' in empty.stdout.replace(" ", "") and "ERROR" not in empty.stderr, empty.stderr
    addon = fx_addon(tmp_path / "dist")
    keep = playground / "addons" / "keep_me"
    keep.mkdir(parents=True)
    (keep / "plugin.cfg").write_text("[plugin]\n", encoding="utf-8")

    sync = godot(exe, playground, "--script", "res://tools/sync_packs.gd", "--", str(addon))
    assert "synced fx_pack" in sync.stdout and "err=0" in sync.stdout, sync.stdout + sync.stderr
    assert (playground / "addons" / "fx_pack" / "shaders" / "glow.gdshader").exists()
    godot(exe, playground, "--import")
    check = godot(exe, playground, "--script", "res://tools/check.gd")
    assert '{"shaders":1,"sounds":0}' in check.stdout.replace(" ", ""), check.stdout + check.stderr
    assert "ERROR" not in check.stderr, check.stderr

    again = godot(exe, playground, "--script", "res://tools/sync_packs.gd", "--")
    assert "removed fx_pack" in again.stdout and "err=0" in again.stdout, again.stdout + again.stderr
    assert not (playground / "addons" / "fx_pack").exists()
    assert (keep / "plugin.cfg").exists()                         # hand-installed addons are never touched


# ---------- the `playground` command, with a stub godot that records its calls ----------

@pytest.fixture
def stub_godot(fac, tmp_path):
    """Records argv; acts like sync_packs.gd / check.gd. STUB_CHECK_ERR puts an ERROR on check's stderr."""
    calls = tmp_path / "godot_calls.txt"
    stub = tmp_path / "godot_stub.py"
    stub.write_text(
        "import json, os, sys\n"
        "a = sys.argv[1:]\n"
        f"open({str(calls)!r}, 'a').write(json.dumps(a) + chr(10))\n"
        "if 'res://tools/sync_packs.gd' in a:\n"
        "    for d in a[a.index('--') + 1:]: print('synced ' + os.path.basename(d))\n"
        "    print('err=0')\n"
        "if 'res://tools/check.gd' in a:\n"
        "    if os.environ.get('STUB_CHECK_ERR'): print('ERROR: boom', file=sys.stderr)\n"
        "    print(json.dumps({'shaders': 1, 'sounds': 0}))\n", encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "godot.cmd"
        exe.write_text(f'@"{sys.executable}" "{stub}" %*\n', encoding="utf-8")
    else:
        exe = tmp_path / "godot"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    (fac / "spec" / "global.local.yaml").write_text(
        f"tools: {{godot: {json.dumps(str(exe))}, butler: {json.dumps(str(tmp_path / 'no-butler-here'))}}}\n",
        encoding="utf-8")
    shutil.copytree(REPO / "playground", fac.parent / "playground", ignore=IGNORE)
    return calls


def godot_calls(calls, wait_for=None):
    import time
    for _ in range(50):                       # the --open launch is detached: give it a moment
        found = [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []
        if not wait_for or any(wait_for(c) for c in found):
            return found
        time.sleep(0.1)
    return found


def seed_packs(fac):
    """A: approved + packaged. B: approved, never packaged. C: one asset still only passed, packaged."""
    con = sqlite3.connect(fac / "t.db")
    con.executescript((fac / "pipeline" / "schema.sql").read_text(encoding="utf-8"))
    for pid, statuses in {"pa": ["approved", "rejected"], "pb": ["approved"], "pc": ["approved", "passed"]}.items():
        con.execute("INSERT INTO packs (pack_id, category, spec_path, spec_hash) VALUES (?, 'shader', 'x', 'h')", (pid,))
        for i, status in enumerate(statuses):
            con.execute("INSERT INTO assets (asset_id, pack_id, kind, name, status) VALUES (?, ?, 'shader', ?, ?)",
                        (f"{pid}/a{i}", pid, f"a{i}", status))
    con.commit()
    con.close()
    for pid in ("pa", "pc"):
        staged = fac / "dist" / pid / "addons" / pid
        staged.mkdir(parents=True)
        (staged / "manifest.json").write_text("[]", encoding="utf-8")


def test_playground_selects_only_approved_packaged(fac, stub_godot):
    seed_packs(fac)
    r = cli(fac, "playground", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    sync = next(c for c in godot_calls(stub_godot) if "res://tools/sync_packs.gd" in c)
    assert sync[sync.index("--") + 1:] == [str(fac / "dist" / "pa" / "addons" / "pa")]
    ev = events(r)
    assert next(e for e in ev if e["event"] == "playground")["packs"] == ["pa"]
    assert {"event": "check", "shaders": 1, "sounds": 0}.items() <= next(e for e in ev if e["event"] == "check").items()
    assert not any(c[:1] == ["--path"] for c in godot_calls(stub_godot))      # no --open, no launch


def test_playground_open_launches_detached_only_after_check(fac, stub_godot):
    seed_packs(fac)
    r = cli(fac, "playground", "--open", "--json", env={"STUB_CHECK_ERR": "1"})
    assert r.returncode == 1
    assert any(e["event"] == "error" and "boom" in e.get("message", "") for e in events(r))
    assert not any(c[:1] == ["--path"] for c in godot_calls(stub_godot))
    r = cli(fac, "playground", "--open", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    launch = godot_calls(stub_godot, wait_for=lambda c: c[:1] == ["--path"])
    assert ["--path", str(fac.parent / "playground")] in launch
    assert any(e["event"] == "opened" for e in events(r))
