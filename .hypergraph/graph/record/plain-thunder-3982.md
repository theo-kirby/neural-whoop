---
node_id: e306e2c3-f9e1-518a-8781-0c8d073f9786
slug: plain-thunder-3982
title: 'Tooling: Studio 2-tab UX overhaul — draggable sidebar, Simulation (player+editor merged), Real (bench + calibration mode)'
created_at: '2026-07-14T16:11:08.275917+00:00'
parents:
- proud-wind-5129
- rapid-meadow-0957
- white-surf-8279
- summer-smoke-5603
summary: 'Condensed the Studio from 4 tabs to a sim-to-real pair vs the axis-gizmo parent: Player+Editor merge into one Simulation tab (✎ Edit-course toggle overlays the editor on the shared player scene — one WebGL scene, Save & fly with no tab switch); Bench→Real gains a Betaflight-style Calibration mode (frameDrone close-up, full roll/pitch/yaw glyph, degree readout, 4 rolling charts: attitude/gyro/battery+throttle/link age; yaw newly forwarded from MSP_ATTITUDE); the Live tab UI is removed but /ws/live is retained and verified serving the Real tab''s parallel-sim twin; a draggable divider (280–640 px, persisted) replaces the fixed 348 px sidebar. All pilot/flight/studio tests pass on the bench Mac; net −120 LoC. Commit 40dff4d. Verdict: shipped (method).'
origin:
  backend: flywheel
  node_id: e306e2c3-f9e1-518a-8781-0c8d073f9786
  slug: plain-thunder-3982
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Goal

Condense and modernize the Studio UX (Theo's ask): fewer, clearer tabs that read as a **sim-to-real pair**; a resizable sidebar; and a Betaflight-setup-style **calibration mode** so a freshly-plugged real drone can be sanity-checked (tilt it by hand, watch the on-screen drone track) before any flight.

## Setup / what changed (vs parent `322ab11f`, the axis-gizmo state)

**1. Draggable sidebar divider** (`index.html`, `main.js`): sidebar width is now `var(--sidebar-w)`; a 6 px grab strip between `#view` and `#sidebar` drags it (clamped 280–640 px), persisted to `localStorage[nw_sidebar_w]`; drag + window-resize share one `onLayoutChange()` (view resize + hero-inset sync + chart redraw).

**2. 4 tabs → 2**:
- **Simulation** = Player + Editor merged. `createEditor` no longer builds its own scene — it rides the shared player `view`, with every editor object (gizmo proxy, gate wireframes, pick meshes, arena ring, reference drone) in one toggleable `THREE.Group`. An **✎ Edit course** toggle flips `simMode` play↔edit: play shows policy-meta/playback/charts sections and the hero insets; edit shows the course sections and enables the gizmo + ground-click gate dropping (the pointer handler stays attached, gated by an `active` flag). *Save & fly* now flips back to play mode and runs — no tab switch. A fresh replay always lands in play mode.
- **Real** = the renamed Bench tab (internal `bench*` ids kept to minimize churn).
- **Live tab UI removed** (`web/studio/live.js` deleted, panel + mount + wiring gone) — but `studio/live.py` + the `/ws/live` route are **retained**: the Real tab's parallel-sim twin rides them (verified live post-change: `/ws/live` ready + frames with a hover policy).

**3. Calibration mode** (Real tab, `bench.js` + `cameras.js::frameDrone` + `pilot/controller.py`):
- **⌖ Calibrate** swaps the dashboard for a calibration sub-panel and zooms the camera onto the drone glyph (`frameDrone`: same 3/4 hero direction, fixed 1.1 m distance); exit restores the dashboard + default wide view.
- `_make_frame` now forwards **yaw** (sim-signed, negated MSP_ATTITUDE compass heading) — it was decoded but never sent. The glyph orients from full roll/pitch/yaw (`"ZYX"` Euler — yaw first, so a hand-yawed drone still rolls about its own body axes on screen; the plan's `"XYZ"` composes wrongly at large yaw).
- Sidebar: big roll/pitch/yaw degree readout + four rolling charts via a generalized `drawSeries` (N series, per-series scales): **attitude** (±auto-sym), **gyro p/q/r**, **battery + throttle** (native units, dual scale), **link age**. ARMED/OVERRIDE chips stay visible; the radio still owns arm + override + kill (unchanged).
- The fake bridge now synthesizes a **yaw wobble** too, so calibration exercises end-to-end with no hardware.

## Results

- `node --check` clean on all edited JS; `live.js` 404s; the page serves exactly 2 tabs.
- Fake-bridge serve on the bench Mac (`NW_FLIGHT_FAKE=1`, CPU venv): `/ws/flight` frames now carry `telemetry.yaw` (−0.105 rad observed from the synthesized wobble); `/ws/live` still serves ready+frames (the sim-twin dependency proven intact).
- Tests: `test_flight_controller` + `test_flight_ws` (17) and `test_pilot_*`/`test_msp` (35) all pass on the Mac venv; `test_studio` passes except the pre-existing `tensorboard`-missing env gap (fails identically on the clean tree).
- Net **−120 LoC** (425 insertions / 545 deletions across 10 files) while adding two features (divider, calibration).

## Verdict / Honesty

Shipped (method node — no metric claim). The final **visual** pass (drag feel, edit-mode overlay on a loaded replay, calibration camera framing) is Theo's — WebGL can't be driven headlessly here; everything scriptable was verified above. Yaw caveat surfaced in the UI: with no magnetometer it's the FC's gyro-integrated heading — tracks hand rotation, drifts slowly, re-zeros at gyro reset. Interactive wind/push/drop UI is gone with the Live tab; the socket commands still exist server-side if a future tab wants them back (idea nodes `2ed708fd` / `fd6a3569` remain valid against the backend).

## Lineage

- Parent `322ab11f` — RGB body-axis gizmo (the studio state this overhauls; commit a80d705).
- Parent `f0111520` — unified bench dashboard (the Bench tab restructured into Real + calibration).
- Parent `8dc5078f` — Live interactive tab (UI removed here; its `/ws/live` backend retained for the sim twin).
- Parent `9eac6fbd` — hero-layout viewport + 3D course editor (the editor merged into Simulation here).
- Commit `40dff4d` (`theo-kirby/neural-whoop`, main). Docs updated: `docs/STUDIO.md`, `CLAUDE.md`.