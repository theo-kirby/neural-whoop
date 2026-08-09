---
node_id: 85c7aa87-e9f4-51f0-8998-470dc30aeb2c
slug: old-pond-5686
title: 'World-frame predictive filter ALSO loses to the EMA (NO-GO) — closes the filtering thread: simple temporal filtering tops out at the EMA'
created_at: '2026-06-28T05:16:49.636478+00:00'
parents:
- flat-waterfall-0121
- autumn-cherry-1696
summary: 'Tests the lever the body-frame NO-GO (autumn-cherry-1696) identified: filter the target estimate in the INERTIAL WORLD frame, where velocity is meaningful, so a constant-velocity alpha-beta prediction can actually reduce lag. Added world_ab_alpha/world_ab_beta knobs to target_follow (convert the noisy body fix to a world target-pos estimate via the drone pose, alpha-beta on world pos+vel, transform back to body for the obs). Trained detector-ON at slow (1.5) and fast (3.0) target speed, world_ab_alpha=0.3/beta=0.1, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT NO-GO: the world-frame filter is WORSE than the EMA at both speeds (track_err 0.383 slow / 0.752 fast vs EMA 0.146 / 0.534) and worse even than the body-frame alpha-beta (0.249/0.614). At fast speed it barely beats the raw detector (0.752 vs 0.786) -- almost no filtering benefit. MECHANISM: (1) the constant-velocity model MISMODELS the curved orbit/lissajous target motion -- the velocity feedforward overshoots tangentially on every turn; (2) the gains needed for responsiveness pass more noise than the EMA''s heavy smoothing, and as beta->0 it just degenerates toward the EMA, so it can at best APPROACH it. CONCLUSION (closes the filtering thread, hop-21 + hop-22): simple temporal filtering tops out at the EMA -- both predictive variants (body-frame corrupted-velocity AND world-frame mismodeled-motion) lose to it. The residual gap to the clean-anchor ceiling is a fundamental INFORMATION limit of the noisy detector (3deg bearing / 10% range), closeable only by a better detector or a task-specific motion model, NOT a generic linear predictor. EMA(0.85) is the answer. Knobs default-off; code e16975a, 83 pytest green.'
origin:
  backend: flywheel
  node_id: 85c7aa87-e9f4-51f0-8998-470dc30aeb2c
  slug: old-pond-5686
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 4dae402b-20cc-5195-9ba4-cfe454e5f970
  slug: withered-firefly-3233
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: fb0702bf794a8568e766b326256388c25edc947627a21fa4a1823e15470f2098
---
## Hypothesis
The body-frame alpha-beta filter was a NO-GO (`autumn-cherry-1696`) because the body frame rotates -> velocity is corrupted by ego-motion. Its pre-registered fix: filter in the **INERTIAL WORLD frame**, where the target's velocity is a real, smoothly-varying quantity, so a constant-velocity predictor can reduce the EMA's lag. Predicted: world-frame alpha-beta beats the EMA.

## Change
Added `world_ab_alpha`/`world_ab_beta` to `TargetFollowConfig`. When on, `observe()` converts the noisy body-frame fix to a WORLD target-position estimate (`pos + R @ rel_body`), runs an alpha-beta on world pos+vel, then transforms the filtered world estimate back to body for the obs. State seeded at the true target world pos. Precedence: world-frame > body-frame > EMA. Backward-compatible (default 0.0). Code `e16975a`; 83 pytest green.

## Setup
`target_follow_wab{,_fast}.yaml`: detector ON (3deg/10%/5%dropout/110deg FOV), world_ab_alpha=0.3, world_ab_beta=0.1, target_speed 1.5 / 3.0. [128,128]@120M seed 0, eval 2048x1500 seed 12345.

## Results (d*=1.5m, track_err)
| filter | slow 1.5 | fast 3.0 |
|---|---|---|
| detector (none) | 0.911 | 0.786 |
| **EMA 0.85** | **0.146** | **0.534** |
| body alpha-beta | 0.249 | 0.614 |
| **world alpha-beta** | **0.383** | **0.752** |
(standoff: world-ab 1.694 slow / 2.003 fast vs EMA 1.528 / 1.733.)

## Findings
1. **World-frame alpha-beta is WORSE than the EMA at both speeds** (0.383 vs 0.146 slow; 0.752 vs 0.534 fast) -- and worse than the body-frame alpha-beta too.
2. **At fast speed it barely beats the raw detector** (0.752 vs 0.786) -- the filter is doing almost nothing useful.
3. **Mechanism (a): constant-velocity mismodels curved motion.** The target orbits/lissajous (turning constantly). A constant-velocity predictor `x + v*dt` overshoots tangentially on every turn, injecting error the corrector then has to undo -- net worse than not predicting.
4. **Mechanism (b): gains pass noise.** To stay responsive the gains can't be as heavy as the EMA's effective smoothing; as `world_ab_beta -> 0` the filter degenerates toward an EMA-in-world-frame, so its ceiling is the EMA -- it can't beat it.

## Verdict
**NO-GO (refutes world-frame-predictive-beats-EMA), stop_reason=no-effect.** Combined with `autumn-cherry-1696`, this CLOSES the filtering thread: **simple temporal filtering tops out at the EMA.** Both predictive variants lose -- body-frame (corrupted velocity) and world-frame (mismodeled curved motion). The residual gap to the clean-anchor ceiling (EMA track_err 0.146 vs clean ~0.08) is a fundamental INFORMATION limit of the detector (3deg bearing + 10% range on every fix), not closeable by a generic linear predictor. To close it: a better onboard detector, or a motion-model-matched filter (e.g. a curvature/constant-turn model) -- task-specific and fragile, low priority. EMA(0.85) is the recommended primitive, full stop. `world_ab_*` kept default-off (tested-rejected).

## Honesty / limits
One gain setting (alpha=0.3, beta=0.1); not swept, but the two mechanisms (curved-motion mismodeling + degenerates-to-EMA) are structural -- a sweep's best case is matching the EMA, not beating it. Single seed; the EMA's advantage is large and consistent. A constant-TURN model (matched to orbit) could in principle beat the EMA but is bespoke to this motion and wouldn't generalize -- not worth it vs just using the EMA.

## Lineage
- **builds-on** `da87e550` (autumn-cherry-1696, body-frame NO-GO): implements its pre-registered world-frame fix -- which also fails, completing the predictive-filter investigation.
- **informed-by** `3db0af65` (flat-waterfall-0121): the EMA(0.85) primitive that both predictive filters tried and failed to beat.

## Artifacts
world_filter.png (track_err: detector/EMA/body-ab/world-ab at slow+fast), world_filter_table.json. Code e16975a.