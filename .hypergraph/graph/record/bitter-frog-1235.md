---
node_id: ae3fa47c-d84f-5514-951e-084618a7d03a
slug: bitter-frog-1235
title: 'State of the frontier: current best per cluster, exhausted levers, open directions (synthesis)'
created_at: '2026-06-28T11:47:42.401300+00:00'
parents:
- morning-base-2167
- shrill-limit-5398
- old-truth-3996
- summer-wave-6268
- rapid-union-8239
- small-art-6235
summary: 'Navigational synthesis (multi-parent onto each cluster''s current best). Current best: reward-shaping time_penalty 3.185s (-18% vs the first baseline, but ~37% honest-oracle headroom remains); capacity/budget 120M knee 2.60s; generalization scale-generalist (big 0.49->0.72, giant 0.21->0.50); swarm 24-drone ring formation (flat GREEN, ~8x racing''s n=3 shared-track ceiling); perception EMA filter generalizes to hand_follow (hold 0.63->0.985) + a 3-way command vocabulary. Exhausted levers (don''t re-run): reward-weight tuning, ent_coef exploration, DR curriculum, reliability reward, latency frame-stacking, scale curriculum + importance weighting (tight<->big is budget/capacity-bound, not a sampling artifact), shared-track swarm scaling past n=3, and predictive filters (all top out at the EMA). Open frontier: differentiable control (SHAC/BPTT) for the racing headroom, more budget/capacity to dominate the generalization Pareto, perception-aware swarm scaling, and the real objective -- MCU hardware deployment.'
origin:
  backend: flywheel
  node_id: ae3fa47c-d84f-5514-951e-084618a7d03a
  slug: bitter-frog-1235
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
# State of the frontier (synthesis / navigational anchor)

A multi-parent "what won and why" map across the active clusters, parented on each cluster's current best result. Created as part of the conventions upgrade (the cardinal rule: no empty nodes; see CLAUDE.md / docs/FLYWHEEL.md). Honest snapshot as of commit 92384b1.

## Current best per cluster
- **reward-shaping** (`e4a66478` time_penalty=0.05): best_lap 3.185s (-18% vs the first baseline 3.87s), beats the old path-length oracle. But the honest dynamically-feasible oracle (`bd57f350`) shows **~37% lap-time headroom REMAINS**.
- **capacity-budget** (`8db85abb` 120M knee): [128,128]@120M -> ~2.60s multi-seed (capacity unlocked ~12%; the training-budget knee is at 120M, 160/200M are flat).
- **generalization** (`b4c3466f` scale-generalist, the current studio-baseline): one [128,128]@120M policy trained across course scales -> big 0.49->0.72, giant 0.21->0.50, for a modest tight tax 0.95->0.88.
- **reliability-dr** (`8403a22c`): DR-on completion 0.80 is the binding reliability constraint at the 120M baseline.
- **swarm** (`e3519636` formation N-scaling): ONE tiny shared policy holds a 24-drone ring formation flat (GREEN) -- own-slot formation is the scalable swarm regime (~8x racing's n=3 shared-track ceiling).
- **perception / follow** (`c92c91db` hand_follow envelope, `5a0515b2` command_follow): the EMA precision filter closes the detector back-off and generalizes to abrupt motion (hold 0.63->0.985), with the benefit vanishing ~4.5 m/s; the command channel scales to a 3-way STOP/NEAR/FAR vocabulary (precision degrades, held loosely by a tiny net).

## Exhausted levers (RED / NO-GO -- don't re-run)
- **Racing speed**: reward-weight tuning saturated (`5fcc1b12`); PPO exploration / ent_coef moves the WRONG way (`08c0c825`); racing-line reward reward-hacks (`0238f7d7`). The ~37% headroom is a CONTROL / algorithm limit, not a reward or exploration one.
- **DR reliability**: DR curriculum REFUTED (`fe78365c`); reliability-weighted reward NO-GO (`7a7e6be5`); latency frame-stacking NO-GO (`35f51233`).
- **Generalization**: scale curriculum is a Pareto shift, not a free win (`fc3019c1`); scale-importance weighting REFUTED (`b4681823`) -- the tight<->big tradeoff is BUDGET/CAPACITY-bound, not a course-sampling artifact (two distribution-reshaping levers both failed to beat the frontier).
- **Swarm**: shared-track racing completion collapses super-linearly past n=3 (`0bd2cc36`); relaxing shared-fate doesn't lift it (`ffc5d9e4`).
- **Filtering**: predictive alpha-beta (`da87e550`) and world-frame predictive (`85c7aa87`) both lose to the EMA -- simple temporal filtering tops out at the EMA.

## Open frontier
- **Differentiable control (SHAC/BPTT)** or a finer action representation to attack the ~37% racing headroom (the standing control-limit conclusion from `08c0c825`).
- **More budget/capacity** within the MCU param envelope to actually DOMINATE the generalization Pareto rather than slide along it.
- **Perception-aware swarm**: noisy anchor detection degrades + destabilizes formation across N (`c31b8155`, multi-seed confirmed) -- recover the clean flat-scaling the noise-free version has.
- **Hardware deployment** (`a30d17a6` / `099aa301`): the actual objective -- get a tiny policy onto the ~32 g whoop MCU (RC-stick into Betaflight vs CTBR act-v2).
- **Honest camera-only perception eval** (deferred -- Blackwell tiled-camera path).