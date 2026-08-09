---
node_id: ed8ae30b-89f8-5c41-8416-1d3984f428fd
slug: wild-waterfall-3546
title: 'Hypothesis: action-history in obs + an action-rate penalty kill the 2.5 Hz delay limit-cycle (the ''shake'')'
created_at: '2026-07-11T17:07:55.354782+00:00'
parents:
- fancy-rice-9295
- polished-band-7171
- lively-cell-6933
summary: 'The wobble decomposition isolated a ~2.5 Hz pitch limit cycle as a delay-induced (delayed-derivative) oscillation, plus latency-tail excursions. SOTA names two documented cures: (a) append the last k≈2-4 actions to the obs — restores Markovness under delay, the standard latency fix, AND supplies the input implicit inertial odometry needs; (b) an action-difference (rate) penalty in the reward — SimpleFlight''s named anti-oscillation lever. Prediction: together they damp the 2.5 Hz shake and shrink the excursions without new hardware. Note: an earlier action-history ''echo'' arm (s8a) went RED, but the CORRECTED mechanism was a train/eval mismatch (sampled vs deterministic echo), not the idea failing — so this must use the deterministic-mean echo in training. Untested.'
origin:
  backend: flywheel
  node_id: ed8ae30b-89f8-5c41-8416-1d3984f428fd
  slug: wild-waterfall-3546
  revision: 1
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f1922ae1-9e92-555b-87c9-1fa2d0535c47
  slug: tight-waterfall-0956
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: a3409d25da0d8dded147dbb135cd2485107f806341bf647175724a906243279d
---
# Hypothesis: action-history + smoothness penalty kill the delay limit-cycle

## Hypothesis
The measured ~2.5 Hz pitch limit cycle (q spikes to ~90°/s) is the classic delayed-derivative oscillation from ~25 ms link + FC + motor delay in the rate loop. Two documented levers should damp it:
1. **Action history in obs** (k≈2-4): restores Markovness under constant delay (Delay-Aware MDP) — at 40-50 Hz, 25 ms ≈ 1-1.25 steps so k=2 suffices — and is simultaneously the input LIO-style implicit odometry uses.
2. **Action-rate penalty**: penalize |a_t − a_{t-1}| in reward; SimpleFlight ('What Matters in Zero-Shot Sim-to-Real', 2024) identifies this as its anti-oscillation cure.

## Setup (planned, 5090)
- The `append_prev_action` env seam already exists (built during the IMU-only campaign). Extend to k>1 and wire the deterministic-mean action (not the sampled action) into the echo, per the s8a correction.
- Add an action-difference reward term; sweep its weight.
- Also: measure TRUE end-to-end latency incl. motor time constant and bracket the action-latency DR to it (motor-delay sysID, arXiv 2404.07837) rather than a generic 0-100 ms.
- Grade: M1-live FFT (does the 2.5 Hz peak shrink?) + bench flight.

## Honesty / risk
s8a (action-history echo) was RED, but the corrected attribution (red-fire-4210) was a sampled-vs-deterministic train/eval mismatch in the echo channel, NOT a PPO collapse — so the deterministic-mean echo is the untried, non-refuted version. s8jit (jitter distribution-matching) was also RED and traded noise robustness; distribution-matching alone doesn't solve the latency×noise interaction. Smoothness + action-history is a different, additive lever.

## Lineage
Parents: roadmap hub (Tier-1.2), the wobble-decomposition measurement (the 2.5 Hz cycle this predicts a fix for), and the first Bench-session node (the link p99 tail / near-LOC excursion it also targets).