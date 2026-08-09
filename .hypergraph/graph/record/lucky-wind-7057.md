---
node_id: ce631b1c-b9bf-56c0-9b98-88f6d58b426c
slug: lucky-wind-7057
title: 'acro_flip v2 TRAINED for the first time: RED — flip_success_rate 0.000 final (best-ever 0.122) vs v1''s 0.845; the station-keeping terms v2 added make hovering the reward''s optimum'
created_at: '2026-08-01T12:53:29.368034+00:00'
parents:
- wispy-wood-0453
summary: 'First actual training of configs/acro_flip_v2.yaml (400 M steps, RTX 4070): flip_success_rate 0.845 (v1) -> 0.000 final, best-ever 0.122, mean_completion_time 0.000 — it ends never attempting the maneuver. RED. Cause is structural: lat_scale 1.0 + sink_scale 1.0 make ''hover at the spawn point collecting alive_bonus'' a strong local optimum and a policy that never inverts never discovers the far side pays, so this is an EXPLORATION failure, not a tuning one. The v2 config had only ever been a stated hypothesis; its header numbers were targets. Also confirms pop_allow 0.4 contradicts the reference''s measured peak_climb 0.617 m.'
origin:
  backend: flywheel
  node_id: ce631b1c-b9bf-56c0-9b98-88f6d58b426c
  slug: lucky-wind-7057
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis

`acro_flip` v2 (`wispy-wood-0453`) predicted that four coupled changes would turn v1's wide, loopy
barrel roll into a **point-in-space** flip: an obs-8 maneuver clock, a lateral station-keeping term,
an asymmetric altitude term (heavy `sink_scale` 1.0, light `rise_scale` 0.2 past `pop_allow` 0.4 m
of free headroom), and `alive_bonus` cut 0.1 -> 0.02. Targets stated there: keep
`flip_success_rate` >= 0.845 (v1's GREEN), `altitude_loss` < 0.15 m, `max_lateral_drift` < 0.20 m,
`peak_climb` 0.2-0.4 m.

**This is the first time that config was actually trained.** It was committed as a stated
hypothesis; the numbers in its header were targets, not results.

## Setup

`configs/acro_flip_v2.yaml` unchanged, 400 M env-steps, `n_envs` 8192, `[64,64]` tanh policy,
obs-8, `act.min_thrust_normed` 0.25, DR on with a 0.5 curriculum. RTX **4070** (12 GB) rather than
the 5090 — 532 k env-steps/s end-to-end, ~12 min wall-clock, so this is not a truncated run.
`scripts/env_check.py` green (after a portability fix to its arch gate, which asserted an exact
`sm_120` string and false-failed on `sm_89`).

## Results

| | v1 (parent, reported) | v2 (this run) |
|---|---|---|
| `flip_success_rate` final | **0.845** | **0.000** |
| `flip_success_rate` best-ever | — | 0.122 |
| `mean_completion_time` final | — | 0.000 (never reaches PHI) |
| `peak_climb` final | 0.000 | 0.442 |
| `max_lateral_drift` final | 0.672 | 0.244 |

The run does not simply fail to converge — it **oscillates**. It reaches ~0.10-0.12 around 220 M
steps, collapses back to 0.000, partially recovers, and ends at 0.000 with
`post_recovery_tilt_deg` 0.000 and `mean_completion_time` 0.000: at the end, no drone is attempting
the maneuver at all. What it converges to instead is a stationary hover at the spawn point with a
small pop (`peak_climb` 0.44) and tight lateral hold (0.24) — i.e. it *does* satisfy the
station-keeping half of the v2 reward, and only that half.

## Verdict / Honesty — RED (`stop_reason: regressed`)

The cause is structural, and it is the two terms v2 **added**. `lat_scale` 1.0 and `sink_scale` 1.0
make "sit at the spawn point collecting `alive_bonus`" a strong local optimum; the pop is punished
on the way up; and a policy that never inverts never observes that the far side of the rotation
pays. **This is an exploration failure, not a capacity or tuning one** — which matters, because it
means re-weighting is not guaranteed to fix it. The shaping intended to make the flip *tighter*
removed the gradient that produced a flip at all.

Two honest caveats on this result:

- **v1's 0.845 was measured on the 5090; this is a 4070.** The substrate is the same pure-torch
  DiffAero and the step budget is 400 M either way, so hardware is not a plausible explanation for
  0.845 -> 0.000, but the two numbers were not produced on the same box and no v1 re-run was done
  here to control for it.
- This run trained against the **rate-loop-fixed** DiffAero (same day). A roll flip is planar, so
  its omega lies on R's fixed axis and the fix is a no-op for it (alignment measured 1.000000000) —
  but that is an argument, not a measured A/B.

Separately, `pop_allow: 0.4` contradicts the hand-authored reference, which measures `peak_climb`
**0.617 m** (0.680 deployable): under this reward the shape the docs say we want collects a
`rise_scale` penalty. Flagged, not changed.

## Lineage

Tests the v2 setup in `wispy-wood-0453`. This RED is the direct motivation for `reference_track`:
if describing an acro maneuver in penalty terms cannot reliably reach it, track the maneuver that
already exists as exactly-derived data instead.
