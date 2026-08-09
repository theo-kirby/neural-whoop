---
node_id: d1292eb5-b801-5a8d-bac5-d2cee166fa3e
slug: patient-dew-6473
title: 'Capacity curve has a knee at [256,256]: [384,384] regresses at fixed 120M budget — NO-GO'
created_at: '2026-06-28T16:38:16.548668+00:00'
parents:
- sparkling-feather-0123
- purple-base-8302
summary: 'Third capacity point: [384,384] on the giant range, same 120M budget. Completion tight/spread/big/giant = 0.891/0.830/0.781/0.562, WORSE than the [256,256] seed-mean 0.940/0.902/0.840/0.600 at every scale (mean 0.766 vs 0.821) and fails the tight gate (0.891<0.90). At a fixed step budget a wider net is under-trained — capacity pays 128->256 then reverses 256->384. [256,256] is the sweet spot. NO-GO.'
origin:
  backend: flywheel
  node_id: d1292eb5-b801-5a8d-bac5-d2cee166fa3e
  slug: patient-dew-6473
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
B5 (`wild-tree-5582`) left giant seed-fragile. If [128,128]->[256,256] helped by adding capacity, maybe [384,384] keeps paying — raising and/or stabilizing giant.

## Setup
- **Policy:** `runs/gate_race_general_giant_w384_s0`, `configs/gate_race_general_giant_w384.yaml` (committed `07bd169`). Identical to the w256 winner except `hidden_sizes` [256,256]->[384,384] (~70k -> ~150k params). Same giant range (radius 4.5->18), DR, **same 120M budget**, 4096 envs, seed 0.
- **Eval:** identical `scripts/eval_scales.py` cycled regime.

## Results — the capacity curve (completion), all giant-range, 120M budget
| scale | [128,128] | [256,256] s0 | [256,256] s1 | [256,256] mean | **[384,384]** | Δ vs 256-mean |
|---|---|---|---|---|---|---|
| tight  | 0.844 | 0.954 | 0.927 | 0.940 | **0.891** | −0.049 |
| spread | 0.833 | 0.889 | 0.915 | 0.902 | **0.830** | −0.072 |
| big    | 0.774 | 0.843 | 0.836 | 0.840 | **0.781** | −0.059 |
| giant  | 0.635 | 0.694 | 0.506 | 0.600 | **0.562** | −0.038 |

Mean completion: [128,128] (giant-range) ~0.77 → **[256,256] 0.821** → [384,384] 0.766. The curve is **non-monotonic with a knee at [256,256]**.

## Verdict / Honesty
**NO-GO.** [384,384] is worse than [256,256] at every scale and fails the tight gate (0.891<0.90). Capacity pays from [128,128] (bottlenecked) to [256,256] (sweet spot), then **reverses** to [384,384] — the classic signature of a wider net being **under-trained at a fixed 120M step budget** (more params need more data to converge; the same budget spread over ~2x params trains it less). It did NOT stabilize giant either (0.562, between the two w256 seeds). **No pointer move** — [256,256] (`purple-base-8302`) stays the studio-baseline. Honest caveat: this is a *budget-coupled* result — [384,384] might match/beat [256,256] given more steps; the claim is specifically "at 120M steps, [256,256] is the capacity sweet spot," not "384 is fundamentally worse." Single seed (s0).

## Read (closes the capacity thread)
The capacity-budget question for scale generalization is answered: **[256,256] is the knee at 120M steps.** Going wider needs more compute to pay off, which is out of scope for the tiny-policy goal anyway (the deployable target is *smaller*, not bigger). The remaining open thread is giant's instability, addressed by the distribution lever (giant-importance sampling, B7) rather than more capacity.

## Lineage
Governed by control `sparkling-feather-0123`; a capacity-curve sibling of the winner `purple-base-8302`, building on the seed-variance finding `wild-tree-5582`. Artifacts: eval_scales.json (decisive), capacity_curve.csv (128/256x2/384), visual pack vs w256-s0 replay.