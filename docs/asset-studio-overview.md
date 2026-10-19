# Asset Studio — what was built

The Asset Studio turns this fork of mr-mak-workspace into an app for making, checking, packaging and selling Godot asset packs on itch.io. You can also try every approved pack in a small Godot playground. It was built in six steps (PRs #1–#6, all merged into `main`). The design is in [the spec](superpowers/specs/2026-10-18-asset-studio-design.md).

## How it fits together

```
Studio view (React, Workspace window)
   │  HTTP + live job log (SSE), desktop bearer token
   ▼
Service routes  /factory/*   (desktop/service/factory.mjs)
   │  reads factory.db read-only          │  runs the CLI for every change
   ▼                                      ▼
factory/factory.db  ◄── only writer ──  factory/pipeline/run.py  ──► Godot · butler · Blender
                                          │
                                          └──► playground/  (Godot walkaround scene)
```

- **One writer.** Only the Python CLI changes `factory.db`. The service starts the CLI and reads the database; it never writes.
- **Nothing ships by accident.** Publishing needs a passing report, every asset approved, a zip that matches the approved files, and a typed confirmation.
- **Agents make, people decide.** Agents write generators, shaders and specs and run builds. Approving and publishing stay with you in the Studio.

## Features

### 1. Asset factory in the repo (PR #1)
- The factory pipeline lives in `factory/`: generators, quality gates (audio, Godot shader compile, preview frames), pack specs, the Godot test harness, and the license allowlist.
- Two example packs: `ui_sfx_v1` (procedurally made UI sounds) and `dark_fantasy_shaders_v1` (4 spatial shaders).
- The `asset-factory` agent skill explains how to write generators and specs, run builds and read gate failures. A process doc covers the path from brief to publish (`processes/asset-factory.md`).
- Generated state is gitignored: `factory.db`, `build/`, `dist/`, `inbox/`, `spec/global.local.yaml`.

### 2. CLI additions (PR #2)
- `--json` on every command prints one event per line (`gate`, `report`, `refused`, `push`, `error`…) and always ends with `{"event":"done","exit":N}`.
- `new --kind <ui_sfx|shader|inbox_mesh> --id <pack>` creates a pack spec from a template and refuses to overwrite.
- `listing` writes `dist/<pack>/listing.md`, a draft itch.io page: title, description, AI-disclosure tags, file list and price.
- `publish [--dry-run]` uploads with `butler` and records each upload in a new `releases` table. It refuses when:
  - the report fails
  - an asset is not approved
  - the zip doesn't match the approved files
  - the recipe changed since the last build
  - `itch.user` or butler is missing
- Per-machine settings (tool paths, `itch.user`) go in the gitignored `factory/spec/global.local.yaml`.

### 3. Service routes (PR #3)
All routes need the desktop app's bearer token.

| Route | What it does |
|---|---|
| `GET /factory/packs` | Every pack, with asset counts by status, license blockers and the last release |
| `GET /factory/packs/:id` | Assets, failed gates (current recipe), provenance and releases |
| `GET /factory/file?path=` | Serves files only from `factory/build/` and `factory/dist/`; blocks traversal and links that lead elsewhere |
| `POST /factory/packs/:id/{build,approve,package,listing,publish}` | Runs the CLI and streams its events live |
| `POST /factory/playground` | Syncs packs into the playground and can open it (added in PR #6) |

- One job per pack at a time; a second request gets **409**.
- A missing tool (Python, Godot, butler, `itch.user`) gets **424** with the configured path.
- A run that ends without a `done` line counts as a failure, as does a CLI usage error.
- Every job's events are also saved to `factory/build/<pack>/jobs/<time>-<cmd>.log`.

### 4. Studio view (PR #4)
Open **Asset Studio** in the Workspace sidebar (desktop app only).
- **Pack list:** status chips (pending, failed, passed, approved, rejected, shipped), blocker badge and last release. It refreshes every 5 s.
- **Pack page:**
  - an asset table with each failed gate's measured and expected values
  - an audio player for each sound
  - the first, middle and last preview frame for each shader
  - the rendered `VERIFY.md`
  - a live job log
- **Actions:**
  - **Build** · **Package** · **Open web demo**
  - **Approve selected** and **Approve all passed**, both asking for confirmation first
  - **Copy listing**, which writes the listing and copies it to the clipboard
- The job log keeps running when you move to another page and back. Setup problems show as a card that names the missing tool and the path it looked at.

### 5. Publish flow (PR #5)
- **Publish…** first does a dry run and shows exactly what would be uploaded: channel (`godot-addon`, `html5`), target and SHA-256 of each file. If the CLI would refuse, it shows the reason instead.
- The Publish button only unlocks when you type `<itch user>/<pack>` exactly. The service checks it again against the configured itch user.
- If butler isn't logged in, a card tells you to run `butler login` once.
- A **Releases** table on the pack page lists every upload.

### 6. Asset playground (PR #6)
- `playground/` is a Godot 4.5 scene with a third-person capsule (WASD or arrows; click to look around, Esc to release the mouse):
  - shaders appear on spheres on pedestals
  - sounds whose names contain "foot" or "step" become footsteps
  - other sounds become buttons in an on-screen panel
- `run.py playground [--open]`:
  1. Picks every pack whose assets are all approved and whose packaged addon matches those approvals.
  2. Copies the packs into `playground/addons/`.
  3. Checks headless that the scene loads with zero errors.
  4. With `--open`, launches Godot on the scene.
- Packs that lost approval are removed on the next sync. Addons you installed by hand are never touched.
- **Open in playground** on the Studio pack list does all of this, with a live log.

## Typical workflow

1. **Draft:** ask an agent to write a generator or shader and a pack spec (`run.py new`).
2. **Build:** in the Studio, click **Build** and read the failed gates. Agents fix the source, never the files in `build/`.
3. **Review:** listen to and look at each asset, then **Approve** the good ones.
4. **Package**, then **Open in playground** to try the pack in Godot.
5. **Copy listing** and paste it into the itch.io page.
6. **Publish…**: check the targets and hashes, type the confirmation, then upload.

## Setup

In `factory/spec/global.local.yaml`:

```yaml
tools:
  godot: 'C:\Tools\Godot\Godot_v4.5-stable_win64_console.exe'
  butler: 'C:\Tools\butler\butler.exe'
itch:
  user: your-itch-username
```

- Run `butler login` once in a terminal before the first upload.
- On this machine, run Python with `PY_PYTHON3=3.12`.

## Tests

| Suite | Command | Covers |
|---|---|---|
| Factory (pytest) | `npm run test:factory` | CLI events, `new`, `listing`, publish refusals and dry run (butler stubbed), playground sync and headless load (real Godot on temp copies) |
| Service | `node --test desktop/service/test/factory.test.mjs` | Read routes, path traversal, 409/424, missing `done`, publish confirm, dry run, job logs, playground lock |
| Studio UI | `npm run build && node desktop/service/test/studio-ui.mjs` | Pack list, pack page, job log, approve confirm, publish dialog, butler-login card, playground button |

Tests never run a real upload, approve or publish on real packs; they replace the CLI or butler with a stub.

## Added after step 6 (PRs #8, #9)

- **Ask agent:** on a failing asset, puts its gate failures and source paths into the active Claude or Codex chat as a draft. It is never sent; you press Send.
- **Cancel:** stops a stuck job and every process it started. Stopping approve or publish asks first.
- **Publish only what you saw:** the real upload carries the hashes the preview showed and is refused if any file changed since.
- **Playground:** also places VFX scenes, mesh kits (0.5 m grid) and UI themes, and has an Esc pause menu.
- **Safer CLI:**
  - a spec's `pack_id` must match its file name
  - approve needs a build under the current recipe
  - license edits force a rebuild
  - a crashing gate fails only its own asset
  - the dry run writes nothing
- **Service:** jobs keep running if the app quits mid-upload, and `done` is always the last event.

## Not done yet

- **First real upload:** no real butler push has run yet. Do the first one yourself, watching, to a draft or restricted itch.io page. If butler isn't logged in, run `butler login` once.
- **Playground window:** the playground has only run headless; open it once from the Studio to check walking and sounds.
- **Release build ids:** butler's build id isn't saved in `releases.butler_build` yet; that needs a real upload to learn the output format.
- **Mesh gate:** `inbox_mesh` packs can't pass a build yet, because the mesh gate and its Blender scripts don't exist. A mesh build now fails per asset with `gate_error` instead of crashing.
- **Godot version:** not part of the recipe hash, so an engine upgrade doesn't force a rebuild.
