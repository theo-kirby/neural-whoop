---
node_id: 8dc5078f-cf47-5cf0-b207-4062d8ba46f8
slug: white-surf-8279
title: 'Live interactive Studio: real-time disturbance sandbox (wind/push/drop/move) over /ws/live (GREEN)'
created_at: '2026-06-28T18:49:40.065971+00:00'
parents:
- misty-paper-7383
- floral-sunset-3918
summary: 'Realizes the interactive-perturbation Studio idea (floral-sunset-3918): upgrades the Studio from pre-recorded playback to a LIVE interactive sim loop. A new /ws/live websocket + stateful LiveSession steps a policy at ~50 Hz while the browser injects disturbances — wind (continuous), push/drop-block (one-shot impulses), click-to-move the hover setpoint — all through the same add_velocity/add_body_rate seam the hover policy trained against. Verified end-to-end against the hover policy: push arrested (2.16→0.18 m/s), dropped-block tumble recovered (spin 4.38→0.15), setpoint move arrived (0.22 m); single-flight with /api/rollout (409). The hands-on stability demo the branch wanted.'
origin:
  backend: flywheel
  node_id: 8dc5078f-cf47-5cf0-b207-4062d8ba46f8
  slug: white-surf-8279
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## What shipped
- **Backend**: `studio/live.py` `LiveSession` (stateful, steppable); `/ws/live` websocket in `server.py` (build off-thread, single-flight via the shared `ROLLOUT_LOCK`, reader-queue + ~50 Hz step/stream loop, frees the GPU session on disconnect); a `build_session` refactor (env+agent construction shared with the rollout path); and a shared `hero_pose_snapshot` frame extractor so the live wire-format can't drift from the recorded replay schema.
- **Frontend**: `web/studio/live.js` (own three.js scene, WS client, reuses the shared glyph/marker builders, rolling per-drone trails, a top-down wind pad, push/drop buttons, raycast click-to-move-setpoint) + a third **Live** tab in `index.html`/`main.js`.
- **Disturbances**: wind (continuous world accel), push (one-shot velocity kick), drop-block (downward+lateral impulse **+ a body-rate tumble**, impulse-only — no real collision), setpoint move (hover only). All ride `WhoopDynamics.add_velocity`/`add_body_rate` — the external-wrench primitive this idea called for, **identical to the training seam** (`impulse_dv`/`impulse_dw`).

## Verification (idea: placeholder → working)
Parent `floral-sunset-3918` was a placeholder idea (not started). This delivers the working feature, verified end-to-end against the trained hover policy over the real websocket:
- wind 4 m/s² → leans in, holds.
- push → peak 2.16 → 0.18 m/s (**arrested**).
- drop-block → peak spin 4.38 → 0.15 rad/s, pos err 0.18 m (**tumble recovered**).
- setpoint click-move → flew there, err 0.22 m (**arrived**).
- single-flight: `/api/rollout` returns **409** while live runs; a second live socket is rejected; both free on disconnect.

## Verdict / Honesty
**GREEN** — the Studio is now a hands-on stability sandbox: you feel a policy's robustness by trying to knock it down. Honest simplification vs the idea: the dropped ball is modeled as an **impulse (+tumble), not a real rigid-body contact** (the idea's “a small rigid body that falls and bumps the drone”) — a faithful disturbance for the demo without adding a contact-physics engine, and it reuses the trained impulse seam so it's exactly what the policy was hardened against. Click-to-move is hover-only (other families have no setpoint).

## Lineage
- realizes **`floral-sunset-3918`** (interactive perturbations in the Studio) — placeholder → working.
- builds on the **hover policy** (`misty-paper-7383`): the policy it pokes, trained against this exact impulse seam.
- builds on the Studio playback harness (`e0d57844`, floral-sunset's parent) — upgraded playback → a live loop.
- commits 74fdf8c (backend), d76ed4a (frontend).