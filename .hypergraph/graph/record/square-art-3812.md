---
node_id: 7db66eaa-d354-5411-a31d-fc0b5e60538b
slug: square-art-3812
title: 'flip v2: the position gradient is largely refuted — and the control seed is why'
created_at: '2026-08-01T15:18:16.579966+00:00'
parents:
- patient-limit-7117
- calm-fog-9257
- ancient-lake-3956
summary: 'Pre-registered patient-limit-7117 (pos_sigma 0.25->0.60 + a linear position term); its own falsifier fires. Over the MANEUVER WINDOW: v1 (parent, seed 0) crashes at 38%, 0.455 m / 12.73 deg; CONTROL (parent, seed 1) survives 100%, 0.539 m / 3.77 deg; v2 (pos gradient, seed 0) survives 100%, 0.420 m / 2.44 deg. The control is the finding: v1''s crash was SEED VARIANCE, not the reward, so every single-seed reference_track result carries an unmeasured error bar. v2''s win is smaller than the seed spread. No arm nears the authored 3.80 pop or 0.680 m apex (all 2.17-2.86 against a 4.0 ceiling), so the position gradient is not what limits the flip. Also corrects the record twice: v1 never COMPLETES the maneuver (dies at step 42/110, never reaches CATCH), and metrics must be quoted over the window not the 499-step episode (swing 0.195->0.114, orbit 0.239->0.172). REFUTED. Commit c24e770.'
origin:
  backend: flywheel
  node_id: 7db66eaa-d354-5411-a31d-fc0b5e60538b
  slug: square-art-3812
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis

Pre-registered as `patient-limit-7117`: the flip's position reward is a bell `exp(-(err/0.25)^2)`.
At the achieved 0.448 m error it is worth 0.040 of a possible 1.0 and its *slope* there is smaller
still, while attitude at 12.77 deg against sigma 0.40 is worth 0.73 — so the policy collects nearly
all the attitude reward, almost none of the position reward, and (the actual claim) has no gradient
telling it which way to move. Widen `pos_sigma` 0.25 -> 0.60 and add a constant-slope `pos_linear`
1.0 term.

Its own falsifier, written before the run: *"if `pos_err_m` does not improve and `peak_climb` stays
near 0.21 m, the position gradient was not the binding constraint and the inverted coast's missing
authority is the real ceiling."*

## Setup

Three arms, 300 M steps each, RTX 4070, ~10 min/run. DR-off eval through the `rsi_frac 0` twins.

- **v1** — the parent config, seed 0 (the already-recorded result).
- **control** — the parent config, seed 1. **Only** `env.seed` differs. Pre-registered, because
  every reference_track result so far is single-seed and that variance is unmeasured.
- **v2** — the reward change, seed 0. Nothing else moves.

All numbers below are over the **maneuver window** (110 steps), not the 499-step episode — see the
Honesty section, this turned out to matter.

## Results

| arm | flew | pos_err_m | att_err_deg | peak thrust | peak climb |
|---|---|---|---|---|---|
| v1 — parent, seed 0 | **38 %, crash** | 0.455 | 12.73 | 2.17 | 0.228 |
| **control — parent, seed 1** | **100 %** | 0.539 | 3.77 | 2.73 | 0.189 |
| v2 — pos gradient, seed 0 | 100 % | 0.420 | 2.44 | 2.86 | 0.290 |
| *reference (authored)* | 100 % | 0 | 0 | **3.80** | **0.680** |

**The control arm is the finding.** The parent config at seed 1 also survives the whole maneuver.
So v1's crash was **seed variance, not the reward gradient**, and the headline "v2 fixed the flip"
would have been wrong. v2 does win on both error channels — but by less than the spread between the
two parent seeds (pos_err 0.455 vs 0.539), so at n=1 per cell the reward change cannot be separated
from seed noise.

What is solid, and is what the falsifier asked about: **no arm approaches the authored pop.** All
three command 2.17-2.86 normed thrust against an act-v2 ceiling of **4.0** while the reference
commands 3.80, and all three apex at 0.19-0.29 m against the authored 0.680 m. The position
gradient is not what limits the flip's shape. **Hypothesis largely REFUTED.**

## Verdict / Honesty

Two corrections to the previously published record, both making it worse:

1. **The v1 flip did not "fly a flatter flip" — it did not complete the maneuver.** Every hero
   episode ends identically at step 42 of 110 (0.84 s of 2.20 s), falling through `bound_z_min`
   during `COAST`; `CATCH` and `RECOVER` are never reached. The published
   `crash_rate_per_step` 0.0227 reads like "2 % of drones crash" and is 1/44 — *every* drone
   crashes, after ~44 steps. `tracking_ok` 0.9773 is 43/44 steps alive, not 98 % of drones
   tracking. A per-step rate needs its denominator before it means anything.
2. **Quote the maneuver window, not the episode.** The eval runs to a 499-step cap against a
   110/268/223-step reference, so the full-horizon per-step mean blends the maneuver with the
   trivial hold-station tail — 78 % tail on the flip, 46 % swing, 55 % orbit — and blends it
   *differently* for a policy that crashed early (all maneuver) than for one that survived (mostly
   tail). Corrected: swing 0.195 -> **0.114 m**, orbit 0.239 -> **0.172 m**; the tail had made both
   look *worse*, and both stay GREEN. This is the same failure mode as the `ep_`-prefixed
   accumulators, one level further out.

The flip is **unwilling to pop, not unable**: `act[0]` never exceeds +0.087 of its +1.0 range. It
has roughly twice the authority it uses, and its rate tracking through the roll is fine (~9-10 rad/s
vs the authored 9.0) — so this is thrust/credit-assignment, not attitude.

**Next lever, untested:** `rsi_frac 0.8` means 80 % of episodes start *placed* in the reference's
own mid-maneuver state and therefore never have to generate the pop to get there; only the 20 %
starting at phase 0 do, and the pop is ~10 of 110 steps. Phase-weighted RSI — not more reward
shaping. Also: re-run the swing and orbit at a second seed before trusting their GREENs.

## Lineage

Parents: the hypothesis this tests (`patient-limit-7117`) and the first results it descends from
(`calm-fog-9257`). The overlay tooling node is the sibling that made the failure legible — the
"never reaches CATCH" finding came out of its per-phase chart, not the scalar metrics.

Commit `c24e770`; configs `reference_track_flip_v2.yaml`, `reference_track_flip_seed1.yaml`.
