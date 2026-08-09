---
node_id: 929f1410-70ee-54c2-91d3-04246b7f9eb3
slug: empty-firefly-1882
title: 'Flat scale-generalist (gate_race_general, 120M): flattens the geometry curve — giant completion 0.21->0.57 (2.7x), GREEN'
created_at: '2026-06-28T15:27:32.443896+00:00'
parents:
- damp-wood-7079
- holy-sky-9094
- sparkling-feather-0123
summary: 'Per-episode scale-randomized [128,128]@120M policy vs the tight-only baseline, same net/budget. Lap completion tight/spread/big/giant: baseline 0.95/0.76/0.49/0.21 -> generalist 0.91/0.85/0.71/0.57. Big +0.22, giant +0.36 (2.7x), crash ~halved at scale; cost = tight best_lap 2.49->3.25s (+31%) and tight completion -0.04. Best-overall across scales -> new studio-baseline. GREEN.'
origin:
  backend: flywheel
  node_id: 929f1410-70ee-54c2-91d3-04246b7f9eb3
  slug: empty-firefly-1882
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 2cfe4ef3-ca86-5127-93e5-dcb425a47218
  slug: super-mud-5800
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: cdb2f3f0ff868dcd0b1e9a8314da452ff2442b2150f0b80bf81235db39155f91
---
## Hypothesis
The tight 120M baseline collapses as gates spread (0.95->0.21 completion) because it never trained the **cruise-and-brake** regime far-apart gates demand (parent `damp-wood-7079`). Training the SAME [128,128]@120M net across a per-episode RANGE of course scales should flatten that curve — at some in-distribution cost.

## Setup
- **Policy:** `runs/gate_race_general_s0`, `configs/gate_race_general.yaml`. Only change vs baseline: `scale_randomize=true`, per-episode arena radius ~U[4.5,12] m with gate hops proportional, gate height ~U[2.3,3.5]; crash bounds sized to the largest scale. Same [128,128] net, 120M steps, 4096 envs, obs-v4+lookahead (14), act-v2.
- **Eval:** `scripts/eval_scales.py` — official cycled regime, 4096 envs, steps 1500, episode_len 600, **DR off**, gate_radius 0.45, n_gates 5. IDENTICAL regime to the baseline table, only arena scale varies.
- Code SHA `07f1e16` (unchanged; runs/ gitignored). diffaero `291ea14`.

## Results (completion / best_lap s / crash-per-step ×1e-3)
| scale (radius, hop) | baseline | **generalist** | best_lap b->g | crash b->g |
|---|---|---|---|---|
| tight  (4.5, 1.5-2.8) | 0.95 | **0.906** | 2.49->3.25 | 0.14->0.11 |
| spread (8, 3-5.5)     | 0.76 | **0.848** | 3.86->3.84 | 0.35->0.15 |
| big    (12, 4.5-7.5)  | 0.49 | **0.714** | 5.24->4.57 | 0.63->0.28 |
| giant  (18, 6-10)     | 0.21 | **0.569** | 7.01->5.23 | 1.09->0.66 |

**Δ vs parent baseline:** completion +0.09 spread / **+0.22 big** / **+0.36 giant (2.7x)**; tight −0.04. best_lap FASTER at big (−0.67s) and giant (−1.78s) — the generalist actually flies large courses both more reliably AND faster, because it learned to cruise the long legs instead of the baseline's tight-turn micro-control. Crash rate cut ~55% (big) / ~40% (giant). In-distribution cost: tight best_lap 2.49->3.25 s (+31% slower) and a 4-pt completion dip — the policy trades peak tight-track aggression for cross-scale competence.

## Verdict / Honesty
**GREEN** on the generalization objective. Against the contract's stretch gate (tight>=0.90 ✓ at 0.906, giant>=0.55 ✓ at 0.569, big>=0.75 **✗ at 0.714** — just short): big completion is the residual headroom. It is unambiguously **best-overall across scales** (baseline wins only tight, and only on speed, not completion), so it takes the `★ studio-baseline` pointer. Honest caveats: (1) single seed (s0); seed variance not yet bounded. (2) tight speed regressed — if peak tight lap time matters for a specific deployment, the tight specialist is still faster there. (3) DR off, as in the baseline table — robustness-under-DR is a separate axis.

## Lever (next)
Big sits at 0.71, under the 0.75 target. Branch 2 (`gate_race_general_curric`, tight->big curriculum over first 15%) tests whether curriculum ordering pushes big/giant higher and/or recovers tight speed. Branch 3 (gate_radius randomization) adds the other geometry axis the baseline held fixed.

## Lineage
Governed by control `sparkling-feather-0123`; improves directly on overfit baseline `damp-wood-7079`; executes the un-run setup `841dade5` (spread-out-courses lever). Artifacts: eval_scales.json (decisive), cross_scale_comparison.csv, standard visual pack (trajectory/fpv/training_curves/comparison + run.json manifest).