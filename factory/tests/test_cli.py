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
