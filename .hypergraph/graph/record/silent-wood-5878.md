---
node_id: 360b5dc1-b36e-5479-82c4-19339c900da4
slug: silent-wood-5878
title: 'Giant''s weakness was training-MASS, not capacity: giant-importance sampling lifts giant 0.60->0.84 (tight cost) — Pareto dial'
created_at: '2026-06-28T16:51:17.983642+00:00'
parents:
- sparkling-feather-0123
- purple-base-8302
- wild-tree-5582
summary: 'Biasing the per-episode radius draw toward large courses (scale_sample_weight 0.5) on the w256 winner: giant 0.600->0.837 (+0.24, best ever, crash 0.27->0.09e-3) and big +0.05, but tight 0.941->0.785 (-0.16, below gate). Confirms giant was UNDER-trained (rarest slice), not capacity-bound. scale_sample_weight is a tight<->giant Pareto dial; B4 (w=1.0) and this (w=0.5) are its ends. No pointer move; B8 (w=0.7) probes the balanced middle.'
origin:
  backend: flywheel
  node_id: 360b5dc1-b36e-5479-82c4-19339c900da4
  slug: silent-wood-5878
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 016a4d83-0687-541e-93ff-7da4328e1ebc
  slug: purple-forest-6778
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 492f2bea76927557cd46f2913030eada3ecf3526beee9e8399945505c1942065
---
## Hypothesis
B5/B6 left giant as the weak, seed-fragile scale. Mechanism guess (from `wild-tree-5582`): giant is the **rarest, hardest slice** of the uniform U[4.5,18] radius draw, so it's under-trained. Prediction: biasing the sampler toward large courses (more giant mass) should lift and stabilize giant — testing whether giant's weakness is a **distribution** problem (fixable by reweighting) rather than a capacity one (B6 showed more capacity didn't help).

## Setup
- **Policy:** `runs/gate_race_general_giant_w256_bigwt_s0`, `configs/gate_race_general_giant_w256_bigwt.yaml` (committed `fafc409`). Identical to the w256 winner (`purple-base-8302`) except `scale_sample_weight` 1.0->**0.5**: radius = lo+(hi-lo)·U[0,1]^0.5, skewing the per-episode draw toward the large end. Same [256,256]@120M, DR, seed 0.
- **Eval:** identical `scripts/eval_scales.py` cycled regime.

## Results (completion / crash ×1e-3) vs the uniform w256 seed-mean
| scale | uniform mean (w=1.0) | **bigwt (w=0.5)** | Δ compl | bigwt crash |
|---|---|---|---|---|
| tight  | 0.941 | **0.785** | **−0.155** | 0.258 |
| spread | 0.902 | **0.886** | −0.016 | 0.116 |
| big    | 0.839 | **0.886** | +0.047 | 0.091 |
| giant  | 0.600 | **0.837** | **+0.237** | 0.090 |

bigwt MEAN completion 0.849 — the **highest of any policy in the lineage** — and the giant crash rate collapses to 0.090e-3 (vs ~0.27 uniform, 1.09 original baseline). But tight craters to 0.785 (its weakest scale now), failing the 0.90 gate.

## Verdict / Honesty
**Mixed / Pareto — no clean outcome, no pointer move — but a decisive MECHANISM confirmation.** Giant's weakness was **training mass, not capacity**: a 2x-toward-large sampler lifts giant +0.24 to 0.84 (and *stabilizes* it — crash 1/3 of uniform), while B6 showed doubling capacity did nothing for giant. So `scale_sample_weight` is a **tight↔giant Pareto dial**: w=1.0 (`purple-base-8302`) is tight-strong (0.94/0.90/0.84/0.60), w=0.5 (here) is giant-strong (0.79/0.89/0.89/0.84). Neither dominates; the right setting depends on the deployment's course-size mix. The **studio-baseline stays on B4 (w=1.0)** as the balanced default (tight is the common case). Honest caveats: single seed; bigwt's tight regression is large and real (not noise). The natural follow-up is the middle of the dial.

## Lever (next)
**B8 (running):** `scale_sample_weight 0.7` — the intermediate dial point. If a balanced weight clears ALL gates at once (tight>=0.90 AND big>=0.75 AND giant>=0.55), that is the clean dominant generalist B4 just missed on giant.

## Lineage
Governed by control `sparkling-feather-0123`; a distribution-reweighting variant of the capacity winner `purple-base-8302`, motivated by the giant-fragility finding `wild-tree-5582` (a true parent: this directly tests that node's mechanism guess). Artifacts: eval_scales.json (decisive), pareto_dial.csv (w=1.0 vs w=0.5), visual pack vs w256-uniform replay.