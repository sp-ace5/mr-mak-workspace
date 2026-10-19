# Studio View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An **Asset Studio** view in the desktop Workspace window: pack list, pack page with gate table, audio and preview frames, VERIFY.md, and Build / Approve / Package / Copy listing / Open web demo actions with a live job log.

**Architecture:** New `src/studio/` (React, lazy-loaded) talks to the step-3 `/factory/*` routes with the desktop bearer token. Media and documents go through the existing `/api/preview` (token-free content-server grant URLs) and the existing `FilePreview` pane (`setPreview`). Small hooks only in `App.tsx`, `Sidebar.tsx`, `desktop/client.ts` and `server.mjs`.

**Tech Stack:** React 19 + TypeScript (Vite), Playwright UI test in the style of `desktop/service/test/*-ui.mjs`, `node:test`.

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` — section 4 (Studio view), section 7 (error handling), section 8 (UI test). Service contract: `docs/superpowers/plans/2026-10-18-factory-service.md` ("Decisions made here").

## Global Constraints

- Desktop only (`isDesktop`); the plain web/mobile builds never show the Studio.
- Agents must not run `approve` or `publish`; in tests the CLI is a node stub. No Publish button in this step (step 5).
- **Ask agent** is deferred (no Workspace→Chats draft channel exists yet).
- Route: `#/@studio` (pack list) and `#/@studio/<pack_id>` (pack page). `@` cannot collide with a workspace card id.
- Media (`.wav`, `.png`) and `index.html` are shown through `api('/preview?path=<absolute>')` URLs, not `/factory/file` (an `<audio>`/`<img>` tag cannot send the bearer token). This replaces the blob-URL idea from brainstorming: same outcome, zero new code.
- Status chips: `pending`, `failed`, `passed`, `approved`, `rejected` counts from `counts`, plus `shipped` when `last_release` is set.
- Job events (SSE, step 3): last frame is always `done`; `exit !== 0` is failure. 409 → "A job is already running for this pack". 424 → setup card showing `tool` and `path`. 503 `{retry:true}` → keep the last data, retry on the next poll.
- Poll `GET /factory/packs` (list) and `GET /factory/packs/:id` (page) every 5 s while visible, and once after every job ends.

## Review Focus

1. Pack page while a job runs and the user navigates away and back → job log keeps streaming (job state lives in a module-level store keyed by pack id, not in the component).
2. Asset with `output_path` null (never built) → row renders with "not built", no audio element, no crash.
3. `factory.db` missing (fresh checkout) → list shows "No packs yet — create one with `run.py new`", not an error.
4. CLI fails before any JSON (argparse, missing Python) → log shows the stderr lines and a red "failed (exit N)" line.
5. Long job output → log keeps the last 500 events and stays scrolled to the bottom.

---

### Task 1: Studio route, pack list, shared fixture

**Files:**
- Create: `desktop/service/test/fixtures/factory-fixture.mjs` — `export async function writeFactoryFixture(factoryDir: string, repoRoot: string): Promise<void>` (moved verbatim from `fixture()` in `factory.test.mjs`: DB rows, `dist/ui_sfx_v1/listing.md`, `build/ui_sfx_v1/a.wav`, `spec/packs/ui_sfx_v1.yaml`; additionally `dist/ui_sfx_v1/VERIFY.md` = `# VERIFY ui_sfx_v1`, and assets `click.output_path` = absolute path of `build/ui_sfx_v1/a.wav`, `hover.output_path` = null).
- Modify: `desktop/service/test/factory.test.mjs` (use the helper; behaviour unchanged)
- Modify: `desktop/service/server.mjs` — `createService({ ..., factoryOptions })` spreads `factoryOptions` into `createFactory` (tests pass `runner`).
- Modify: `src/desktop/client.ts` — `export const authHeader = () => ({ Authorization: \`Bearer ${token}\` })`
- Create: `src/studio/api.ts`, `src/studio/Studio.tsx`, `src/studio/studio.css`
- Modify: `src/App.tsx` — lazy `Studio`; when `route.id === '@studio'` render `<Studio />` in `.content` instead of the report/home branch.
- Modify: `src/components/Sidebar.tsx` — when `isDesktop`, a first item in `.sidebar-list`: `<a href="#/@studio" className="sidebar-item studio-link">` with text `Asset Studio`, `aria-current` when active.
- Create: `desktop/service/test/studio-ui.mjs`; Modify: `package.json` (`desktop:test:ui` chain gets `&& node desktop/service/test/studio-ui.mjs`)

