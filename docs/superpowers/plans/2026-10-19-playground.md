# Asset Playground Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Godot 4.5 walkaround scene that loads every approved, packaged pack, opened from the Studio with one button.

**Architecture:** `playground/` is a small Godot project. A new CLI command `run.py playground [--open] --json` picks the packs (DB read + staged addon present), runs `playground/tools/sync_packs.gd` headless to copy them into `playground/addons/`, imports, runs a headless load check, and with `--open` launches Godot detached on the project. The service exposes it as `POST /factory/playground` (SSE, like other jobs); the Studio pack list gets an **Open in playground** button. The service never spawns Godot itself — it only runs the CLI, as before.

**Tech Stack:** Godot 4.5 (GDScript), Python CLI + pytest, Node service + `node:test`, React + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` §6 (playground), §8 (Playground test: headless load of all synced packs with zero errors). Earlier plans: `2026-10-18-factory-service.md`, `2026-10-18-studio-view.md`, `2026-10-19-publish-flow.md`.

## Global Constraints

- Godot from `tools.godot` in the merged `global.yaml` + `global.local.yaml` (the `_console` exe). Python with `PY_PYTHON3=3.12`.
- A pack is synced only if every non-rejected asset is `approved` **and** `factory/dist/<pack>/addons/<pack>/manifest.json` exists (packaged).
- `playground/addons/`, `playground/.godot/` and `*.uid` under `playground/` are gitignored; only sources are committed.
- Content placement in this step: spatial `.gdshader` → a sphere on a pedestal; `AudioStreamRandomizer` `.tres` with `foot`/`step` in its name → the player's footsteps, every other randomizer → a button in an on-screen sound panel. Other content (VFX scenes, UI themes, mesh kits) is out of scope ("later" in the spec).
- No butler, approve or publish anywhere in this step.

## Decisions (spec silent)

- **Selection lives in the CLI**, since it needs the DB; `sync_packs.gd` only copies the directories it is given and removes addons it synced earlier that are no longer listed (tracked in `playground/addons/.factory_synced.json`). Hand-installed addons are never touched.
- **"Launch Godot on the project"** = run the game (`godot --path playground`), detached, so closing the Studio leaves it running. The editor is one click away from there.
- **Load check** = `playground/tools/check.gd`: instantiate `Playground.tscn`, run 3 frames, print one JSON line `{"shaders":N,"sounds":M}`; the CLI fails the command if Godot's stderr contains `ERROR` or `SCRIPT ERROR`, or the JSON line is missing.
- Service route is global, not per pack: `POST /factory/playground {open?: boolean}`, lock key `@playground`, tool `godot` (424 when missing).

## Review Focus

1. No packs qualify → command succeeds, playground opens empty with a "No approved, packaged packs yet" label; the sync removes previously synced addons.
2. A previously synced pack loses approval → it disappears from `playground/addons/` on the next sync.
3. A hand-installed addon in `playground/addons/` (not in `.factory_synced.json`) survives every sync.
4. A shader that fails to compile in the playground → check fails, the CLI exits 1, `--open` does not launch.
5. Pack id with an existing `playground/addons/<id>` from a stale run with fewer files → old files removed (copy replaces the whole folder).

---

### Task 1: Godot playground project with headless load check

**Files:**
- Create: `playground/project.godot` (Godot 4.5, main scene `res://Playground.tscn`, `forward_plus`), `playground/Playground.tscn`, `playground/playground.gd`, `playground/player.gd`, `playground/tools/sync_packs.gd`, `playground/tools/check.gd`
- Modify: `.gitignore` (`playground/addons/`, `playground/.godot/`, `playground/**/*.uid`)
- Create: `factory/tests/test_playground.py`

**Interfaces (Produces):**
- `sync_packs.gd` usage: `godot --headless --path playground --script res://tools/sync_packs.gd -- <abs addon dir>...`; prints `synced <id>` per pack, `removed <id>` per dropped pack, and `err=0` last on success.
- `check.gd` usage: `godot --headless --path playground --script res://tools/check.gd`; prints `{"shaders":N,"sounds":M}`.
- `playground.gd` (root `Node3D`): on `_ready`, scans `res://addons/*/` (skipping dot entries) for `shaders/*.gdshader` and `*.tres`; spheres on a 3 m pedestal grid with a `Label3D` (shader file name) each; sound panel (`CanvasLayer` → `VBoxContainer` of `Button`s named after the randomizer); empty-state `Label`. Exposes `shader_count` and `sound_count`.
- `player.gd` (`CharacterBody3D`, capsule, `SpringArm3D` + `Camera3D`): WASD/arrows + mouse look (captured on click, released on Esc), gravity, plays `footsteps` (an `AudioStreamPlayer3D`) every 0.45 s while moving on floor when a footstep randomizer was assigned by `playground.gd`.

