"""publish never reaches itch.io here: butler is a stub script set through the temp copy's global.local.yaml."""
import hashlib
import json
import os
import pathlib
import shutil
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
                    "os.environ.get('STUB_READ') and sys.stdin.read()\n"
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


def fake_zip(fac, manifest=True, tamper=False):
    """Stands in for `package` (needs Godot): a zip whose manifest lists the DB's current approved outputs."""
    z = fac / "dist" / "t_sfx" / "t_sfx.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(fac / "t.db")
    rows = con.execute("SELECT name, output_sha256 FROM assets WHERE pack_id='t_sfx' AND status='approved'").fetchall()
    con.close()
    entries = [{"name": n, "sha256": ("0" * 64 if tamper and i == 0 else h)} for i, (n, h) in enumerate(rows)]
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("addons/t_sfx/a.wav", b"x")
        if manifest:
            zf.writestr("addons/t_sfx/manifest.json", json.dumps(entries))
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
    assert pushes[0]["sha256"] == hashlib.sha256(z.read_bytes()).hexdigest()   # what the dialog shows
    assert len(pushes[1]["sha256"]) == 64
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


def test_refuses_stale_zip(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac, tamper=True)          # e.g. packaged before a rebuild: old output hashes
    assert_refused(publish(fac, pack), fac, butler[1], "package")


def test_refuses_zip_without_manifest(fac, butler):
    pack = built_sfx(fac)
    fake_zip(fac, manifest=False)
    assert_refused(publish(fac, pack), fac, butler[1], "package")


def test_temp_copy_never_sees_real_butler(fac, tmp_path):
    from conftest import py
    out = py(fac, "from pipeline.run import global_spec; print(global_spec()['tools']['butler'])").strip()
    assert out.startswith(str(tmp_path))


def test_butler_gets_no_stdin(fac, butler):
    """An unauthenticated butler waits for an interactive login; the CLI must not hang on it."""
    import subprocess
    pack = built_sfx(fac)
    fake_zip(fac)
    p = subprocess.Popen([sys.executable, str(fac / "pipeline" / "run.py"), "publish", *pack],
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={**os.environ, "FACTORY_DB": str(fac / "t.db"), "STUB_READ": "1"})
    try:
        assert p.wait(timeout=60) == 0
    finally:
        p.kill()
        p.stdin.close()


def test_package_clears_stale_web_demo(fac):
    """A package run that skips the web export (no templates) must not leave an old demo for publish to push."""
    from conftest import py
    pack = built_sfx(fac)
    old = fac / "dist" / "t_sfx" / "web_demo"
    old.mkdir(parents=True)
    (old / "index.html").write_text("old", encoding="utf-8")
    (fac / "dist" / "t_sfx" / "t_sfx_web.zip").write_bytes(b"old")
    py(fac, "import yaml, pipeline.run as r; r.godot_randomizers = lambda *a: None; "
            "pack = yaml.safe_load(open(r.ROOT / 'spec/packs/t_sfx.yaml', encoding='utf-8')); "
            "assert r.cmd_package(r.connect(), pack) == 0")
    assert (fac / "dist" / "t_sfx" / "t_sfx.zip").exists()
    assert not old.exists()
    assert not (fac / "dist" / "t_sfx" / "t_sfx_web.zip").exists()


def test_refuses_pack_with_no_approved_assets(fac, butler):
    """Every asset rejected: report, approvals and an empty manifest all agree, but there is nothing to sell."""
    exe, calls = butler
    pack = built_sfx(fac)
    con = sqlite3.connect(fac / "t.db")
    con.execute("UPDATE assets SET status='rejected' WHERE pack_id='t_sfx'")
    con.commit()
    con.close()
    fake_zip(fac)
    assert_refused(publish(fac, pack), fac, calls, "no approved assets")


def test_dry_run_writes_nothing(fac, butler):
    """A preview: no VERIFY.md, manifest or wiki copy is (re)written, while the report check still runs."""
    pack = built_sfx(fac)
    fake_zip(fac)
    dist = fac / "dist" / "t_sfx"
    for name in ("VERIFY.md", "manifest.json"):
        (dist / name).unlink(missing_ok=True)
    shutil.rmtree(fac / "wiki", ignore_errors=True)
    r = publish(fac, pack, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (dist / "VERIFY.md").exists() and not (dist / "manifest.json").exists()
    assert not (fac / "wiki").exists()


def test_relative_butler_path_resolves_against_factory(fac, butler):
    exe, calls = butler
    pack = built_sfx(fac)
    fake_zip(fac)
    rel = os.path.relpath(exe, fac)                  # e.g. ..\butler.cmd; the CLI runs with cwd = repo root
    (fac / "spec" / "global.local.yaml").write_text(
        f"tools: {{butler: {json.dumps(rel)}}}\nitch: {{user: tester}}\n", encoding="utf-8")
    r = publish(fac, pack, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [e["cmd"][0] for e in events(r) if e["event"] == "push"][0] == str(exe)


def test_publish_refuses_when_files_changed_since_the_preview(fac, butler):
    """--expect carries the channel:sha256 pairs the user saw in the dry run; anything else is not what they confirmed."""
    exe, calls = butler
    pack = built_sfx(fac)
    z = fake_zip(fac)
    seen = [f"{e['channel']}:{e['sha256']}" for e in events(publish(fac, pack, "--dry-run")) if e["event"] == "push"]
    (fac / "dist" / "t_sfx" / "web_demo").mkdir()                 # a channel appears after the preview
    (fac / "dist" / "t_sfx" / "web_demo" / "index.html").write_text("<html>", encoding="utf-8")
    assert_refused(publish(fac, pack, "--expect", *seen), fac, calls, "changed since the preview")
    (fac / "dist" / "t_sfx" / "web_demo" / "index.html").unlink()
    (fac / "dist" / "t_sfx" / "web_demo").rmdir()
    r = publish(fac, pack, "--expect", *seen)
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls_made(calls) == [["push", str(z), "tester/t_sfx:godot-addon"]]


def test_dry_run_on_a_fresh_checkout_refuses_cleanly(fac, butler):
    """No factory.db yet: a refusal, not a crash, and no database file created by a preview."""
    assert cli(fac, "new", "--kind", "ui_sfx", "--id", "t_sfx").returncode == 0
    r = publish(fac, ("--pack", "spec/packs/t_sfx.yaml"), "--dry-run")
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(e["event"] == "refused" and "never built" in e["reason"] for e in events(r)), r.stdout
    assert not (fac / "t.db").exists()


def test_bare_butler_name_is_found_on_path(fac, butler):
    exe, calls = butler
    pack = built_sfx(fac)
    fake_zip(fac)
    (fac / "spec" / "global.local.yaml").write_text(f"tools: {{butler: {exe.stem}}}\nitch: {{user: tester}}\n", encoding="utf-8")
    r = publish(fac, pack, "--dry-run", env={"PATH": f"{exe.parent}{os.pathsep}{os.environ['PATH']}"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert pathlib.Path([e["cmd"][0] for e in events(r) if e["event"] == "push"][0]).samefile(exe)
