---
node_id: 3db0af65-99cc-53fd-89e0-20d291c4ac69
slug: flat-waterfall-0121
title: 'EMA alpha sweep + seed confirm: precision-filter GREEN holds, but alpha=0.85 (not 0.7) is the robust operating point'
created_at: '2026-06-27T23:05:08.686129+00:00'
parents:
- long-tree-2976
summary: 'Confirms and corrects the EMA precision-filter GREEN (long-tree-2976). Alpha sweep {0.5,0.7,0.85} x 2 seeds on detector-ON target_follow, [128,128]@120M, eval 2048x1500 seed 12345 deterministic. FINDINGS: (1) alpha=0.85 is a ROBUST GREEN — BOTH seeds hold d* (1.528 & 1.514m, track_err 0.146, crash 5.5/6.5e-5, reward 1.674/1.684 ~= the clean policy''s 1.688) and dominate the 0.7 point on every axis. (2) alpha=0.7 is SEED-FRAGILE — seed0 lands close (1.543m) but seed1 backs off (2.112m, track_err 0.767); the original single-seed GREEN sat right on the transition. (3) alpha=0.5 is too weak (2.213m, ~= the backed-off detector). So there is a sharp THRESHOLD: the filter must be strong enough (alpha>=~0.85) to reliably pull the policy into the close-standoff basin; below it the per-fix variance still forces back-off and which basin you land in is seed-dependent. NET: the precision-filtering mechanism is CONFIRMED and robust (GREEN), and the recommended operating point is revised 0.7 -> 0.85 (configs/target_follow_ema.yaml default updated, 819ba1b). Honest correction of the earlier single-seed result — mechanism right, alpha was on the knife-edge.'
origin:
  backend: flywheel
  node_id: 3db0af65-99cc-53fd-89e0-20d291c4ac69
  slug: flat-waterfall-0121
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
Follow-up to `long-tree-2976` (the EMA precision-filter GREEN, single seed at alpha=0.7) to (a) confirm it across seeds and (b) find the lag<->variance knee. Alpha sweep `estimate_ema_alpha` in {0.5, 0.85} (0.0=detector anchor and 0.7=the prior GREEN already exist) + a **second seed** of 0.7 and 0.85. Detector-ON `target_follow` (3deg bearing / 10% range / 5% dropout / 110deg FOV), [128,128]@120M, n_envs=4096, full seam DR. Eval each under its own regime, 2048x1500 seed 12345 deterministic. Reward identical throughout; only alpha + train seed vary.

## Results (noisy / own-regime; d* = 1.5 m)
| alpha | seed | standoff (m) | track_err (m) | crash/step | reward | verdict |
|---|---|---|---|---|---|---|
| 0.0 (detector) | 0 | 2.173 | 0.911 | 7.5e-6 | 1.167 | backed off (anchor) |
| 0.5 | 0 | 2.213 | 0.901 | 9.5e-5 | 1.037 | too weak |
| 0.7 | 0 | 1.543 | 0.250 | 8.7e-5 | 1.571 | close (but fragile) |
| **0.7** | **1** | **2.112** | **0.767** | 9.8e-5 | 1.051 | **backed off — FRAGILE** |
| **0.85** | 0 | **1.528** | 0.146 | 5.5e-5 | 1.674 | **GREEN robust** |
| **0.85** | 1 | **1.514** | 0.146 | 6.5e-5 | 1.684 | **GREEN robust** |
| clean (ref) | - | 1.521 | 0.132 | 4.85e-4 | 1.688 | accurate, brittle |

## Findings
1. **alpha=0.85 is a ROBUST GREEN.** Both seeds land at d* (1.514-1.528m, track_err 0.146), crash 5.5-6.5e-5 (well under the racing bar, ~7x safer than clean), reward 1.674-1.684 — essentially matching the clean policy's accuracy AND reward while keeping detector robustness. It dominates the 0.7 point on standoff, track_err, crash and reward.
2. **alpha=0.7 is SEED-FRAGILE.** seed0 1.543m (close) but seed1 2.112m / track_err 0.767 (backed off). The prior single-seed GREEN (long-tree-2976) sat right on the transition — mechanism real, but that specific alpha was a coin-flip. Honest correction.
3. **alpha=0.5 is too weak** — 2.213m, indistinguishable from the backed-off detector. Light filtering doesn't cut per-fix variance enough to change the policy's risk calculus.
4. **There is a sharp THRESHOLD in filter strength.** Below ~0.85 the residual bearing/range variance still makes close standoff unsafe, and which basin (close vs backed-off) the policy converges to is seed-dependent; at/above 0.85 the close-standoff basin is reliably reached. This is the lag<->variance knee: 0.85 (~6-7 step / ~0.13s lag) is strong enough to win and the lag doesn't hurt this slow-follow task.

## Verdict
**GREEN (mechanism robustly confirmed; operating point corrected), stop_reason=improved.** Precision-filtering closes the back-off reliably at alpha=0.85. Recommended default revised 0.7 -> 0.85 (`configs/target_follow_ema.yaml`, committed 819ba1b); sweep configs `target_follow_ema0{5,85}.yaml` kept as the recipe.

## Honesty / limits
2 seeds per alpha (up from 1) — 0.85 confirmed on both, 0.7's fragility caught precisely because of the second seed (the original n=1 GREEN would have stood unchallenged otherwise; this is why the branch's n=1 convention warrants seed-confirm before promoting an operating point). Alpha grid is coarse (0.5/0.7/0.85); the exact threshold between 0.7 and 0.85 isn't pinned, and >0.85 untested (likely fine but more lag). Faster-target stress still unrun (EMA lag could bite a quicker mover).

## Next
- The EMA(0.85) precision-filter is now a confirmed, reusable perception primitive — generalize to other detector-fed tasks (hand_follow, perception-aware swarm).
- Optional: pin the 0.7-0.85 threshold; faster-target_speed stress; >0.85.

## Lineage
- **builds-on** `dc26435a` (long-tree-2976): confirms its precision-filter GREEN across seeds and corrects its recommended alpha (0.7 was seed-fragile -> 0.85 robust).

## Artifacts
alpha_sweep.png (standoff & crash vs alpha, both seeds; the threshold + the fragile 0.7), alpha_table.json (full sweep x2 seeds). Config revision 819ba1b.