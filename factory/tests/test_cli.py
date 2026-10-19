import json

from conftest import cli, py

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


def test_listing_quoted_price(fac):
    """YAML turns `price_usd: "4.99"` into a string; it still lists, and a non-number is a clear refusal."""
    pack = built_sfx(fac, 'price_usd: "4.99"\n')
    r = cli(fac, "listing", *pack)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "$4.99" in (fac / "dist" / "t_sfx" / "listing.md").read_text(encoding="utf-8")
    spec = fac / "spec" / "packs" / "t_sfx.yaml"
    spec.write_text(spec.read_text(encoding="utf-8").replace('price_usd: "4.99"', "price_usd: free"), encoding="utf-8")
    r = cli(fac, "listing", *pack, "--json")
    assert r.returncode == 1
    assert any(e["event"] == "refused" and "price_usd" in e["reason"] for e in events(r)), r.stdout
    assert "Traceback" not in r.stderr


def test_recipe_hash_covers_cli_and_harness(fac):
    """Changing the CLI or a Godot harness script can change gate results, so it must force a rebuild."""
    code = ("import pathlib; from pipeline.run import recipe_hash, ROOT; "
            "print(recipe_hash(ROOT / 'spec' / 'packs' / 'ui_sfx_v1.yaml'))")
    before = py(fac, code)
    for path in (fac / "godot_harness" / "check.gd", fac / "pipeline" / "run.py"):
        path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        after = py(fac, code)
        assert after != before, path.name
        before = after


def test_emit_survives_a_closed_pipe(fac):
    """The desktop service may exit mid-job; the CLI must finish its work rather than die on its next print."""
    out = py(fac, "import io, sys\n"
                  "import pipeline.run as r\n"
                  "class Gone(io.TextIOBase):\n"
                  "    def write(self, s): raise BrokenPipeError(32, 'pipe closed')\n"
                  "    def flush(self): raise BrokenPipeError(32, 'pipe closed')\n"
                  "real = sys.stdout\n"
                  "sys.stdout = Gone()\n"
                  "r.JSON = True\n"
                  "r.emit('still working', 'log')\n"
                  "sys.stdout = real\n"
                  "print('survived')")
    assert "survived" in out


def test_pack_id_must_match_the_file_name(fac):
    """Two files claiming one pack_id would overwrite each other's approvals and publish to the wrong target."""
    src = (fac / "spec" / "packs" / "ui_sfx_v1.yaml").read_text(encoding="utf-8")
    (fac / "spec" / "packs" / "ui_sfx_v2.yaml").write_text(src, encoding="utf-8")    # still says pack_id: ui_sfx_v1
    r = cli(fac, "build", "--pack", "spec/packs/ui_sfx_v2.yaml", "--json")
    assert r.returncode == 1
    assert any(e["event"] == "refused" and "pack_id" in e["reason"] for e in events(r)), r.stdout
    assert not (fac / "t.db").exists() or "ui_sfx_v1" not in py(fac, "import sqlite3, os; print([r[0] for r in "
        "sqlite3.connect(os.environ['FACTORY_DB']).execute('SELECT pack_id FROM packs')])")


def test_approve_refuses_on_a_stale_recipe(fac):
    """Passed under the old budgets is not passed: approving before a rebuild would freeze unchecked assets."""
    pack = built_sfx(fac)
    spec = fac / "spec" / "packs" / "t_sfx.yaml"
    spec.write_text(spec.read_text(encoding="utf-8") + "\n# budgets changed\n", encoding="utf-8")
    r = cli(fac, "approve", *pack, "--json")
    assert r.returncode == 1
    assert any(e["event"] == "refused" and "rebuild" in e["reason"] for e in events(r)), r.stdout


def test_license_edits_make_the_build_stale_and_sync_on_build(fac):
    """global.yaml's license table decides blockers; editing it must not leave old verdicts in place."""
    code = ("from pipeline.run import recipe_hash, ROOT; "
            "print(recipe_hash(ROOT / 'spec' / 'packs' / 'ui_sfx_v1.yaml'))")
    before = py(fac, code)
    g = fac / "spec" / "global.yaml"
    g.write_text(g.read_text(encoding="utf-8").replace("{license_id: own-work,             commercial_ok: 1",
                                                       "{license_id: own-work,             commercial_ok: 0"), encoding="utf-8")
    assert py(fac, code) != before


def test_recipe_hash_covers_shared_pipeline_code_and_harness_scenes(fac):
    code = ("from pipeline.run import recipe_hash, ROOT; "
            "print(recipe_hash(ROOT / 'spec' / 'packs' / 'ui_sfx_v1.yaml'))")
    before = py(fac, code)
    for path in (fac / "pipeline" / "audio_io.py", fac / "godot_harness" / "preview.tscn"):
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        after = py(fac, code)
        assert after != before, path.name
        before = after


def test_a_gate_crash_fails_that_asset_only(fac):
    """One broken asset must not abort the build: it fails with a gate_error and its attempt counts."""
    assert cli(fac, "new", "--kind", "ui_sfx", "--id", "t_sfx").returncode == 0
    pack = ("--pack", "spec/packs/t_sfx.yaml")
    gates = fac / "pipeline" / "gates" / "audio.py"
    gates.write_text(gates.read_text(encoding="utf-8") + "\n\ndef _boom(*a, **k):\n    raise RuntimeError('gate exploded')\n"
                     "check = _boom\n", encoding="utf-8")
    r = cli(fac, "build", *pack, "--json")
    ev = events(r)
    gate_events = [e for e in ev if e["event"] == "gate"]
    assert gate_events and all(not e["ok"] for e in gate_events), r.stdout + r.stderr
    assert all(e["failed"][0]["gate"] == "gate_error" and "gate exploded" in e["failed"][0]["measured"] for e in gate_events)
    assert ev[-1] == {"event": "done", "cmd": "build", "exit": 0}
