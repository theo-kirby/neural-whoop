---
node_id: 4a80675e-d382-5358-ad20-92d2c745aba3
slug: orange-pond-7208
title: 'Curriculum generalist (gate_race_general_curric, 120M): no gain over flat scale-rand, regresses giant — NO-GO'
created_at: '2026-06-28T15:46:00.565092+00:00'
parents:
- empty-firefly-1882
- sparkling-feather-0123
summary: Tight->big scale curriculum (range grows over first 15%) vs the flat scale-randomized generalist (empty-firefly-1882), same net/budget. Completion tight/spread/big/giant = 0.905/0.836/0.710/0.461 vs flat 0.906/0.848/0.714/0.569. Flat-or-worse everywhere; giant -0.11 (curriculum extrapolates WORSE to the OOD largest scale). Curriculum ordering buys nothing. NO-GO; flat generalist stays studio-baseline.
origin:
  backend: flywheel
  node_id: 4a80675e-d382-5358-ad20-92d2c745aba3
  slug: orange-pond-7208
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 53ad0200-ae2a-55ae-87ba-1adf3ef93aa8
  slug: delicate-base-6766
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 109570db1f9f3a72e6fa9ed461d7c87400aa25c21ac76c0d364209ea570ffda9
---
## Hypothesis
B1 (flat per-episode scale randomization) left big completion at 0.71, under the 0.75 target. Ordering the scale exposure tight->big over the first 15% of training (a curriculum) might let the policy master tight control first, then transfer it outward — pushing big/giant higher and/or recovering the tight speed B1 lost.

## Setup
- **Policy:** `runs/gate_race_general_curric_s0`, `configs/gate_race_general_curric.yaml`. Same [128,128]@120M net, 4096 envs as B1. Only difference vs B1: the scale range grows tight->big over the first 15% of steps (`scale_curriculum_frac`) instead of being full-range from step 0. Both top out at radius 12 m (big); giant (18 m) is out-of-distribution for both.
- **Eval:** identical `scripts/eval_scales.py` cycled regime (4096 envs, steps 1500, episode_len 600, DR off, gate_radius 0.45, n_gates 5).
- Code SHA `07f1e16`; diffaero `291ea14`.

## Results (completion / best_lap s / crash ×1e-3) vs B1 flat generalist
| scale | flat (B1) | **curric (B2)** | Δ compl |
|---|---|---|---|
| tight  | 0.906 | **0.905** | −0.001 |
| spread | 0.848 | **0.836** | −0.012 |
| big    | 0.714 | **0.710** | −0.004 |
| giant  | 0.569 | **0.461** | **−0.108** |

best_lap within ±0.1 s of B1 at every scale (tight marginally faster 3.25->3.18 s, giant slower 5.23->5.39 s). Crash rate equal-or-higher, worst at giant (0.66->0.88e-3, +33%).

## Verdict / Honesty
**NO-GO.** The curriculum matches flat scale-randomization on tight/spread/big and **regresses the hardest, out-of-distribution scale (giant −0.11 completion, +33% crash)**. It did NOT recover B1's tight-speed cost in any meaningful way (3.25->3.18 s is within noise) and did NOT push big past the 0.75 target. Mechanism read: spending early budget on a narrowed scale range leaves the final policy a worse extrapolator beyond the training max — flat exposure from step 0 generalizes outward better. **No pointer move** — the flat generalist `empty-firefly-1882` remains the studio-baseline. Honest caveats: single seed each (B1 s0 vs B2 s0), so the small tight/spread/big deltas are within plausible seed noise — but the giant regression (−0.11) is larger than the other deltas and consistent with the worse-extrapolation mechanism. This closes the curriculum-ordering thread for scale generalization.

## Lever (next)
Curriculum is exhausted. Remaining frontier: (3) **gate_radius randomization** — the baseline AND both generalists held gate_radius fixed at 0.45; big sits at 0.71 partly because the policy never trained varied gate apertures. (4) **capacity** — B1/B2 training completion both plateaued ~0.66 across the mixed distribution, hinting the [128,128] net may be capacity-bound for the full scale range; a wider net is the n=2 lookahead candidate if radius-rand also stalls.

## Lineage
Governed by control `sparkling-feather-0123`; an alternative to (and measured against) the flat generalist `empty-firefly-1882`. Both descend from the spread-out-courses setup. Artifacts: eval_scales.json (decisive), curric_vs_flat.csv, visual pack vs B1 replay.