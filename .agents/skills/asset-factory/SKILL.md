---
name: asset-factory
description: Author and verify sellable Godot asset packs (shaders, UI sounds, meshes) with the factory pipeline in factory/. Use when drafting generators, shaders or pack specs, running builds, or reading gate failures.
---

# Asset factory

## What the factory is

A pack is a recipe: a spec YAML in `factory/spec/packs/`, the generator or
shader source, and the gates that measure the result. `factory.db` is the
source of truth for state. `VERIFY.md` is generated from it; never write it by hand.
Tool paths (Godot and others) come from `factory/spec/global.yaml`.

## Commands

Run from the repository root. `--pack` is resolved relative to `factory/`.

    node scripts/run-python.mjs factory/pipeline/run.py <command> --pack spec/packs/<id>.yaml

- `init`: register the pack and its assets.
- `build`: generate assets and run the gates. Shader packs also render turntable
  previews in forward_plus, mobile and gl_compatibility; Godot windows open briefly.
- `report`: print the gate results.
- `package`: write `factory/dist/<pack>/` with VERIFY.md, manifest.json, the zip
  and, for audio packs, AudioStreamRandomizer .tres files. Shader packs also get
  a README, a demo scene and an optional HTML5 web_demo (needs the Godot path).

`npm run test:factory` runs the pipeline tests.

## Fix sources, never outputs

Edit `factory/shaders/`, `factory/generators/` and `factory/spec/`. Never
hand-edit `factory/build/` or `factory/dist/`; the next build overwrites them.

## Reading failures

Each FAIL line names the gate, the measured value and the expected value. Change
the generator or shader, then rebuild. If a gate itself looks wrong, change it
only with the user's agreement.

## Hard rules

Never run `approve` or `publish`. Approval means the user listened or looked; publishing is a public action. Leave both to the user in the Studio or terminal.

Never mark a license `commercial_ok: 1` without the user reviewing the license page.

## Adding a pack

Copy an existing `factory/spec/packs/*.yaml`, change `pack_id`, assets and
budgets, and keep `disclosure.text` truthful about AI assistance.
