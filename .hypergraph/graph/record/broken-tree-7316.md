---
node_id: 6d82d25c-d04c-5a76-8e1e-caf6530ce51f
slug: broken-tree-7316
title: One environment, one render entry point, one video vocabulary — and why a preset could never reach two of its three callers
created_at: '2026-08-01T18:24:23.157320+00:00'
parents:
- ancient-lake-3956
- hidden-field-0837
- square-art-3812
summary: 'One environment, one render entry point, one video vocabulary. `--preset hero` became `capture_video.render()`''s own keyword defaults (`video/look.py::VIDEO_LOOK`), because a CLI flag could never reach `scripts/viz.py` or the Studio''s `/api/export` — both call `render()` directly — so those two had been silently shipping every clip in the WALLED greybox room while the reference/comparison clips shipped the cyclorama, with nothing failing. The walled room is deleted everywhere (Studio included); `environment.js::setStage` derives fog from the camera standoff, floor size from the fog (4x), grid from the framing. New `video/` package (look/names/framing/render) replaces `reference/video.py`; clips are named `<maneuver> maneuver <kind> video`. VERIFIED: the un-flagged `render(replay, out)` path now emits PNGs BYTE-IDENTICAL to the old `--preset hero`. Nine checked-in clips (render-examples/, 3.5 MB): worst |NDC| 0.71 < 0.9, worst apparent-size spread 13% < 35%. The step-0 seam test immediately caught real drift (titleFrames 40 in Python vs 0 in JS). 398 -> 405 tests. GREEN. Commit cda2c82.'
origin:
  backend: flywheel
  node_id: 6d82d25c-d04c-5a76-8e1e-caf6530ce51f
  slug: broken-tree-7316
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: dadb87ac-39c8-5060-a183-4c1c0773c30e
  slug: flat-frost-3702
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: 5a05ddd569f2058ff85f5bce3d25fa8c830e5325987c16c1d2250f76b8aec3b7
---
## Hypothesis

Not a hypothesis — a consolidation, and a bug found while doing it. The repo had grown **three ways
to render a video and two different 3D looks**, and the naming had never settled.

## The problem: a preset is the wrong shape for a deliverable

`--preset hero` (node: "The concept shot, standardized") was a **CLI flag**. But the two callers
that matter most do not use the CLI:

- `scripts/viz.py::_maybe_render_video` does `from capture_video import render` and calls it;
- the Studio's `/api/export` (`studio/server.py::_run_capture`) does exactly the same.

A flag could never reach either of them. So every clip those two produced came out in the **walled
greybox room**, while the reference and comparison clips came out on the **fogged cyclorama** — two
different environments shipped side by side, with no error, no warning, and no visual artefact that
said an option had been dropped. The "one invocation, same picture, any replay" promise was only
ever true for the callers that happened to type the flag.

Three more symptoms of the same drift: "hero" meant four different things (camera preset, concept
clip, the *recorded subject drone*, the Studio's PiP boxes); `reference_vs_policy.py` forked the
pinned invocation and hand-copied `subject_y = -0.06` out of the preset with nothing cross-checking
the two; and video filenames were ad-hoc (`flip.mp4`, `flip_policy.mp4`, `vs_reference.mp4`,
`hero.mp4`) — four names in four directories, none saying what the clip was.

## Setup

**Step 0, before anything moved: pin the untested seam.** `capture_video.py` builds a snake_case →
camelCase dict and injects it as `window.__CAPTURE_OPTS__`; `web/capture/capture.js` spreads it over
its own `DEFAULTS`. Nothing checked that the two agreed — a renamed key silently falls back to the
page default and still encodes a video. `page_options()` is now a pure function and
`tests/test_capture_opts_contract.py` diffs it against `DEFAULTS` both ways, plus the shared
literals; `capture.js` throws on an unknown injected key.

**It immediately found real drift: `titleFrames` was 40 in Python and 0 in JS**, so `render()`'s
docstring promised an opening title card that no render had ever drawn. Settled on 0.

Then, in order:

1. **One environment.** `geometry.js`'s `buildRoom` → `buildStageFloor` (walls branch deleted);
   `environment.js` gains `STAGE_LOOK` + **`setStage`**, which derives fog from the camera standoff,
   the floor size from the fog (4×), and the grid subdivision from the framing — so *"you can never
   see the stage end"* is true by construction at any scale. `scene.js` gains `configureKeyLight` /
   `setToneMapping`, and the steep key + 2048² shadow map move into the **base rig**, so the Studio
   gets the same contact shadow the video does.
2. **The look becomes the default.** New `video/look.py::VIDEO_LOOK` = the union of the old
   `LOOK_DEFAULTS` and `PRESETS["hero"]`. `--preset` and `--backdrop` are gone. The load-bearing
   part: `render()`'s **keyword defaults** are now that dict field for field, pinned by
   `test_render_defaults_match_the_video_look`. `viz.py` and `server.py` needed **no edit at all**
   beyond a docstring — which is the whole proof.
3. **The video-kind API.** New `video/` package (`look`/`names`/`framing`/`render`); deleted
   `reference/video.py` outright. A clip is `<maneuver> maneuver <kind> video`, kinds
   `reference|policy|comparison`, filename `flip_maneuver_reference.mp4`.
4. **`render-examples/`** — nine checked-in 720²/CRF-26 clips (3.5 MB) + README + manifest; 1080²
   masters stay in gitignored `runs/`.

## Results

**The byte-identity check is the headline.** Render stills through the *un-flagged* path — literally
`from capture_video import render; render(replay, out)`, what `viz.py` and `/api/export` do — and
compare against the pre-change `--preset hero` render:

| frame | result |
|---|---|
| f00040 / f00120 / f00220 | **byte-identical PNGs** |

So the callers that were silently getting the walled room now get, bit for bit, the picture the
flag used to buy — and the JS move (step 1) changed no values.

**The nine shipped clips**, all inside spec (worst |NDC| < 0.9, apparent-size spread < 0.35):

| clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| `flip_maneuver_reference` | 0.25 | 11.7–12.1% | 3% |
| `flip_maneuver_policy` | 0.22 | 11.8–12.2% | 3% |
| `flip_maneuver_comparison` | 0.66 | 11.7–12.1% | 3% |
| `swing_maneuver_reference` | 0.49 | 30.7–34.7% | 13% |
| `swing_maneuver_policy` | 0.49 | 30.6–34.7% | 13% |
| `swing_maneuver_comparison` | 0.71 | 30.7–34.7% | 13% |
| `orbit_maneuver_reference` | 0.26 | 20.2–20.9% | 3% |
| `orbit_maneuver_policy` | 0.26 | 20.2–20.9% | 3% |
| `orbit_maneuver_comparison` | 0.46 | 20.2–20.9% | 3% |

The identical size column *within* each maneuver is the shared framing plan working: one plan per
maneuver, derived from that maneuver's **comparison** shot, reused by all three of its clips — so
the reference clip is literally the comparison with the policy removed (same camera path, same
airframe size, same horizon). All three replays are cut from the one overlay document.

**The guarantee changed, honestly.** It was "no per-clip flag, ever". The two-drone comparison broke
that legitimately — it needs more framing room than a one-drone shot, and *how much* is the result
being reported. So: **no hand-typed flag ever; every flag is derived from one measured quantity and
recorded in the manifest** (`video/framing.py::FramingPlan`).

**The orbit's `track_smooth 6`, re-measured on this framing** (the exception now lives in
`framing.py::TRACK_SMOOTH` with its reason attached, not in a shell history):

