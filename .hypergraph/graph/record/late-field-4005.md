---
node_id: 30d3704a-1051-53ce-962c-7152c076ba94
slug: late-field-4005
title: 'Tooling: in-repo headless capturer (web/capture/) replaces the missing nw-viz — the Studio''s own scene, true scale, as a concept video'
created_at: '2026-07-30T23:37:48.105967+00:00'
parents:
- lucky-bush-5765
- gentle-bonus-7668
- gentle-resonance-7390
- lively-block-9924
summary: 'Video capture moves in-repo: web/capture/ + scripts/capture_video.py import web/studio/''s scene modules verbatim, so the MP4 is the dashboard''s CAD chassis + greybox room instead of nw-viz''s procedural glyph on a flat grid — and it works at all here (../nw-viz is not checked out, so `viz.py --video` skipped and /api/export 503''d). Rendered the take-off→hover→flip→land concept video at the TRUE 82 mm airframe scale (vs the Studio''s ~7x hero glyph): 666 frames rendered == 666 decoded, 13.32 s @ 50 fps, 1920x1080. Trajectory retuned to match: rests ON the floor (WHOOP_REST_Z_M 9.2 mm, from the chassis CAD bbox), hover 2.3→1.6 m, land ends at 0.062→0.0092 m via a descent ramp + ground-contact clamp, phi/Φ=1.02. GREEN.'
origin:
  backend: flywheel
  node_id: 30d3704a-1051-53ce-962c-7152c076ba94
  slug: late-field-4005
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: a914407b-a111-528e-9b1e-811e96bd3af3
  slug: raspy-sun-7547
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 054fe85504c745061761afb20b83e92e4dad8c5a21446e3a99efa1f71e2cc26b
---
## Hypothesis

A concept video should be the *target*, rendered honestly: the real Air65 II airframe at its real size, starting on the ground, taking off, hovering, flipping, landing, in the environment the Studio dashboard already shows. If a capture harness points at the Studio's own scene modules rather than reimplementing them, the video and the dashboard cannot drift.

## Setup

Two things were true before this node:

1. **The trajectory already existed** — `scripts/hero_takeoff_flip_land.py` drives `WhoopDynamics` through the real deploy split: an altitude/attitude PD owns climb/hover/land, the **trained `acro_flip` policy** owns the flip window (parent `lively-block-9924`). It had never been run.
2. **No renderer could produce this look.** The only MP4 path was `../nw-viz/capture.mjs` (parent `lucky-bush-5765`), which is **not checked out on this machine** — so `scripts/viz.py --video` silently skipped and `POST /api/export` returned 503. Even upstream, nw-viz's scene is the *old* look: a procedural box-and-cylinder glyph on a flat `GridHelper`, no shadows, no room. The CAD chassis (`gentle-resonance-7390`) and the "1 METER / PROTOTYPE" greybox room (`gentle-bonus-7668`) live only in `web/studio/`, which had no capture path.

**What was built** (commit `b1f1e28`):

