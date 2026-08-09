---
node_id: 322ab11f-0a94-5828-88ab-a21dc08cab59
slug: proud-wind-5129
title: 'Tooling: per-drone RGB body-axis gizmo (replaces nav-light dots) + brighter lighting'
created_at: '2026-07-14T10:50:55.383556+00:00'
parents:
- withered-bar-0632
summary: 'Swapped the four white/red nav-light dots for a single RGB body-axis triad per drone (THREE.AxesHelper, length 0.34: red +X forward, green +Y left, blue +Z up), so each drone''s heading/orientation reads directly off the gizmo instead of front/rear glow. Drawn depthTest=false / renderOrder 10 so it stays visible through the chassis, and attached to the drone group (not the swap-out placeholder) so it survives the CAD mesh swap and shows on all four tabs (Bench, Live, playback, editor). Also brightened scene.js another step: hemisphere 1.35->1.75, sun 2.1->2.7, opposite-side fill 0.7->1.0. Verified: node --check on both modules, no dangling nav references, live studio serves at 200, offline render shows the triad correctly oriented (red out the nose). Pure viz — no contract/env/training change. GREEN.'
origin:
  backend: flywheel
  node_id: 322ab11f-0a94-5828-88ab-a21dc08cab59
  slug: proud-wind-5129
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 17d9387e-15ef-5297-ac88-fa45e2ff799c
  slug: polished-dream-7991
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 2643e96bbab8cecb6a57b77e8752ff24bafc238973eb340c066c915cb8e23bbd
---
## Setup
Theo asked to replace the drone's red/white nav lights with a plain RGB direction axis, and to raise brightness once more.
- **`drone-model.js`**: removed the four `MeshBasicMaterial` nav-light spheres (and the `front` flag / `navGeo` that drove them). Added one `THREE.AxesHelper(0.34)` per drone — the built-in three-line gizmo, red=+X, green=+Y, blue=+Z, matching the sim body frame (+X forward, +Y left, +Z up). Set `material.depthTest = false`, `material.transparent = true`, `renderOrder = 10` so the axes render on top of the chassis and stay legible; added to the drone `Group` (like the identity center marker) rather than the procedural placeholder, so it persists after the CAD chassis swaps in. The arms/rotors placeholder loop is unchanged apart from dropping the nav dots.
- **`scene.js`** (shared `createScene`, every tab): `HemisphereLight` 1.35->1.75, sun `DirectionalLight` 2.1->2.7, opposite-side fill 0.7->1.0.

## Results
- `node --check` clean on `drone-model.js` + `scene.js`; grep confirms nothing else referenced the old nav lights.
- Live studio (`--bridge fake`) serves `drone-model.js` / `scene.js` / index at 200.
- Offline render (chassis + drawn triad, artifact): the axes sit at the drone origin with red pointing out the nose (+X), green out the left (+Y), blue up (+Z) — the intended direction gizmo.

## Verdict / Honesty
GREEN — gizmo + lighting change is in and self-consistent across tabs. Caveats: (1) **not eyeballed in a real WebGL context** — the always-on-top axes (depthTest off) can, with many drones, visually overlap through each other; fine for the single/few-drone Bench/Live views, worth a second look if a big swarm renders. (2) Brightness is now noticeably up three steps total; if it clips, hemisphere/sun are the two dials. (3) The identity center marker (per-drone tint) is kept — only the nav dots were removed.

## Lineage
Direct child of the textured-chassis node (`df7aa1c6`): same mesh/asset, only the drone's heading indicator (nav dots -> RGB axes) and a further lighting bump. Commit `a80d705`.

## Commit
- `a80d705` studio: RGB body-axis gizmo per drone (replaces nav lights) + brighter lighting (hemi/sun/fill up)