---
node_id: 5a0515b2-9a39-524a-88d9-11c7b4007e42
slug: small-art-6235
title: 'command_follow: the command channel SCALES to a 3-way vocabulary but precision DEGRADES (nuanced) — a tiny net holds 3 behaviours loosely'
created_at: '2026-06-28T08:07:06.964329+00:00'
parents:
- proud-field-5681
summary: 'Tests whether the gesture command channel (gesture_follow, proud-field-5681, 2-way STOP/GO) scales to a VOCABULARY. Built command_follow: a 3-way command STOP/NEAR(d*=0.7)/FAR(d*=1.8) via one obs scalar (obs_dim 12); the same [128,128] net must produce 3 distinct standoffs, switching as the command resamples mid-episode. Subclasses hand_follow; detector+EMA, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT (nuanced, scales-but-degrades): the channel SCALES -- the policy genuinely distinguishes the 3 commands (nonzero near_hold 0.307 AND far_hold 0.255 at NON-OVERLAPPING bands 1.1m apart, which a command-ignoring fixed-distance policy physically cannot do; STOP 0.698; in_view 0.933; crash 2.5e-5) -- BUT per-command precision degrades sharply vs the 2-way gesture_follow (stop 0.947->0.698, follow-modes 0.583->0.25-0.31). A [128,128] net holds a 3-command vocabulary LOOSELY: capacity split 3 ways + COMPOUNDED re-acquisition transients (every command resample jumps the target standoff while the zigzag hand keeps moving, so transients are frequent). Honest counterpoint to the clean 2-way GREEN: command-conditioning is learnable as a vocabulary in principle, but the tiny net''s capacity is the binding constraint on per-command precision. Bigger net / curriculum / longer training is the lever. Task kept as catalog infra (4fc5046, 85 pytest green); marked partial in the catalog.'
origin:
  backend: flywheel
  node_id: 5a0515b2-9a39-524a-88d9-11c7b4007e42
  slug: small-art-6235
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Idea
`gesture_follow` (`proud-field-5681`) proved a tiny policy holds TWO command-conditioned behaviours (STOP/GO) from one obs bit. The discovery question: does the command channel **scale to a vocabulary**? This builds a 3-way command and asks whether the same net can hold three distinct behaviours.

## Change
`command_follow` (`tasks/command_follow.py`, subclasses `HandFollowTask`):
- **3-way command** STOP / NEAR (d*=0.7) / FAR (d*=1.8), encoded as a single obs scalar in {0, 0.5, 1} (obs_dim 12). The command **resamples** to a new random value with prob 0.008/step (not just toggles), so one episode contains all three.
- **switched reward**: STOP -> hover (low-speed bell); NEAR/FAR -> the standoff bell at the respective d*.
- **per-command metrics**: `stop_compliance`, `near_hold` (|d-0.7|<tol), `far_hold` (|d-1.8|<tol).

## Setup
`command_follow.yaml`: zigzag hand, detector ON + EMA 0.85, [128,128]@120M seed 0, eval 2048x1500 seed 12345.

## Results
| command | target | compliance | 2-way ref (gesture_follow) |
|---|---|---|---|
| STOP | hover (speed<0.5) | 0.698 | 0.947 |
| NEAR | d*=0.7 ±0.4 | 0.307 | 0.583 (follow) |
| FAR | d*=1.8 ±0.4 | 0.255 | -- |
| (global) | in_view / crash | 0.933 / 2.5e-5 | -- |

## Findings
1. **The channel SCALES -- the policy reads the 3-way command.** Decisive proof: near_hold (0.307) and far_hold (0.255) are BOTH nonzero, at bands 1.1 m apart (>2x the 0.4 tol). A policy parked at one fixed distance, ignoring the command, could score on at most ONE -> the policy genuinely moves to different standoffs per command. Three distinguishable behaviours emerge.
2. **But per-command PRECISION degrades vs 2-way.** stop 0.947->0.698, follow-type hold 0.583->0.25-0.31. The policy holds each mode loosely (only ~1/4-1/3 of steps within tolerance).
3. **Mechanism: capacity + compounded re-acquisition transients.** The [128,128] net splits across 3 behaviours; and because the command RESAMPLES (not toggles), the target standoff jumps frequently while the zigzag hand keeps moving -> more, larger re-acquisition transients than the 2-way (the same tax `proud-field-5681` flagged, worse with 3 modes).
4. **Still safe.** crash 2.5e-5, in_view 0.933 -- the policy tracks and stays safe throughout, it just doesn't hold the precise standoff.

## Verdict
**Nuanced (scales-but-degrades, no single outcome): a command vocabulary is learnable in principle -- 3 distinct behaviours emerge -- but a tiny [128,128] net holds it LOOSELY (per-command hold ~0.25-0.70 vs the 2-way's 0.58-0.95).** The binding constraint is the tiny net's capacity + compounded transients, not a failure to read the command. An honest counterpoint to the clean 2-way GREEN. The lever to tighten precision: a bigger net, a curriculum (grow the vocabulary), or longer training -- a capacity-budget question. Task kept as catalog infra (`4fc5046`); marked partial.

## Honesty / limits
Single seed. hold_tol 0.4 m is demanding for a 3-way conditional; a looser tol would raise the numbers but the 2-way-vs-3-way GAP (the real finding) is tol-robust. follow-mode holds include the frequent post-resample transients, so they understate steady-state per-command precision. I did NOT scale the net (MCU-locked) -- so this is the capacity limit AT the deploy size, which is the honest deployable answer; a larger net is a non-MCU research lever, not a whoop policy.

## Lineage
- **builds-on** `82dca633` (proud-field-5681, gesture_follow GREEN): scales its 2-way command channel to a 3-way vocabulary -- which works but loosely.

## Artifacts
command_follow.png (3-way compliance vs the 2-way reference lines), command_follow_table.json. Code 4fc5046.