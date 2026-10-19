import json
import sys

from conftest import REPO, cli, py


def snapshot():
    """Every file the factory writes in the real checkout, with its mtime."""
    root = REPO / "factory"
    files = [p for d in ("build", "dist") for p in (root / d).rglob("*") if p.is_file()]
    files += [root / "factory.db"] if (root / "factory.db").exists() else []
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in files}


def test_ui_sfx_pack_ships_from_repo_root(fac):
    before = snapshot()
    for cmd in ("init", "build", "approve"):
        r = cli(fac, cmd, "--pack", "spec/packs/ui_sfx_v1.yaml")
        assert r.returncode == 0, r.stderr
    r = cli(fac, "report", "--pack", "spec/packs/ui_sfx_v1.yaml")
    assert r.returncode == 0, r.stderr
    assert "16/16 passed, 0 license blockers" in r.stdout
    assert (fac / "t.db").exists()
    assert snapshot() == before


def test_global_local_overlay(fac):
    (fac / "spec" / "global.local.yaml").write_text("tools: {butler: X}\nitch: {user: me}\n", encoding="utf-8")
    g = json.loads(py(fac, "import json; from pipeline.run import global_spec; print(json.dumps(global_spec()))"))
    assert g["tools"]["butler"] == "X"
    assert g["tools"]["godot"].endswith(".exe")
    assert g["itch"]["user"] == "me"
    assert g["licenses"]


def test_export_template_per_os(fac, tmp_path):
    env = {"APPDATA": str(tmp_path / "ad"), "HOME": str(tmp_path / "h"), "XDG_DATA_HOME": str(tmp_path / "x")}
    got = py(fac, "from pipeline.run import export_template; print(export_template('godot-4.5'))", env).strip()
    base = {"win32": tmp_path / "ad" / "Godot", "darwin": tmp_path / "h" / "Library" / "Application Support" / "Godot"}
    want = base.get(sys.platform, tmp_path / "x" / "godot") / "export_templates" / "4.5.stable" / "web_nothreads_release.zip"
    assert got == str(want)
