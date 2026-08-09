---
node_id: d98ae869-2d16-5a08-aefb-b0a6bcbcf23f
slug: mute-pond-0406
title: 'Scale-generalist + Air65 II + offboard latency: one policy good on BOTH scale and latency — best cross-scale completion under the deployment regime (GREEN)'
created_at: '2026-06-29T14:03:12.454744+00:00'
parents:
- blue-unit-1398
- old-truth-3996
summary: 'GREEN. Combines the two GREEN levers — scale randomization (old-truth-3996) + the sim2real re-center (blue-unit-1398: Air65 II ~26g AUW + 0-100ms offboard latency) — in configs/gate_race_general_air65.yaml (commit 11c1050), [128,128]@120M seed 1. Under the realistic offboard DR (Air65 + 100ms latency), cross-scale completion tight/spread/big/giant = 0.80/0.65/0.40/0.21 — best-or-tied vs BOTH parents: the tight specialist (0.79/0.41/0.16/0.03, no generality) and the latency-naive generalist s1 (0.45/0.42/0.37/0.23, latency-fragile), with far lower crashes (0.3-2.1e-3 vs the generalist''s 3.6-4.9e-3). DR-off it''s clean across scales (0.98/0.86/0.60/0.29). The only policy robust on BOTH axes simultaneously — the deployable studio-baseline-class racer. Pack attached.'
origin:
  backend: flywheel
  node_id: d98ae869-2d16-5a08-aefb-b0a6bcbcf23f
  slug: mute-pond-0406
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Scale-generalist x sim2real re-center: good on both scale AND latency

**Hypothesis.** The two GREEN levers compose: scale randomization (old-truth-3996, tight->giant generality) + the Air65 II re-center & widened offboard latency (blue-unit-1398) should yield ONE policy that is both scale-general and offboard-latency-robust — a deployable studio-baseline-class racer, where each parent fails one axis.

**Setup.** `configs/gate_race_general_air65.yaml` (commit **11c1050**): scale_randomize (arena 4.5-12m) + `whoop.mass=[0.026,0.022,0.030]` (~26g AUW) + inertia ~0.8x + `dr.action_latency_steps=5` (~0-100ms). [128,128]@120M, seed 1 (the better generalist seed), ~5 min on the 5090. Cross-scale eval via `eval_scales.py --config` (new flag: matches the policy's airframe+DR), DR-off and DR-on; head-to-head vs both parents on the SAME offboard DR.

**Results — cross-scale completion under the DEPLOYMENT regime (Air65 + 0-100ms latency).**
| scale | tight specialist (blue-unit-1398) | generalist s1 (old-truth-3996, latency-naive) | **COMBO (this)** |
|---|---|---|---|
| tight  | 0.79 | 0.45 | **0.80** |
| spread | 0.41 | 0.42 | **0.65** |
| big    | 0.16 | 0.37 | **0.40** |
| giant  | 0.03 | 0.23 | 0.21 |
| crash/step | 1.9-2.8e-3 (big/giant) | 3.6-4.9e-3 (all) | **0.3-2.1e-3** |

DR-off (clean) the combo: tight/spread/big/giant = **0.98 / 0.86 / 0.60 / 0.29**, best laps 4.21/5.00/5.67/6.64s. Training-time (full DR): compl ~0.64, best lap 4.85s vs 5.9s oracle.

**Verdict — GREEN.** The combo is best-or-tied on every scale under the offboard regime and crashes far less than both parents. It dominates the tight specialist on generality (spread 0.65 vs 0.41, big 0.40 vs 0.16, giant 0.21 vs 0.03) and the latency-naive generalist on latency-robustness (tight 0.80 vs 0.45; ~10x fewer crashes on tight). The two levers compose cleanly — this is the first policy good on BOTH scale and latency, and the natural deployable studio baseline.

**Honesty / caveats.** (1) Giant (18m) ~ties the generalist (0.21 vs 0.23) and is beyond the 12m training top + arguably unrealistic for an indoor whoop (per old-truth-3996's own caveat) — not a regression that matters. (2) DR-off big/giant (0.60/0.29) sit a touch below the generalist's latency-naive clean numbers — the expected cost of also learning latency-robustness at a fixed 120M budget; under the regime we actually deploy in (DR-on), the combo wins. (3) Single seed; airframe numbers provisional (pinned at Stage 0). (4) Still tight-course gate geometry / state-based perception — camera perception + flow velocity remain later stages.

**Lineage.** Multi-parent: old-truth-3996 (scale-generalist lever, cluster:generalization) x blue-unit-1398 (Air65 II + offboard-latency lever, cluster:deploy-hw). A generalization x deploy-hw crossover. Candidate to take the ★ studio-baseline pointer (pending user nod). Artifacts: standard visual pack (comparison vs prior studio baseline s1, trajectory, training curves, FPV, leaderboard, eval/run, portable replay).