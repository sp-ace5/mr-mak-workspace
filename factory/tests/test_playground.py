"""The asset playground (playground/): sync, headless load check, and the `playground` command.
Godot runs only headless here; nothing is launched on screen and nothing is pushed anywhere."""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from conftest import REPO

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
