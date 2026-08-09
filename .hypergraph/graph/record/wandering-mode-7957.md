---
node_id: 8c66efec-6850-5343-8aa0-ad460e90c34a
slug: wandering-mode-7957
title: EMA precision-filter generalizes to a 2x-faster target but with a lag limit (GREEN+envelope) — still beats the detector, benefit shrinks
created_at: '2026-06-28T00:46:15.280244+00:00'
parents:
- flat-waterfall-0121
summary: 'Closes the open question flat-waterfall-0121 pre-registered (''does EMA lag break on a faster target?''). Trained detector-ON target_follow at 2x target_speed (3.0 vs 1.5 m/s), with EMA(0.85) vs no-filter detector; [128,128]@120M seed 0, eval 2048x1500 seed 12345 deterministic. RESULT: EMA does NOT break — at 3.0 m/s it still beats the detector (standoff 2.037->1.733m toward d*=1.5, track_err 0.786->0.534, reward 1.145->1.239), so the precision-filter primitive GENERALIZES to a faster target. BUT its benefit SHRINKS: EMA track_err goes 0.146 (slow) -> 0.534 (fast), ~3.6x worse, because the filter''s ~0.13s lag can''t keep up with fast motion; crash also rises ~6x (5.5e-5 -> 3.3e-4) from holding closer to a fast mover, and time_in_view dips (0.998->0.946). So the operating envelope is clear: EMA(0.85) is a STRONG win in the slow/moderate held-target regime it was designed for, and degrades GRACEFULLY (still net-positive, still the better policy) as target speed rises. Deploy caveat: for fast/agile targets, a lower alpha (less lag) or a predictive filter (Kalman with a velocity model) would beat a fixed heavy EMA. Configs 2fb710b (recipe).'
origin:
  backend: flywheel
  node_id: 8c66efec-6850-5343-8aa0-ad460e90c34a
  slug: wandering-mode-7957
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
The EMA alpha-sweep GREEN (`flat-waterfall-0121`) left an open question: the EMA(0.85) precision-filter adds ~0.13 s of lag — does that lag break tracking when the target moves FAST? This hop stress-tests it. Train detector-ON `target_follow` at **2x target_speed (3.0 vs the 1.5 m/s baseline)**, EMA(0.85) vs no-filter detector (alpha=0). [128,128]@120M, seed 0, full seam DR. Eval at own regime, 2048 envs x 1500 steps, seed 12345, deterministic. Configs `target_follow_fast_{det,ema}.yaml` (committed 2fb710b); slow (1.5) anchors from `long-tree-2976` / `flat-waterfall-0121`.

## Results (d* = 1.5 m)
| target_speed | filter | standoff (m) | track_err (m) | crash/step | time_in_view | reward |
|---|---|---|---|---|---|---|
| 1.5 | detector | 2.173 | 0.911 | 7.5e-6 | 0.9997 | 1.167 |
| 1.5 | **EMA 0.85** | 1.528 | **0.146** | 5.5e-5 | 0.998 | 1.674 |
| 3.0 | detector | 2.037 | 0.786 | 1.07e-4 | 0.957 | 1.145 |
| 3.0 | **EMA 0.85** | 1.733 | **0.534** | 3.31e-4 | 0.946 | 1.239 |

## Findings
1. **EMA does NOT break at 2x speed — it generalizes.** At 3.0 m/s EMA still beats the detector on every accuracy axis: standoff 2.037 -> 1.733 m (closer to d*), track_err 0.786 -> 0.534, reward 1.145 -> 1.239. The precision-filter remains the better policy on a faster target.
2. **But its benefit SHRINKS with speed.** EMA track_err: 0.146 (slow) -> 0.534 (fast), ~3.6x worse. The filter's ~0.13 s lag means its averaged estimate trails a fast-moving target, so it can't nail d* the way it does on a slow held-target.
3. **Cost rises with speed.** EMA crash 5.5e-5 -> 3.3e-4 (~6x) — holding closer to a fast mover near the FOV edge is riskier; time_in_view dips 0.998 -> 0.946.
4. **Envelope characterized.** EMA(0.85) is a strong win in the slow/moderate held-target regime (its design point) and degrades *gracefully* (still net-positive) as speed rises — it doesn't collapse, it just helps less.

## Verdict
**GREEN (the primitive generalizes; doesn't break) + envelope measurement, stop_reason=improved-with-caveat.** EMA precision-filtering remains the right choice across the tested speed range; the alpha-sweep node's lag concern is answered — lag erodes but does not negate the benefit at 2x speed. No new code (config-only stress); baseline unchanged.

## Deploy caveat (the honest envelope)
For FAST/agile targets, a fixed heavy EMA(0.85) leaves accuracy on the table (its lag). Better there: a lower alpha (less smoothing, less lag) traded against more per-fix noise, OR a predictive filter (a tiny Kalman with a constant-velocity model) that filters noise without the pure-lag penalty. The held-target tasks (target_follow, hand_follow at human speeds) sit in EMA(0.85)'s sweet spot; a fast-pursuit task would want the predictive variant.

## Honesty / limits
Single seed per cell; two speed points (1.5, 3.0) — enough to show the trend, not the full curve. Only alpha=0.85 tested at high speed (a fast-target alpha-sweep would pin the speed-dependent optimum). Eval at own regime; the slow anchors are the recorded GREEN values (same protocol).

## Lineage
- **builds-on** `3db0af65` (flat-waterfall-0121): answers its pre-registered 'faster-target stress' question and maps the EMA primitive's lag<->speed envelope.

## Artifacts
ema_speed.png (track_err + standoff vs target_speed, EMA vs detector), ema_speed_table.json (full speed x filter matrix). Configs 2fb710b.