---
node_id: 00a0ca61-644b-5381-95d4-652070ae7003
slug: cool-resonance-0983
title: 'target_follow detector-hardening: robust but conservative — buys invariance via back-off, not lost tracking (MIXED/Pareto)'
created_at: '2026-06-27T19:52:46.125909+00:00'
parents:
- tight-limit-5820
- little-feather-5786
summary: 'First empirical perception result (tests idea 96fbd7ef sub-branch a). Trained two target_follow policies, [128,128]@120M, full seam DR, single seed: detector-ON (hardened) vs detector-OFF (oracle-clean control). Eval matrix 2x2 (policy x {clean,noisy} condition), 2048 envs x 1500 steps, seed 12345. VERDICT MIXED (no clean GREEN). (1) ROBUSTNESS CONFIRMED: detector-trained policy is condition-invariant (noisy==clean on every metric) and crashes ~65x less under noise than the naive policy (7.5e-6 vs 4.85e-4 /step). (2) THE PREDICTED GAP DID NOT MATERIALIZE on the headline metric: the oracle-clean policy under detector noise KEEPS the target (time_in_view 0.996, track_err 0.13m) — it does not collapse; detector noise at this level hurts it mainly as a ~21x crash-rate bump (still low absolute). time_in_view is saturated ~1.0 everywhere and does NOT discriminate. (3) COST/PARETO: the hardened policy bought robustness by BACKING OFF to 2.17m vs the 1.5m target (track_err 0.91 vs the clean policy''s 0.08 at 1.52m) and earns LOWER reward (1.17) than the clean policy does under the same noise (1.69) — a conservative high-margin local optimum that sacrifices the standoff objective. Partly a reward-shaping artifact (track_sigma=0.6 wide + flat in_view bonus make excess distance cheap insurance). Single seed; effect sizes large. Commits df0baee (task) + 332c2a6 (control config + gate-less viz fix).'
origin:
  backend: flywheel
  node_id: 00a0ca61-644b-5381-95d4-652070ae7003
  slug: cool-resonance-0983
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
Two `target_follow` policies, identical except the detector seam:
- **detector** = `configs/target_follow.yaml` (DetectorNoise ON: 3-deg bearing, 10% range, 5% dropout, 110-deg FOV)
- **clean** = `configs/target_follow_clean.yaml` (detector identity; all OTHER seam DR — wind/rate/thrust/latency/obs-noise — ON in both)

Both [128,128]@120M, n_envs=4096, seed 0. Eval matrix: each policy x each condition (the condition = which config's DR is applied at eval, so clean-vs-noisy decouples from training), 2048 envs x 1500 steps, seed 12345, deterministic.

## Results (eval matrix)
| policy / condition | time_in_view | track_err (m) | distance (m) | bearing (deg) | crash/step | reward |
|---|---|---|---|---|---|---|
| detector / noisy | 0.9997 | 0.911 | 2.173 | 9.86 | 7.5e-6 | 1.167 |
| detector / clean | 0.9997 | 0.927 | 2.179 | 9.63 | 8.5e-6 | 1.159 |
| clean / noisy | 0.9960 | 0.132 | 1.521 | 20.16 | 4.85e-4 | 1.688 |
| clean / clean | 0.9999 | 0.082 | 1.517 | 19.82 | 2.3e-5 | 1.762 |
(desired standoff d* = 1.5 m; track_err = |distance - d*|.)

## Findings
1. **time_in_view is saturated (~1.0) for both policies in every condition** — the in-view/FOV objective is trivially solved and does NOT discriminate. The informative signals are standoff accuracy (track_err) and crash rate.
2. **Detector-training => condition-invariance (robustness CONFIRMED).** The detector policy is identical noisy-vs-clean on every metric and crashes ~65x less under noise than the naive policy (7.5e-6 vs 4.85e-4 /step). Training through the seam makes the policy indifferent to whether the detector is noisy.
3. **The predicted 'oracle policy collapses under detection error' gap is REFUTED at this noise level.** The clean (oracle-trained) policy under detector noise keeps time_in_view 0.996 and track_err 0.13 m — it does not lose the target. Detector noise's real damage to the naive policy is a ~21x crash-rate increase (2.3e-5 -> 4.85e-4), still low in absolute terms. The honest gap is a reliability (crash) effect, not a tracking effect.
4. **Cost / Pareto: hardening was bought with excess standoff.** The detector policy sits at 2.17 m (track_err 0.91) vs the clean policy's correct 1.52 m (track_err 0.08) — an 11x worse standoff error — and earns LOWER total reward (1.17) than the clean policy achieves under the same noise (1.69). Detector noise acts as a risk pressure the policy answers by increasing margin, settling in a conservative local optimum that sacrifices the actual task objective. Reward-shaping artifact: track_sigma=0.6 is wide and the in_view bonus is flat, so extra distance is cheap insurance.

## Verdict
**MIXED / Pareto (no clean GREEN).** Detector-training delivers real robustness (invariance + 65x fewer crashes under noise) but regresses standoff accuracy 11x and total reward, and the headline 'collapse' gap didn't appear — at this noise level the naive policy is fine on tracking and only pays in crash rate. Honest signal: this needs a reward fix, not a victory lap.

## Artifacts
Eval matrix JSONs (runs/_perception_matrix/*.json), detector-policy-under-noise viz pack (trajectory/fpv/comparison/table) with the clean policy as baseline, both policies' replay.json.gz + ONNX (~19k params). runs/ is gitignored; artifacts attached here.

## Lineage
- builds-on method `7601adfd` (the target_follow implementation).
- tests-idea `96fbd7ef` sub-branch (a) (detector-noise-hardened obs) — partially refutes its 'dominant gap' framing for tracking, confirms it for crash-reliability.

## Next (spawned hypothesis)
Tighten the standoff reward (smaller track_sigma / explicit over-distance penalty / distance-gated in_view bonus) so detector-hardening can't buy robustness by backing off — target a policy that is BOTH robust (crash ~= detector pol) AND accurate (track ~= clean pol). Also: multi-seed confirmation (this is n=1) and a harsher detector regime to find where the naive policy actually does lose the target.