---
node_id: 96fbd7ef-1627-55bc-b531-6233bf52f842
slug: tight-limit-5820
title: 'Idea: close the perception sim2real gap — detector-noise-hardened obs + honest camera-only eval'
created_at: '2026-06-27T16:17:32.357357+00:00'
parents:
- old-truth-3996
- royal-firefly-3187
summary: 'Idea (placeholder, branch opened, not started) to close the perception sim2real gap — currently the dominant un-bracketed gap. Every policy today is fed a perfect body-frame gate-direction vector from OracleEstimator, but a real ~32 g whoop has no oracle (a camera detector/VIO/mocap must produce it, with bearing/range/FOV error and dropout). Two sub-branches: (a) train on detector-noise-hardened observations using the existing DetectorNoise seam (bearing/range/FOV/dropout + stale-hold) so obs-v4 survives real detection error, and (b) add an honest camera-only eval via the DiffAero depth render (Blackwell-OK) instead of the oracle while keeping the render-free oracle as the fast training path. This framing opened the broader perception/follow thread and feeds the hardware-deploy branch.'
origin:
  backend: flywheel
  node_id: 96fbd7ef-1627-55bc-b531-6233bf52f842
  slug: tight-limit-5820
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: d63344f0-a5ac-5e6a-93f5-ccfc5317d250
  slug: dark-snowflake-2707
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 57e5685d43be76f68166e8e6f1448bceaa887c0089936c3fbda097c82b0b80a0
---
## Status: PLACEHOLDER (branch opened, not started)

## The gap
The policy's only perception input is a body-frame 3-vector pointing at the current gate (+ a next-gate lookahead), produced by `OracleEstimator` from ground-truth gate positions. `general_s1` (and the racing baselines) trained with the **detector seam OFF** (`detector_*` knobs identity), so they have never seen perception error. On a real ~32 g whoop there is no oracle — a camera blob/gate detector, VIO, or external mocap must produce that vector, with bearing error, range error, finite FOV, and dropout. This is the **largest currently un-bracketed sim2real gap**.

## Two sub-branches
- **(a) Detector-noise-hardened obs (cheap, train-time).** The framework already has `apply_detector_noise` (bearing/range/FOV/dropout + stale-hold via `last_valid`) wired into `gate_race.observe()` behind the DR `detector` config. Train a `general`/baseline variant with it ON and re-measure cross-scale + DR-on reliability. Question: how much completion does honest detection error cost, and does training through it recover most of it?
- **(b) Honest camera-only eval (measurement).** Replace the oracle with the DiffAero depth render (the Blackwell-OK path; `render_depth` is a documented stub today) at EVAL time, so the reported number reflects real onboard perception, not ground truth. The render-free oracle stays the fast training path; this is the honesty check on top.

## Lineage
- builds-on `b4c3466f` (general_s1 — the concrete policy whose perception gap is open).
- builds-on `8403a22c` (DR-on reliability measurement — perception is the NEXT sim2real axis after the disturbance seam this quantified).

## Related
Feeds the deploy branch (the real obs estimator is open question #1 there).