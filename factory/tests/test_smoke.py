import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns(
    "build", "dist", "wiki", "inbox", "factory.db", "__pycache__",
    ".godot", "addons", "pack", "tests",
)


def run_cli(cmd, pack, tmp_path):
    dst = tmp_path / "factory"
    if not dst.exists():
        shutil.copytree(REPO / "factory", dst, ignore=IGNORE)
    return subprocess.run(
        [sys.executable, str(dst / "pipeline" / "run.py"), cmd, "--pack", pack],
        cwd=REPO,
        env={**os.environ, "FACTORY_DB": str(tmp_path / "t.db")},
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_ui_sfx_pack_ships_from_repo_root(tmp_path):
    for cmd in ("init", "build", "approve"):
        r = run_cli(cmd, "spec/packs/ui_sfx_v1.yaml", tmp_path)
        assert r.returncode == 0, r.stderr
    r = run_cli("report", "spec/packs/ui_sfx_v1.yaml", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "16/16 passed, 0 license blockers" in r.stdout
    assert not (REPO / "factory" / "build" / "ui_sfx_v1").exists()
    assert not (REPO / "factory" / "dist" / "ui_sfx_v1").exists()


def test_tests_never_touch_real_db(tmp_path):
    real = REPO / "factory" / "factory.db"
    before = real.stat().st_mtime_ns if real.exists() else None
    r = run_cli("init", "spec/packs/ui_sfx_v1.yaml", tmp_path)
    assert r.returncode == 0, r.stderr
    after = real.stat().st_mtime_ns if real.exists() else None
    assert before == after
    assert (tmp_path / "t.db").exists()
