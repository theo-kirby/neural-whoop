---
node_id: c24fe7be-f05b-5b80-aacf-d878b0a95d46
slug: royal-wildflower-3231
title: 'Tighter standoff reward REFUTED (RED): detector back-off is a real robustness↔accuracy frontier, not a reward artifact'
created_at: '2026-06-27T21:22:31.593367+00:00'
parents:
- cool-resonance-0983
- old-leaf-3989
summary: 'Tests hypothesis old-leaf-3989. Retrained the detector-ON target_follow policy with a tightened standoff reward (track_sigma 0.6->0.35 + new over_distance_penalty=0.5 taxing d>d*), [128,128]@120M, same detector seam, single seed; eval matrix vs the prior detector/clean policies (2048 envs x 1500 steps, seed 12345). REFUTED. The tight reward only nudged the converged standoff from 2.17m -> 1.97m (track_err 0.911 -> 0.789, ~13%) — nowhere near the clean policy''s 1.52m / 0.13m — and paid for even that modest gain with an ~8x crash-rate increase (7.5e-6 -> 5.76e-5) AND a time_in_view drop (0.9997 -> 0.967). Hits the pre-registered refutation exactly: accuracy is only recovered by regressing crash-robustness. CONCLUSION: the detector-trained back-off is a GENUINE robustness↔accuracy tradeoff forced by the detector (5% dropout + 110-deg FOV + bearing/range noise make close standoff unsafe to hold), NOT a reward-shaping artifact. You move ALONG the frontier (clean-trained = accurate+brittle at 1.52m/4.85e-4; detector-trained = robust+loose at 2.17m/7.5e-6; tight = a middle point 1.97m/5.8e-5), you don''t beat it with the standoff term — the same lesson as the racing tight<->big Pareto. The lever to actually close it is the detector regime / perception quality (wider FOV, less dropout) or temporal memory/filtering + an explicit risk budget, not reward weights. Commit ffb466b.'
origin:
  backend: flywheel
  node_id: c24fe7be-f05b-5b80-aacf-d878b0a95d46
  slug: royal-wildflower-3231
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: e9da5a38-6b08-504a-a8e3-2b6033c5518a
  slug: red-mouse-9483
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 0713b848dc5f7e02b45f909b7141ccda74a9a0d791bf9573f2b94d236914a33b
---
## Setup
Retrained `target_follow` detector-ON with a tightened standoff reward (`configs/target_follow_tight.yaml`): `track_sigma` 0.6->0.35 (sharper peak) + new `over_distance_penalty=0.5` (linear tax on d > d*). Identical otherwise (detector seam, [128,128], 120M, full DR, seed 0). Eval matrix vs the prior policies, 2048 envs x 1500 steps, seed 12345, deterministic.

## Results (+ prior policies for comparison)
| policy / condition | time_in_view | track_err (m) | distance (m) | crash/step | reward |
|---|---|---|---|---|---|
| **tight / noisy** | 0.967 | **0.789** | **1.972** | **5.76e-5** | 1.191 |
| tight / clean | 0.982 | 0.786 | 1.978 | 5.47e-5 | 1.196 |
| detector / noisy (prior) | 0.9997 | 0.911 | 2.173 | 7.5e-6 | 1.167 |
| clean / noisy (prior) | 0.996 | 0.132 | 1.521 | 4.85e-4 | 1.688 |
(d* = 1.5 m; track_err = |distance - d*|.)

## Findings
1. **The strong hypothesis is REFUTED.** The pre-registered bar was track_err ~= clean (0.13 m) WHILE crash ~= detector (~1e-5). The tight policy lands at track_err 0.789 / crash 5.76e-5 — it does not get close to the clean corner on accuracy, and its accuracy gain came with a robustness loss.
2. **The over_distance_penalty + tighter sigma DID bite, but only modestly:** standoff 2.173 -> 1.972 m (the 3M smoke had already shown the pull, 2.17 -> 1.80). The policy chooses to stay ~0.47 m beyond d* despite a 0.5/step linear penalty there — i.e. the expected return of holding 1.5 m under the noisy detector is *lower* than staying back, even with the penalty.
3. **It only recovered accuracy by spending robustness** (crash 7.5e-6 -> 5.76e-5, ~8x; time_in_view 0.9997 -> 0.967) — the exact pre-registered refutation clause. The back-off is a GENUINE risk/accuracy tradeoff imposed by the detector (dropout + finite FOV + bearing/range error make a close, near-FOV-edge target dangerous to hold on stale fixes), NOT a reward artifact.
4. **It's a Pareto frontier, slid not beaten.** Three points on one robustness<->accuracy<->in-view frontier: clean-trained (accurate+brittle, 1.52 m / 4.85e-4), detector-trained (robust+loose, 2.17 m / 7.5e-6), tight (middle, 1.97 m / 5.76e-5). Same structural lesson as the racing tight<->big Pareto (curriculum/importance-weighting also only slid along it).

## Verdict
**RED / refuted (stop_reason=no-effect on the joint bar).** Reward-shaping cannot make a detector-trained follower both clean-accurate and detector-robust at this noise level; the frontier is set by the perception, not the reward. Baseline unchanged; `over_distance_penalty` kept as a default-off tested reward primitive (committed ffb466b) and the tight config retained as the reproducible RED recipe.

## Next (the lever that's actually left)
To move the frontier (not along it): (a) improve perception in-sim — wider FOV / lower dropout, or temporal memory/filtering (a small recurrent/eligibility state, or feeding detection confidence) so close standoff stays safe under dropout; (b) an explicit risk budget / CVaR objective rather than a distance penalty; (c) characterize the frontier by sweeping the detector regime (dropout/FOV) to map where close standoff becomes feasible. Plus multi-seed confirmation (n=1).

## Lineage
- tests-hypothesis `a4497e46` (which it refutes).
- builds-on `00a0ca61` (the detector/clean policies it compares against).