import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns(
    "build", "dist", "wiki", "inbox", "factory.db", "__pycache__",
    ".godot", "addons", "pack", "tests", "global.local.yaml",
)


@pytest.fixture
def fac(tmp_path):
    """A throwaway copy of factory/ (sources only), so nothing touches the real checkout."""
    dst = tmp_path / "factory"
    shutil.copytree(REPO / "factory", dst, ignore=IGNORE)
    # safety net: no test can reach the real butler, even one that forgets the stub fixture
    (dst / "spec" / "global.local.yaml").write_text(
        f"tools: {{butler: '{tmp_path / 'no-butler-here'}'}}\n", encoding="utf-8")
    return dst


def cli(fac, *args, env=None):
    return subprocess.run(
        [sys.executable, str(fac / "pipeline" / "run.py"), *args],
        cwd=REPO,
        env={**os.environ, "FACTORY_DB": str(fac / "t.db"), **(env or {})},
        capture_output=True,
        text=True,
        timeout=300,
    )


def py(fac, code, env=None):
    """Run code with the copy's pipeline importable; returns stdout."""
    r = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(fac)!r}); {code}"],
        env={**os.environ, "FACTORY_DB": str(fac / "t.db"), **(env or {})},
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout
