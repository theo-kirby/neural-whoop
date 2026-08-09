---
node_id: 4d5ed6b9-fa79-5edc-8cd7-6f6d4f38fec2
slug: damp-wood-7079
title: 'Measurement: the 120M tight baseline overfits course geometry — reliability collapses as gates spread out'
created_at: '2026-06-27T12:35:12.341325+00:00'
parents:
- wispy-dust-3157
- shrill-limit-5398
summary: 'Studio-motivated diagnosis. The [128,128]@120M baseline is 0.95 lap completion on tight courses but degrades monotonically with course scale: 0.76 spread / 0.49 big / 0.21 giant, crash rate ~8x. It only trained on tight back-to-back-turn geometry, never the cruise-and-brake regime far-apart gates demand.'
origin:
  backend: flywheel
  node_id: 4d5ed6b9-fa79-5edc-8cd7-6f6d4f38fec2
  slug: damp-wood-7079
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Trigger
In the new Studio the baseline policy visibly fumbles on every course except the tight one. This node quantifies why.

## Method
Evaluated `gate_race_big128_120M_s0` over RANDOM courses of four scales with the OFFICIAL eval regime (4096 envs, episode_len 600 < steps 1500 so lap-completion is a valid cycled metric, DR off). Only the arena scale varies — `gate_radius` (0.45) and `n_gates` (5) held at training values. Tooling: `scripts/eval_scales.py`.

## Result (completion / best_lap / crash-per-step)
| scale (radius, hop) | completion | best_lap | crash/step |
|---|---|---|---|
| tight  (4.5 m, 1.5–2.8) | 0.95 | 2.49 s | 0.14e-3 |
| spread (8 m, 3–5.5)     | 0.76 | 3.86 s | 0.35e-3 |
| big    (12 m, 4.5–7.5)  | 0.49 | 5.24 s | 0.63e-3 |
| giant  (18 m, 6–10)     | 0.21 | 7.01 s | 1.09e-3 |

## Read
The policy is excellent IN-distribution (0.95 tight, matching its 0.94 training-eval) but generalizes poorly: completion falls monotonically and crash rate rises ~8x with scale. The failure mode is the unlearned **cruise-and-brake** control regime — a long leg then a hard decel into the gate — which tight back-to-back turns never exercise. This is overfitting to course geometry, not a weak policy.

## Honest caveats
- The studio's single-fixed-course `lap_completion_rate` is phase-sensitive (a `(laps>0)` snapshot that resets on each crash) and is NOT a fair score — it can read 0.06 on a course the policy actually flies at 0.91. The numbers above use the valid cycled regime (`eval_scales.py`); the studio summary metric is for watching, not ranking.
- `studio_rollout` sets `episode_len = max_steps`, which is what deflates that summary metric (it doesn't affect what you watch; `best_lap` is fine).

## Lever
Train across a RANGE of course scales (next node). Commit `d56a16d` adds the scale-randomization knob + `eval_scales.py`.