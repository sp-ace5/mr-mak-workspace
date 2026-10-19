# Asset Factory Step 2 (Pipeline CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the parked step-1 fixes and add the spec section 2 CLI surface (`--json`, `new`, `listing`, `publish`) so the step-3 service can drive the factory as a subprocess.

**Architecture:** Everything stays in `factory/pipeline/run.py` (one file, existing style). Human `print` calls become `emit(text, event, **fields)`, which prints the text, or one JSON object per line under `--json`. `publish` shells out to the butler path from the merged global config; tests point that path at a stub script through a test-only `spec/global.local.yaml` in the temp factory copy.

**Tech Stack:** Python 3.12 (`PY_PYTHON3=3.12`), pyyaml, sqlite3, pytest; Node scripts `npm run test:factory`, `npm run test:template`.

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` (section 2, section 8 Python tests)

## Global Constraints

- Python CLI is the only `factory.db` writer.
- `--json`: one JSON object per stdout line; last line `{"event":"done","cmd":"<cmd>","exit":<n>}`. Human output unchanged without the flag.
- `new --kind <shader|ui_sfx|inbox_mesh> --id <pack>` writes `spec/packs/<pack>.yaml`; refuses to overwrite.
- `listing --pack` writes `dist/<pack>/listing.md`: title, short description, body from README + VERIFY summary, itch AI-disclosure from `disclosure.itch_ai_tags`, file list, suggested price from `spec.price_usd` (default none).
- `publish --pack [--dry-run]`: exit 1 with reason unless `report` exits 0, every non-rejected asset is `approved`, the addon zip exists. Pushes `butler push <zip> <itch.user>/<pack>:godot-addon` and, if present, `butler push dist/<pack>/web_demo <itch.user>/<pack>:html5`. Records each push in `releases` (DDL verbatim from spec). `--dry-run` prints the exact commands, pushes nothing.
- Never run a real `butler push`; tests use a stub butler. Agents never run `approve`/`publish` on real packs.
- Tests never write to the real `factory/factory.db`, `factory/build/`, `factory/dist/`, `factory/spec/`.

## Decisions (defaults taken; say if you want otherwise)

- `itch.user` lives in `global.yaml` as `itch: {user: ''}`; the real value goes in gitignored `spec/global.local.yaml`. Overlay = recursive dict merge, lists replaced.
- `publish` also refuses when `itch.user` is empty, butler path does not exist, or the spec/recipe changed since the last build (`recipe_hash(spec) != packs.spec_hash`) — stale gate results must not ship.
- `releases.butler_build` stored NULL (butler output format not pinned yet; step 5 fills it). `file_sha256` for the html5 channel = hash of the sorted (relpath, bytes) of `web_demo/`.
- Export templates: `<data dir>/Godot/export_templates/<X.Y>.stable/web_nothreads_release.zip`, where data dir = `%APPDATA%` (Windows), `~/Library/Application Support` (macOS), `$XDG_DATA_HOME` or `~/.local/share` (Linux, lowercase `godot`), and `X.Y` from `engine_target`.
- `new` templates are inline strings in `run.py`; `--id` must match `[a-z][a-z0-9_]*`.

## Review Focus

1. A real build in the user's checkout (`factory/build/ui_sfx_v1` exists) → tests still pass. Snapshot test in Task 1.
2. User's real `global.local.yaml` (with real butler path) leaking into the temp test copy → test copy ignores it. Task 1 IGNORE + Task 4 stub.
3. Exception mid-command under `--json` → stdout still ends with a `done` event, `exit: 1`; traceback on stderr. Task 2.
4. `publish` with a butler failure on the first push → exit 1, no `releases` row. Task 4.
5. `new --id ../evil` → refused, nothing written outside `spec/packs/`. Task 3.

---

### Task 1: Parked step-1 fixes

**Files:** Modify `factory/pipeline/run.py` (`global_spec`, `web_demo`), `factory/spec/global.yaml`, `.gitignore`, `factory/tests/test_smoke.py`.

**Interfaces — Produces:** `global_spec() -> dict` (global.yaml deep-merged with optional global.local.yaml); `export_template(engine_target: str) -> pathlib.Path`.

- [ ] Test: replace the absence asserts in `test_ui_sfx_pack_ships_from_repo_root` with `snapshot()` = `{relpath: st_mtime_ns}` of every file under real `factory/build`, `factory/dist`, plus `factory/factory.db`; assert equal before/after the init→report run. Fold `test_tests_never_touch_real_db` into it (keep the `t.db exists` assert). Add `global.local.yaml` to the copy IGNORE.
- [ ] Test `test_global_local_overlay`: write `spec/global.local.yaml` with `tools: {butler: X}` in the temp copy; a `python -c` importing `pipeline.run` prints `global_spec()`; butler is X and godot unchanged.
- [ ] Implement overlay; add `factory/spec/global.local.yaml` to `.gitignore`; add `itch: {user: ''}` to `global.yaml`.
- [ ] `web_demo(stage_dir, pack, godot)`: use `export_template(pack["engine_target"])`; absent → `SKIP web demo: no export templates at <dir>` and return. No `os.environ["APPDATA"]` KeyError on non-Windows.
- [ ] `npm run test:factory` green; commit `fix(factory): snapshot-based smoke test, per-OS export templates, global.local.yaml overlay`.

### Task 2: `--json` events

**Files:** Modify `factory/pipeline/run.py`; Test `factory/tests/test_cli.py` (new).

**Interfaces — Produces:** `emit(text: str, event: str = "log", **fields)`; event names: `db` (init), `gate` (`asset, ok, failed:[{gate,measured,expected}]`), `wait` (`asset`), `approved` (`count`), `report` (`passed,total,blockers,path`), `packaged` (`path,assets`), `skip`, `created` (`path`), `listing` (`path`), `refused` (`reason`), `push` (`channel,target,cmd,dry_run`), `error` (`message`), `done` (`cmd,exit`). Every JSON event also carries `msg` = the human text. `main()` returns exit code; `--pack` optional for `new` only.

- [ ] Test `test_build_json_events`: `new --kind ui_sfx --id t_sfx` then `init`, `build --json` in the temp copy; every stdout line `json.loads`; ≥1 `gate` event with keys `asset, ok, failed`; last line `{"event":"done","cmd":"build","exit":0}`.
- [ ] Test `test_human_output_unchanged`: same build without `--json` → lines start with `PASS ` / `FAIL `, no `{`.
- [ ] Test `test_json_error_still_done`: `report --json --pack spec/packs/ui_sfx_v1.yaml` against a fresh, uninitialised DB (no tables) → last stdout line is `done` with `exit: 1`.
- [ ] Implement; uncaught exceptions → traceback to stderr, `error` event, exit 1.
- [ ] Green; commit `feat(factory): --json event stream on every command`.

### Task 3: `new` and `listing`

**Files:** Modify `factory/pipeline/run.py`; Test `factory/tests/test_cli.py`.

**Interfaces — Produces:** `cmd_new(kind, pack_id) -> int`; `cmd_listing(con, pack) -> int`. `ui_sfx` template: category audio, ui_sfx_v1 budgets, one `click` group with `variations: 2` (fast tests rely on it).

- [ ] Tests: `test_new_writes_spec` (file exists, `yaml.safe_load` has `pack_id == id`, category matches kind for all 3 kinds); `test_new_refuses_overwrite` (second call exit 1, bytes unchanged); `test_new_rejects_bad_id` (`../evil`, `Bad`) exit 1, nothing written.
- [ ] Test `test_listing`: t_sfx pack with `price_usd: 4.99` and `title`, init/build/approve, fake README at `dist/<id>/addons/<id>/README.md`, fake zip with one member → `listing.md` contains the title, `$4.99`, `code` (itch tag), the zip member name, the VERIFY `- Assets:` line, README text. Without `price_usd` → `Suggested price: none`.
- [ ] Implement. `listing` runs `cmd_report` first (fresh VERIFY.md); title = `spec.title` or pack_id; short description = `spec.description` or disclosure text first sentence; file list = zip members or `(not packaged yet)`.
- [ ] Green; commit `feat(factory): new and listing commands`.

### Task 4: `publish` + `releases`

**Files:** Modify `factory/pipeline/run.py`, `factory/pipeline/schema.sql`; Test `factory/tests/test_publish.py`.

**Interfaces — Consumes:** `global_spec()`, `cmd_report`, `recipe_hash`. **Produces:** `cmd_publish(con, pack, spec_path, dry_run: bool) -> int`; `releases` table.

- [ ] Fixture: temp copy, `global.local.yaml` with `itch: {user: tester}` and `tools.butler` = stub (`butler.cmd` → `python stub.py %*` on Windows, `#!/bin/sh` script elsewhere); stub appends argv to `calls.txt`, exit code from env `STUB_EXIT` (default 0). Pack t_sfx built.
- [ ] Refusal tests (exit 1, `refused` reason substring, `calls.txt` absent, 0 releases): `unapproved` (not approved), `blocker` (approved, then `UPDATE provenance SET license_id='unknown'` → `report`), `missing zip` (`zip`), `no itch.user`, `stale spec` (edit spec after build → `rebuild`).
- [ ] `test_dry_run`: approved + fake zip + fake `web_demo/index.html` → stdout has both exact commands `<butler> push <zip> tester/t_sfx:godot-addon` and `… web_demo tester/t_sfx:html5`; no calls, 0 releases.
- [ ] `test_publish_records_releases`: both pushes in `calls.txt`, 2 rows with channel, target, sha of the zip, spec_hash = packs.spec_hash. Without web_demo → 1 call, 1 row.
- [ ] `test_publish_butler_failure`: `STUB_EXIT=1` → exit 1, 0 rows.
- [ ] Implement; add DDL to `schema.sql`; `publish` runs the schema script first so pre-step-2 DBs gain the table.
- [ ] Green; commit `feat(factory): publish via butler with refusals and releases table`.

### Task 5: Docs + final checks

**Files:** `.agents/skills/asset-factory/SKILL.md` (+ `npm run skills:sync`), `processes/asset-factory.md`.

- [ ] Document `--json`, `new`, `listing`, `publish --dry-run`, `global.local.yaml`; keep "never run approve or publish".
- [ ] `npm run test:factory` and `npm run test:template` green; commit `docs(factory): CLI step 2 commands`.
- [ ] Ask the user, then push `feat/factory-cli` and open a PR into the fork's `main` (stacked on PR #1).
