---
node_id: 2682e5ff-efcf-5e0c-8ac4-777375c406fa
slug: lingering-resonance-4887
title: 'Tooling: the real chassis CAD is now the Studio drone mesh (STEP -> GLB, procedural fallback)'
created_at: '2026-07-14T08:45:45.038053+00:00'
parents:
- wispy-dust-3157
- lucky-bush-5765
summary: 'Replaced the procedural box/arms/rotors glyph with the actual Air65 airframe: whoop_assembly_draft.step (build123d, 46x46x16 mm, 17 named products — chassis/4 motors/4 props/4 grommets/FC/ESP-RX/ToF) tessellated to web/studio/assets/whoop_chassis.glb (551 KiB, 19k tris) via a new standalone scripts/chassis_to_glb.py (cascadio; run --no-project on the bench Mac since the cu128 torch pin has no macOS wheel). drone-model.js lazy-loads the GLB once and clones it into every drone across all four tabs (Bench, Live, playback, editor); the procedural glyph stays as the instant placeholder and the no-asset fallback, and the identity center-marker + heading nav lights survive the swap. CAD frame is -Y-forward/Z-up in meters -> yaw +90 to sim +X, bbox-recenter, scale 6.59x to the 0.54 m glyph footprint (verified: front motors land at x=+0.152, ToF under the belly at z=-0.047); FPV_OFFSET moved to x=0.28 to clear the scaled canopy nose. Verified: transform-chain render (front parts forward, z-thin), node ES-module syntax check, and the live studio (--bridge fake) serves the GLB at 200/563992B. No training-path or contract change — pure viz. GREEN.'
origin:
  backend: flywheel
  node_id: 2682e5ff-efcf-5e0c-8ac4-777375c406fa
  slug: lingering-resonance-4887
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
The Studio/Bench drone was a crude procedural glyph (a box + four cylinder rotors). Theo has a CAD model of the actual airframe (`whoop_assembly_draft.step`); using it should make every viewer — especially the Bench real-drone dashboard — show the true chassis instead of an abstraction, at no cost to the training or replay path.

## Setup
- **Source**: `~/Downloads/whoop_assembly_draft.step` — an Open CASCADE / build123d export, 1.8 MB, 46x46x16 mm, 17 named products: `chassis`, `motor_{front,rear}_{left,right}`, `prop_*`, `grommet_*`, `fc`, `esp_rx`, `tof_rangefinder`. Frame: **-Y forward** (front motors at y=-23 mm), **+Z up**, units meters.
- **Converter** (`scripts/chassis_to_glb.py`, new, standalone): `cascadio.step_to_glb` tessellates STEP -> GLB (Three.js can't read STEP), prints bounds + tri count. Must run `uv run --no-project` on this Mac — the repo's `torch==2.11.0+cu128` pin has no darwin wheel, so the project venv can't resolve; `--no-project` sidesteps it. Output committed at `web/studio/assets/whoop_chassis.glb` (551 KiB, 19k tris).
- **Frontend** (`web/studio/drone-model.js`): `GLTFLoader.loadAsync` once, memoized in a module-level promise shared by every drone; on resolve, each `makeDrone()` group swaps its procedural placeholder subgroup for a `proto.clone(true)` (clones share geometry+materials). Part materials keyed on product-name regex (props translucent, motors dark metal, FC/ESP green PCB, ToF blue). The center identity marker (per-drone tint, the gate-detection point) and the front/rear nav lights are added to the group directly, so they survive the swap. On load failure it `console.warn`s and keeps the glyph.
- **Transform**: CAD is -Y-forward/Z-up meters -> `rotation.z = +pi/2` (nose -> sim +X), recenter on bbox, `scale = 0.54 / max(sizeX,sizeY)` to match the historic ~7x-lifesize glyph footprint that reads in the wide hero shot. `FPV_OFFSET` 0.10 -> **0.28** so the nose-cam sits just past the scaled canopy instead of inside it.

## Results
- **Transform-chain check** (offline, replaying the exact JS steps on the GLB): raw extents `[0.082, 0.082, 0.0166]` (z-thin, as expected); after yaw+recenter+scale the front motors land at **x=+0.152** (forward, correct), rear at x=-0.152, ToF rangefinder centered under the belly at **z=-0.047**, FC at z~0. Nose reaches x=0.27 so FPV at 0.28 clears it. 3/4 + top renders look like a real whoop (ducts, props, green FC diamond).
- **Syntax**: `node --check` clean on `drone-model.js` + `playback.js`.
- **Live serve**: studio booted `--bridge fake` (repo `.venv` on the Mac has CPU torch + fastapi) serves `/assets/whoop_chassis.glb` -> **200, 563992 B**, `drone-model.js` -> 200, index -> 200.

## Verdict / Honesty
GREEN — the CAD mesh loads and is oriented/scaled correctly across all four drone-drawing tabs (Bench, Live, playback, editor), with a graceful procedural fallback if the GLB is ever absent. Caveats: I have **not** yet eyeballed it in a real browser/WebGL context (checks are the offline transform render + HTTP 200 + syntax) — a live visual pass on the Bench tab is the natural next step. The GLB is a static asset checked into the repo; regenerate via `scripts/chassis_to_glb.py` when the CAD changes. Purely cosmetic: no obs/act contract, env, or training-path change.

## Lineage
Parents: the **Studio** tooling node (interactive viewer that owns `drone-model.js` + the Bench/Live tabs) and the **nw-viz** node (the sibling Three.js hero-MP4 tool that shares the same drone-glyph lineage). Commit `5f12edb`.

## Commit
- `5f12edb` studio: real chassis CAD as the drone mesh (STEP -> GLB via scripts/chassis_to_glb.py; drone-model.js swap + procedural fallback; FPV_OFFSET nose clearance)