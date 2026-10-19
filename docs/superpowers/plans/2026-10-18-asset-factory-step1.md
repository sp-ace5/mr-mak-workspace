# Asset Factory Step 1 (Fork + Move Factory In) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fork of mr-mak-workspace that contains the working asset factory under `factory/`, runnable from the repo, tested, and documented for agents — with every existing app check still passing.

**Architecture:** Copy the C:\Factory source tree into `factory/` unchanged except two small hooks in `run.py` (`FACTORY_DB` override, `sys.path` so it runs from any cwd). Generated state stays gitignored. A new shared skill and process doc teach agents the workflow; approve/publish stay user actions.

**Tech Stack:** Python 3.12 (numpy, scipy, pyyaml, pillow, lxml, pytest), Godot 4.5 console exe, Node ≥ 22.20 (existing repo scripts), `gh` CLI (logged in as `sp-ace5`).

**Spec:** `docs/superpowers/specs/2026-10-18-asset-studio-design.md` (sections 1, 5, 9 step 1)

## Global Constraints

- Code home: factory pipeline lives in the fork under `factory/`; `factory.db`, `build/`, `dist/`, `inbox/` gitignored.
- Existing cards, chats, projects and skills are untouched (only the skill-count assertion and the new skill change).
- Agents must not run `approve` or `publish`; those stay user actions.
- Shared skills must start with `---\nname:` and must not contain a local account path (`C:\Users\...`).
- `.claude/skills/` is generated: edit `.agents/skills/` then run `npm run skills:sync`.
- Fork + push + PR are public actions on the user's GitHub account: confirm with the user immediately before each.

## Review Focus

1. Running the CLI from the repo root (not `factory/`) → works, because `run.py` puts `factory/` on `sys.path` and resolves `--pack` against `factory/`. Test in Task 2.
2. Tests must never touch the user's real `factory/factory.db` → `FACTORY_DB` env override; test asserts the real DB file is not created/modified. Task 2.
3. Generated Godot state (`godot_harness/.godot/`, `godot_harness/addons/`, `godot_harness/pack/`, `*.uid` under addons) accidentally committed → `.gitignore` entries + `git status --porcelain` check. Task 2.
4. Copying build outputs from C:\Factory (`build/`, `dist/`, `factory.db`, `wiki/`) into the repo → copy list is explicit; verified by `git check-ignore`. Task 2.
5. Template check failing on skill count (hard-coded `20`) → bumped to `21` in Task 3, and `npm run test:template` must pass.

---

### Task 1: Fork and branch

**Files:** none (repo setup)

**Interfaces:**
- Produces: local clone at `C:\Tools\mr-mak-workspace`, remote `origin` = `sp-ace5/mr-mak-workspace`, remote `upstream` = `witnesstodark/mr-mak-workspace`, branch `feat/asset-factory`.

- [ ] **Step 1: Confirm with the user** that a public fork `sp-ace5/mr-mak-workspace` may be created. Stop if no.
- [ ] **Step 2: Fork + clone**

Run (with cwd `C:\Tools`): `gh repo fork witnesstodark/mr-mak-workspace --clone --default-branch-only` (`--clone` adds `upstream` itself)
Expected: `git -C C:\Tools\mr-mak-workspace remote -v` lists `origin` (sp-ace5) and `upstream` (witnesstodark).

- [ ] **Step 3: Branch**

Run: `git -C C:\Tools\mr-mak-workspace switch -c feat/asset-factory`

- [ ] **Step 4: Baseline checks pass before any change**

Run (in the clone): `npm run test:template`
Expected: `Template passed: four cards, one pin, ... 20 shared skills ...`. If it fails on the untouched fork, stop and report; do not fix upstream issues in this plan.

---

### Task 2: Move the factory into `factory/`