- **`web/capture/`** — a second page that *imports* `web/studio/`'s `scene.js` / `environment.js` / `geometry.js` / `drone-model.js` / `playback.js` unchanged. Cinematic mode on top: clean full frame (no PiP cells, no HUD chrome), a **fixed** camera box-fitted to the flight, the **true 82 mm** airframe, spinning props, and a DOM title/phase caption layer baked in by screenshotting `#app` rather than the canvas.
- **`scripts/capture_video.py`** — the driver, the same four moving parts `capture.mjs` had, in Python: read the replay (`viz.replay.load_run`), serve `web/` on an ephemeral loopback port, drive headless Chromium under SwiftShader with `renderFrame(i)` → screenshot, pipe PNGs to ffmpeg (`imageio_ffmpeg`'s bundled binary — there is no system ffmpeg). **The frame index is the only clock**: no rAF, no wall time, so a render is reproducible and cannot drop or double a frame. three.js is cached under `.cache/three/`, so renders after the first are offline.
- **Trajectory, retuned for true scale** — the drone now *rests on the floor* (`contract.WHOOP_REST_Z_M`, measured off the chassis GLB's own bbox: 81.96 × 83.40 × 18.68 mm normalized to the 82 mm footprint → 9.2 mm half-height), hovers at 1.6 m instead of 2.3 (a room, not a gym), and each frame carries a **numeric** `scene.phase` code whose labels ride in `meta.scene_info.phase_labels` — additive optional fields, so the replay version stays at **2**.

## Results

**vs `lucky-bush-5765` (nw-viz):** the capturer is in-repo and points at the Studio's scene. Concretely: CAD chassis instead of a procedural glyph; greybox room + contact shadows instead of a flat grid in a void; true 82 mm scale instead of the ~7× hero glyph; and it runs here at all. `scripts/viz.py --video` and `POST /api/export` both route through it — the export endpoint returns **200 with an MP4 where it used to 503**.

**vs `lively-block-9924` (the acro-flip sequence):** the sequence is now ground-truthful end to end.

| | before | after |
|---|---|---|
| start z | 0.25 m (floating 3× its own height) | **0.0092 m** (resting on the floor) |
| end z | 0.062 m (hovering, PD never arrives) | **0.0092 m** (touched down) |
| hover altitude | 2.3 m | **1.6 m** |
| rotation completed | — | **phi/Φ = 1.02** |
| min z during flip/recover | — | 1.165 m (0.40 m lost, ample clearance) |

The landing fix is the substantive one: DiffAero has **no contact model**, so a pure altitude PD only ever approaches the floor exponentially (τ ≈ 0.93 s — it ended 6.2 cm up, 3.4× the airframe's own height). Replaced with a **descent ramp that runs through the floor** plus a minimal ground clamp (`pos.z ≥ rest`, no downward velocity). That is a real touchdown with the throttle cut, and it also fixes take-off (the airframe sits still while the props spool instead of sagging).

**Render:** 1920×1080, 50 fps, 666 frames (75 title + 516 flight + 75 end card) → **666 frames decoded, 13.32 s** via ffmpeg's null muxer. Stills verified by eye at the take-off, hover, flip and landed frames: CAD chassis present (not the placeholder glyph), true scale against the 1 m floor squares, props resting on the floor at t=0, contact shadow visible, no axis triad / trail / HUD.

**Three fixes the true-scale requirement forced out:**

1. **Shadows.** `scene.js` sizes the sun's shadow ortho for a ±30 m arena at 1024². An 82 mm drone spans ~1.4 texels of that — no contact shadow at all, the drone reads as *pasted over* the floor. The capture page refits the ortho to the room and doubles the map.
2. **Camera fit.** `cameras.js` fits a bounding *sphere* with a 2 m floor (right for a course, wrong here): it parked the camera 5.4 m from an 82 mm drone. Replaced with an exact **box** fit — this flight is tall and thin (1.6 m of climb inside 0.7 m of drift) — plus a 40° lens instead of 55°.
3. **Room size.** The room must be big enough that the *camera stands inside it*, or the near wall culls (it's a `BackSide` box) and a hard diagonal seam cuts across the frame.

## Verdict / Honesty

**GREEN** as tooling: the video exists, is reproducible, and both previously-dead seams (`--video`, `/api/export`) now produce MP4s. `pytest`: 274 passed, 1 pre-existing failure (`tensorboard` not installed on this Mac — identical on a stashed tree).

Honest caveats:

- **Prop spin is the one deliberately non-literal element in the frame.** A real whoop turns ~30 000 rpm, which at 50 fps aliases to a stroboscopic mess; `--prop-rate` sets a stylized rate that reads as spin and scales with the recorded collective thrust. Said so in the docstring and in `docs/STUDIO.md`.
- **The ground clamp is a modelling choice, not physics.** DiffAero has no contact; the clamp is the minimum needed to end a flight on the floor, and it touches nothing else about the flight.
- **The flip is the trained policy, the rest is a PD.** That is the real deploy split, not an animation — but it is a *sim* trajectory, not a recorded real flight. The real blind flip is `soft-sky-1694`.
- **SwiftShader is the only path on this Mac** (no CUDA). 666 frames at 1080p is minutes, not seconds; `--stride` and a smaller `--width/--height` are the iteration path.
- `--axis pitch` is still broken (`runs/acro_flip_pitch/` has no weights). Out of scope, untouched.

## Lineage

- `lucky-bush-5765` — nw-viz, the Node hero-MP4 tool this replaces (kept as a fallback when it happens to be checked out).
- `gentle-bonus-7668` — the greybox room + light/dark theme the video renders inside.
- `gentle-resonance-7390` — the textured CAD chassis that is now the drone at true scale.
- `lively-block-9924` — the take-off→flip→land acro harness whose sequence this renders.

Artifacts: `takeoff_flip_land.mp4` (the concept video), `hero_still.png` (mid-flip frame), `replay.json.gz` (the source trajectory, contract v2 with `scene.phase`), `run.json` (reproducibility manifest).