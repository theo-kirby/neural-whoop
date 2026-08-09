---
node_id: 3ed4e414-ee32-5f28-9b14-47bdbfa757f3
slug: dawn-hill-4820
title: 'Giant-range generalist (radius->18, 120M): Pareto trade — big/giant up & giant-crash halved, but tight regresses below gate'
created_at: '2026-06-28T15:59:45.828102+00:00'
parents:
- empty-firefly-1882
- sparkling-feather-0123
summary: 'Extends the flat generalist''s scale range 4.5->12 to 4.5->18 (giant in-distribution), same [128,128]@120M net. vs B1: big 0.714->0.774 (now >0.75 target), giant 0.569->0.635, giant crash 0.66->0.34e-3 (halved); BUT tight 0.906->0.844 (below the 0.90 gate) and spread ~flat. Higher mean completion (0.772 vs 0.759) and flatter, but neither dominates. Mixed/Pareto, no GREEN. Pointer stays on B1. Tight regression = capacity-bottleneck signal -> motivates B4 wider net.'
origin:
  backend: flywheel
  node_id: 3ed4e414-ee32-5f28-9b14-47bdbfa757f3
  slug: dawn-hill-4820
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
B1's giant completion (0.57) was pure EXTRAPOLATION — it trained radius 4.5->12 but giant is 18 m. Making giant in-distribution (train the full 4.5->18 range) should lift giant (and big), with an unknown cost to tight/spread from spreading the distribution thinner.

## Setup
- **Policy:** `runs/gate_race_general_giant_s0`, `configs/gate_race_general_giant.yaml` (committed `f53c671`). Identical to B1's `gate_race_general` except `scale_radius_max` 12->18 and crash bounds widened to fit (`bound_xy` 14->22, `bound_z_max` 5->6). Same [128,128]@120M net, same DR, 4096 envs.
- **Eval:** identical `scripts/eval_scales.py` cycled regime (4096 envs, steps 1500, episode_len 600, DR off, gate_radius 0.45, n_gates 5).
- diffaero `291ea14`.

## Results (completion / crash ×1e-3) vs B1 flat generalist
| scale | B1 flat | **B3 giant-range** | Δ compl | crash B1->B3 |
|---|---|---|---|---|
| tight  | 0.906 | **0.844** | **−0.062** | 0.11->0.22 |
| spread | 0.848 | **0.833** | −0.015 | 0.15->0.19 |
| big    | 0.714 | **0.774** | **+0.060** | 0.28->0.22 |
| giant  | 0.569 | **0.635** | **+0.066** | 0.66->0.34 |

Mean completion 0.759 (B1) -> **0.772** (B3); completion spread (max-min) 0.337 -> **0.209** (much flatter). best_lap within ~0.4 s of B1 at every scale (tight 3.25->3.62 s slower, big/giant ~unchanged). Giant crash rate **halved** (0.66->0.34e-3); tight crash roughly doubled (0.11->0.22e-3, still low).

## Verdict / Honesty
**Mixed / Pareto — no GREEN, no pointer move.** B3 is the better LARGE-course flyer (big now clears the 0.75 target, giant +0.066 with half the crashes) and the flatter, higher-mean generalist; B1 is the better TIGHT/spread flyer. Against the contract's GREEN gate (tight>=0.90 ✗ at 0.844, big>=0.75 ✓, giant>=0.55 ✓) B3 FAILS only on tight, so it is not a clean win and does **not** take the `★ studio-baseline` pointer — B1 (`empty-firefly-1882`) holds it. Honesty: single seed (s0) each, so ±0.06-scale deltas should be read as directional, not precise; but the pattern (big/giant up, tight down) is internally consistent and mechanistically expected.

**Key read (the actual finding): this is a capacity bottleneck.** Forcing the SAME [128,128] net to also master giant made it surrender tight — the policy traded in-distribution capacity at one end of the scale range for the other. A bigger net should be able to hold BOTH ends. That is the decisive motivation for B4.

## Lever (next, promoted by this result)
**B4 — wider net on the giant range** (`gate_race_general_giant` geometry + [256,256] hidden). Tests whether added capacity lets one policy hold tight>=0.90 AND big/giant up (a clean GREEN + flatter curve), or whether [128,128] was already sufficient and the tradeoff is fundamental. Deployability caveat: [256,256] (~70k params) is bigger than the ~19k [128,128] MCU target — this is a research probe of the capacity ceiling, not necessarily the shippable policy.

## Lineage
Governed by control `sparkling-feather-0123`; a scale-range variant of the flat generalist `empty-firefly-1882`, measured against it. Sibling to the curriculum NO-GO `orange-pond-7208`. Artifacts: eval_scales.json (decisive), giant_vs_flat.csv, visual pack vs B1 replay.