**Interfaces (Produces):**
- `src/studio/api.ts`:
  - `type PackSummary = { pack_id: string; category: string; counts: Record<string, number>; blockers: number; last_release: Release | null }`
  - `type Gate = { gate: string; passed: 0 | 1; measured: string | null; expected: string | null }`
  - `type Asset = { asset_id: string; name: string; kind: string; status: string; attempts: number; output_path: string | null; gates: Gate[] }`
  - `type Release = { channel: string; target: string; file_sha256: string; butler_build: string | null; created_at: string }`
  - `type PackDetail = PackSummary & { spec_hash: string; assets: Asset[]; provenance: object[]; releases: Release[] }`
  - `class FactoryError extends Error { status: number; body: Record<string, unknown> }`
  - `factory<T>(path: string): Promise<T>` — GET `/factory${path}` with `authHeader()`, throws `FactoryError` on non-2xx.
  - `runJob(pack: string, cmd: 'build'|'approve'|'package'|'listing', body: object, onEvent: (e: JobEvent) => void): Promise<JobEvent>` — POST, reads `response.body` as a stream, splits on `\n\n`, parses `data: ` frames, resolves with the final `done`; throws `FactoryError` for non-200.
  - `type JobEvent = { event: string; msg?: string; exit?: number; synthetic?: boolean; [k: string]: unknown }`
  - `factoryPath(repo: string, rel: string): string` — `repo + sep + 'factory' + sep + rel` using the separator found in `repo`.
- `Studio.tsx` default export reads `location.hash` (`#/@studio/<id>`) and listens to `hashchange`.

- [ ] **Step 1: Write failing UI test** `studio-ui.mjs` (pattern of `links-ui.mjs`: temp repo under `.cache/studio-ui-`, `workspace/workspace.json` with `{entities: []}`, `writeFactoryFixture(repo/factory)`, `createService({ repo, uiDir: root/dist, mcpOptions: {home, env: {}}, factoryOptions: { runner: [process.execPath, [stub]] } })`, `launchBrowser()`):
  - `page.goto(service.urls.workspace + '#/@studio')`; `getByRole('link', { name: 'Asset Studio' })` visible.
  - `getByRole('link', { name: /ui_sfx_v1/ })` visible; its row contains text `approved 1`, `failed 1`, `shipped`.
  - no `pageerror`.
- [ ] **Step 2: Run, verify fail** — `npm run build && node desktop/service/test/studio-ui.mjs` → fails waiting for "Asset Studio".
- [ ] **Step 3: Implement** fixture helper, `factoryOptions`, `authHeader`, `api.ts` (`factory`, `FactoryError`, types, `factoryPath`), `Studio.tsx` list (`<ul className="studio-packs">`, one `<a href="#/@studio/<id>">` row per pack: id, category, chips, blocker badge `N blockers` when > 0, last release target + date), empty and 503 states, hooks in `App.tsx`/`Sidebar.tsx`, `package.json` chain.
- [ ] **Step 4: Verify** — `node --test desktop/service/test/factory.test.mjs` (11 pass), `npm run build` (tsc clean), `npm run lint`, `node desktop/service/test/studio-ui.mjs` → exits 0.
- [ ] **Step 5: Commit** — `feat(studio): Asset Studio route and pack list`.

### Task 2: Pack page — gates, audio, frames, VERIFY.md

**Files:**
- Create: `src/studio/PackPage.tsx`; Modify: `src/studio/Studio.tsx`, `src/studio/studio.css`, `desktop/service/test/studio-ui.mjs`

**Interfaces:**
- Consumes: `factory`, `PackDetail`, `factoryPath`, `useDesktop().repo`, `api('/preview?path=')` → `Preview` (`src/desktop/types.ts`), `api('/files?path=')` for frame folders, `MarkdownView` from `src/components/MarkdownDocument.tsx`.
- Produces: `PackPage({ id }: { id: string })`.