| orbit reference clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| standard single-subject framing, `track_smooth 20` | 0.65 | 13.9–30.2% | **117%** |
| this maneuver's plan, `track_smooth 20` | 0.46 | 18.1–23.7% | 31% |
| **this maneuver's plan, `track_smooth 6`** (shipped) | 0.26 | 20.2–20.9% | **3%** |

Worth noting: the overlay's wider framing *masks* the problem without fixing it (117% → 31% just by
standing further back). Good argument for attaching the number to the **maneuver** rather than to
whichever clip happened to expose it.

**Tests: 398 → 405.** Studio + bench load headless with **zero JS errors**.

## Verdict / Honesty

**GREEN.** One environment, one render entry point, one vocabulary — and the un-flagged path is
byte-identical to what the flag used to buy.

Three honest caveats:

1. **This fixed a bug that had been shipping.** Every `scripts/viz.py --video` and every Studio
   `/api/export` clip made before commit cda2c82 was rendered in the walled room. They are not
   wrong, just *not the standard look* — and no artifact of theirs says which it was.
2. **Two defects were found by the verification, not by the plan**, and both would have shipped:
   the Studio's **first paint** (before Run) showed the 10 m floor's own edge as a hard horizon,
   because `setStage` only fired on run/arena and the walls used to hide it (`createEnvironment` now
   stages at construction); and at giant-arena scale the derived fog far (806 m) **overran the
   camera's 800 m far plane**, so the fade would not complete before the frustum clipped (clamped to
   0.9 × `camera.far`). Verified across all seven real call-site scales, camDist 0.65 m → 57.6 m.
3. **`scripts/serve.py` could not be started on this host** (`runs/hover_blind_air65_d50var_s8/
   policy_weights.json` is absent — the deploy weights live on the bench Mac), so the Studio was
   verified through a static headless harness plus a direct check of `setStage`'s invariant, not
   through a live rollout. The `showRun` path's arithmetic is checked; its pixels are not.

Also deliberately **not** done: "hero" is retired from the *video* vocabulary only. The replay
schema's **hero drone** / **hero episode** / `heroFrames` / `--n-heroes` mean "the recorded subject
drone", are load-bearing in `eval/rollout.py`, `viz/replay.py` and `playback.js`, and **stay** — with
a defensive note added to `docs/VISUAL_CONTRACT.md` so nobody "finishes" the rename into a wire
format.

## Lineage

- **reference vs policy in ONE frame** — this generalizes its per-clip framing derivation into
  `FramingPlan`, and reuses `build_overlay` as a *function* to measure each maneuver's separation.
- **The concept shot, standardized (`--preset hero`)** — this node supersedes its *shape*. The
  values it measured all survive verbatim in `VIDEO_LOOK`; what is refuted is that a **preset** was
  the right container for them.
- **flip v2** — supplies the flip policy the shipped clips use (the arm that completes the maneuver;
  a clip of the v1 arm would show a failure mode rather than a comparison).

Commit `cda2c82`. Regenerate with `uv run python scripts/render_examples.py --publish`.
