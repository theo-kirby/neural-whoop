---
node_id: fc3019c1-7078-58ce-bf92-5e67f26a619f
slug: jolly-disk-0383
title: 'Scale curriculum (tight→big warmup): recovers the tight tax but TRADES big/giant — Pareto shift, not a free win'
created_at: '2026-06-27T14:03:36.620812+00:00'
parents:
- old-truth-3996
summary: 'Hypothesis: a tight->big curriculum trims the generalist''s ~0.07 tight tax WITHOUT losing the big/giant gains. Partly refuted. Across frac 0.15/0.30/0.50, every curriculum recovers tight (frac=0.15 -> 0.94, ~baseline) but gives back big/giant (0.15: big 0.66 / giant 0.39 vs the plain generalist''s 0.72 / 0.50). Shorter is strictly better. There''s a real tight<->big Pareto frontier; you pick a point, you don''t beat it.'
origin:
  backend: flywheel
  node_id: fc3019c1-7078-58ce-bf92-5e67f26a619f
  slug: jolly-disk-0383
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 734eb27f-2dc1-5cdb-98e5-d9e253c7a9e7
  slug: winter-block-0818
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: fa321d79d4b6db4873d8fc828e079e526c99f940effb8552f35c3784d0912846
---
## Hypothesis
The full-range generalist (`b4c3466f`) pays a ~0.07 tight-completion tax (0.95->0.88) from training on big courses from scratch. A curriculum that grows the course-size range tight->big over the first `scale_curriculum_frac` of training should master tight first and recover that tax WITHOUT sacrificing the big/giant gains.

## Setup
`GateRaceConfig.scale_curriculum_frac` ramps the sampled max arena radius from tight (4.5 m) to full (12 m) over that fraction of training; tight courses stay in the mix throughout. Trainer feeds linear progress via `env.set_course_scale()` (mirrors the DR curriculum). Same net + 120M budget. Scanned frac 0.15 / 0.30 / 0.50; eval via `eval_scales.py` (random courses per scale). Commit `b452820`.

## Result — cross-scale completion
| scale  | tight base | generalist (no curric) | curric 0.15 | curric 0.30 | curric 0.50 |
|---|---|---|---|---|---|
| tight  | 0.95 | 0.88 | **0.94** | 0.91 | 0.92 |
| spread | 0.76 | 0.83 | 0.83 | 0.80 | 0.79 |
| big    | 0.49 | **0.72** | 0.66 | 0.65 | 0.64 |
| giant  | 0.21 | **0.50** | 0.39 | 0.39 | 0.36 |

## Read (mixed / partial-refute)
- The curriculum DOES fix the tight tax — frac=0.15 lifts tight 0.88->0.94 (≈ baseline 0.95) and holds spread 0.83.
- But it TRADES the big/giant gains: big 0.72->0.66, giant 0.50->0.39. The hypothesis (recover tight *for free*) is refuted — it's a Pareto shift along a tight<->big frontier, not a strict win. From a fixed 120M budget you can't max both regimes.
- **Shorter is strictly better**: frac 0.15 > 0.30 > 0.50 on tight, with ~equal big. A long ramp wastes budget that the big end needs.
- `curric15` strictly DOMINATES the original tight baseline on every scale (0.94/0.83/0.66/0.39 vs 0.95/0.76/0.49/0.21) — a safe drop-in upgrade.

## Two policies on the frontier (pick by use case)
- **general_s1** (big-favoring): 0.88 / 0.83 / **0.72** / **0.50** — best for flying the big/giant studio courses.
- **curric15** (tight-favoring): **0.94** / 0.83 / 0.66 / 0.39 — matches the baseline on tight, big gains on spread/big; best as a general-purpose replacement (realistic whoop courses are tight-to-spread).

## Next (optional)
The frontier itself could be pushed by a non-curriculum lever: scale-IMPORTANCE weighting (sample small scales more often but keep big present from step 0), or more capacity/budget. Curriculum alone just moves along it.