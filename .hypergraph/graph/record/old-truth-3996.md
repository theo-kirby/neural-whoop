---
node_id: b4c3466f-1dcf-5db9-b7b6-5f1a90c83574
slug: old-truth-3996
title: 'Scale-generalist policy: training tight→big recovers big/giant reliability (GREEN) — new studio baseline'
created_at: '2026-06-27T12:36:06.982203+00:00'
parents:
- damp-wood-7079
- holy-sky-9094
- shrill-limit-5398
summary: 'One [128,128]@120M policy trained with per-episode course-scale randomization (arena 4.5–12 m) generalizes far better than the tight-only baseline: big completion 0.49→0.72, giant 0.21→0.50 (>2x), for a modest tight tax 0.95→0.88. Beats a spread-only specialist on big/giant (range matters). gate_race_general_s1 is the new recommended studio policy.'
origin:
  backend: flywheel
  node_id: b4c3466f-1dcf-5db9-b7b6-5f1a90c83574
  slug: old-truth-3996
  revision: 25
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
The baseline fumbles on big courses because it never trained on far-apart gates (measurement `4d5ed6b9`). Training ONE policy across a range of course scales (the `scale_randomize` knob, commit `d56a16d`) should recover big/giant reliability at a modest tight cost.

## Setup
Same net ([128,128]) + 120M budget + DR as the racing baseline `8db85abb`; the ONLY change is the course distribution. `gate_race_general`: per-episode arena radius ~U[4.5,12] m, gate hops proportional (step = 0.34–0.62 × radius), gate height ~U[2.3,3.5], crash bounds sized to the largest scale. Two seeds. A spread-only specialist (`gate_race_spread`, arena 8 m) trained as a comparison. ~4.5 min/run at 430k steps/s on the 5090.

## Result — cross-scale completion (eval_scales.py, random courses per scale)
| scale  | tight base | spread-spec | general_s0 | general_s1 |
|---|---|---|---|---|
| tight  | **0.95** | 0.88 | 0.83 | 0.88 |
| spread | 0.76 | **0.87** | 0.82 | 0.83 |
| big    | 0.49 | 0.54 | 0.68 | **0.72** |
| giant  | 0.21 | 0.26 | 0.45 | **0.50** |

## Read (GREEN)
- The generalist roughly **doubles** giant completion (0.21→0.50) and lifts big +47% (0.49→0.72), while keeping tight near-baseline (s1 0.88 vs 0.95) — the expected, modest generalization tax.
- **Range matters**: the spread specialist (trained only to 8 m) barely helps big/giant (0.54/0.26) — it never saw 12–18 m geometry. The generalist trained to 12 m generalizes UP to 18 m (giant) far better. This is the key design confirmation: train to the top of the range you care about.
- `general_s1` > `general_s0` (seed variance); **s1 is the new recommended studio baseline** (best all-around: 0.88/0.83/0.72/0.50).
- Visual sanity in the studio (seeded fixed courses, gates-passed): giant-circuit baseline 83 → s1 109 (+31%).

## Caveats / next
- Giant (18 m) is beyond the 12 m training top, so 0.50 there is extrapolation — and arguably unrealistic for a 32 g indoor whoop anyway (per the locked range decision, big=12 m is the real target, where s1 hits 0.72).
- Only 2 generalist seeds; a 3rd would tighten the variance. The tight tax (~0.07) could likely be trimmed by oversampling small scales or a tight→big curriculum (start tight, grow) — a natural follow-up branch.
- New policies auto-appear in the Studio dropdown (`runs/*/ckpt_final.pt`); pick `gate_race_general_s1` to watch it fly the big/giant courses.

Runs are local artifacts (runs/ is gitignored); the infra + configs + eval harness are in commit `d56a16d`.