"""The asset playground (playground/): sync, headless load check, and the `playground` command.
Godot runs only headless here; nothing is launched on screen and nothing is pushed anywhere."""
import base64
import json
import os
import pathlib
import shutil
import sqlite3
import struct
import subprocess
import sys
import wave

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


def tiny_wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack("<480h", *([1000, -1000] * 240)))


def tiny_gltf(path):
    """One triangle, its buffer embedded as a data URI."""
    data = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    path.write_text(json.dumps({
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "Crate"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(data), "uri": "data:application/octet-stream;base64," + base64.b64encode(data).decode()}],
        "bufferViews": [{"buffer": 0, "byteLength": len(data)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
    }), encoding="utf-8")


def randomizer(path, wav_res):
    path.write_text('[gd_resource type="AudioStreamRandomizer" load_steps=2 format=3]\n\n'
                    f'[ext_resource type="AudioStream" path="{wav_res}" id="1"]\n\n'
                    '[resource]\nstreams_count = 1\nstream_0/stream = ExtResource("1")\n', encoding="utf-8")


def fx_addon(root):
    """A packaged-looking addon with one of each content type the playground places."""
    addon = root / "fx_pack"
    (addon / "shaders").mkdir(parents=True)
    (addon / "shaders" / "glow.gdshader").write_text(
        "shader_type spatial;\nuniform vec4 c : source_color = vec4(1.0);\nvoid fragment() { ALBEDO = c.rgb; }\n",
        encoding="utf-8")
    tiny_wav(addon / "Foot_Step01.wav")
    tiny_wav(addon / "UI_Click01.wav")
    randomizer(addon / "Foot_Steps.tres", "res://addons/fx_pack/Foot_Step01.wav")
    randomizer(addon / "UI_Click.tres", "res://addons/fx_pack/UI_Click01.wav")
    (addon / "fx_theme.tres").write_text('[gd_resource type="Theme" format=3]\n\n[resource]\ndefault_font_size = 18\n',
                                         encoding="utf-8")
    (addon / "sparks.tscn").write_text('[gd_scene format=3]\n\n[node name="Sparks" type="GPUParticles3D"]\namount = 16\n',
                                       encoding="utf-8")
    tiny_gltf(addon / "crate.gltf")
    (addon / "manifest.json").write_text(json.dumps([{"name": "glow", "kind": "shader"}]), encoding="utf-8")
    return addon


@pytest.mark.skipif(not real_godot(), reason="Godot not installed at tools.godot")
def test_playground_loads_synced_addons(playground, tmp_path):
    exe = real_godot()
    godot(exe, playground, "--import")
    empty = godot(exe, playground, "--script", "res://tools/check.gd")    # nothing synced, no addons/ yet
    assert '"shaders":0,' in empty.stdout.replace(" ", "") and "ERROR" not in empty.stderr, empty.stderr
    addon = fx_addon(tmp_path / "dist")
    keep = playground / "addons" / "keep_me"
    keep.mkdir(parents=True)
    (keep / "plugin.cfg").write_text("[plugin]\n", encoding="utf-8")

    sync = godot(exe, playground, "--script", "res://tools/sync_packs.gd", "--", str(addon))
    assert "synced fx_pack" in sync.stdout and "err=0" in sync.stdout, sync.stdout + sync.stderr
    assert (playground / "addons" / "fx_pack" / "shaders" / "glow.gdshader").exists()
    godot(exe, playground, "--import")
    check = godot(exe, playground, "--script", "res://tools/check.gd")
    counts = json.loads(next(l for l in check.stdout.splitlines() if l.startswith("{")))
    assert counts == {"shaders": 1, "sounds": 2, "footsteps": True, "buttons": 1, "vfx": 1, "meshes": 1, "themes": 1}, \
        check.stdout + check.stderr
    assert "ERROR" not in check.stderr, check.stderr

    clash = tmp_path / "dist" / "keep_me"                          # same name as the hand-installed addon
    clash.mkdir()
    refused = godot(exe, playground, "--script", "res://tools/sync_packs.gd", "--", str(addon), str(clash))
    assert "err=0" not in refused.stdout and "installed by hand" in refused.stderr, refused.stdout + refused.stderr
    assert (keep / "plugin.cfg").exists()

    ledger = playground / "addons" / ".factory_synced.json"
    ledger.write_text(json.dumps(["", "..", ".", "fx_pack"]), encoding="utf-8")   # never a path outside one addon
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
    """A: approved + packaged. B: approved, never packaged. C: one asset still only passed, packaged.
    D: approved, but packaged before a1 was rejected, so its addon still ships a1."""
    con = sqlite3.connect(fac / "t.db")
    con.executescript((fac / "pipeline" / "schema.sql").read_text(encoding="utf-8"))
    for pid, statuses in {"pa": ["approved", "rejected"], "pb": ["approved"], "pc": ["approved", "passed"],
                            "pd": ["approved", "rejected"]}.items():
        con.execute("INSERT INTO packs (pack_id, category, spec_path, spec_hash) VALUES (?, 'shader', 'x', 'h')", (pid,))
        for i, status in enumerate(statuses):
            con.execute("INSERT INTO assets (asset_id, pack_id, kind, name, status) VALUES (?, ?, 'shader', ?, ?)",
                        (f"{pid}/a{i}", pid, f"a{i}", status))
    con.commit()
    con.close()
    for pid in ("pa", "pc", "pd"):
        staged = fac / "dist" / pid / "addons" / pid
        staged.mkdir(parents=True)
        shipped = [{"name": "a0"}, {"name": "a1"}] if pid == "pd" else [{"name": "a0"}]   # pd still ships a1
        (staged / "manifest.json").write_text(json.dumps(shipped), encoding="utf-8")


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
    assert any(e["event"] == "error" and "boom" in e.get("message", "") and "boom" in e["msg"] for e in events(r))
    assert not any(c[:1] == ["--path"] for c in godot_calls(stub_godot))
    r = cli(fac, "playground", "--open", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    launch = godot_calls(stub_godot, wait_for=lambda c: c[:1] == ["--path"])
    assert ["--path", str(fac.parent / "playground")] in launch
    assert any(e["event"] == "opened" for e in events(r))
