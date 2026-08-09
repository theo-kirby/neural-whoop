---
node_id: 9eac6fbd-2175-56fe-8577-8af17ea996fd
slug: summer-smoke-5603
title: 'Tooling: Studio hero-layout viewport + 3D course editor + in-dashboard hero-MP4 export'
created_at: '2026-06-28T14:08:27.005028+00:00'
parents:
- lucky-bush-5765
- twilight-boat-1997
summary: 'Three Studio additions (shipped, commit 06a3425 on theo-kirby/neural-whoop@main). (1) Hero-layout viewport REPLACES the UX-overhaul parent''s movable per-drone PiPs with nw-viz''s fixed composition — a wide 3/4 main shot + three 4:3 cells stacked left (FPV top / top-down middle / stats HUD bottom), FPV splitting into a near-square grid (cap 6, ''+N more'') for multi-drone runs — so what''s on screen == the exported frame (web/studio/layout.js+cameras.js port nw-viz/src/{layout,cameras}.js). (2) A 3D course editor tab revives the lab''s deferred editor: click the ground to add a gate, drag a translate gizmo (incl. height), numeric gate list, live flyability validation (course_validate.py, pure geometry off ArenaSpec), Save -> assets/courses/_web/<slug>.yaml (422 on unflyable), Save&fly. (3) POST /api/export shells out to ../nw-viz/capture.mjs (byte-identical to scripts/viz.py --video), off the event loop under a single-flight lock; 503 if node/nw-viz absent. Tooling node, no racing-metric change. Verified end-to-end: 8 new validator/route tests green; headless Playwright run renders the 3-box layout + 4-drone FPV grid with 0 console errors and pixel-correct cell positions; a real 960x540 50fps H.264 MP4 was produced via the export route. Closes the UX-overhaul''s two deferred items (fixed hero layout + Editor tab).'
origin:
  backend: flywheel
  node_id: 9eac6fbd-2175-56fe-8577-8af17ea996fd
  slug: summer-smoke-5603
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 582c88db-2d90-5179-9638-b85ee5f999a1
  slug: lively-resonance-9838
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 3342886c13c6fb8878dbac557f12bbd79acb47f90673e8e48d8b23a5d4806639
---
# Studio: hero-layout viewport + course editor + in-dashboard hero-MP4 export

## What & why
The Studio UX-overhaul parent (twilight-boat-1997) left two things open: the viewport was movable/resizable per-drone PiP frames (handy but *not* what the exported hero MP4 looks like), and the gate Editor tab was deferred. This node closes both and adds server-side video export, so the loop is: **design a course -> fly a policy on it -> watch it in a viewport that matches the hero render -> export the exact hero MP4 from a button**. Tooling only; changes no racing metric.

Locked with the user: video export = server-side via nw-viz (byte-identical to the committed pipeline); hero layout *replaces* the floating PiPs; editor = unified 3D scene + gate list; authored courses save to assets/courses/_web/ with live validation.

## What landed (commit 06a34255cb5d71bf40ce943d9f508291f8f67d2f, theo-kirby/neural-whoop@main)

