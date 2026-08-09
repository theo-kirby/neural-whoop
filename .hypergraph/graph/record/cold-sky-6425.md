---
node_id: bfdbedd7-d80d-5ae4-b90e-c18f880fcaf5
slug: cold-sky-6425
title: 'hand_follow (NEW TASK): the EMA precision primitive GENERALIZES to abrupt motion (GREEN) — recovers hold 0.63->0.985 on a jerky zigzag hand'
created_at: '2026-06-28T06:16:51.062620+00:00'
parents:
- flat-waterfall-0121
- old-pond-5686
summary: 'Fifth catalog task + a new motion primitive, testing whether the EMA (validated only on SMOOTH orbit/lissajous, flat-waterfall-0121) survives JERKY motion -- the regime the closed filtering thread (old-pond-5686) flagged as where filter lag should bite hardest. Added KIND_ZIGZAG to target.py (a triangle-wave mover: piecewise-linear with sharp, abrupt direction REVERSALS -- closed-form, the first non-smooth mover, a stand-in for a held hand). hand_follow subclasses target_follow (config_cls hook, reuses the whole detector seam) + close-follows d*=0.8m + adds a follow_hold_rate responsiveness metric. Trained clean / detector / detector+EMA, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT GREEN: (1) the task WORKS -- clean policy follows the jerky hand at hold 0.996 (track_err 0.11, ~0 crash), so abrupt zigzag motion is trackable; (2) detector noise degrades it (hold 0.996->0.630, backs off 0.8->1.05m -- the same robustness<->accuracy back-off as smooth target_follow); (3) the EMA(0.85) primitive RECOVERS it on ABRUPT motion (hold 0.630->0.985, track_err 0.359->0.153, standoff back to ~d*). The lag concern -- that the EMA would fail when the hand suddenly reverses -- did NOT materialize at target_speed 1.8: variance-reduction still outweighs lag. So the EMA is a MOTION-REGIME-ROBUST primitive, not a smooth-motion artifact -- its validated envelope extends to jerky motion. NOTE: caught + fixed a config bug first (the inherited YAML''s motion:mixed/d*:1.5 overrode the new task''s zigzag/0.8 defaults -- the first run silently used smooth motion; verified the instantiated params and re-ran on real zigzag). Code 32d7698 (promoted), 84 pytest green.'
origin:
  backend: flywheel
  node_id: bfdbedd7-d80d-5ae4-b90e-c18f880fcaf5
  slug: cold-sky-6425
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Idea
The filtering thread closed (`old-pond-5686`) with: the EMA is the best simple precision filter, but it was only ever validated on SMOOTH orbit/lissajous motion. The open question it raised: does the EMA survive **abrupt** motion, where its lag should hurt most? `hand_follow` (catalog ⬜ -> ✅) answers it with a new task: close-follow a jerky hand.

## Change
1. **`KIND_ZIGZAG` mover** in `target.py`: per-axis triangle wave `center + amp*(2/pi)*asin(sin(freq*t+phase))` -- piecewise-linear with sharp corners, so velocity flips sign instantly at each peak (an abrupt direction reversal). Closed-form (no per-step state), the first non-smooth mover; `mixed` sampling excludes it (backward-compatible).
2. **`hand_follow` task** (`tasks/hand_follow.py`): subclasses `TargetFollowTask` via a new `config_cls` hook -- reuses the entire obs-v4 + detector seam + EMA/alpha-beta machinery. `HandFollowConfig` defaults: motion=zigzag, d*=0.8m (close follow, not standoff), tighter bell. Adds a `follow_hold_rate` metric (frac of steps within `hold_tol`=0.4 of d* -- a responsiveness measure a policy can only sustain through reversals if it tracks fast).

## Setup
`hand_follow_{clean,det,ema}.yaml`: motion=zigzag, d*=0.8, target_speed 1.8. clean=detector off; det=detector on (3deg/10%/5%/110deg); ema=detector + estimate_ema_alpha 0.85. [128,128]@120M seed 0, eval 2048x1500 seed 12345.

## Results (zigzag hand, d*=0.8m)
| config | follow_hold_rate | track_err (m) | standoff (m) | crash/step |
|---|---|---|---|---|
| clean (no detector) | **0.996** | 0.110 | 0.805 | 7.1e-5 |
| detector (no filter) | 0.630 | 0.359 | 1.052 | 4.4e-5 |
| detector + **EMA 0.85** | **0.985** | 0.153 | 0.845 | 7.4e-5 |

## Findings
1. **The task works** -- the clean policy close-follows the jerky zigzag hand at hold 0.996, standoff 0.805 (≈ d*=0.8), ~0 crash. Abrupt, sharply-reversing motion is trackable by the tiny policy.
2. **Detector noise degrades it** -- hold 0.996->0.630, backs off 0.8->1.05m: the same robustness<->accuracy back-off the smooth `target_follow` showed (`cool-resonance-0983`), milder in absolute terms.
3. **The EMA RECOVERS it on ABRUPT motion** -- hold 0.630->0.985, track_err 0.359->0.153, standoff back to ≈d*. Near-clean tracking restored.
4. **The lag concern did NOT materialize.** I expected the EMA's lag to hurt on sharp reversals (the mechanism behind the speed-envelope `wandering-mode-7957`). At target_speed 1.8 the variance-reduction benefit still dominates -- the EMA is a **motion-regime-robust** primitive, not a smooth-motion artifact.

## Verdict
**GREEN: hand_follow is a working fifth task, and the EMA primitive generalizes from smooth to abrupt motion** (recovers hold 0.63->0.985 under detector noise on a jerky hand). This extends the perception branch's headline result -- the EMA isn't tuned to orbit/lissajous, it's a general detector-precision filter. Code promoted (`32d7698`); `KIND_ZIGZAG` + `hand_follow` + `config_cls` hook + the responsiveness metric land in the repo. 84 pytest green.

## Honesty / limits
Single seed. The lag-vs-variance balance is speed-dependent: a much faster / sharper hand could eventually expose the EMA lag (the `wandering-mode-7957` envelope) -- a clean future sweep (zigzag speed sweep) would map where it finally breaks. Config-bug caught on the way: the inherited `target_follow.yaml` keys (motion:mixed, d*:1.5) overrode the new task's zigzag/0.8 defaults, so the FIRST run silently used smooth motion (a redundant re-test); I verified the instantiated config params and re-ran on the real zigzag before recording -- the numbers above are the corrected run.

## Lineage
- **builds-on** `3db0af65` (flat-waterfall-0121): extends its EMA(0.85) primitive's validated envelope from smooth to abrupt motion.
- **informed-by** `85c7aa87` (old-pond-5686): the filtering-thread close raised 'does the EMA survive abrupt motion?' -- this answers yes.

## Artifacts
hand_follow.png (hold + track_err across clean/det/ema), hand_follow_table.json. Code 32d7698.