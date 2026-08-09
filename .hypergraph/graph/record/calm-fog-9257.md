---
node_id: 4ab9c87b-7185-5010-8f83-45151997ee6e
slug: calm-fog-9257
title: 'reference_track first results: swing GREEN (att_err 1.78°), orbit GREEN (the lab''s first non-planar policy), flip partial — where acro_flip_v2 reached 0.000'
created_at: '2026-08-01T12:56:43.906584+00:00'
parents:
- white-hat-1285
summary: '300 M steps each, DR-off eval through the rsi_frac-0 twins, full-horizon per-step metrics: swing pos_err 0.195 m / att_err 1.78° / tracking_ok 1.0000 / crash 0.0000 GREEN; orbit 0.239 m / 10.49° / 1.0000 / 0.0000 GREEN; flip 0.448 m / 12.77° / 0.9773 / 0.0227 partial. Parent acro_flip_v2 reached flip_success_rate 0.000 at 400 M steps having never attempted the maneuver. The ORDERING was predicted by the reference''s own authoring numbers — the swing is fully powered, planar, 32% rate headroom and tracks to under 2°; the flip is hardest structurally (throttle floored at 0.25 through an inverted coast, so lateral error cannot be bought back until CATCH) and under-does the pop (peak_climb 0.212 m vs the reference''s 0.680 m). The orbit is the lab''s first non-planar trained policy, possible only after the rate-loop fix. Honesty: metrics() was reporting 0.186 m where the honest full-horizon path reads 0.448 m (2.4x optimistic, reset-biased accumulators) — fixed and pinned by a test.'
origin:
  backend: flywheel
  node_id: 4ab9c87b-7185-5010-8f83-45151997ee6e
  slug: calm-fog-9257
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 0a50110b-9791-56ac-b3e7-dd01b4e65594
  slug: purple-sea-5989
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: c91ba0da558aced59f75b76322cba64d957b493c02b5e865385133985a71da7f
---
## Hypothesis

`white-hat-1285` predicted that tracking an exactly-derived reference would reach maneuvers that
reward-shaped discovery could not (`lucky-wind-7057`: `flip_success_rate` 0.000 at 400 M steps), and
that **one** task would serve all three because `ManeuverSpec` emits one format.

## Setup

300 M env-steps each, `n_envs` 8192, `[64,64]` tanh, RTX 4070, ~10 min per run. Evaluated through
the `_eval` twins (`rsi_frac: 0`, no station jitter — the whole maneuver from phase 0) with
`--no-dr`. The flip tracks the **`--deployable`** reference, because the aesthetic variant's
motors-off coast has zero rate authority for 10% of the flight and a policy cannot be trained to
track an interval where it has no control authority.

## Results

Quoting the **full-horizon per-step** metrics (see the honesty note — this distinction is not
cosmetic):

| maneuver | `pos_err_m` | `att_err_deg` | `tracking_ok` | crash/step | verdict |
|---|---|---|---|---|---|
| **swing** | 0.195 | **1.78** | **1.0000** | 0.0000 | **GREEN** |
| **orbit** | 0.239 | 10.49 | **1.0000** | 0.0000 | **GREEN** |
| **flip** | 0.448 | 12.77 | 0.9773 | 0.0227 | partial |

vs the parent (`lucky-wind-7057`, reward-shaped flip): `flip_success_rate` 0.000 at 400 M steps and
no maneuver attempted at all. Early signal on the tracked flip was `att_rmse` 22 deg at **1 M**
steps.

**The ordering is the finding, and it was predicted by the reference package's own authoring
numbers.** The swing is fully powered (`zero_authority_frac` exactly 0), planar, keeps 32% rate
headroom, and closes at machine precision — and it is the one that tracks to under 2 deg. The orbit
is fully powered but genuinely 3D and lands in between. The flip is hardest for a **structural**
reason rather than a tuning one: through its coast the throttle is floored at 0.25 and the airframe
is inverted, so lateral error taken on before or during the coast cannot be bought back until
`CATCH`.

The flip also **under-does the pop**: `peak_climb` 0.212 m against the reference's 0.680 m. It
rotates correctly but flies a *flatter* flip than authored.

**The orbit is this lab's first non-planar trained policy.** It exists only because of
`bitter-rain-0437` — a satisfying closure, since the maneuver that found the rate-loop bug is the
one that could not be trained until it was fixed.

Hero videos render from these replays with the **same `--preset hero` invocation** as the reference
clips, with no renderer changes — which is what the shared replay schema was for.

## Verdict / Honesty — GREEN for the method (`stop_reason: improved`), flip arm unresolved

Honesty, and this one is load-bearing:

- **I nearly reported the flip at 3.70 deg instead of 12.77.** The task's `metrics()` published
  `pos_rmse_m` / `att_rmse_deg` from accumulators that **zero on every episode auto-reset**, so a
  read at log cadence catches most drones part-way through an episode and averages the hard middle
  of the maneuver against whatever easy tail is in the window. `eval/rollout.py` already anticipates
  this and overrides task metrics with full-horizon means of the per-step tensors — but *only for
  keys of the same name*, and none of those four were per-step, so the override could not reach them.
  Same rollout: **0.186 m through `metrics()` vs 0.448 m through the honest path, 2.4x in the
  flattering direction.** Fixed by `ep_`-prefixing the windowed values, plus a test that *bans* the
  un-prefixed names, because the failure is silent and the wrong number looks entirely plausible.
- `tracking_ok` 0.9773 on the flip means the hero drone does not always survive the window — its
  hero clip is 42 frames, not the full maneuver. The swing and orbit clips are complete.
- These are single-seed runs at DR-off. No seed variance, and no DR-on reliability number yet.
- The DR here is deliberately lighter than `acro_flip`'s, so these are **not** comparable to a
  DR-hardened result; the reference is authored against the nominal airframe.

## Lineage

First results for `white-hat-1285`; supersedes the reward-shaped approach in `lucky-wind-7057` for
these three maneuvers; the orbit arm depends on `bitter-rain-0437`.
