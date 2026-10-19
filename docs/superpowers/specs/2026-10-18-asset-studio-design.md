# Asset Studio for mr-mak-workspace — Design

Date: 2026-10-18 · Status: awaiting review

## Goal

Fork `witnesstodark/mr-mak-workspace` and add an **Asset Studio**: generate, verify, package and sell
Godot asset packs on itch.io from inside the app, with or without a game project. Game-making features stay
unchanged. A Godot **asset playground** lets you try every approved pack in one scene.

## Decisions (agreed)

| Topic | Decision |
|---|---|
| Code home | Factory pipeline moves into the fork under `factory/` (one repo). |
| UI | Native React **Studio** view in the Workspace window. |
| Bridge | Service runs the Python CLI for every write and reads `factory.db` read-only with `node:sqlite`. Python is the only DB writer. |
| Publishing | `butler` upload (addon zip + HTML5 demo) behind a confirm dialog, plus a generated listing draft to paste into itch.io. |
| Test game | Asset playground: walkaround scene that auto-loads all approved packs. |

## Non-goals

itch.io page editing via API (none exists) · sales analytics · multi-user · Fab/Unity storefronts · mobile
Studio view · rewriting the pipeline in Node.

## 1. Repo layout

```
factory/                      moved from C:\Factory; cwd for `py -m pipeline.run`
  pipeline/ spec/ generators/ shaders/ godot_harness/ blender/
  factory.db build/ dist/ inbox/            gitignored
playground/                   Godot 4.5 project (section 6)
desktop/service/factory.mjs   /factory/* routes
src/studio/                   Studio React view
.agents/skills/asset-factory/SKILL.md      synced to .claude/skills via `npm run skills:sync`
processes/asset-factory.md
```

`factory/spec/global.yaml` keeps tool paths (Godot, Blender, resvg, butler) and gains `itch.user`.
Existing cards, chats, projects and skills are untouched.

## 2. Pipeline CLI additions (`factory/pipeline/run.py`)

- `--json` on every command: one JSON object per stdout line, e.g.
  `{"event":"gate","asset":"runic_glow","ok":false,"failed":[{"gate":"...","measured":"...","expected":"..."}]}`,
  `{"event":"done","cmd":"build","exit":0}`. Human output unchanged without the flag.
- `new --kind <shader|ui_sfx|inbox_mesh> --id <pack>`: writes `spec/packs/<pack>.yaml` from a template; refuses
  to overwrite.
- `listing --pack`: writes `dist/<pack>/listing.md` — title, short description, body from README + VERIFY
  summary, itch AI-disclosure categories from `disclosure.itch_ai_tags`, file list, suggested price from
  `spec.price_usd` (default none).
- `publish --pack [--dry-run]`: refuses (exit 1, reason printed) unless `report` exits 0, every non-rejected
  asset is `approved`, and the addon zip exists. Runs `butler push <zip> <itch.user>/<pack>:godot-addon` and,
  if present, `butler push dist/<pack>/web_demo <itch.user>/<pack>:html5`. Records each push in a new table:

```sql
CREATE TABLE IF NOT EXISTS releases (
  pack_id TEXT NOT NULL REFERENCES packs(pack_id), channel TEXT NOT NULL, target TEXT NOT NULL,
  file_sha256 TEXT NOT NULL, butler_build TEXT, spec_hash TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')));
```

`--dry-run` prints the exact butler commands and pushes nothing.

## 3. Service routes (`desktop/service/factory.mjs`)

| Route | Behaviour |
|---|---|
| `GET /factory/packs` | packs with counts by status, license blockers, last release |
| `GET /factory/packs/:id` | assets, latest-attempt gate results for current recipe, provenance, releases |
| `GET /factory/file?path=` | serves files only under `factory/build/` and `factory/dist/` (path resolved, symlinks rejected) |
| `POST /factory/packs/:id/{build,approve,package,listing,publish}` | spawns `py -m pipeline.run <cmd> --pack spec/packs/<id>.yaml --json`; streams events as SSE |