**Files:**
- Create: `factory/` copied from `C:\Factory`: `pipeline/` (all `.py` + `schema.sql`), `spec/` (`global.yaml`, `packs/*.yaml`), `generators/`, `shaders/`, `godot_harness/` (`project.godot`, `check.gd`, `preview.gd`, `preview.tscn`, `make_randomizers.gd`, `build_demo.gd`, `demo/demo.gd`), `docs/superpowers/` → repo `docs/superpowers/` (spec + this plan). Do **not** copy `build/`, `dist/`, `inbox/`, `wiki/`, `factory.db`, `godot_harness/.godot/`, `godot_harness/addons/`, `godot_harness/pack/`, `__pycache__/`.
- Create: `factory/requirements.txt`, `factory/tests/test_smoke.py`
- Modify: `factory/pipeline/run.py` (top of file: `DB`, `sys.path`)
- Modify: `.gitignore` (append factory block)
- Modify: `package.json` (`scripts.test:factory`)

**Interfaces:**
- Consumes: Task 1 clone.
- Produces: `factory/pipeline/run.py` runnable as `node scripts/run-python.mjs factory/pipeline/run.py <cmd> --pack spec/packs/<id>.yaml` from repo root; DB path = `os.environ.get("FACTORY_DB")` or `factory/factory.db`; `npm run test:factory`. Later steps (CLI `--json`, service routes) build on these exact entry points.

- [ ] **Step 1: Copy the explicit file list above.** Verify: `git status --porcelain` shows only `factory/...` and `docs/superpowers/...` new files.

- [ ] **Step 2: Write the failing tests** in `factory/tests/test_smoke.py` (run CLI as a subprocess with `sys.executable`, `env={**os.environ, "FACTORY_DB": str(tmp_path / "t.db")}`, `cwd` = repo root):

```python
def test_ui_sfx_pack_ships_from_repo_root(tmp_path):
    for cmd in ("init", "build", "approve"):
        assert run_cli(cmd, "spec/packs/ui_sfx_v1.yaml", tmp_path).returncode == 0
    r = run_cli("report", "spec/packs/ui_sfx_v1.yaml", tmp_path)
    assert r.returncode == 0
    assert "16/16 passed, 0 license blockers" in r.stdout

def test_tests_never_touch_real_db(tmp_path):
    real = REPO / "factory" / "factory.db"
    before = real.stat().st_mtime_ns if real.exists() else None
    run_cli("init", "spec/packs/ui_sfx_v1.yaml", tmp_path)
    after = real.stat().st_mtime_ns if real.exists() else None
    assert before == after
    assert (tmp_path / "t.db").exists()
```

`run_cli(cmd, pack, tmp_path)` = `subprocess.run([sys.executable, str(REPO / "factory/pipeline/run.py"), cmd, "--pack", pack], cwd=REPO, env=..., capture_output=True, text=True, timeout=300)`. `REPO = Path(__file__).resolve().parents[2]`.

- [ ] **Step 3: Run to verify failure**

Run: `node scripts/run-python.mjs -m pytest factory/tests -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline'` (script run from repo root) and real DB used.

- [ ] **Step 4: Implement in `factory/pipeline/run.py`** (directly after `ROOT = ...`):
  - `sys.path.insert(0, str(ROOT))` (`sys` is already imported; the `pipeline`/`generators` imports are function-local, so this line at module top is enough).
  - `DB = pathlib.Path(os.environ.get("FACTORY_DB") or ROOT / "factory.db")`

- [ ] **Step 5: Run tests to verify pass**

Run: `node scripts/run-python.mjs -m pytest factory/tests -q`
Expected: `2 passed`.

- [ ] **Step 6: Add support files**
  - `factory/requirements.txt`: `numpy`, `scipy`, `pyyaml`, `pillow`, `lxml`, `pytest` (one per line, no pins).
  - `package.json` scripts: `"test:factory": "node scripts/run-python.mjs -m pytest factory/tests -q"`.
  - `.gitignore` append:

```
# Asset factory: generated state (sources are committed)
factory/factory.db
factory/build/
factory/wiki/
factory/godot_harness/.godot/
factory/godot_harness/addons/
factory/godot_harness/pack/
```

(`dist/` and `inbox/*` are already ignored repo-wide.)

- [ ] **Step 7: Verify ignores and checks**

Run: `git check-ignore factory/factory.db factory/build/x factory/dist/x factory/inbox/x factory/godot_harness/.godot/x factory/godot_harness/addons/x`
Expected: all six paths printed.
Run: `npm run test:factory` → `2 passed`; `npm run test:template` → still passes (20 skills).
Run: `git status --porcelain` → no `.godot`, `build`, `dist`, `.db`, `__pycache__` entries.

