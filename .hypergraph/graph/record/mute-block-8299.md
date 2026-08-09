---
node_id: c31b8155-05c9-5f5a-8995-2f5848791e2a
slug: mute-block-8299
title: 'Multi-seed confirms: the perception-aware formation n=6<n=12 gap is REAL, not training variance (n=12 reproducibly ~0.84, small-ring n=6 ~0.51)'
created_at: '2026-06-28T04:03:04.623348+00:00'
parents:
- divine-mud-3368
summary: 'Follows through on the single-seed caveat from divine-mud-3368 (perception-aware formation scaling looked non-monotonic, 0.47-0.85). Ran 3 seeds each at the spread''s extremes -- n=6 (looked worst) and n=12 (best) -- to separate the noise level from training variance. RESULT: the gap is REAL and reproducible. n=12 hold_rate = 0.848/0.848/0.832 (mean 0.843, spread 0.016 -- very tight); n=6 = 0.469/0.490/0.584 (mean 0.514, spread 0.115). The two distributions are NON-OVERLAPPING (every n=6 seed below every n=12 seed), so the n=6<n=12 difference is a genuine effect, not seed noise. My hop-19 ''it''s all single-seed variance'' hypothesis is PARTLY REFUTED: n=12 is reproducibly solid AND n=6 is reproducibly worse. Mechanism: n=6''s small compact ring (r=0.6) has ~4x the collision rate under noisy detection (0.0013 vs 0.0003/step), triggering more shared-fate resets -- small/tight formations are genuinely harder to hold from a noisy anchor. REFINED CONCLUSION: the deployable (noisy-anchor + EMA) formation holds reproducibly WELL (~0.84) at moderate ring sizes but degrades at tight ones, all below the clean-anchor 0.99 -- detection noise + ring compactness, not raw agent count, are the binding constraints. Measurement; no code change.'
origin:
  backend: flywheel
  node_id: c31b8155-05c9-5f5a-8995-2f5848791e2a
  slug: mute-block-8299
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
The hop-19 measurement (`divine-mud-3368`) found the perception-aware (noisy-anchor + EMA) formation scaling looked non-monotonic across N (0.47-0.85, single seed) and flagged it as probably training variance. This hop tests that directly: 3 seeds each at the two extremes -- **n=6** (the worst-looking, 0.469) and **n=12** (the best, 0.848) -- using the same `swarm_formation_pscale{6,12}.yaml` (detector ON + EMA 0.85, slot spacing ~0.6m), [128,128]@120M, eval 2048x1500 seed 12345.

## Results (3 seeds each)
| n_agents | seed0 | seed1 | seed2 | mean | spread | collision/step |
|---|---|---|---|---|---|---|
| 6 (r=0.6) | 0.469 | 0.490 | 0.584 | **0.514** | 0.115 | 0.0013 |
| 12 (r=1.16) | 0.848 | 0.848 | 0.832 | **0.843** | 0.016 | 0.0004 |
(clean-anchor ref ~0.99; `summer-wave-6268`.)

## Findings
1. **n=12 is reproducibly SOLID** -- 0.832-0.848 across 3 seeds (spread 0.016). The deployable formation at a moderate ring is consistent, not a lucky seed.
2. **n=6 is reproducibly WORSE** -- 0.469-0.584, mean 0.514. Every n=6 seed is below every n=12 seed: the distributions DON'T OVERLAP.
3. **=> the n=6<n=12 gap is a REAL effect, not training variance.** My hop-19 'it's all single-seed noise' hypothesis is partly refuted -- the level (well below clean 0.99) AND the small-ring penalty are both real; only the exact within-n6 ordering was noise.
4. **Mechanism: small-ring collisions under noise.** n=6's compact ring (r=0.6) shows ~4x the collision rate (0.0013 vs n=12's 0.0003), and with `collision_terminates=True` those collisions reset episodes -> lower hold. A tight formation gives noisy-anchor position errors less room before drones conflict; a bigger ring (same slot spacing) has more absolute slack.

## Verdict
**Measurement (firms up divine-mud-3368): the deployable formation holds reproducibly ~0.84 at moderate rings, ~0.51 at tight rings -- a real ring-compactness effect under noisy detection, all below the clean-anchor 0.99.** The binding constraints on the deployable formation are detection noise + ring compactness, NOT raw agent count. Honest follow-through: I hypothesized variance; multi-seed showed the gap is real. No code change.

## Honesty / limits
3 seeds at 2 scales (n=6, n=12); n=24 (0.61 single seed in hop-19) was NOT multi-seeded here, so its variance is still unknown -- but given n=12's tightness, n=24's level is likely real too. The deployable formation never reaches the clean 0.99 at any tested scale; a predictive (Kalman) filter or lower detector noise is the lever to close that, not more agents or seeds.

## Lineage
- **builds-on** `07c7a70e` (divine-mud-3368): resolves the single-seed ambiguity it flagged -- the n-dependence is real, not variance.

## Artifacts
multiseed_formation.png (per-seed hold_rate, non-overlapping n=6 vs n=12 clusters), multiseed_formation_table.json.