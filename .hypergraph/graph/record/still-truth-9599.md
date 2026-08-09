---
node_id: b4681823-a785-54b2-9d7a-99e8b35a68a3
slug: still-truth-9599
title: 'Scale-importance weighting REFUTED: lands on the budget-bound tight↔big Pareto, doesn''t beat it (RED)'
created_at: '2026-06-27T15:38:11.981378+00:00'
parents:
- old-truth-3996
- cool-grass-4001
summary: 'Tested cool-grass-4001: bias the per-episode arena-radius draw toward small (radius=lo+(hi-lo)*U**weight, weight 2 & 4, 2 seeds, 120M) keeping big present from step 0. REFUTED. No policy clears the pre-registered bar (tight>=0.92 AND big>=0.70 AND giant>=0.45). simp2 (w=2) multi-seed 0.94/0.87/0.68/0.34, simp4 (w=4) 0.93/0.79/0.48/0.18 — monotonic: more small-bias recovers tight/spread but gives back big/giant (giant 0.34/0.18 vs general_s1 0.50). Same shape as the curriculum: it slides ALONG the tight<->big frontier, doesn''t beat it. The tradeoff is budget/capacity-bound, not a course-sampling artifact — the hypothesis''s own stated refutation condition.'
origin:
  backend: flywheel
  node_id: b4681823-a785-54b2-9d7a-99e8b35a68a3
  slug: still-truth-9599
  revision: 9
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ae343ea7-303b-5261-abcf-db8d9e512823
  slug: twilight-feather-3896
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 1a0f4bd99731cfcfc1d9d93bf58101f569750c6c5f1f0325cded6c9ea76e791a
---
## Lineage
- **tests** `7999315d` (cool-grass-4001) — the hypothesis this resolves.
- **builds-on** `b4c3466f` (scale-generalist) — same net/budget/DR; the ONLY change is the radius-draw weighting.

## Hypothesis (refuted)
The curriculum (`fc3019c1`) only moves ALONG a tight<->big frontier because it *withdraws* big courses early. Importance-weighting — keep the full range from step 0 but draw radius = lo+(hi-lo)*U**weight (biased small) — was predicted to lift tight WITHOUT giving back big/giant, clearing **tight≥0.92 AND big≥0.70 AND giant≥0.45 simultaneously**.

## What was run (default-off `scale_sample_weight` knob, commit 027df8f; eval_scales.py random courses per scale, DR-off, episode_len<steps)
weight ∈ {2.0 (simp2), 4.0 (simp4)}, 2 seeds each, [128,128]@120M, ~5 min/run on the 5090. weight=1.0 control = the existing generalist (general_s1).

| scale | tight base | general_s1 (w=1) | curric15 | **simp2 (w=2)** | **simp4 (w=4)** |
|---|---|---|---|---|---|
| tight  | 0.95 | 0.88 | 0.94 | **0.94** (.96/.91) | 0.93 (.88/.97) |
| spread | 0.76 | 0.83 | 0.83 | **0.87** (.90/.83) | 0.79 (.76/.81) |
| big    | 0.49 | **0.72** | 0.66 | 0.68 (.70/.65) | 0.48 (.51/.44) |
| giant  | 0.21 | **0.50** | 0.39 | 0.34 (.30/.37) | 0.18 (.22/.13) |

## Verdict: RED / refuted
No policy clears the simultaneous bar — the closest single seed, simp2_s0 (tight 0.96 / big 0.70 / **giant 0.30**), misses giant by 0.15. The result is **monotonic in the weight**: more small-bias buys a little tight/spread and steadily loses big/giant (giant 0.50 -> 0.34 -> 0.18 as weight 1->2->4). That is the signature of sliding ALONG a frontier, not beating it — the SAME outcome as the curriculum (`fc3019c1`), reached by a mechanistically different lever.

**Decision-relevant conclusion:** the tight<->big tradeoff is **budget/capacity-bound, not a course-sampling artifact** — exactly the refutation branch the hypothesis pre-registered ('if it just lands on the frontier, the real lever is capacity/budget, not sampling'). Two distribution-reshaping levers (curriculum, importance-weighting) have now both failed to beat the frontier. To actually dominate it you must change the *budget or capacity* (more steps / a wider net under the MCU constraint), or the *method* — not how you sample courses.

## Where each policy sits on the (confirmed) frontier
- **general_s1** (w=1) — big/giant-favoring (0.88/0.83/**0.72/0.50**): still the best for the big/giant Studio courses.
- **curric15 / simp2** — tight/spread-favoring (~0.94/0.85/0.67/0.35): interchangeable points; simp2 marginally beats curric15 on spread+big but loses giant. No strict dominator.
- **simp4** — over-biased; dominated, keep only as the monotonicity datapoint.

Studio baseline pointer UNCHANGED (no GREEN; general_s1 stays the big-favoring pick, curric15 the balanced one). The `scale_sample_weight` knob stays as default-off tested infra; configs marked REFUTED.

## Stop reason: refuted (frontier is budget-bound; reweighting slides along it)

## Next (optional)
The only remaining lever to BEAT the frontier is capacity/budget (more steps, or a wider net within the ~19k-param MCU envelope) or a different optimizer — a distinct branch from course-distribution shaping, which is now exhausted (2 refutations).