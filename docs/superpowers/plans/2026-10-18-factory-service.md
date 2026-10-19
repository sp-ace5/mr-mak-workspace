# Factory Service Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/factory/*` routes in the desktop service: read `factory.db` read-only, serve build/dist files safely, and run factory CLI commands as SSE jobs.

**Architecture:** One new module `desktop/service/factory.mjs` exports `createFactory()`, whose `handle()` answers `/factory/*` and returns `false` for anything else. `server.mjs` gets a three-line hook behind the existing bearer-token `authorize()`. The Python CLI stays the only DB writer; the service spawns it and opens the DB with `node:sqlite` `readOnly`.

**Tech Stack:** Node ≥22 (`node:sqlite`, `node:child_process`, `node:test`), existing `util.mjs` / `files.mjs` helpers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` — section 3 (routes) and section 8 (Service tests).

## Global Constraints

- Python CLI is the only `factory.db` writer; the service opens it `readOnly`.
- Job command: `node scripts/run-python.mjs factory/pipeline/run.py <cmd> --pack spec/packs/<id>.yaml --json` (absolute paths for the script and run.py; `--pack` stays relative, run.py resolves it against `factory/`).
- One job per pack at a time; a concurrent request returns 409.
- A job without a `{"event":"done"}` line is a failure (covers argparse exit 2 and Ctrl-C).
- `publish` requires `{confirm: "<itch.user>/<pack>"}` equal to the target built from merged `global.yaml` + `global.local.yaml`.
- Missing tool → 424 `{error, tool, path}` with the configured path.
- `GET /factory/file` serves only under `factory/build/` and `factory/dist/`; resolve first, reject traversal and links leaving those roots.
- Tests never run real Python CLI commands, butler, approve or publish: the CLI is a node stub.
- Pack ids match `^[a-z][a-z0-9_]*$` (same rule as `run.py new`).

## Decisions made here (spec silent)

- **Auth:** `/factory/*` sits behind the same `authorize()` as `/api/*` (bearer token, host, origin). Spawning a CLI must never be unauthenticated.
- **Merged config:** read by running `run-python.mjs -c "<code>"` in `factory/` that prints `json.dumps(pipeline.run.global_spec())`. Exact merge semantics, no YAML dependency in Node. Costs one Python start per POST.
- **Tool per command:** `build`, `package` → `tools.godot`; `publish` → `tools.butler` and non-empty `itch.user`; any POST → Python itself (`run-python.mjs` exits 1 with "Python 3 not found"). `approve`, `listing` need no tool. `ponytail:` mesh packs also need Blender on build; add when the first mesh pack ships.
- **SSE frames:** every CLI stdout line becomes `data: <json>\n\n`. Non-JSON stdout → `{"event":"log","msg":line}`; stderr lines → `{"event":"stderr","msg":line}`. If the process exits without a done line, the service sends `{"event":"done","cmd":<cmd>,"exit":<code || 1>,"synthetic":true}`. Response always ends after the done frame.
- **Client disconnect:** the job keeps running and keeps its lock until the process exits (killing approve/publish halfway is worse than finishing).
- **SQLITE_BUSY:** 503 `{error, retry: true}`; the Studio retries on its next poll. Missing DB → `GET /factory/packs` returns `{packs: []}`.
- **Job logs** (`factory/build/<pack>/jobs/*.log`, spec §7) are deferred to step 5 (publish flow).

## Review Focus

1. URL-encoded traversal (`%2e%2e%2f`, `..\\` on Windows, absolute `C:\...`) on `/factory/file` → 403, never a file outside build/dist.
2. A junction/symlink inside `dist/` pointing outside → 403.
3. CLI that prints a done line and then exits nonzero, or exits 0 with no done line → treated as failure (`exit` ≠ 0 in the final frame).
4. Pack id like `../x` or `UI` in a POST URL → 400 before anything spawns.
5. `publish` with `itch.user` empty → 424 `tool: "itch.user"`, even when `confirm` is `"/<pack>"`.

---

### Task 1: Read routes and file route

**Files:**
- Create: `desktop/service/factory.mjs`
- Create: `desktop/service/test/factory.test.mjs`
- Create: `desktop/service/test/fixtures/factory-cli-stub.mjs` (used in Task 2; fixture helper writes the DB here)

**Interfaces:**
- Produces: `createFactory({ factoryDir: string, repo: string, runner?: [string, string[]], db?: string }) → { handle(request, response, url: URL): Promise<boolean>, close(): void }`.
  `runner` defaults to `[process.execPath, [path.join(repo, 'scripts/run-python.mjs')]]`; `db` defaults to `path.join(factoryDir, 'factory.db')`.
- Test helper in `factory.test.mjs`: `async function fixture(stubEnv = {})` → `{ root, factoryDir, url, close }` — temp dir under `<repo>/.cache/factory-test-*`, writes `factory/factory.db` by executing `factory/pipeline/schema.sql` with `DatabaseSync` and inserting one pack `ui_sfx_v1` (two assets: `click` approved, `hover` failed with one failed gate row for the current `spec_hash`, one provenance row, one release row), `factory/dist/ui_sfx_v1/listing.md`, `factory/build/ui_sfx_v1/a.wav`, `factory/spec/packs/ui_sfx_v1.yaml`, and `secret.txt` beside `factory/`. Serves `createFactory` on a bare `http.createServer` at `127.0.0.1:0`.

- [ ] **Step 1: Write failing tests**

```js
test('packs list reads the fixture DB', async () => {
  // GET /factory/packs → 200, packs[0].pack_id === 'ui_sfx_v1',
  // packs[0].counts deepEqual { approved: 1, failed: 1 }, packs[0].blockers === 0,
  // packs[0].last_release.target === 'me/ui_sfx_v1'
});
test('pack detail has assets, current gate results, provenance, releases', async () => {
  // GET /factory/packs/ui_sfx_v1 → assets.length 2; assets.find(a => a.name==='hover').gates[0].passed === 0;
  // provenance.length 1; releases.length 1. GET /factory/packs/nope → 404. GET /factory/packs/UI → 400.
});
test('file route serves build and dist only', async () => {
  // /factory/file?path=dist/ui_sfx_v1/listing.md → 200 body matches
  // path=build/ui_sfx_v1/a.wav → 200
  // each → 403: '../secret.txt', 'dist/../../secret.txt', encodeURIComponent('dist/..\\..\\secret.txt'),
  //   absolute path.join(root,'secret.txt'), 'spec/packs/ui_sfx_v1.yaml', 'factory.db'
  // junction dist/ui_sfx_v1/out → root (fs.symlink(root, link, 'junction')), path=dist/ui_sfx_v1/out/secret.txt → 403
});
```

- [ ] **Step 2: Run, verify fail** — `node --test desktop/service/test/factory.test.mjs` → FAIL, cannot find `../factory.mjs`.

- [ ] **Step 3: Implement read routes in `factory.mjs`**

`openDb()` opens `new DatabaseSync(db, { readOnly: true })` per request and closes it in `finally` (no long-held handle, so the CLI never waits on us). Map `errcode === 5` (`SQLITE_BUSY`) / message `database is locked` to 503 `{retry:true}`. Queries:
- packs: `packs` + `SELECT pack_id, status, COUNT(*) FROM assets GROUP BY 1,2` folded into `counts`, `COUNT(*) FROM v_license_blockers JOIN assets` per pack, latest `releases` row per pack.
- detail: assets of the pack; `gate_results` where `recipe = packs.spec_hash` and `attempt = assets.attempts`, attached as `asset.gates`; `provenance` joined on `assets.run_id`; `releases` newest first.
File route: `realFile(root, rel)` from `util.mjs` against `factoryDir/build` or `factoryDir/dist`, chosen by the first segment of `path.normalize(rel)`; anything else 403; then `serveFile` from `files.mjs`. Reject absolute `rel` up front.

- [ ] **Step 4: Run, verify pass** — same command → 3 pass.

- [ ] **Step 5: Commit** — `feat(service): read-only factory pack routes and file route`.

### Task 2: Job routes (SSE, lock, confirm, 424)

**Files:**
- Modify: `desktop/service/factory.mjs`
- Modify: `desktop/service/test/factory.test.mjs`
- Modify: `desktop/service/test/fixtures/factory-cli-stub.mjs`

**Interfaces:**
- Consumes: `createFactory`, `fixture()` from Task 1.
- Stub contract (`factory-cli-stub.mjs`, run as `node stub.mjs <run.py> <cmd> ...args`): appends `JSON.stringify(process.argv.slice(3))` to `$STUB_LOG`. If `argv[2] === '-c'` prints `$STUB_CONFIG` (JSON) and exits 0. Otherwise behaviour by `$STUB_MODE`: `ok` (default) → prints `{"event":"log","msg":"hi"}`, `not json`, writes `warn` to stderr, then `{"event":"done","cmd":<cmd>,"exit":0}`, exit 0; `slow` → like ok after 800 ms; `argparse` → stderr `usage: ...`, exit 2, no stdout; `nodone` → one log event, exit 0. `$STUB_CONFIG` default from the fixture: `{"tools":{"godot":<existing file>,"butler":<existing file>},"itch":{"user":"me"}}`.

- [ ] **Step 1: Write failing tests** (helper `post(route, body)` returns `{status, events}` where `events` parses every `data:` frame)

```js
test('build streams events as SSE and ends with done', async () => {
  // 200, content-type text/event-stream; events include {event:'log',msg:'not json'}, {event:'stderr',msg:'warn'};
  // last event {event:'done', exit:0}; STUB_LOG has ['build','--pack','spec/packs/ui_sfx_v1.yaml','--json']
});
test('missing done or argparse exit counts as failure', async () => {
  // STUB_MODE=nodone → last event {event:'done', synthetic:true, exit:1}
  // STUB_MODE=argparse → last event {event:'done', synthetic:true, exit:2}
});
test('second job on the same pack returns 409', async () => {
  // STUB_MODE=slow: start build (don't await), second POST build → 409; after first finishes, a third POST → 200
});
test('approve passes names as --only', async () => {
  // POST approve {names:['click','hover']} → argv includes '--only','click','hover';
  // {names:'click'} or names with '-x' → 400, nothing spawned
});
test('publish without matching confirm is rejected', async () => {
  // {} → 400; {confirm:'me/other'} → 400; {confirm:'evil/ui_sfx_v1'} → 400; STUB_LOG has no 'publish'
  // {confirm:'me/ui_sfx_v1'} → 200, argv starts with 'publish'
});
test('missing tool returns 424 with configured path', async () => {
  // STUB_CONFIG butler '/no/butler.exe' → POST publish {confirm:'me/ui_sfx_v1'} → 424 {tool:'butler', path:'/no/butler.exe'}
  // itch.user '' → 424 {tool:'itch.user'}; godot missing → POST build 424 {tool:'godot'}
  // STUB_MODE=nopython (stub prints 'Python 3 not found' to stderr and exits 1, also on -c) → 424 {tool:'python'}
});
test('unknown pack or command', async () => {
  // POST /factory/packs/nope/build → 404; POST /factory/packs/ui_sfx_v1/init → 404; POST ../x → 400
});
```

- [ ] **Step 2: Run, verify fail** — new tests FAIL (404s).

- [ ] **Step 3: Implement jobs in `factory.mjs`**

`const COMMANDS = { build: 'godot', approve: null, package: 'godot', listing: null, publish: 'butler' }`. Order per POST: validate id + command + spec file exists (`factoryDir/spec/packs/<id>.yaml`) → 409 if `jobs.has(id)` → validate body (`names`: array of strings matching `^[\w.-]+$` and not starting with `-`; `confirm` string) → `config()` → tool checks (`fs.access`) → for publish, compare `confirm` to `${itch.user}/${id}` → reserve `jobs.set(id, child)` → spawn with `windowsHide`, `stdio: ['ignore','pipe','pipe']`, `cwd: repo` → `readline` on stdout and stderr → write frames → on `close`, synthesize done if none seen, `jobs.delete(id)`, `response.end()`. Reserve the lock before the `await config()` so two quick POSTs cannot both pass (release on any error). `close()` kills running children.

- [ ] **Step 4: Run, verify pass** — `node --test desktop/service/test/factory.test.mjs` → all pass.

- [ ] **Step 5: Commit** — `feat(service): factory CLI jobs over SSE with lock, confirm and tool checks`.

### Task 3: Hook into the service route table

**Files:**
- Modify: `desktop/service/server.mjs` (import; `const factory = createFactory({ repo, factoryDir: path.join(repo, 'factory') })` after `files`; in the request handler before `if (url.pathname.startsWith('/api/'))`: `if (url.pathname.startsWith('/factory/')) { authorize(request); if (await factory.handle(request, response, url)) return; }`; `factory.close()` in `close()`)
- Modify: `desktop/service/test/factory.test.mjs`

- [ ] **Step 1: Write failing test**

```js
test('service requires the bearer token on /factory routes', async () => {
  // createService({ repo: temp repo with ui/index.html and factory/ }) →
  // fetch(origin + '/factory/packs') → 401; with Authorization: Bearer <token> → 200 {packs: []}
});
```

- [ ] **Step 2: Run, verify fail** — FAIL on the 200 assertion (`/factory/packs` falls through to the static UI handler today).

- [ ] **Step 3: Add the hook** (above).

- [ ] **Step 4: Verify everything**

Run (PowerShell, `$env:PY_PYTHON3='3.12'`):
`node --test desktop/service/test/factory.test.mjs` → all pass
`npm run test:factory` → passes (unchanged Python suite)
`npm run test:template` → passes
`npm run desktop:test` → no new failures versus `origin/main`.

- [ ] **Step 5: Commit** — `feat(service): register /factory routes behind service auth`.
