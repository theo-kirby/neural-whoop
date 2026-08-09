---
node_id: dd488d47-4f19-5efa-bb4a-ff094c6712ab
slug: gentle-resonance-7390
title: 'Tooling: textured FBX chassis mesh (authored per-part materials) + brighter Studio lighting'
created_at: '2026-07-14T09:27:32.117532+00:00'
parents:
- lingering-resonance-4887
summary: 'Superseded the STEP-derived chassis GLB with the whoop-assembly.fbx, which carries authored per-part materials the STEP export never had: colored rotors/stators, red/green/yellow PCBs, translucent props (alpha 0.49), black plastics — 15 materials across 16 named meshes (chassis / 4 props / rotors / stators / grommets / flight-controller / tof-sensor / esp32-s3). Converted headlessly through Blender 4.2 (new scripts/chassis_fbx_to_glb.py; the FBX''s one texture ref was a stale screenshot, neither embedded nor on disk, so nothing was lost — base-color materials survive) -> web/studio/assets/whoop_chassis.glb (9.3 MB, 139k tris). drone-model.js now keeps the GLB''s own materials (dropped the name-regex override from the STEP node) and reorients for the FBX axes: this file is +Y-forward/Z-up in mm (opposite the STEP model''s -Y), so yaw is -90 (was +90) to point the nose at sim +X — verified front props land at x=+0.15, rear at x=-0.15, ToF under the belly at z=-0.05; bbox-recenter + scale-to-0.54 m footprint are unit-agnostic and unchanged. Also brightened scene.js: hemisphere 0.9->1.35, sun 1.4->2.1, plus a soft blue fill from the opposite side so the near-black plastics don''t crush to silhouette. Verified: transform-chain render (front props forward, colors read), node --check on drone-model.js + scene.js, live studio (--bridge fake) serves the 9.56 MB GLB at 200 across all tabs. Still pure viz — no contract/env/training change. GREEN.'
origin:
  backend: flywheel
  node_id: dd488d47-4f19-5efa-bb4a-ff094c6712ab
  slug: gentle-resonance-7390
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: c8669145-6d1f-55ed-919a-f050c96fd3c2
  slug: small-mud-2269
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 75af77452a33b10ea2b2c1edb8a23f399898ee7825af07d6cf35fa1531f7bd5e
---
## Hypothesis
The STEP-derived chassis GLB (parent node) gave every part a regex-guessed material because STEP carries no appearance. Theo's `whoop-assembly.fbx` was authored with real per-part materials ("all the textures and stuff") — loading those instead should make the Studio/Bench drone look like the actual airframe, and a brightness bump keeps the dark plastics from reading as a black blob.

## Setup
- **Source**: `~/Downloads/whoop-assembly.fbx` (Kaydara FBX 7400, 3.4 MB). 16 meshes, **15 authored materials**: props (baseColor `[.13,.13,.13]`, **alphaMode BLEND** alpha .49), rotors/stators (dark metal + a red `[.8,0,0]`), FC/ESP green `[.03,.32,.04]`, a yellow `[.78,.8,0]`, greys and blacks. Real part names: `chassis`, `front/rear-left/right-prop`, `rotors`, `stators`, `grommets`, `flight-controller`, `tof-sensor`, `esp32-s3`. **No embedded textures** — the lone `RelativeFilename` was a `Screenshot ....png` under `~/Documents/captures/` that is neither embedded (0 `Content` blobs) nor still on disk, so it drops harmlessly; the base-color materials are the substance.
- **Converter** (`scripts/chassis_fbx_to_glb.py`, new; **replaces** the STEP-path `chassis_to_glb.py`, now `git rm`-ed): Blender 4.2 headless (`--background --factory-startup --python`) imports the FBX and exports GLB with `export_materials=EXPORT`, `export_yup=False` (keep Blender/CAD axes; the frontend reorients). Blender is the only thing on the bench Mac that reads FBX materials faithfully; glTF export inlines everything so the frontend keeps its single-file `GLTFLoader` path (no `FBXLoader`, no external texture fetch). Output `web/studio/assets/whoop_chassis.glb` = **9.3 MB, 139k tris**.
- **Frontend** (`drone-model.js`): **removed** the STEP node's `CHASSIS_MATS` name-regex override — the GLB's authored materials are now kept verbatim; `traverse` only flags meshes `castShadow`. **Axis fix**: this FBX is **+Y-forward** (front props at y=+23 mm) / Z-up / mm, *opposite* the STEP model's -Y-forward, so `rotation.z` flips **+pi/2 -> -pi/2** to put the nose on sim +X. bbox-recenter + `scale = 0.54 / max(sizeX,sizeY)` are unit-agnostic, so mm-vs-m needs no change. `FPV_OFFSET` stays 0.28 (nose still reaches x~0.27 after scale).
- **Lighting** (`scene.js`, affects every tab — one shared `createScene`): `HemisphereLight` 0.9->1.35, `DirectionalLight` sun 1.4->2.1, **+** a new shadowless fill `DirectionalLight(0xdfe6ff, 0.7)` from `(-12,6,-9)` (opposite the sun) so the chassis's near-black plastics keep form instead of crushing to silhouette.

## Results
- **Transform-chain render** (offline, exact JS steps on the GLB): after yaw-90 + recenter + scale, front props at **x=+0.151**, rear at **x=-0.147**, ToF **under the belly at z=-0.048**, footprint 0.54x0.53 m. Colors read through (yellow rotors, red/green PCBs, black stack) — recognizably a whoop.
- **Syntax**: `node --check` clean on `drone-model.js` + `scene.js`.
- **Live serve**: studio booted `--bridge fake` serves `/assets/whoop_chassis.glb` -> **200, 9560068 B**, `drone-model.js` + `scene.js` -> 200.

## Verdict / Honesty
GREEN — the textured chassis loads with its authored materials, correctly oriented across all four drone-drawing tabs, under brighter lighting; procedural glyph still the fallback. Caveats: (1) same as parent — **not yet eyeballed in a real WebGL context**; a live Bench-tab pass is the next step (the flat matplotlib preview washes out the translucent white duct, which PBR will render correctly). (2) **9.3 MB** is ~17x the STEP GLB (551 KB) and ~139k tris — fine for the local FastAPI-served Studio, but if it ever feels heavy the lever is Blender decimation or Draco (Draco would need a `DRACOLoader` + wasm decoder past the current three-only importmap). (3) The missing screenshot texture means any part that was *meant* to be image-textured falls back to flat base color — acceptable here since it was a stray ref.

## Lineage
Direct child of the STEP->GLB chassis node (`2682e5ff`): same seam and frontend, but the mesh source moves STEP -> textured FBX and the material-override logic is deleted in favor of authored materials, plus the lighting bump. Commit `aedaa33`.

## Commit
- `aedaa33` studio: swap chassis mesh to the textured FBX (Blender headless convert, keep authored materials, yaw -90 for +Y-forward axes) + brighter lighting (hemi/sun up, opposite-side fill)