---
node_id: 3be0cddf-cb6b-561a-9a2d-fc5fdf446b4e
slug: wild-tree-5582
title: 'Seed replicate of the capacity winner (w256, seed 1): tight/spread/big robust, GIANT is seed-fragile (0.69 vs 0.51)'
created_at: '2026-06-28T16:25:28.602842+00:00'
parents:
- sparkling-feather-0123
- purple-base-8302
summary: 'Re-ran the w256 giant-range GREEN at seed 1 to bound the single-seed caveat. tight/spread/big replicate tightly (within +-0.03: 0.927/0.915/0.836 vs s0 0.954/0.889/0.843) and both seeds clearly beat B1 there. But GIANT swings 0.694(s0)->0.506(s1), a 0.19 gap, and s1''s giant dips below B1''s 0.569. So the capacity win is ROBUST on tight/spread/big but the giant gain is high-variance (mean 0.60). Studio-baseline stays on B4 s0 (best eval, seed-mean still >= B1 everywhere), with the giant claim now honestly qualified.'
origin:
  backend: flywheel
  node_id: 3be0cddf-cb6b-561a-9a2d-fc5fdf446b4e
  slug: wild-tree-5582
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 45c68808-afeb-544a-81b0-a642f56b0de3
  slug: shiny-poetry-3784
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: e6f9c73dd1dc82c4ce98086399e6753f90a0ae9233746defdd1ac2a682070bb4
---
## Hypothesis / purpose
B4 (`purple-base-8302`) declared a dominant GREEN on a SINGLE seed (s0). Every node in this branch carried the single-seed caveat. This re-runs the exact same `gate_race_general_giant_w256` config at **seed 1** to test whether the win — especially the headline giant improvement — is robust or seed luck.

## Setup
- **Policy:** `runs/gate_race_general_giant_w256_s1` — identical config to B4 (`configs/gate_race_general_giant_w256.yaml`, `1615bca`), only `--seed 1`. [256,256]@120M, radius 4.5->18, same DR.
- **Eval:** identical `scripts/eval_scales.py` cycled regime (4096 envs, steps 1500, episode_len 600, DR off).

## Results (completion) — seed variance of the w256 winner
| scale | w256 s0 (B4) | **w256 s1** | seed mean | seed spread | B1 flat ref |
|---|---|---|---|---|---|
| tight  | 0.954 | **0.927** | 0.940 | 0.027 | 0.906 |
| spread | 0.889 | **0.915** | 0.902 | 0.026 | 0.848 |
| big    | 0.843 | **0.836** | 0.840 | 0.007 | 0.714 |
| giant  | 0.694 | **0.506** | 0.600 | **0.188** | 0.569 |

## Verdict / Honesty
**Nuanced — partial confirmation (no clean outcome tag).** The capacity win **replicates robustly on tight/spread/big**: both seeds land within ±0.03 of each other and both beat B1 decisively (big +0.12..+0.13, spread +0.04..+0.07, tight +0.02..+0.05). Those three scales are solid. **But giant is seed-fragile:** 0.694 (s0) vs 0.506 (s1) — a 0.19 spread, and s1's giant (0.506) actually falls *below* B1's 0.569. So the B4 claim "dominates at EVERY scale" holds for s0 but **does not hold robustly at giant**; the honest aggregate is "capacity reliably wins tight/spread/big; giant improves on average (mean 0.60 > B1 0.57) but with high variance."

This **qualifies, not overturns, B4.** The studio-baseline pointer stays on B4 (s0): it is still the best single eval, and the two-seed MEAN of w256 (0.940/0.902/0.840/0.600) beats B1 at every scale. But giant near radius 18 is the unstable frontier — a single seed there is not trustworthy.

Mechanism read: giant courses are the rarest/hardest slice of the U[4.5,18] training distribution (largest hops, longest cruise legs, fewest laps per episode), so the policy gets the least and noisiest training signal there — hence the seed sensitivity. Two levers follow: more capacity (does [384,384] stabilize it? → B6, running) and/or giant-importance weighting (give large scales more training mass via the existing scale-importance knob).

## Lever (next)
- **B6 (running):** [384,384] capacity-curve point — does more capacity raise AND stabilize giant, or is [256,256] the knee?
- **Open:** giant-importance weighting (bias the per-episode radius draw toward large via the existing `scale-importance weight` knob) to reduce giant variance; multi-seed giant characterization.

## Lineage
Governed by control `sparkling-feather-0123`; a seed replicate of the capacity winner `purple-base-8302`. Artifacts: eval_scales.json (s1), seed_variance.csv (s0 vs s1, the decisive table), visual pack vs B4-s0 replay.