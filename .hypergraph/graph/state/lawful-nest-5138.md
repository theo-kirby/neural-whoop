---
node_id: 24043791-6bb7-59f1-ba36-63357e5a9db0
slug: lawful-nest-5138
title: 'The visual observability seam: replay schema, Studio, and the in-repo video capturer'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- dusty-pine-0511
summary: A versioned replay schema, a lazy renderer, the two-tab Studio, and an in-repo headless capturer that imports the Studio's own scene modules so the video cannot drift from the dashboard. Working. Carries the finding that a CLI preset was the wrong shape for a look.
---
Status: working

## Current

`viz/replay.py` [rec: square-smoke-0918] is a versioned, self-describing replay schema
(`format="neural-whoop-replay"`, `docs/VISUAL_CONTRACT.md`) — pure stdlib plus numpy,
importable without the sim or viz extras. It is the durable record of what a policy
actually did, and it is portable: the Studio, the video capturer and other repos all
consume the same `replay.json.gz`. Recording is hero-subset, so the training path
stays render-free.

`web/capture/` [rec: late-field-4005] is not a second renderer — it imports the Studio's own `scene.js`,
`environment.js`, `geometry.js`, `drone-model.js` and `playback.js`, so the video is
the dashboard's look and cannot drift. What it adds is the cinematic mode: clean full
frame, a precomputed camera track, true-scale airframe, spinning props and captions.

The standing rule is that the look is `render()`'s own default
(`video/look.py::VIDEO_LOOK`), not a flag: "no hand-typed flag ever — every flag is
derived from one measured quantity and recorded" [rec: broken-tree-7316]. Every
render prints a framing check (worst |NDC| over *every* drone, plus apparent-size
spread) into `run.json`, so framing is measured rather than eyeballed.

## Negative knowledge

- [scope: expressing a look as a CLI flag | confidence: high | evidence: broken-tree-7316] `--preset hero` was the wrong shape and shipping it was the bug. `scripts/viz.py` and the Studio's `/api/export` both call `capture_video.render()` directly, so a CLI flag could never reach them — every clip those two made came out in the walled greybox room, and nothing failed. The walled room is now deleted everywhere, Studio included, and the look is the function's own default.
- [scope: framing checks that measure only the hero drone | confidence: high | evidence: ancient-lake-3956, broken-tree-7316] On the first two-drone overlay the hero-only check reported a comfortable worst |NDC| of 0.47 while the policy sat 3.16 outside the frame. It would have passed a video that hides its own subject. The check now measures every drone.
- [scope: the follow camera rig on a fast closed orbit | confidence: high | evidence: broken-tree-7316] At the standard `track_smooth = 20` the orbit's apparent size swings 117% — a +-0.4 s window against a 0.898 s revolution collapses the smoothed track to the circle's centre and the follow rig degenerates into a tripod. `track_smooth 6` fixes it, and the exception lives in `framing.py::TRACK_SMOOTH` with its reason attached rather than retuning the look for every other clip.

## Provenance

- square-smoke-0918 — the original replay schema, recorder and standard pack
- broken-tree-7316 — one environment, one render entry point, one video vocabulary, and why a preset could not reach two of its callers
- ancient-lake-3956 — the two-drone overlay and the framing check that can see the subject
