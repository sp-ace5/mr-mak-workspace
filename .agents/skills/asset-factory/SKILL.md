---
name: asset-factory
description: Author and verify sellable Godot asset packs (shaders, UI sounds) with the factory pipeline in factory/. Use when drafting generators, shaders or pack specs, running builds, or reading gate failures.
---

# Asset factory

## What the factory is

A pack is a recipe: a spec YAML in `factory/spec/packs/`, the generator or
shader source, and the gates that measure the result. `factory.db` is the
source of truth for state. `VERIFY.md` is generated from it; never write it by hand.
Tool paths (Godot, butler and others) and `itch.user` come from `factory/spec/global.yaml`,
overlaid by the gitignored `factory/spec/global.local.yaml` for this machine.

## Commands

Run from the repository root. `--pack` is resolved relative to `factory/`.

    node scripts/run-python.mjs factory/pipeline/run.py <command> --pack spec/packs/<id>.yaml

- `new --kind <shader|ui_sfx|inbox_mesh> --id <pack>` (no `--pack`): write
  `factory/spec/packs/<pack>.yaml` from a template. Refuses to overwrite.
- `init`: register the pack and its assets.
- `build`: generate assets and run the gates. Shader packs also render turntable
  previews in forward_plus, mobile and gl_compatibility; Godot windows open briefly.
- `report`: write `factory/dist/<pack>/VERIFY.md` (per-asset failed gates with measured and expected values), `manifest.json`, and print a one-line summary.
- `package`: write `factory/dist/<pack>/` with VERIFY.md, manifest.json, the zip
  and, for audio packs, AudioStreamRandomizer .tres files. Shader packs also get
  a README, a demo scene and an optional HTML5 web_demo (needs the Godot path).

- `listing`: write `factory/dist/<pack>/listing.md`, a draft for the itch.io page
  (title, description, VERIFY summary, AI-disclosure tags, file list, suggested price).
- `publish [--dry-run]`: user only (see Hard rules). Refuses unless the pack is
  built from the current spec, report passes, every asset is approved and the zip's
  manifest matches the approved outputs; `--dry-run` prints the butler commands.

Add `--json` to any command for one JSON event per stdout line, ending with
`{"event":"done","cmd":...,"exit":N}`. Prefer it when you parse the output.

`npm run test:factory` runs the pipeline tests.

## Fix sources, never outputs

Edit `factory/shaders/`, `factory/generators/` and `factory/spec/`. Never
hand-edit `factory/build/` or `factory/dist/`; the next build overwrites them.

## Reading failures

`build` prints `FAIL <asset> gate=measured` (with `--json`: `gate` events with `failed[]` carrying measured and expected); the expected values are in VERIFY.md after `report`. Change
the generator or shader, then rebuild. If a gate itself looks wrong, change it
only with the user's agreement. Mesh packs (`inbox_mesh`) are not supported yet: their gate code is not in this repo.

## Hard rules

Never run `approve` or `publish`. Approval means the user listened or looked; publishing is a public action. Leave both to the user in the Studio or terminal.

Never mark a license `commercial_ok: 1` without the user reviewing the license page.

## Adding a pack

Run `new`, then edit the assets and budgets, and keep `disclosure.text` truthful about AI assistance.
