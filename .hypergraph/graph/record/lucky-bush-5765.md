---
node_id: 6f89cea9-d3b4-57eb-939d-c2c051232e2c
slug: lucky-bush-5765
title: 'Tooling: nw-viz — Three.js replay -> hero MP4 (3D wide + FPV/top-down PiP)'
created_at: '2026-06-26T15:19:22.379763+00:00'
parents:
- square-smoke-0918
- cold-pond-1089
summary: 'Off-frontier infrastructure (no racing-metric change). A standalone Node/Three.js sibling project (/home/theo/nw-viz, repo theo-kirby/nw-viz @ 390bb94) that turns a neural-whoop-replay v1 doc into a polished hero VIDEO: a fixed wide 3/4 3D course shot plus synced onboard-FPV and top-down picture-in-picture insets, composited into one H.264 MP4, rendered deterministically and headlessly (Playwright + SwiftShader -> ffmpeg-static). Ports the lab replay-viewer scene; consumes the locked replay contract unchanged. The only neural-whoop edit is an optional, non-fatal `scripts/viz.py --video` shell-out seam (commit 887cffa on main) — no JS enters the pure-Python package; pytest still green (46). builds-on 563fc6d9 (the visual observability seam / replay contract this extends) + 92a180c8 (the [128,128]@80M 2.72s baseline = code state + hero subject). Verified: smoke + full hero renders (big128 best ep, tp005), 1280x720 @ 50fps, 599 frames in ~41s.'
origin:
  backend: flywheel
  node_id: 6f89cea9-d3b4-57eb-939d-c2c051232e2c
  slug: lucky-bush-5765
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: fd60a857-a840-5fb4-b715-35d30f947d3b
  slug: bold-wood-3559
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: 3abf0c2a5f819b584e3eba2d7a44c66b40db6ab93750bbfb1495d23eebb30a61
---
# nw-viz — Three.js replay -> hero MP4 (tooling node)

## What & why
The visual pack (`563fc6d9`) gave us static PNGs, a 6-frame FPV slideshow, and an ad-hoc matplotlib trajectory animation — visually thin for a hero artifact. This adds a real **Three.js 3D perspective** render of the drone flying the whole course, with two **picture-in-picture** insets (onboard FPV + top-down line) synced to the timeline, composited to an **MP4** by a one-command CLI.

**Hard constraint (user decision):** keep neural-whoop **pure-Python / no Node**. All JS/Three.js/browser tooling lives in a **separate sibling repo** `/home/theo/nw-viz/` (`theo-kirby/nw-viz`). Locked with the user: **Three.js + headless capture** (real WebGL), **fixed wide-shot** main camera, charcoal/grey theme.

**Lineage:** builds-on `563fc6d9` (the `neural-whoop-replay` v1 contract this consumes **unchanged**) and `92a180c8` (the `[128,128]@80M` GREEN baseline — its `replay.json.gz` is the hero subject, and the `--video` seam commit sits on that code state). Not an empirical hop — changes no racing metric; it equips the loop with a shareable hero video.

## What landed
### Sibling repo `theo-kirby/nw-viz` @ `390bb94` (was an empty git init)
- `capture.mjs` — **one-command CLI**: `node capture.mjs --replay <run>/replay.json.gz --out out/x.mp4`. Node gunzips+parses the replay (fflate), injects it via `addInitScript` (no fetch/CORS), drives a deterministic frame loop (`NWVIZ.renderFrame(i)` -> screenshot the `#app` container -> pipe PNG to `ffmpeg-static` H.264, `fps = control_hz/stride`). `--episode` (default `best`), `--stride`, `--width/--height` (even-clamped), `--fps`, `--crf`.
- `src/viewer.js` — **port** of `neural-whoop-lab/web/replay-viewer/viewer.js`: `world` group rotated -90deg about X (sim Z-up RH -> three Y-up RH; pose quaternion applies VERBATIM — does NOT use `meta.unity_hint`), drone glyph, gate wireframe spheres recolored by progress, gz decode, `applyFrame(idx)` core. Exposes `window.NWVIZ.{frameCount, meta, renderFrame}` + `NWVIZ_READY`. Best-episode pick mirrors `render.py::_best_episode` (laps -> gates -> length).
- `src/cameras.js` — fixed wide `PerspectiveCamera(50)` auto-framed from the gates+trajectory Box3 (3/4 hero angle, pulled to fit the limiting FOV); FPV `PerspectiveCamera(90)` parented to the drone glyph (looks down body +x / up +z, mirroring `render_fpv`); top-down `OrthographicCamera` (up=(0,0,-1)) fit to the inset aspect per render.
- `src/layout.js` — single `WebGLRenderer({preserveDrawingBuffer})`, `setPixelRatio(1)`; 3 scissor/viewport passes (main full-frame + 2 bottom-corner insets ~27%). HUD + PiP borders/labels are **DOM overlays** in `index.html`, captured for free by screenshotting `#app`. Drone hidden during the FPV pass.
- `src/palette.js` — `render.py`-exact gate RGB (NEXT 255,150,30 / UPCOMING 120,130,150 / PASSED 60,200,90) + Turbo speed-trail ramp normalized to a fixed per-episode p95.
- `serve.mjs` (zero-dep static server, importmap `/vendor/*` -> local `node_modules/three`, offline/deterministic), `index.html`, `scripts/smoke.mjs`, `package.json` (postinstall fetches Chromium).
- **Theme:** charcoal/grey throughout (background, ground, grid, HUD, PiP labels). Drone glyph is monochrome charcoal with **white nav lights on the front motors, red on the rear** (heading still legible); gate-state colors + Turbo trail kept (they carry meaning).

### neural-whoop `887cffa` on `main` (the ONLY repo edit)
- `scripts/viz.py` — opt-in `--video` flag: after `build_pack`, shells out to `../nw-viz/capture.mjs` (guarded on `shutil.which("node")` + script existing) to drop `viz/replay.mp4`; non-fatal skip notice if absent. Mirrors the `render_depth` documented-seam pattern. No JS in the Python package; `pytest -q` green (46).

## Verification
- `node scripts/smoke.mjs` -> 3 frames (`--stride 200`), `out/smoke.mp4`, decoded frames > 1. GREEN.
- Full hero: `gate_race_big128_120M_s0` best episode (ep 5, 4 laps) -> `out/big128.mp4`, **1280x720, 50 fps, 599 frames, ~41s** headless (SwiftShader software WebGL — no GPU needed).
- Second sample `gate_race_tp005` renders. Mid-frames eyeballed: gate colors/positions agree with `viz/trajectory.png` + `fpv_*.png`; drone flies all laps through the static wide frame; both PiPs track.
- Python seam exercised end-to-end (`_maybe_render_video` -> `replay.mp4`) and the no-op-without-node path verified.

## Notes / open follow-ups
- Headless WebGL via **SwiftShader** is the portability path (works without a usable GPU); drop `--enable-unsafe-swiftshader` if a real GPU is available for speed.
- Wide camera is generously framed (1.25x margin) so the whole figure-8 always fits — drone reads small mid-course; could tighten for a punchier shot.
- Top-down marker is the glyph (tiny at course scale) — a fixed-screen-size sprite would make it pop.
- HUD `policy` label shows `meta.config` baked into the replay at record time (here `gate_race_baseline`), not the run-dir name.
- Neither repo pushed to its GitHub remote (local-only autonomy); node references local commits.