### A. Hero-layout viewport (replaces floating PiPs)
- **web/studio/layout.js** ports nw-viz/src/layout.js verbatim: margin = round(min(W,H)*0.02), three equal 4:3 cells (cellH = floor((H-2margin-2gap)/3), cellW = round(cellH*4/3)) stacked down the left edge as bottom-origin WebGL rects; a `layoutInsetsCss` variant converts to top-origin for the DOM overlay boxes.
- **web/studio/cameras.js** ports nw-viz's course-bbox framing; `frameHeroCamera` initializes the orbit camera to the fixed 3/4 hero angle (dir (0.9,0.65,1.0), distance fit to the limiting FOV) each run, leaving it orbitable for inspection. playback.js delegates frameToCamera to it and bumps the per-drone FPV to 90 deg.
- **main.js compositor** (`compositeHero`): view.render() draws the wide main shot full-canvas, then scissor passes (scene.js::renderInset) draw the FPV cell (single drone -> whole cell hiding its own glyph; N>1 -> ceil(sqrt(N)) grid, hero first, capped at MAX_FPV=6 with a '+N more' chip) and the top-down cell; the three DOM boxes (#hero-fpv/#hero-top/#hero-stats) are positioned each frame from the CSS-px rects so borders/labels track on resize. The stats box is a DOM-only HUD (title/t/step/gate/speed/reward, relocated from the old sidebar telemetry section). FPV box / top-down box toggles show/hide the cells.

### B. Course editor (Editor tab) — unified 3D + gate list
- **src/neural_whoop/studio/course_validate.py** (new): `validate_gates(gates, ArenaSpec) -> {ok, issues}`, pure geometry (no torch), ArenaSpec as the single source of bounds; errors = no gates / non-positive radius / gate outside radius / height out of band; warning = consecutive XY spacing outside [step_min,step_max]. Ported from the lab's validator, adapted to a plain [{pos,radius}] list.
- **courses.py**: `save_course` (validate-then-write to courses_dir/_web/<slug>.yaml, ValueError on error-level issues -> 422), `_web/` surfaced in list_courses (kind:'web') and resolve_course_file (so a freshly authored course is flyable by stem without restart), `load_course_named`.
- **server.py routes**: GET /api/courses/{name} (load one for editing), POST /api/courses/validate (?preset=), POST /api/courses (?preset=).
- **web/studio/editor.js**: shared createScene view; in-memory gates, click the ground plane (raycast vs three y=0, mapped sim(x,y)=(X,-Z)) to add a gate, click invisible pick spheres to select, TransformControls (translate/local) on a proxy under `world` to drag incl. height; right panel = name + arena-preset select (drives validation bounds + a dashed arena ring) + x/y/z/radius + reorder/delete/+gate + scrollable gate list + live issues panel (250 ms debounce) tinting gates by worst issue; Save / Save&fly.
- index.html: Player/Editor tab bar; main.js tab routing swaps the render loop (player hero compositor <-> editor orbit+gizmo) and the sidebar sections.

### C. In-dashboard hero-MP4 export (server-side nw-viz)
- **server.py POST /api/export** (run_path[,width,height,fps,crf]): resolves the replay under runs/, locates node + ../nw-viz/capture.mjs (like scripts/viz.py's NW_VIZ_CAPTURE) -> 503 with install guidance if either is missing, else runs `node capture.mjs --replay <abs> --out runs/studio/<stem>.mp4 ...` off the event loop under a single-flight EXPORT_LOCK, returns {video_path}. Frontend button (api.js exportVideo) downloads it via GET /api/runs/<video_path>.

## Verification
- **Unit:** tests/test_course_validate.py (8 tests) — validator error/warning/ok cases, preset-widened bounds, save round-trip under _web + resolve-by-stem, 422 on unflyable, and the validate/save/get routes + export-404. `uv run pytest -q tests/test_course_validate.py tests/test_studio.py tests/test_course.py` green (27).
- **Frontend (headless Playwright + SwiftShader WebGL against a live CPU server):** page loads with 2 canvases + 3 hero boxes + 0 console/page errors; a real 4-drone gate_race rollout renders the hero layout (FPV/top-down/stats cells at pixel-correct positions left=14, tops 15/250/485 for a 1366x768 view, w=295 == the 4:3 math), FPV grid for 4 drones, export button enabled; Editor tab shows the gizmo on the selected gate, the arena ring, a 3-row gate list, and live '✓ course is flyable' / error flags. Screenshots attached.
- **Export (real):** POST /api/export on a studio replay produced runs/studio/<stem>.mp4 = H.264 High, 960x540, 50 fps, ~24s, served as octet-stream attachment by /api/runs. Confirms byte-identical-pipeline parity with `node ../nw-viz/capture.mjs`.

## Lineage
- **twilight-boat-1997 (Studio UX overhaul)** — the Studio UI this reworks: the fixed hero layout *replaces* its movable per-drone PiPs, and its deferred Editor tab is now delivered.
- **lucky-bush-5765 (nw-viz)** — layout.js/cameras.js port nw-viz/src/{layout,cameras}.js, and /api/export shells out to nw-viz/capture.mjs (the same pipeline scripts/viz.py --video uses), so the on-screen composition and the exported MP4 are one and the same.

## Notes / honest
- The on-screen orbit camera is *initialized* to the hero framing but stays orbitable; the canonical fixed framing is reproduced exactly at capture time by nw-viz (the export is the source of truth, not the live orbit pose).
- FPV grid is capped at 6 shown cells (busy swarms get a '+N more' chip) — a deliberate legibility cap, logged in the box.
- The on-screen top-down cam is kept as the existing heading-up chase (FPV aligned to nw-viz 90 deg); exact ortho parity is deferred to the capture, which is what ships.