- [ ] **Step 1: Failing test** `test_playground_loads_synced_addons` (skipped when `global_spec()["tools"]["godot"]` does not exist): copy `playground/` to `tmp_path`, write a fixture addon `fx_pack/shaders/glow.gdshader` (`shader_type spatial; uniform vec4 c : source_color = vec4(1.0); void fragment(){ ALBEDO = c.rgb; }`) and `fx_pack/manifest.json`; run `sync_packs.gd` with that dir, then `--import`, then `check.gd`. Assert `synced fx_pack` and `err=0`, check prints `{"shaders":1,"sounds":0}`, stderr has no `ERROR`. Second run with no dirs → `removed fx_pack`, `addons/fx_pack` gone; a hand-made `addons/keep_me/plugin.cfg` still exists.
- [ ] **Step 2: Run** `npm run test:factory` → FAIL (no `playground/`).
- [ ] **Step 3: Implement** the project files above. `sync_packs.gd` copies recursively with `DirAccess` (remove destination first), writes `.factory_synced.json`, exits with `quit(0)`/`quit(1)`.
- [ ] **Step 4: Run** `npm run test:factory` → all pass. Also run the scene once by hand: `godot --path playground` (no packs) and confirm walking and the empty-state label.
- [ ] **Step 5: Commit** `feat(playground): Godot walkaround scene, sync and headless check`.

### Task 2: CLI `playground` command

**Files:** Modify `factory/pipeline/run.py` (`cmd_playground(con, open_after: bool) -> int`, argparse: `playground` added to `cmd` choices, `--open` flag, no `--pack` required), `factory/tests/test_playground.py`.

**Interfaces:** events `{"event":"playground","packs":[ids]}`, `{"event":"synced","pack":id}`, `{"event":"check","shaders":N,"sounds":M}`, `{"event":"opened","path":...}`; refusal-free (no packs is fine). Exit 1 when sync or check fails.

- [ ] **Step 1: Failing tests** (stub godot: a Python script recording argv, set via the temp copy's `global.local.yaml`, like `test_publish.py`):
  - `test_playground_selects_only_approved_packaged` — packs: A all approved + staged manifest, B approved but no `dist/B/addons/B`, C one `passed` asset + staged → sync call args contain only A's addon dir.
  - `test_playground_open_launches_detached_only_after_check` — stub check prints the JSON line → with `--open` the last stub call is `["--path", <playground>]`; stub check printing `ERROR: boom` on stderr → exit 1 and no `--path` launch call.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — DB query + `Path.exists`; `subprocess.run` for sync/import/check (`stdin=DEVNULL`, `timeout=600`); `--open` via `subprocess.Popen([godot, "--path", playground], stdin/stdout/stderr=DEVNULL, creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP on Windows, start_new_session=True elsewhere)`. `PLAYGROUND = ROOT.parent / "playground"`.
- [ ] **Step 4: Run** `npm run test:factory` → all pass.
- [ ] **Step 5: Commit** `feat(factory): playground command syncs approved packs and opens Godot`.

### Task 3: Service route and Studio button

**Files:** Modify `desktop/service/factory.mjs`, `desktop/service/test/factory.test.mjs`, `desktop/service/test/fixtures/factory-cli-stub.mjs` (`playground` → `playground` + `check` events, done 0), `src/studio/api.ts` (`runPlayground(open, onEvent)` or `runJob` generalised to a path), `src/studio/jobs.ts`, `src/studio/Studio.tsx`, `desktop/service/test/studio-ui.mjs`.

**Interfaces:** `POST /factory/playground` body `{open?: boolean}` (non-boolean → 400) → spawns `run.py playground --json [--open]` with cwd repo; lock key `@playground` (409 while running); 424 when `tools.godot` is missing; job log under `factory/build/@playground/jobs/` → use `factory/build/_playground/jobs/` (no `@` in folder names).

- [ ] **Step 1: Failing tests**
  - service: `playground runs the CLI without a pack` — POST `{open:true}` → 200, stub log last call `['playground','--json','--open']`; `{open:'yes'}` → 400; godot missing → 424 `tool:'godot'`; second concurrent call → 409.
  - UI: on the pack list, `Open in playground` → log shows `done (exit 0)`; stub log has `playground` with `--open`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — reuse the job runner by passing `{ key, cmd, args, tool, logDir }` into the existing spawn/stream code (extract that part of `startJob` into `runCli(response, job, args, logDir)`); Studio: job store keyed `@playground`, button + log above the pack list.
- [ ] **Step 4: Verify everything** — `node --test desktop/service/test/factory.test.mjs`, `npm run lint`, `npm run build`, `node desktop/service/test/studio-ui.mjs`, `npm run test:factory`, `npm run test:template`.
- [ ] **Step 5: Commit** `feat(studio): open in playground`.