- [ ] **Step 1: Extend UI test**
  - click the `ui_sfx_v1` link → URL hash `#/@studio/ui_sfx_v1`; `getByRole('heading', { name: 'ui_sfx_v1' })`.
  - `getByRole('table', { name: 'Assets' })` has rows `click` (status `approved`) and `hover` (status `failed`); the `hover` row shows `peak`, `0`, `<=-1`.
  - `page.locator('audio').count()` === 1 and its `src` starts with the content-server origin (`/view/`).
  - `getByRole('heading', { name: 'VERIFY ui_sfx_v1' })` visible.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `PackPage`**
  - Asset table (`<table aria-label="Assets">`): checkbox (enabled only for `passed`), name, kind, status chip, attempts, failed gates as `gate: measured (expected expected)` lines, media cell.
  - Media cell: `.wav` → `<audio controls preload="none" src={preview.url}>`; shader assets → up to 3 PNG thumbnails from `build/<pack>/preview/<name>/<renderer>/` (first, middle, last of the sorted `*.png` from `/api/files`), each clickable to `setPreview`. `output_path` null → "not built".
  - Preview URLs fetched once per `output_path` and cached in a `Map` inside the module.
  - VERIFY section: `api('/preview?path=' + factoryPath(repo, 'dist/<id>/VERIFY.md'))`, `kind === 'text'` → `<MarkdownView text={preview.text} />`; missing → "Run Build to write VERIFY.md".
  - Back link `← All packs` to `#/@studio`.
- [ ] **Step 4: Verify** — `npm run build`, `npm run lint`, `node desktop/service/test/studio-ui.mjs` → exits 0.
- [ ] **Step 5: Commit** — `feat(studio): pack page with gates, audio, frames and VERIFY`.

### Task 3: Actions and live job log

**Files:**
- Create: `src/studio/jobs.ts`; Modify: `src/studio/PackPage.tsx`, `src/studio/studio.css`, `desktop/service/test/studio-ui.mjs`

**Interfaces:**
- Consumes: `runJob`, `FactoryError`, `setPreview`, `api`.
- Produces `src/studio/jobs.ts`: `startJob(pack, cmd, body?): void`, `useJob(pack): { cmd: string; events: JobEvent[]; running: boolean; result: JobEvent | null; error: FactoryError | null } | null` (module-level `Map` + `useSyncExternalStore`, keeps last 500 events).

- [ ] **Step 1: Extend UI test** (stub `STUB_MODE=ok`, `STUB_LOG` in the temp repo)
  - click `Build` → log (`role="log"`) shows `not json`, `warn`, and a line `done (exit 0)`; `Build` is disabled while running and enabled after.
  - the `click` row's checkbox is disabled (already `approved`); `Approve selected` is disabled with nothing selected.
  - set `STUB_MODE=argparse`, click `Package` → log shows `usage:` and `failed (exit 2)` styled `.job-failed`.
  - set the stub config `tools.godot` to a missing path, click `Build` → setup card (`role="alert"`) contains `godot` and the missing path.
  - stub log contains `["build","--pack","spec/packs/ui_sfx_v1.yaml","--json"]` and never `approve` or `publish`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - Toolbar: `Build`, `Approve selected` (names of checked rows), `Approve all passed` (names of all `passed` assets; disabled when none), `Package`, `Copy listing` (runs `listing`; on `exit 0` reads `dist/<id>/listing.md` via `/api/preview` and `navigator.clipboard.writeText`, then shows "Listing copied"), `Open web demo` (enabled when `dist/<id>/web_demo/index.html` previews; `setPreview(preview)`). All disabled while this pack's job runs.
  - Approve buttons confirm with `window.confirm('Approve N assets in <pack>?')` — approving is a user decision.
  - Log: one line per event — `msg` when present, else compact JSON; `stderr` lines dimmed; final `done` line `done (exit 0)` or `failed (exit N)` with `.job-failed`. Auto-scroll to bottom.
  - Errors: 424 → setup card `"<tool> not found at <path> — set it in factory/spec/global.local.yaml"` (`python`: "Install Python 3"); 409 → inline "A job is already running for this pack"; other → `reportError`.
  - After every job: refetch the pack.
- [ ] **Step 4: Verify everything**
  - `node --test desktop/service/test/factory.test.mjs` → 11 pass
  - `npm run build`, `npm run lint` → clean
  - `node desktop/service/test/studio-ui.mjs` → exits 0
  - `npm run test:factory`, `npm run test:template` → pass (PowerShell: `$env:PY_PYTHON3='3.12'`)
- [ ] **Step 5: Commit** — `feat(studio): build, approve, package, listing actions with live job log`.

## Environment note

UI tests run against `dist/` from `npm run build`, which needs root dependencies (`npm ci` at the repo root; `react` is currently missing on this machine) and the browser `desktop/service/test/browser.mjs` launches.
