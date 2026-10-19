import json

from conftest import cli

SFX = ("--pack", "spec/packs/ui_sfx_v1.yaml")


def events(r):
    return [json.loads(line) for line in r.stdout.splitlines()]


def test_build_json_events(fac):
    assert cli(fac, "init", *SFX).returncode == 0
    r = cli(fac, "build", *SFX, "--json")
    assert r.returncode == 0, r.stderr
    ev = events(r)
    gates = [e for e in ev if e["event"] == "gate"]
    assert len(gates) == 16
    assert all({"asset", "ok", "failed", "msg"} <= e.keys() for e in gates)
    assert ev[-1] == {"event": "done", "cmd": "build", "exit": 0}


def test_human_output_unchanged(fac):
    cli(fac, "init", *SFX)
    r = cli(fac, "build", *SFX)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines and all(l.startswith(("PASS ", "FAIL ")) for l in lines)


def test_json_error_still_done(fac):
    r = cli(fac, "report", *SFX, "--json")          # no init: tables are missing
    assert r.returncode == 1
    ev = events(r)
    assert ev[-2]["event"] == "error"
    assert ev[-1] == {"event": "done", "cmd": "report", "exit": 1}
    assert "Traceback" in r.stderr


# ---------- new ----------

import yaml
import zipfile

import pytest


@pytest.mark.parametrize("kind,category", [("ui_sfx", "audio"), ("shader", "shader"), ("inbox_mesh", "mesh")])
def test_new_writes_spec(fac, kind, category):
    r = cli(fac, "new", "--kind", kind, "--id", "t_pack")
    assert r.returncode == 0, r.stderr
    spec = yaml.safe_load((fac / "spec" / "packs" / "t_pack.yaml").read_text(encoding="utf-8"))
    assert spec["pack_id"] == "t_pack"
    assert spec["category"] == category
    assert spec["assets"]


def test_new_refuses_overwrite(fac):
    assert cli(fac, "new", "--kind", "ui_sfx", "--id", "t_pack").returncode == 0
    path = fac / "spec" / "packs" / "t_pack.yaml"
    before = path.read_bytes()
    r = cli(fac, "new", "--kind", "shader", "--id", "t_pack", "--json")
    assert r.returncode == 1
    assert events(r)[0]["event"] == "refused"
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad", ["../evil", "Bad", "1x", ""])
def test_new_rejects_bad_id(fac, bad):
    packs = sorted((fac / "spec" / "packs").iterdir())
    r = cli(fac, "new", "--kind", "ui_sfx", "--id", bad)
    assert r.returncode == 1
    assert sorted((fac / "spec" / "packs").iterdir()) == packs
    assert not (fac / "spec" / "evil.yaml").exists()


# ---------- listing ----------

def built_sfx(fac, extra=""):
    """A small ui_sfx pack from the template, built and approved in the temp copy."""
    assert cli(fac, "new", "--kind", "ui_sfx", "--id", "t_sfx").returncode == 0
    spec = fac / "spec" / "packs" / "t_sfx.yaml"
    spec.write_text(spec.read_text(encoding="utf-8") + extra, encoding="utf-8")
    pack = ("--pack", "spec/packs/t_sfx.yaml")
    for cmd in ("init", "build", "approve"):
        r = cli(fac, cmd, *pack)
        assert r.returncode == 0, r.stdout + r.stderr
    return pack


def test_listing(fac):
    pack = built_sfx(fac, "title: Soft UI Clicks\nprice_usd: 4.99\n")
    dist = fac / "dist" / "t_sfx"
    (dist / "addons" / "t_sfx").mkdir(parents=True)
    (dist / "addons" / "t_sfx" / "README.md").write_text("# t_sfx\n\nDrop-in clicks.\n", encoding="utf-8")
    with zipfile.ZipFile(dist / "t_sfx.zip", "w") as zf:
        zf.writestr("addons/t_sfx/a.wav", b"x")
    r = cli(fac, "listing", *pack, "--json")
    assert r.returncode == 0, r.stderr
    assert events(r)[-2]["event"] == "listing"
    md = (dist / "listing.md").read_text(encoding="utf-8")
    assert md.startswith("# Soft UI Clicks\n")
    assert "$4.99" in md
    assert "Drop-in clicks." in md
    assert "- Assets: 2/2 pass every gate" in md
    assert "code" in md
    assert "addons/t_sfx/a.wav" in md


def test_listing_without_price_or_package(fac):
    pack = built_sfx(fac)
    assert cli(fac, "listing", *pack).returncode == 0
    md = (fac / "dist" / "t_sfx" / "listing.md").read_text(encoding="utf-8")
    assert md.startswith("# t_sfx\n")
    assert "Suggested price: none" in md
    assert "(not packaged yet)" in md
