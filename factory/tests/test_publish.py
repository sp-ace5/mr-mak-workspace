"""publish never reaches itch.io here: butler is a stub script set through the temp copy's global.local.yaml."""
import json
import os
import sqlite3
import sys
import zipfile

import pytest

from conftest import cli
from test_cli import built_sfx, events


@pytest.fixture
def butler(fac, tmp_path):
    calls = tmp_path / "calls.txt"
    stub = tmp_path / "stub.py"
    stub.write_text("import json, os, sys\n"
                    f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv[1:]) + chr(10))\n"
                    "sys.exit(int(os.environ.get('STUB_EXIT', '0')))\n", encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "butler.cmd"
        exe.write_text(f'@"{sys.executable}" "{stub}" %*\n', encoding="utf-8")
    else:
        exe = tmp_path / "butler"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    local = fac / "spec" / "global.local.yaml"
    local.write_text(f"tools: {{butler: {json.dumps(str(exe))}}}\nitch: {{user: tester}}\n", encoding="utf-8")
    return exe, calls


def calls_made(calls):
    return [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []


def releases(fac):
    con = sqlite3.connect(fac / "t.db")
    try:
        return con.execute("SELECT channel, target, file_sha256, spec_hash FROM releases ORDER BY rowid").fetchall()
    except sqlite3.OperationalError:
        return []


def fake_zip(fac):
    z = fac / "dist" / "t_sfx" / "t_sfx.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("addons/t_sfx/a.wav", b"x")
    return z


def publish(fac, pack, *extra, env=None):
    return cli(fac, "publish", *pack, "--json", *extra, env=env)


def assert_refused(r, fac, calls, reason):
    assert r.returncode == 1, r.stdout + r.stderr
    refused = [e for e in events(r) if e["event"] == "refused"]
    assert refused and reason in refused[0]["reason"], r.stdout
    assert calls_made(calls) == []
    assert releases(fac) == []


def built_unapproved(fac):
    assert cli(fac, "new", "--kind", "ui_sfx", "--id", "t_sfx").returncode == 0
    pack = ("--pack", "spec/packs/t_sfx.yaml")
    for cmd in ("init", "build"):
        assert cli(fac, cmd, *pack).returncode == 0
    return pack


def test_refuses_unapproved(fac, butler):
    pack = built_unapproved(fac)
    fake_zip(fac)
    assert_refused(publish(fac, pack), fac, butler[1], "not approved")


def test_refuses_license_blocker(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac)
    con = sqlite3.connect(fac / "t.db")
    con.execute("UPDATE provenance SET license_id='unknown'")
    con.commit()
    con.close()
    assert_refused(publish(fac, pack), fac, butler[1], "report")


def test_refuses_missing_zip(fac, butler):
    pack = built_sfx(fac)
    assert_refused(publish(fac, pack), fac, butler[1], "zip")


def test_refuses_without_itch_user(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac)
    local = fac / "spec" / "global.local.yaml"
    local.write_text(local.read_text().replace("itch: {user: tester}", ""), encoding="utf-8")
    assert_refused(publish(fac, pack), fac, butler[1], "itch.user")


def test_refuses_stale_spec(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac)
    spec = fac / "spec" / "packs" / "t_sfx.yaml"
    spec.write_text(spec.read_text(encoding="utf-8") + "# edited after the build\n", encoding="utf-8")
    assert_refused(publish(fac, pack), fac, butler[1], "rebuild")


def test_dry_run_prints_commands_only(fac, butler):
    exe, calls = butler
    pack = built_sfx(fac)
    z = fake_zip(fac)
    (fac / "dist" / "t_sfx" / "web_demo").mkdir()
    (fac / "dist" / "t_sfx" / "web_demo" / "index.html").write_text("<html>", encoding="utf-8")
    r = publish(fac, pack, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    pushes = [e for e in events(r) if e["event"] == "push"]
    assert [p["cmd"] for p in pushes] == [
        [str(exe), "push", str(z), "tester/t_sfx:godot-addon"],
        [str(exe), "push", str(fac / "dist" / "t_sfx" / "web_demo"), "tester/t_sfx:html5"],
    ]
    assert all(p["dry_run"] for p in pushes)
    assert calls_made(calls) == []
    assert releases(fac) == []


def test_publish_records_releases(fac, butler):
    exe, calls = butler
    pack = built_sfx(fac)
    z = fake_zip(fac)
    (fac / "dist" / "t_sfx" / "web_demo").mkdir()
    (fac / "dist" / "t_sfx" / "web_demo" / "index.html").write_text("<html>", encoding="utf-8")
    r = publish(fac, pack)
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls_made(calls) == [["push", str(z), "tester/t_sfx:godot-addon"],
                                 ["push", str(fac / "dist" / "t_sfx" / "web_demo"), "tester/t_sfx:html5"]]
    import hashlib
    spec_hash = sqlite3.connect(fac / "t.db").execute("SELECT spec_hash FROM packs").fetchone()[0]
    rows = releases(fac)
    assert [(c, t) for c, t, _, _ in rows] == [("godot-addon", "tester/t_sfx:godot-addon"),
                                               ("html5", "tester/t_sfx:html5")]
    assert rows[0][2] == hashlib.sha256(z.read_bytes()).hexdigest()
    assert all(h == spec_hash for *_, h in rows)


def test_publish_without_web_demo(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac)
    assert publish(fac, pack).returncode == 0
    assert len(calls_made(butler[1])) == 1
    assert len(releases(fac)) == 1


def test_publish_butler_failure(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac)
    r = publish(fac, pack, env={"STUB_EXIT": "1"})
    assert r.returncode == 1
    assert len(calls_made(butler[1])) == 1
    assert releases(fac) == []
    assert events(r)[-1] == {"event": "done", "cmd": "publish", "exit": 1}
