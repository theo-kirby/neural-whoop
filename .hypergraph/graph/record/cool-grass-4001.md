---
node_id: 7999315d-5276-5030-acbd-8885b13130b0
slug: cool-grass-4001
title: 'Hypothesis: scale-importance weighting beats the tight↔big Pareto (keep big from step 0, sample small more)'
created_at: '2026-06-27T15:03:01.130229+00:00'
parents:
- old-truth-3996
- jolly-disk-0383
summary: Open hypothesis branching off the curriculum Pareto finding (fc3019c1). The tight->big curriculum only moves ALONG a tight<->big frontier because it withdraws big courses early. A non-curriculum lever — keep ALL scales present from step 0 but importance-weight the per-episode scale sampling toward small courses — should lift tight WITHOUT giving back big/giant, because big geometry is never removed from training. Predicts a single policy clearing tight>=0.92 AND big>=0.70 AND giant>=0.45 (beating both general_s1 and curric15). Untested.
origin:
  backend: flywheel
  node_id: 7999315d-5276-5030-acbd-8885b13130b0
  slug: cool-grass-4001
  revision: 8
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Status: OPEN HYPOTHESIS (not yet run)

## Where it comes from
`fc3019c1` (scale curriculum) showed the tight->big warmup recovers the generalist's tight tax (0.88->0.94) but TRADES away its big/giant gains (big 0.72->0.66, giant 0.50->0.39) — a Pareto shift along a tight<->big frontier, not a strict win. The mechanistic read there: a fixed 120M budget split as 'ramp then full' gives the big end less training time, and the curriculum *withdraws* big courses during the early ramp.

## The hypothesis
The curriculum's flaw is **withdrawal**, not the idea of emphasising small courses. A different lever should beat the frontier rather than slide along it:

- Keep the FULL scale range (tight..big, radius ~4.5–12 m) sampled from **step 0** — big is never removed.
- But **importance-weight** the per-episode scale draw toward small/tight scales (e.g. sample radius ∝ w(r) with w decreasing in r), so the policy gets enough tight reps to hold 0.94 there.

**Prediction:** one policy clears **tight ≥0.92 AND big ≥0.70 AND giant ≥0.45 simultaneously** — strictly dominating both current frontier points (general_s1 0.88/–/0.72/0.50 and curric15 0.94/–/0.66/0.39). If instead it just lands on the same frontier (gain tight, lose big), the frontier is budget-bound and the real lever is capacity/budget, not sampling — also a useful refutation.

## How to test (cheap, ~5 min/run on the 5090)
- Add a `scale_sample_weight` knob to the `scale_randomize` draw in `gate_race.py` (default uniform = current behaviour, byte-identical).
- Sweep the small-bias weight (e.g. {1.0 uniform, 2.0, 4.0} on a 1/r-style kernel), 120M, 2 seeds; eval with `eval_scales.py` across tight/spread/big/giant.
- Decision: GREEN if the simultaneous bar above is met; NO-GO/REFUTED if it lands on the existing Pareto frontier.

## Lineage
- builds-on `b4c3466f` (the scale-generalist — the policy/infra this varies).
- informed-by `fc3019c1` (the curriculum Pareto refutation that motivates a non-withdrawal lever).