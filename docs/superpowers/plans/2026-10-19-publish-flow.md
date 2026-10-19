# Publish Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish end to end from the Studio: button → dry-run preview dialog (target, channels, file hashes) → typed confirm → CLI `publish` → butler, with a butler-login setup card and a job log file per job.

**Architecture:** The CLI already refuses unsafe publishes and records `releases`. This step adds the file hash to its `push` event, lets the service run `publish --dry-run` without a confirm, writes every job's events to `factory/build/<pack>/jobs/<timestamp>.log`, and adds the Publish dialog and a releases table to the Studio pack page.

**Tech Stack:** Python CLI (`factory/pipeline/run.py`, pytest), Node service (`desktop/service/factory.mjs`, `node:test`), React (`src/studio/`), Playwright UI test.

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` — §2 (publish), §3 (confirm rule), §4 (Publish dialog), §7 (butler not logged in, job logs), §8 (Release: first real push only with the user watching). Earlier plans: `2026-10-18-factory-service.md`, `2026-10-18-studio-view.md`.

## Global Constraints

- Never run a real butler push, in tests or while developing. Tests stub the CLI (service, UI) or butler (pytest stub from step 2). The first real push is the user's, watching, to a draft/restricted itch page.
- A real publish still requires `{confirm: "<itch.user>/<pack>"}` matching the merged config (unchanged step-3 rule). Only `{dryRun: true}` skips the confirm, and it always passes `--dry-run`.
- The dialog's confirm text is typed by the user; the Publish button stays disabled until it equals `<user>/<pack>` (user taken from the dry-run `push` target).
- Python is the only DB writer; the service only adds log files under `factory/build/`.
- Run Python with `PY_PYTHON3=3.12` on this machine.

## Decisions (spec silent)

- **Dry run as preview:** the dialog runs `publish --dry-run` first. Its `refused` event (not approved, zip stale, recipe changed…) is shown instead of the confirm field, so the user sees why before typing anything.
- **Hashes:** the CLI's `push` event gains `sha256` (zip hash, or `dir_sha256` for `web_demo`) — the same value the `releases` row stores.
- **Butler not logged in:** a failed publish whose `error` event message matches `/login|credentials|api key/i` shows a setup card: "Run `butler login` in a terminal, then publish again."
- **Job logs:** every job (all commands) appends one JSON line per event to `factory/build/<pack>/jobs/<YYYYMMDD-HHMMSS>-<cmd>.log`; the service creates the folder. Logs are gitignored (under `build/`).
- **Deferred:** parsing butler's build id into `releases.butler_build` (output format unverified without a real push) and the Ask-agent draft.

## Review Focus

1. Dry run succeeds, then the user rebuilds before confirming → the real publish is refused by the CLI (recipe changed); the dialog shows that refusal, not a success.
2. Confirm typed with surrounding spaces or different case → button stays disabled; the service compares exactly.
3. A real publish where the first channel pushes and the second fails → log shows `pushed` for one and the error for the other; releases table shows only the pushed one after refresh.
4. Job log folder missing or not writable → the job still runs and streams; logging failure is reported once as a `stderr`-style log line, never a crash.
5. Closing the dialog while a publish runs → the job keeps running (job store), the log stays visible on the pack page.

---

### Task 1: CLI push event carries the file hash

**Files:** Modify `factory/pipeline/run.py` (the `emit(... "push", ...)` call in `cmd_publish`), `factory/tests/test_publish.py` (`test_dry_run_prints_commands_only`).

- [ ] **Step 1: Failing test** — in `test_dry_run_prints_commands_only` add: `assert pushes[0]["sha256"] == sha256_of(z)` (hashlib over the zip bytes) and `assert len(pushes[1]["sha256"]) == 64`.
- [ ] **Step 2: Run** `npm run test:factory` → that test FAILS (`KeyError: 'sha256'`).
- [ ] **Step 3: Implement** — pass `sha256=file_sha` to the `push` emit.
- [ ] **Step 4: Run** `npm run test:factory` → all pass.
- [ ] **Step 5: Commit** `feat(factory): push events carry the file hash`.

### Task 2: Service — dry run without confirm, job log files

**Files:** Modify `desktop/service/factory.mjs`, `desktop/service/test/factory.test.mjs`, `desktop/service/test/fixtures/factory-cli-stub.mjs`.

**Interfaces:** POST `/factory/packs/:id/publish` with `{dryRun: true}` → spawns `... publish --pack ... --json --dry-run`, no confirm, still needs Python + `tools.butler` + `itch.user` (424 otherwise). Any other body → unchanged step-3 rules.

- [ ] **Step 1: Failing tests**
  - `publish dry run needs no confirm` — POST `{dryRun: true}` → 200; stub log last call `['publish','--pack','spec/packs/ui_sfx_v1.yaml','--json','--dry-run']`. POST `{dryRun: 'yes'}` → 400 (must be boolean `true`) — and nothing spawned.
  - `real publish never gets --dry-run and dry run never skips the stub log` — POST `{confirm: 'me/ui_sfx_v1'}` → last call has no `--dry-run`.
  - `every job writes a log file` — after a `build`, `factory/build/ui_sfx_v1/jobs/` holds one file whose name ends `-build.log`, whose lines parse as JSON and whose last line is the `done` event.
- [ ] **Step 2: Run** `node --test desktop/service/test/factory.test.mjs` → new tests FAIL.
- [ ] **Step 3: Implement** — `dryRun === true` branch; `fs.createWriteStream` (append, `mkdir -p` first) fed by `send`, closed in the existing `finally`; a stream error is swallowed after one `{event:'stderr', msg:'job log not written: …'}` frame.
- [ ] **Step 4: Run** → all pass.
- [ ] **Step 5: Commit** `feat(service): publish dry run and per-job log files`.

### Task 3: Studio — Publish dialog, butler login card, releases

**Files:** Create `src/studio/PublishDialog.tsx`; Modify `src/studio/PackPage.tsx`, `src/studio/api.ts` (`JobCommand` gains `'publish'`), `src/studio/studio.css`, `desktop/service/test/fixtures/factory-cli-stub.mjs` (publish behaviour), `desktop/service/test/studio-ui.mjs`.

**Interfaces:** `PublishDialog({ id, onClose }: { id: string; onClose: () => void })`, rendered as a native `<dialog>` opened with `showModal()`.

- Stub behaviour for `publish`: with `--dry-run` print two `push` events (`{event:'push', channel:'godot-addon', target:'me/<pack>:godot-addon', sha256:'a'*64, dry_run:true}` and the `html5` one), then done 0. Without it: `STUB_MODE=nologin` → `{event:'error', message:'Please run butler login first', channel:'godot-addon'}` + done 1; else `pushed` events + done 0. `STUB_MODE=refused` → `{event:'refused', reason:'not approved: hover'}` + done 1 for both.

- [ ] **Step 1: Failing UI test**
  - click `Publish…` → dialog (`role="dialog"`, name `Publish ui_sfx_v1`) lists `godot-addon`, `html5`, the target `me/ui_sfx_v1`, and the 64-char hash.
  - `Publish` button disabled; type `me/ui_sfx_v1 ` (trailing space) → still disabled; type exactly `me/ui_sfx_v1` → enabled; click → log shows `pushed`; stub log has `publish` without `--dry-run`, after the dry-run call.
  - `STUB_MODE=refused`: open dialog → shows `not approved: hover`, no confirm field.
  - `STUB_MODE=nologin`: publish → `role="alert"` containing `butler login`.
  - pack page shows a `Releases` table (`aria-label="Releases"`) with the fixture's `me/ui_sfx_v1` row.
- [ ] **Step 2: Run** `npm run build && node desktop/service/test/studio-ui.mjs` → FAILS.
- [ ] **Step 3: Implement**
  - Toolbar `Publish…` (disabled while a job runs) opens the dialog.
  - Dialog on open: `runJob(id, 'publish', { dryRun: true }, collect)` (not through the job store: a preview is not a job the pack page should show). Shows channels, targets, `sha256` (monospace, first 12 chars + full value in `title`), or the refusal / setup card. Confirm input + `Publish` (`startJob(id, 'publish', { confirm })`, then close the dialog — the log continues on the pack page).
  - `JobError`/log: the butler-login card when a `publish` job's `error` event matches `/login|credentials|api key/i`.
  - Releases table: channel, target, `file_sha256` (12 chars), `created_at`.
- [ ] **Step 4: Verify everything** — `npm run lint`, `npm run build`, `node desktop/service/test/studio-ui.mjs`, `node --test desktop/service/test/factory.test.mjs`, `npm run test:factory`, `npm run test:template`.
- [ ] **Step 5: Commit** `feat(studio): publish dialog with dry-run preview, typed confirm and releases`.
