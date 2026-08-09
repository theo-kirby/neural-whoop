---
node_id: ab7db544-ec8b-5579-a826-43e142fa43f7
slug: weathered-wildflower-1251
title: 'Scale curriculum vs flat uniform sampling: no gain, hurts the giant end (NO-GO)'
created_at: '2026-06-28T21:21:39.493819+00:00'
parents:
- shy-wildflower-8500
summary: 'Tested whether a scale CURRICULUM (anneal easy→hard arena scale over training) beats the flat uniform-scale generalist (node shy-wildflower-8500). It does NOT: curriculum lap_completion is statistically flat at tight/spread/big (0.905/0.836/0.710 vs flat 0.906/0.848/0.714) and clearly WORSE at giant (0.461 vs 0.569, −0.108) with higher crash (0.882 vs 0.658e-3). Annealing spends late-training capacity on the hard tail at the cost of breadth; flat uniform sampling already exposes every scale each batch and wins. NO-GO — keep flat sampling; the lever to recover the giant end is capacity/importance-sampling, not scheduling. Config gate_race_general_curric.yaml; no code change.'
origin:
  backend: flywheel
  node_id: ab7db544-ec8b-5579-a826-43e142fa43f7
  slug: weathered-wildflower-1251
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Scale curriculum vs flat uniform sampling (empirical, RESOLVED — NO-GO)

## Lineage
- **builds-on:** `33021e6e` (the flat uniform-scale generalist, GREEN). Same range (radius 4.5→12 m), same [128,128], same 120M budget — the ONLY change is *how* scale is sampled over training.
- **informed-by:** the generalist's honest caveat (fixed capacity spreads thinner → giant is the weakest scale). This hop asks whether a curriculum recovers the giant end for free.

## Hypothesis
A scale **curriculum** (start narrow/easy, anneal toward the full tight→giant range) lets the policy consolidate control before facing the largest courses, recovering the giant-end completion the flat generalist leaves on the table — at zero extra capacity or budget.

## Setup
- Config `configs/gate_race_general_curric.yaml`: identical to the flat generalist except scale sampling is annealed over training. 120M steps, seed 0. Eval DR-off across the four ARENA_PRESETS.
- Reference: the flat uniform-scale generalist (`33021e6e`).

## Result (lap_completion_rate by scale; DR-off)
| scale | flat generalist | curriculum | Δ |
|---|---|---|---|
| tight | 0.906 | 0.905 | −0.001 |
| spread | 0.848 | 0.836 | −0.012 |
| big | 0.714 | 0.710 | −0.004 |
| giant | 0.569 | 0.461 | **−0.108** |

Crash at giant also worsens (0.658e-3 → 0.882e-3).

## Verdict: NO-GO
The curriculum gives **no gain** at tight/spread/big (all within noise) and **regresses the giant end** — exactly the scale it was meant to help. Annealing concentrates late-training updates on a shifting sub-distribution, so the policy sees the giant regime *less* per unit budget than flat uniform sampling, which exposes every scale in every batch. The flat generalist's breadth-first exposure is already the better schedule at fixed budget. Keep flat sampling; recovering the giant end needs **capacity or importance-sampling**, not curriculum scheduling.

## Artifacts
`curric_vs_flat.csv` (the verdict table), `comparison.png` (curriculum vs flat replay), `trajectory.png`, `training_curves.png`, `table.csv`, `run.json` (repro manifest), `replay.json.gz`.

## Reproduce
`uv run python scripts/train.py --config configs/gate_race_general_curric.yaml` ; eval DR-off across ARENA_PRESETS vs the flat generalist.

## Stop reason: no-effect (NO-GO) — curriculum refuted; flat sampling retained. Next lever for the giant end = capacity + importance-sampling (sibling hops).