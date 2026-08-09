---
node_id: df7aa1c6-ca28-58d0-a0f5-4d86cadee723
slug: withered-bar-0632
title: 'Tooling: embed the battery + flight-controller image textures in the chassis GLB'
created_at: '2026-07-14T09:35:28.060524+00:00'
parents:
- gentle-resonance-7390
summary: 'Closed the parent FBX node''s open caveat ("no embedded textures — the lone texture ref was a stale screenshot"): the updated whoop-assembly 2.fbx carries two real image textures — battery.png (the LAVA 320mAh wrap, on the battery mesh / Material.013) and flightcontroller.png (an Afroflight32 board, on the flight-controller mesh / Material.015). The FBX still references them by their original ~/Documents/captures screenshot paths (11.10.00.png / 11.24.43.png) which don''t travel with the file, so scripts/chassis_fbx_to_glb.py gained a --tex SUBSTR=PATH remap: it repoints each image datablock to the file Theo supplied and packs it, so Blender''s glTF export inlines the bytes and the GLB stays self-contained. Verified: the rebuilt web/studio/assets/whoop_chassis.glb (9.9 MB) embeds exactly 2 image/png, wired to Material.013 (tex 0) and Material.015 (tex 1); geometry/axes unchanged (front props still +Y, yaw -90 still correct), so drone-model.js needed no edit; live studio serves it at 200. Pure viz — no contract/env/training change. GREEN.'
origin:
  backend: flywheel
  node_id: df7aa1c6-ca28-58d0-a0f5-4d86cadee723
  slug: withered-bar-0632
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1b5c6fc9-bcdd-5de8-8470-e54065994b42
  slug: summer-limit-8235
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 3176c94538a78125fc9430cd3fb252745b8849aca50019317eaaae36b20a241c
---
## Hypothesis
The parent node (FBX materials) shipped with a caveat: the FBX's only texture ref was a stale screenshot, so parts meant to be *image*-textured fell back to flat base color. Theo re-exported `whoop-assembly 2.fbx` with two real textures and handed over the image files, so embedding them should give the battery its LAVA wrap and the FC its board silkscreen.

## Setup
- **Source**: `~/Downloads/whoop-assembly 2.fbx` (15 meshes, 138 946 faces, 17 materials — one more than v1's 16). Two `FbxFileTexture` refs, both pointing at now-absent authoring paths: `~/Documents/captures/Screenshot 2026-07-14 at 11.10.00.png` and `...11.24.43.png`.
- **Textures supplied**: `~/Downloads/battery.png` (32 KB, the *LAVA 320mAh 95C* wrap) and `~/Downloads/flightcontroller.png` (338 KB, an *Afroflight32 rev6* board top).
- **Converter change** (`scripts/chassis_fbx_to_glb.py`): new repeatable `--tex SUBSTR=PATH` arg. After FBX import, `remap_textures` walks `bpy.data.images`, and for any datablock whose name/filepath contains SUBSTR, repoints `filepath` -> PATH, `reload()`, and `pack()` (embed bytes). glTF export (`export_image_format=AUTO`) then inlines the packed images into the GLB buffer. Run:
  `Blender --background --factory-startup --python scripts/chassis_fbx_to_glb.py -- --fbx "~/Downloads/whoop-assembly 2.fbx" --tex 11.10.00=~/Downloads/battery.png --tex 11.24.43=~/Downloads/flightcontroller.png`

## Results
- **GLB structure** (rebuilt `web/studio/assets/whoop_chassis.glb`, **9.9 MB**, +~0.4 MB over the untextured v2 ≈ the two PNGs): `images: 2` — `battery` (image/png, bufferView 16) + `flightcontroller` (image/png, bufferView 31); `textures: 2`; `Material.013 -> baseColorTexture tex0`, `Material.015 -> baseColorTexture tex1`.
- **Part mapping**: `Material.013` is on the battery mesh (node `Circle.001`), `Material.015` on node `flight-controller` — so the LAVA wrap lands on the battery and the Afroflight silkscreen on the FC, as intended.
- **Orientation** re-checked on the new file: front props at +Y (23 mm), ToF under the belly — identical to v2, so `drone-model.js` (yaw -90) is untouched.
- **Live serve**: studio `--bridge fake` serves the GLB -> **200, 9 979 912 B**.
- Fixed a misleading log: `img.has_data` reads stale in `--background` right after `pack()` (printed MISSING though the export embedded fine) -> now reports on the source file's existence instead.

## Verdict / Honesty
GREEN — both textures are embedded and mapped to the right parts; the GLB is self-contained. Caveats: (1) **not yet eyeballed in-browser** — GLB-structure + serve checks confirm the bytes are present and wired, but the final look (UV layout correct? wrap oriented right?) is Theo's live Bench-tab call. (2) The `--tex` mapping is by filename substring of the *original* screenshot names; if the FBX is re-exported with different capture timestamps, the SUBSTR args must be updated to match. (3) Total asset now 9.9 MB / ~139k tris — unchanged concern from the parent; decimation/Draco remains the lever if needed.

## Lineage
Direct child of the FBX-materials node (`dd488d47`), resolving its stated "no embedded textures" gap. Same mesh + axes + frontend; only the two image textures are added (and the converter's `--tex` remap that makes them travel). Commit `4c5aebb`.

## Commit
- `4c5aebb` studio: update chassis to whoop-assembly 2.fbx with battery + FC textures (--tex remap + pack; self-contained GLB)