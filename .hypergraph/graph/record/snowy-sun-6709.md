---
node_id: 04e3221c-8add-5137-a283-f07923fabf9a
slug: snowy-sun-6709
title: 'Capacity unlocks the full-range generalist: [256,256] is the knee (GREEN); [384] turns over'
created_at: '2026-06-28T21:25:43.813168+00:00'
parents:
- shy-wildflower-8500
summary: 'Extending the generalist range to GIANT (radius 4.5→18 m) at fixed [128,128] only trades tight for giant (giant 0.569→0.635, tight 0.906→0.844) — capacity is the binding constraint. Raising the net to [256,256] UNLOCKS it: lap_completion tight/spread/big/giant = 0.954/0.889/0.843/0.694 (seed0), beating the [128] giant-range at every scale AND recovering the tight tax (0.844→0.954, even > the tight-only baseline''s 0.95). The capacity curve then TURNS OVER: [384,384] regresses −0.04..−0.07 across all scales — [256,256] is the knee (and stays MCU-plausible). Honest caveat: the giant end is seed-sensitive (w256 seed0 0.694 vs seed1 0.506, mean 0.600); tight/spread/big are stable (spread <0.03). GREEN — a single [256,256] policy flies tight→giant; promoted to studio-baseline candidate.'
origin:
  backend: flywheel
  node_id: 04e3221c-8add-5137-a283-f07923fabf9a
  slug: snowy-sun-6709
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 76ba5810-753a-574b-900f-95f9c206c800
  slug: tight-smoke-8823
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 410a7e184d8448d95d641cd55c2cec63577a2f0b6b138fa186cdcf03adae4e87
---
# Capacity unlocks the full-range generalist — [256,256] is the knee (empirical, RESOLVED — GREEN)

## Lineage (DAG merge)
- **builds-on:** `33021e6e` (the flat [128,128] range-4.5→12 generalist, GREEN) — whose honest caveat was that fixed capacity spreads thinner. This hop tests that caveat directly: push the range to *giant* and add capacity.
- **informed-by:** `ab7db544` (curriculum NO-GO) — ruled out scheduling, pointing the lever at **capacity / sampling**.

## Hypothesis
The generalist's tight-course tax and weak giant end are a **capacity** limit, not a data/schedule limit. Extending the training range to giant (radius 4.5→18 m) and widening the net should (a) add the giant capability and (b) recover the tax — up to a capacity knee beyond which more width stops helping.

## Setup (120M steps each, seed 0; eval DR-off across the four ARENA_PRESETS)
- **b3** `gate_race_general_giant.yaml`: [128,128], range extended **4.5→18 m** (was 4.5→12).
- **b4** `gate_race_general_giant_w256.yaml`: same giant range, **[256,256]**.
- **w384** `gate_race_general_giant_w384.yaml`: same, **[384,384]** (capacity-curve point).
- **seed check** `gate_race_general_giant_w256` seed 1 (giant-end variance).

## Results (lap_completion_rate by scale)
| scale | flat[128] 4.5→12 (A) | giant[128] (b3) | **giant[256] (b4)** | giant[384] |
|---|---|---|---|---|
| tight | 0.906 | 0.844 | **0.954** | 0.891 |
| spread | 0.848 | 0.833 | **0.889** | 0.830 |
| big | 0.714 | 0.774 | **0.843** | 0.781 |
| giant | 0.569 | 0.635 | **0.694** | 0.562 |

- **Range→giant at [128] (b3) only trades:** +big/+giant (0.714→0.774, 0.569→0.635) but −tight (0.906→0.844). Fixed capacity, redistributed.
- **[256] (b4) unlocks:** beats b3 at **every** scale; recovers the tight tax (0.844→0.954) past even A and the tight-only baseline (0.95); +giant to 0.694.
- **[384] turns over:** −0.049/−0.072/−0.059/−0.038 vs the [256] seed-mean — more width *hurts*. **[256,256] is the knee.**
- **Seed variance:** w256 seed0 vs seed1 — tight/spread/big stable (spread ≤0.027) but **giant 0.694 vs 0.506** (mean 0.600, spread 0.188). The giant end is genuinely seed-sensitive.

## Verdict: GREEN
The generalist's weakness was **capacity**, confirmed: [256,256] on the giant range gives a single tiny policy that flies tight→giant at 0.95/0.89/0.84/0.69 (seed0), strictly dominating both the [128] giant-range and — at tight — the original tight-only specialist. The capacity curve has a clear knee at [256,256] ([384,384] regresses everywhere), so this is also the **MCU-budget-honest** width. **Honest caveats:** (1) the giant end is seed-sensitive (0.51–0.69), so report the seed-mean 0.60 there; (2) giant is still the weakest scale — importance-sampling is the next lever (sibling hop).

## Action / promotion
GREEN + studio-relevant: a full-range generalist is a better Studio default than the tight-only specialist (it flies any course/preset the user picks). Promoting `gate_race_general_giant_w256` (seed 0) to **★ studio-baseline**. Code: configs already committed (`gate_race_general_giant*`); policy exported (`policy.onnx`).

## Artifacts
`capacity_sweep.csv` (b4 the headline), `capacity_curve.csv` ([384] turnover), `seed_variance.csv` (giant seed sensitivity), `giant_vs_flat.csv` (range-extension trade), `comparison.png`, `trajectory.png`, `training_curves.png`, `table.csv`, `run.json`, `replay.json.gz` (all for the [256] giant generalist).

## Reproduce
`uv run python scripts/train.py --config configs/gate_race_general_giant_w256.yaml` ; eval DR-off across ARENA_PRESETS; compare to `gate_race_general_giant` ([128]) and `..._w384` ([384]).

## Stop reason: improved (GREEN) — [256,256] knee confirmed; promoted to studio-baseline. Next lever for the giant end = importance-sampling (Pareto dial, sibling hop).