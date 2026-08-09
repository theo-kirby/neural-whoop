---
node_id: c9f20838-5de9-5374-bd17-5fd63bc06e07
slug: twilight-boat-1997
title: 'Tooling: Studio UX overhaul — flat 2D UI, per-drone movable FPV PiP, policy metadata + TB charts'
created_at: '2026-06-27T16:39:12.270068+00:00'
parents:
- square-smoke-0918
- lucky-bush-5765
- wispy-dust-3157
summary: 'A UX overhaul of the neural-whoop Studio viewer (shipped, commit 100d66e): a flat 2D restyle with custom-styled selects and rounded panels; FPV/top-down picture-in-picture insets that are drag-to-move and resizable, split into one onboard-FPV box per drone (each its own tinted PerspectiveCamera); a policy-metadata panel (task, steps, obs/act dims, eval metrics); and collapsible TensorBoard training charts drawn in-browser from a dependency-free, from-scratch TFRecord/protobuf scalar reader (studio/tbscalars.py, no tbparse/pandas/tensorboard). Turns the Studio from a bare player into a usable inspection tool; gate Editor still deferred.'
origin:
  backend: flywheel
  node_id: c9f20838-5de9-5374-bd17-5fd63bc06e07
  slug: twilight-boat-1997
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 65bc87b1-03a3-5bcc-b506-5b4baf3a8c2f
  slug: spring-resonance-6037
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: bd5cbd59df75a785a69b0ceeff6587ea611ffab099670cf009bdb2f0f903bd8b
---
Iteration on the neural-whoop Studio (parent **wispy-dust-3157**) responding to direct user feedback on the viewer's look and feel. Five changes, all shipped in commit `100d66e897614982285dbf30642c790dcf2f9bf0` (pushed to `theo-kirby/neural-whoop@main`):

1. **Flat 2D restyle.** Killed the native browser `<select>` chrome (`appearance:none` + a custom flat SVG chevron) and moved the whole UI to a consistent flat 2D style — rounded corners everywhere, heavier (1.5px) borders instead of hairlines, greyscale palette preserved.

2. **Movable + resizable PiP frames.** The FPV/top-down insets are now drag-to-move (by a header handle) and resize via the element's native corner grip; the inset camera is scissor-rendered onto the main canvas at each frame's live bounding rect, and frame bodies pass pointer-events through so you can still orbit the scene underneath. FPV and top-down default to the same size.

3. **Per-drone FPV.** FPV is split into one box per drone — every drone gets its OWN onboard `PerspectiveCamera` (built per-episode in `playback.js`), each inset hiding only that drone's own body so it doesn't occlude its lens. Multi-drone runs now show every onboard view at once, tinted to match each drone glyph.

4. **Policy metadata panel.** Picking a policy now shows task, creation date (checkpoint mtime), training steps, obs/act dims, and eval metrics (best/oracle lap, completion, reward, crash rate). `/api/policies` enriched with `created`, `act_dim`, `eval`, `has_scalars`, `run`.

5. **Training charts.** A collapsible panel draws 2D canvas line plots (episodic return, best lap, lap completion, entropy, value loss, LR) from a new `/api/policies/{run}/scalars` route. The route is backed by **`studio/tbscalars.py`** — a from-scratch, dependency-free TFRecord + protobuf scalar reader, so charts need NOTHING beyond the existing `studio` extra (no tbparse/pandas/tensorboard). Validated value-for-value against both `tbparse` and torch's `SummaryWriter`.

**Lineage.** Builds directly on the Studio viewer (wispy-dust-3157). The per-drone FPV + top-down PiP layout descends from the nw-viz hero-MP4 PiP work (lucky-bush-5765); the in-Studio training charts descend from the visual-observability seam's `training_curves.png` renderer (square-smoke-0918) — now made interactive and render-free in the browser.

**Verification.** Full pytest suite green (added 3 studio tests: enriched metadata fields, the scalars route 404/empty cases, and a `SummaryWriter` round-trip of the TB reader). Headless Playwright smoke (SwiftShader WebGL) ran a real 3-drone GPU rollout end-to-end: 0 console errors, 3 per-drone FPV frames built, charts rendered, header-drag moves a frame. Screenshots confirmed the layout.

**Deferred / honest notes.** With many drones (toward 16) the default FPV tiling can overlap the top-down box; frames are movable/resizable so the user rearranges, but an auto-pack layout would be nicer. The gate Editor tab remains deferred.