- One job per pack at a time; a concurrent request returns 409.
- `approve` accepts `{names: [...]}`; `publish` requires `{confirm: "<itch.user>/<pack>"}` matching the target,
  so a stale or scripted call cannot publish.
- DB opened `readOnly`; on `SQLITE_BUSY` the read retries on next poll.
- Missing tool (py, Godot, butler) → 424 with the configured path, rendered as a setup card.

## 4. Studio view (`src/studio/`)

- Sidebar entry **Asset Studio** next to the Workspace grid.
- **Pack list**: category, status chips (pending/failed/passed/approved/shipped), blocker badge, last release.
- **Pack page**: asset table with failed gates (measured vs expected); `<audio>` player per WAV; preview frame
  strip / contact sheet for shaders; rendered VERIFY.md; live job log.
- **Actions**: Build · Approve (all / selected) · Package · Open web demo · Copy listing · Publish.
  Publish opens a dialog listing target, channels and file hashes; the user types/clicks to confirm.
- **Ask agent**: sends a failing asset's gate results plus source path to the active chat as a draft message
  (not auto-sent).

## 5. Agent skill + process

`asset-factory` skill: how to write generators/shaders/specs, run `build --json`, read failures, fix the
**source** (never `build/` outputs). Agents must not run `approve` or `publish`; those stay user actions in the
Studio. `processes/asset-factory.md`: brief → draft → build → listen/look → approve → package → listing →
publish.

## 6. Asset playground (`playground/`)

- Godot 4.5 project: capsule third-person controller, ground, pedestal grid.
- `tools/sync_packs.gd` (headless): copies `factory/dist/<pack>/addons/<pack>/` for approved, packaged packs into
  `playground/addons/`.
- `Playground.tscn` + script place content by type at runtime: shaders on spheres, randomizers on footsteps/UI
  clicks; later VFX scenes, UI Theme on the pause menu, mesh kits on a 0.5 m grid.
- Studio **Open in playground**: runs sync, then launches Godot on the project.

## 7. Error handling

CLI nonzero exit → Studio shows the last 40 stderr lines and the failed event. Publish refusals show the
reason from the CLI. Butler not logged in → setup card with `butler login`. Job output is kept in
`factory/build/<pack>/jobs/<timestamp>.log`.

## 8. Testing

- **Python** (`factory/tests/`, pytest): `--json` event shapes; `new` refuses overwrite; `listing` content;
  `publish` refusals (unapproved asset, blocker, missing zip) and `--dry-run` commands; a stub butler script set in
  a test `global.yaml` records arguments — the only fake, because a real push is an outward action.
- **Service** (`desktop/service/test/factory.test.mjs`, `node --test`): routes against a fixture DB + dist; path
  traversal rejected; 409 on concurrent job; publish without matching `confirm` rejected.
- **UI** (`desktop/service/test/studio-ui.mjs`, Playwright like existing `*-ui.mjs`): pack list renders; pack
  page shows gate table and an audio element.
- **Playground**: headless load of all synced packs with zero errors.
- **Release**: first real push only with the user watching, to a draft/restricted itch page.

## 9. Rollout (separate plan + PR each; each usable on its own)

1. Fork; move factory into `factory/`; gitignore; skill + process doc.
2. CLI additions (section 2).
3. Service routes (section 3).
4. Studio view (section 4).
5. Publish flow end to end (button → CLI → butler).
6. Playground.

## Risks

- Upstream changes to the app conflict with the fork → keep changes in new files; only small hooks in
  `Sidebar.tsx`, `App.tsx` and the service route table.
- `node:sqlite` prints an experimental warning on Node 22 → acceptable; read-only use.
- itch.io rules change (AI disclosure) → listing template reads tags from the spec; re-check before each launch.
