---
node_id: 7601adfd-8dc9-500f-86df-572f249ce3e7
slug: little-feather-5786
title: 'Method: target_follow task — moving-target following through a noisy detector (perception seam, code only)'
created_at: '2026-06-27T19:11:06.390227+00:00'
parents:
- tight-limit-5820
summary: 'Realizes sub-branch (a) of the perception-gap idea (96fbd7ef): the first catalog task that feeds the policy a DETECTOR-corrupted target vector instead of a perfect oracle. Single-drone keep-in-view-at-standoff over a moving target (orbit/lissajous via target.py); obs-v4 unchanged (target vector replaces the gate vector, run through OracleEstimator + apply_detector_noise with stale-hold, exactly like gate_race.observe). Reward = standoff bell exp(-((d-d*)/sigma)^2) + in-FOV/centering bonus + alive - smoothness - crash, NO time penalty. Metric = time_in_view_rate + mean_track_error, both from GROUND TRUTH so detector noise can''t be gamed. Pure task-layer, no env changes. Committed df0baee on main; full suite (83 tests, +7 new) + env_check green. Smoke (8M steps): ep_ret 138->248 monotonic; @1M time_in_view 0.78 / track_err 0.40 m. NOT yet trained to convergence or compared clean-vs-noisy — that empirical verdict is the next (experiment) node.'
origin:
  backend: flywheel
  node_id: 7601adfd-8dc9-500f-86df-572f249ce3e7
  slug: little-feather-5786
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: b9e45ea9-89b9-57d5-b68e-e50d38ab27bd
  slug: broad-night-2952
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 58c8b7a68bcdc6a3f261b41e9111d42a9c5a79139a368a6bb3b9a3ec131e82e9
---
## What this is
Code-only method node: implements `target_follow`, the perception beachhead. The dominant un-bracketed sim2real gap is that every policy in the graph (incl. the studio-baseline generalist b4c3466f) is fed a PERFECT body-frame target vector from `OracleEstimator`; on hardware there is no oracle. This task is the first to route obs through the `DetectorNoise` seam (bearing/range/FOV/dropout + stale-hold) as a first-class part of the task, so a tiny policy can learn to track through real detection error without rendering a pixel.

## Design (locked with the user)
- **Behavior**: standoff keep-in-view (vs pursuit/orbit) — hold the target at d*=1.5 m and keep it centered in a 110-deg camera FOV cone.
- **Obs**: obs-v4 PURE (length 11) — the (possibly stale) target estimate replaces the gate vector; the stale-hold is invisible to the policy (deploy-faithful).
- **Reward** (per step): `track_scale*exp(-((d-d*)/sigma)^2)` + `in_view_bonus*[in FOV]` + `center_scale*relu(cos bearing)` + alive - smoothness - crash. No time penalty (holding task, not a race).
- **Target motion**: per-env mixed orbit/lissajous from `neural_whoop.target.TargetField`, resampled per reset; drone spawns at d* facing the target.
- **Metric**: `time_in_view_rate`, `mean_track_error` (|d-d*|), plus mean_distance / mean_bearing_deg, all computed from ground truth.

## Files / artifacts
- `src/neural_whoop/tasks/target_follow.py` (`@register_task('target_follow')`), `configs/target_follow.yaml` (detector seam ON: 3-deg bearing, 10% range, 5% dropout, 110-deg FOV), registered in `tasks/__init__.py`.
- `src/neural_whoop/training/ppo.py`: the console metric line is now task-aware (racing tasks keep the lap-time line; other tasks print their own `metrics()` dict — these already flowed to TensorBoard via `metrics/{k}`).
- `tests/test_target_follow.py` (7 tests): obs shape, standoff/centered spawn, detector path + stale-hold, tracking reward, crash termination, metrics keys.

## Reuse (why it was ~80% pre-built)
- `target.py` (batched moving-target motion) and `perception/estimator.py` (DetectorNoise + apply_detector_noise + stale-hold) were written for exactly this; `reward.py` already carried `pursuit_proximity_scale`/`in_view_bonus` fields.

## Lineage
- realizes-idea `96fbd7ef` sub-branch (a) (detector-noise-hardened obs).
- code state descends from main HEAD (studio UX c9f20838 / commit 100d66e); reuses the [128,128]@120M baseline net + full seam DR.

## Next
Experiment node: train to convergence (120M) and run the honest clean-vs-noisy eval matrix — (1) show an oracle-clean policy degrades under detector noise, (2) show the detector-trained policy holds time-in-view + track error. Verdict on time_in_view_rate / mean_track_error.