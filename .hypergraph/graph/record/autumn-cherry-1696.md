---
node_id: da87e550-54e7-59de-a464-2512353fa1dd
slug: autumn-cherry-1696
title: 'Predictive alpha-beta filter does NOT beat the EMA (NO-GO): body-frame velocity tracking is ill-posed; the EMA''s frame-robust smoothing wins'
created_at: '2026-06-28T04:39:51.507134+00:00'
parents:
- flat-waterfall-0121
- wandering-mode-7957
summary: 'Tests the lever the perception nodes kept pointing to: a PREDICTIVE filter (constant-velocity alpha-beta / steady-state Kalman) that tracks velocity and predicts one step ahead, to beat the EMA''s lag<->variance tradeoff (wandering-mode-7957) and recover more of the clean ceiling. Added ab_alpha/ab_beta knobs to target_follow (alpha-beta replaces the EMA when on; backward-compatible default-off). Trained detector-ON at slow (1.5) and fast (3.0) target speed, ab_alpha=0.2/ab_beta=0.05, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT NO-GO: alpha-beta is WORSE than EMA(0.85) at BOTH speeds -- track_err slow 0.249 vs EMA 0.146, fast 0.614 vs EMA 0.534; standoff slightly worse too (1.533 vs 1.528 slow, 1.810 vs 1.733 fast). It does not even win on the FAST target where its velocity-prediction was supposed to help. MECHANISM (the real finding): the filter tracks velocity in the ROTATING BODY frame, so the velocity it feeds forward is corrupted by the drone''s own rotation/translation -- not a clean target velocity. Predicting with a garbage velocity adds error instead of removing lag. The EMA''s apparent weakness (position-only, no prediction) is its STRENGTH: it is frame-rotation-robust. As ab_beta->0 the alpha-beta degenerates toward the EMA, so a body-frame predictor can at best APPROACH, never beat it. The real lever to beat the EMA is INERTIAL/world-frame filtering (filter in world, transform to body) -- a bigger change. EMA(0.85) remains the recommended precision primitive; ab knobs kept default-off (tested-rejected). Code 96fb55a; 83 pytest green.'
origin:
  backend: flywheel
  node_id: da87e550-54e7-59de-a464-2512353fa1dd
  slug: autumn-cherry-1696
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
The EMA precision primitive trades lag for variance-reduction and leaves a residual per-fix penalty (`wandering-mode-7957`: its benefit shrinks on fast targets due to lag; `mute-block-8299`: deployable formation stuck below the clean ceiling). A **predictive** filter -- a constant-velocity **alpha-beta** filter (steady-state Kalman) that tracks the estimate AND its velocity and predicts one step ahead -- should smooth the noisy detector fix WITHOUT the EMA's pure-lag penalty, especially on a moving target. Predicted: alpha-beta beats EMA, most on the fast target.

## Change
Added `ab_alpha` (position gain) + `ab_beta` (velocity gain) to `TargetFollowConfig`. When `ab_alpha>0`, `observe()` runs the alpha-beta predictor-corrector in place of the EMA (predict `x+v*dt`, correct toward the measurement, update velocity); obs-v4 stays length 11. Backward-compatible (default 0.0). Code `96fb55a`; 83 pytest green.

## Setup
`target_follow_ab{,_fast}.yaml`: detector ON (3deg/10%/5%dropout/110deg FOV), ab_alpha=0.2, ab_beta=0.05, target_speed 1.5 (slow) and 3.0 (fast). [128,128]@120M seed 0, eval 2048x1500 seed 12345. Refs: EMA(0.85) and raw detector from `long-tree-2976`/`flat-waterfall-0121`/`wandering-mode-7957`.

## Results (d*=1.5m)
| target | filter | standoff (m) | track_err (m) | reward |
|---|---|---|---|---|
| 1.5 | detector | 2.173 | 0.911 | 1.167 |
| 1.5 | **EMA 0.85** | 1.528 | **0.146** | 1.674 |
| 1.5 | alpha-beta | 1.533 | 0.249 | 1.559 |
| 3.0 | detector | 2.037 | 0.786 | 1.145 |
| 3.0 | **EMA 0.85** | 1.733 | **0.534** | 1.239 |
| 3.0 | alpha-beta | 1.810 | 0.614 | 1.195 |

## Findings
1. **Alpha-beta is WORSE than EMA at both speeds.** track_err 0.249 vs 0.146 (slow), 0.614 vs 0.534 (fast); standoff and reward also slightly worse. The predictive filter loses even on the FAST target where velocity-tracking was meant to help.
2. **Mechanism: body-frame velocity is ill-posed.** The filter tracks velocity in the body frame, which ROTATES (the drone yaws/translates each step). So the estimated 'velocity' mixes the target's motion with the drone's own ego-motion -- predicting `x + v*dt` with that corrupted v adds error rather than removing lag.
3. **The EMA's simplicity is a feature.** Position-only smoothing is frame-rotation-robust; it doesn't try to extrapolate, so it can't be corrupted by ego-motion. As `ab_beta -> 0` the alpha-beta degenerates toward the EMA, so a body-frame predictor's ceiling is the EMA -- it cannot beat it.
4. **The real lever is inertial-frame filtering.** To predict meaningfully you must filter the target estimate in an INERTIAL/world frame (then transform to body for the obs). That's a bigger estimator change (track world-frame target pos+vel through the detector); a worthwhile but heavier future hop.

## Verdict
**NO-GO (refutes the predictive-filter-beats-EMA hypothesis), stop_reason=no-effect.** A naive body-frame predictive filter does not beat the EMA; EMA(0.85) remains the recommended precision primitive. `ab_alpha`/`ab_beta` kept default-off as tested-rejected infra (+ the reproducible NO-GO recipe). The honest lesson: the EMA's frame-robustness is why it works; closing the residual gap needs world-frame filtering, not a fancier body-frame one.

## Honesty / limits
One gain setting (alpha=0.2, beta=0.05); other gains were not swept, but the mechanism (body-frame velocity corruption) is structural -- better gains move it toward EMA-like behaviour, not past it, so a sweep wouldn't change the conclusion. Single seed; the EMA-vs-alpha-beta gaps are modest but consistently in EMA's favour at both speeds.

## Lineage
- **builds-on** `3db0af65` (flat-waterfall-0121): tries to beat its EMA(0.85) precision primitive with a predictive filter -- and fails.
- **informed-by** `8c66efec` (wandering-mode-7957): its EMA-lag speed-envelope motivated the predictive attempt.

## Artifacts
alphabeta.png (track_err: detector vs EMA vs alpha-beta at slow/fast), alphabeta_table.json. Code 96fb55a.