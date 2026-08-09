---
node_id: 07c7a70e-e768-59d1-ac8f-34157937b4be
slug: divine-mud-3368
title: 'Perception-aware formation does NOT inherit clean flat-scaling: noisy anchor detection degrades + destabilizes it across N (measurement, multi-seed flagged)'
created_at: '2026-06-28T03:28:53.449061+00:00'
parents:
- sweet-bush-8692
- summer-wave-6268
summary: 'Fuses the two strongest swarm/perception results to ask: does the DEPLOYABLE (noisy-anchor + EMA) formation scale flat like the clean one? Clean-anchor formation scales flat to 24 drones (summer-wave-6268, hold ~0.99); the perception-aware bridge recovers n=3 formation under noisy detection to 0.862 (sweet-bush-8692). This hop scales the perception-aware version: detector ON + EMA(0.85), n_agents 6/12/24, slot spacing held ~0.6m (grown ring), n_drones 12288, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT (nuanced): the noisy-anchor formation does NOT reproduce the clean flat 0.99 scaling. hold_rate lands in a wide, NON-MONOTONIC band -- n=3 0.862, n=6 0.469, n=12 0.848, n=24 0.610 -- well below the clean 0.99, with a few collisions appearing (0.0003-0.0013/step). Detection noise both DEGRADES (lower hold) and DESTABILIZES (high across-N variance) the clean size-invariance. With a single seed the across-N pattern (n=6 worst, n=12 best) is dominated by training variance, not a real N-trend -- so the honest claim is ''noisy-anchor formation holds moderately (0.47-0.85) but loses the clean version''s flat near-perfect scaling, and is seed-sensitive''. This is a genuine CAVEAT to the formation-scaling story: the idealized (ground-truth-anchor) result was cleaner than the deployable one. Multi-seed confirmation is the needed next step before any N-trend claim. Configs b6d56ea; measurement, no code change.'
origin:
  backend: flywheel
  node_id: 07c7a70e-e768-59d1-ac8f-34157937b4be
  slug: divine-mud-3368
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 0d8bff65-242c-5f98-8c3a-0f56217daad8
  slug: morning-violet-5305
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 4267ebd7486e56aa4b88cd2e4fc70a82689ba7b53a321549cab688fe3aeedf2a
---
## Setup
The two strongest swarm/perception results so far: (a) **clean-anchor formation scales FLAT to 24 drones** (`summer-wave-6268`, hold ~0.99/0 collisions), and (b) the **perception-aware bridge** recovers n=3 formation under a noisy detector to 0.862 hold via EMA (`sweet-bush-8692`). This hop fuses them: **does the deployable (noisy-anchor + EMA) formation also scale flat?** Detector ON (3deg/10%/5%dropout/110-deg FOV) + `estimate_ema_alpha`=0.85, `n_agents` 6/12/24, slot spacing held ~0.6m by growing the ring (r 0.60/1.16/2.30), `n_drones` held 12288, [128,128]@120M seed 0, eval 2048x1500 seed 12345. Configs `swarm_formation_pscale{6,12,24}.yaml` (b6d56ea).

## Results
| n_agents | condition | hold_rate | formation_error (m) | collision/step |
|---|---|---|---|---|
| 6/12/24 | **clean anchor (ref, summer-wave-6268)** | **~0.99** | ~0.20 | 0.0 |
| 3 | noisy+EMA (ref, sweet-bush-8692) | 0.862 | 0.277 | 0.0 |
| 6 | noisy + EMA(0.85) | **0.469** | 0.560 | 0.0013 |
| 12 | noisy + EMA(0.85) | **0.848** | 0.278 | 0.0003 |
| 24 | noisy + EMA(0.85) | **0.610** | 0.344 | 0.0005 |

## Findings
1. **The clean flat 0.99 scaling is NOT inherited.** Under noisy anchor detection, hold_rate drops into a 0.47-0.85 band (vs clean ~0.99) at every scale -- detection noise degrades formation-keeping at all N.
2. **It also DESTABILIZES scaling.** The across-N pattern is non-monotonic (n=6 0.469 worst, n=12 0.848 best, n=24 0.610) -- the clean version's clean size-invariance is gone. A few collisions appear (0.0003-0.0013/step) where the clean formation had exactly zero.
3. **Single-seed caveat (the honest read).** With one seed, the non-monotonic across-N shape is almost certainly training variance, not a real N-trend -- the noisy-perception regime is harder to optimize than the clean one and lands at different local optima per run. The load-bearing claim is the LEVEL (0.47-0.85, well below clean 0.99) and the VARIANCE, not the ordering.
4. **Caveat to the scaling story.** The earlier 'formation scales flat to 24' (`summer-wave-6268`) used a GROUND-TRUTH anchor. The deployable version (noisy onboard detection) is real but materially more fragile and variable -- an honest correction to how clean that capability looked.

## Verdict
**Measurement (nuanced, no single outcome): noisy-anchor formation holds moderately (0.47-0.85) but loses the clean flat-scaling and is seed-sensitive.** Detection noise is the binding constraint on the deployable formation, not agent count. Next: MULTI-SEED (n=3 seeds per scale) to separate the noise level from training variance, and a stronger filter (predictive/Kalman) to recover more of the clean ceiling. Configs kept as the recipe; no code change.

## Honesty / limits
Single seed per scale -- explicitly insufficient to claim an N-trend; the value here is the honest signal that the deployable formation underperforms + destabilizes vs the idealized one. Same residual-per-fix-noise mechanism as the perception envelope (`wandering-mode-7957`); a predictive filter would likely lift + stabilize these. n=6's small ring (r=0.6) packs neighbours tighter, which may explain its extra collisions under a noisy reference.

## Lineage
- **builds-on** `bcee9cf6` (sweet-bush-8692, perception-aware formation bridge): scales the noisy-anchor formation it introduced.
- **informed-by** `e3519636` (summer-wave-6268, clean formation scaling): the contrast -- clean scales flat 0.99, noisy does not.

## Artifacts
percep_scaling.png (noisy+EMA hold_rate vs N, vs the clean flat line), percep_scaling_table.json. Configs b6d56ea.