- [ ] **Step 8: Commit**

```bash
git add factory docs/superpowers .gitignore package.json
git commit -m "feat(factory): add asset factory pipeline under factory/"
```

---

### Task 3: Agent skill + process doc

**Files:**
- Create: `.agents/skills/asset-factory/SKILL.md`
- Create: `processes/asset-factory.md`
- Modify: `scripts/check-template.mjs:44` (`assert.equal(skillNames.length, 20)` → `21`)
- Modify: `AGENTS.md` (repository map: one line `factory/ — asset factory pipeline; see processes/asset-factory.md`)
- Generated: `.claude/skills/asset-factory/SKILL.md` via `npm run skills:sync`

**Interfaces:**
- Consumes: Task 2 entry point (`node scripts/run-python.mjs factory/pipeline/run.py <cmd> --pack spec/packs/<id>.yaml`).
- Produces: skill name `asset-factory` (later steps reference it from the Studio's "Ask agent").

- [ ] **Step 1: Bump the count and run the check to see it fail**

Edit `scripts/check-template.mjs` line with `skillNames.length, 20` → `21`.
Run: `npm run test:template`
Expected: FAIL `21 !== 20` style assertion (skill not yet present).

- [ ] **Step 2: Write `.agents/skills/asset-factory/SKILL.md`**

Frontmatter (exact):

```
---
name: asset-factory
description: Author and verify sellable Godot asset packs (shaders, UI sounds, meshes) with the factory pipeline in factory/. Use when drafting generators, shaders or pack specs, running builds, or reading gate failures.
---
```

Body sections (English, no local account paths, ≤ 80 lines):
1. *What the factory is* — spec YAML + generator/shader source + gates = recipe; `factory.db` is the source of truth; `VERIFY.md` is generated.
2. *Commands* — the Task 2 entry point with `init`, `build`, `report`, `package`; run from repo root.
3. *Fix sources, never outputs* — edit `factory/shaders/`, `factory/generators/`, `factory/spec/`; never hand-edit `factory/build/` or `factory/dist/`.
4. *Reading failures* — each FAIL line names gate, measured, expected; change the generator or shader, rebuild; a gate that is wrong is changed only with the user's agreement.
5. *Hard rules* (verbatim): "Never run `approve` or `publish`. Approval means the user listened or looked; publishing is a public action. Leave both to the user in the Studio or terminal." and "Never mark a license `commercial_ok: 1` without the user reviewing the license page."
6. *Adding a pack* — copy an existing `factory/spec/packs/*.yaml`, keep `disclosure.text` truthful about AI assistance.

- [ ] **Step 3: Write `processes/asset-factory.md`** (≤ 30 lines, same tone as `processes/creative-production.md`): brief → draft source with the `asset-factory` skill → build → user listens/looks → user approves → package → listing → user publishes. State that a pack can be made with no game project, and that game projects may consume packs from `factory/dist/<pack>/addons/`.

- [ ] **Step 4: Sync and verify**

Run: `npm run skills:sync` then `npm run test:template`
Expected: `Template passed: ... 21 shared skills ...`.
Run: `npm run test:factory` → `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/asset-factory .claude/skills/asset-factory processes/asset-factory.md scripts/check-template.mjs AGENTS.md
git commit -m "feat(factory): add asset-factory skill and process"
```

---

### Task 4: Push and PR (inside the fork)

- [ ] **Step 1: Confirm with the user** before pushing and opening the PR. Stop if no.
- [ ] **Step 2: Push**

Run: `git push -u origin feat/asset-factory`

- [ ] **Step 3: PR into the fork's default branch** (not upstream)

Run: `gh pr create --repo sp-ace5/mr-mak-workspace --base <default branch from `gh repo view sp-ace5/mr-mak-workspace --json defaultBranchRef -q .defaultBranchRef.name`> --head feat/asset-factory --title "Asset factory: pipeline, skill and process (step 1)" --body-file <tmp>` — body: summary of Tasks 2–3, test commands with results, link to spec; ends with the attribution line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
Expected: PR URL printed. Then bind it with the ccd_pr tools.
