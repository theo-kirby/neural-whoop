---
node_id: accf5145-d04b-5837-ba0b-641f7f28a6f4
slug: snowy-rice-0635
title: 'Importance-sampling Pareto dial: upweighting hard scales trades tight for giant (clean frontier)'
created_at: '2026-06-28T21:34:31.508930+00:00'
parents:
- snowy-sun-6709
summary: 'On the [256,256] giant-range generalist, biasing per-episode scale sampling toward LARGE courses (scale_sample_weight<1) opens a clean, monotonic Pareto frontier between tight and giant completion. Sweeping weight 1.0(uniform)→0.7→0.5: giant climbs 0.600→0.706→0.837 while tight falls 0.941→0.861→0.785 (spread/big roughly flat, big even +0.05 at 0.5). bigwt(0.5) buys +0.237 giant for −0.155 tight; wt07(0.7) is the balanced midpoint (tight 0.861 / giant 0.706). No dominating point — it is a genuine DIAL: pick the operating weight for the target course-size mix. Sibling of the [256] knee node; cluster:capacity-budget; no single outcome (Pareto). Configs gate_race_general_giant_w256_bigwt/_wt07 committed; no code change.'
origin:
  backend: flywheel
  node_id: accf5145-d04b-5837-ba0b-641f7f28a6f4
  slug: snowy-rice-0635
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 65fd80e1-2c97-5c9d-a107-6b45f5f883d7
  slug: lingering-haze-7532
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 258a245915f288a6ae22e00bd5a9324399f033d8f43a1654aee07f7cfc6596d2
---
# Importance-sampling Pareto dial — trading tight vs giant on the [256] generalist (empirical, RESOLVED — Pareto/nuanced)

## Lineage
- **builds-on:** `04e3221c` (the [256,256] giant-range capacity-knee generalist, GREEN + studio-baseline) — whose remaining weak spot was the **giant** end (seed-mean 0.60). This hop asks: can we buy giant by re-weighting the scale distribution, and at what cost?
- cluster:capacity-budget (sibling of the knee node).

## Hypothesis
The giant end is under-served because uniform-in-radius sampling spends most episodes on smaller courses. **Importance-sampling** the per-episode arena radius toward large courses (`scale_sample_weight < 1`) should raise giant completion — the open question is whether it is a free lunch or a Pareto trade against the tight end.

## Setup (120M steps, seed 0, [256,256], giant range 4.5→18 m; eval DR-off across ARENA_PRESETS)
Only `scale_sample_weight` changes vs the [256] knee baseline:
- **uniform** = 1.0 (the knee node C, seed-mean reference).
- **wt07** `gate_race_general_giant_w256_wt07.yaml`: 0.7 (intermediate dial).
- **bigwt** `gate_race_general_giant_w256_bigwt.yaml`: 0.5 (strong large-course bias).

## Result (lap_completion_rate by scale)
| scale | weight 1.0 (uniform) | weight 0.7 (wt07) | weight 0.5 (bigwt) |
|---|---|---|---|
| tight | 0.941 | 0.861 | 0.785 |
| spread | 0.902 | 0.891 | 0.886 |
| big | 0.839 | 0.828 | 0.886 |
| **giant** | **0.600** | **0.706** | **0.837** |

bigwt(0.5) vs uniform: giant **+0.237**, big +0.047, spread −0.016, tight **−0.155** (crash at giant also drops 0.090e-3).

## Verdict: Pareto / nuanced (no single outcome)
The dial is **clean and monotonic**: every step of large-course bias moves giant up and tight down, with spread/big roughly flat (big even improves). There is **no dominating setting** — it is a genuine operating-point **dial**, not a win:
- **uniform (1.0):** best tight (0.94), weakest giant (0.60) — the studio-baseline default.
- **wt07 (0.7):** balanced — tight 0.86 / giant 0.71.
- **bigwt (0.5):** best giant (0.84) at a real tight cost (0.79).
Pick the weight to match the deployment's course-size distribution. This both **confirms the C diagnosis** (giant was a sampling/capacity allocation issue, now movable) and **bounds it** (you cannot have both ends maxed at [256] capacity — consistent with the [384] turnover: capacity, not data, is the ceiling).

## Action
Configs `gate_race_general_giant_w256_bigwt.yaml` (0.5) + `_wt07.yaml` (0.7) committed; pure-config, no code. Studio-baseline stays the **uniform** [256] generalist (best all-round); the dialed variants are available for large-course-heavy deployments.

## Artifacts
`pareto_dial.csv` (uniform vs bigwt + crash), `pareto_front.csv` (the 1.0/0.7/0.5 frontier), `comparison.png`, `trajectory.png`, `training_curves.png`, `table.csv`, `run.json`, `replay.json.gz` (the bigwt=0.5 variant).

## Reproduce
`uv run python scripts/train.py --config configs/gate_race_general_giant_w256_wt07.yaml` (and `_bigwt`) ; eval DR-off across ARENA_PRESETS vs the uniform [256] knee.

## Stop reason: characterized (Pareto) — the giant↔tight dial is mapped; capacity is the ceiling. Closes the scale-generalist capacity arc. Backlog remaining: hover task + Studio Live (separate clusters).