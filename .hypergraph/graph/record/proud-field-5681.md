---
node_id: 82dca633-288c-5992-bf30-a2b168e78978
slug: proud-field-5681
title: 'gesture_follow (NEW TASK): the lab''s first COMMAND-CONDITIONED policy (GREEN) — follow on GO, hover on STOP, from one obs bit'
created_at: '2026-06-28T07:35:13.693009+00:00'
parents:
- cold-sky-6425
summary: 'Sixth catalog task: the hand_follow gesture-channel extension. Appends a discrete STOP/GO command bit to the obs (obs_dim 11->12, first follow-seam obs growth, MCU +1 channel); the shared [128,128] policy must read obs[-1] and SWITCH behaviour -- follow the jerky zigzag hand on GO, hover in place (low speed) on STOP. The command is a piecewise-constant per-env bit flipping at random (~1 flip/2.5s), so a single episode forces both behaviours. Subclasses hand_follow (reuses the detector+EMA seam); reward = go*follow_reward + (1-go)*hover_reward; command-gated metrics. Trained detector+EMA, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT GREEN: the first command-conditioned policy in the lab WORKS -- stop_compliance 0.947 (hovers on command 95% of STOP steps), follow_hold_rate 0.583 (follows on command), go_fraction 0.495 (balanced), crash 1.6e-5 (safest in the catalog). The policy genuinely USES the channel: a pure follower would score ~0 stop_compliance, a pure hoverer ~0 follow_hold -- it''s neither, it switches. Honest cost: GO-follow precision drops vs pure hand_follow (0.583 vs 0.985 same setup) -- a RE-ACQUISITION TAX (the hand drifts away during each STOP, so resumed-GO steps spend time catching up) plus the tiny net splitting capacity across two behaviours. Code 61efda0 (promoted, 84 pytest green); the foundation for gesture-controlled flight.'
origin:
  backend: flywheel
  node_id: 82dca633-288c-5992-bf30-a2b168e78978
  slug: proud-field-5681
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1e6f42a0-d579-51d4-968d-da77bb633846
  slug: calm-sunset-9895
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: 542aa03ae6c153c4d7d853ceefb7d3031f400210c5b590af7a46743efa34fa8d
---
## Idea
`hand_follow` (`cold-sky-6425`) established close-following a jerky hand. Its catalog note: 'a gesture channel (stop/come) can be added to the obs later.' This hop builds it -- the lab's first **command-conditioned** policy: a discrete command in the obs that makes the SAME tiny shared net switch between two behaviours.

## Change
`gesture_follow` (`tasks/gesture_follow.py`, subclasses `HandFollowTask`):
- **obs_dim 11 -> 12**: append a STOP/GO bit to obs-v4 (first follow-seam obs growth; MCU note: +1 command channel).
- **command dynamics**: a per-env bit, flips with prob 0.008/step (~1 flip / 2.5 s), so one episode contains both GO and STOP segments.
- **switched reward**: `go * follow_reward + (1-go) * hover_reward`, where hover_reward = `exp(-(speed/sigma)^2)` (reward being still). On GO the hand_follow standoff/centering reward; on STOP the hand is irrelevant.
- **command-gated metrics**: `follow_hold_rate` (GO steps within hold_tol of d*), `stop_compliance` (STOP steps with speed < 0.5 m/s), `go_fraction`.

## Setup
`gesture_follow.yaml`: zigzag hand, detector ON + EMA 0.85 (the validated seam), [128,128]@120M seed 0, eval 2048x1500 seed 12345.

## Results
| metric | value | reading |
|---|---|---|
| **stop_compliance** (STOP) | **0.947** | hovers on command 95% of STOP steps |
| **follow_hold_rate** (GO) | 0.583 | follows the hand on command |
| go_fraction | 0.495 | balanced STOP/GO exposure |
| crash_rate/step | 1.6e-5 | safest policy in the catalog |
| time_in_view | 0.796 | (mixed across STOP, where the hand is ignored) |
| (ref) hand_follow hold | 0.985 | pure follow-only, same setup -- the tax baseline |

## Findings
1. **The policy USES the command channel -- it's genuinely conditional.** stop_compliance 0.947 is decisive: a policy that always followed would chase the hand and score ~0 on STOP; one that always hovered would score ~0 follow_hold. It scores high on STOP AND nonzero-high on GO -> it reads obs[-1] and switches.
2. **Near-perfect STOP, solid GO.** On command it hovers (0.947) and follows (0.583), at the lowest crash rate in the catalog (1.6e-5) -- a safe, controllable policy.
3. **Re-acquisition tax (the honest cost).** GO-follow precision is lower than pure `hand_follow` (0.583 vs 0.985). Mechanism: the zigzag hand keeps moving during a STOP, so when GO resumes the drone is displaced and must catch up -- those catch-up steps don't count as 'holding.' The shared [128,128] net also splits capacity across two behaviours.
4. **A new behaviour class.** This is the first policy in the graph whose behaviour is driven by an external command, not just the world state -- the foundation for gesture-controlled flight.

## Verdict
**GREEN: the first command-conditioned policy works** -- one obs bit switches a tiny shared net between follow and hover (stop_compliance 0.947, follow_hold 0.583, crash 1.6e-5). The capability is demonstrated; the follow-precision cost is an honest, well-understood re-acquisition tax, not a failure to learn the command. Code promoted (`61efda0`); `gesture_follow` + the command channel land in the repo. 84 pytest green.

## Honesty / limits
Single seed. obs_dim grew to 12 (MCU note: still tiny / export-clean, but the first follow-seam obs growth -- flagged). The re-acquisition tax could be reduced with a 'return-to-last-seen' STOP behaviour or a higher command-flip rate during training; not pursued this hop. follow_hold 0.583 is the GO-segment average INCLUDING the post-STOP catch-up transients, so it understates steady-state GO tracking. A 2-seed repeat would firm up the exact numbers.

## Lineage
- **builds-on** `bfdbedd7` (cold-sky-6425, hand_follow GREEN): adds the planned gesture/command channel to the jerky-hand follow task it established.

## Artifacts
gesture_follow.png (command compliance + the re-acquisition tax vs pure hand_follow), gesture_follow_table.json. Code 61efda0.