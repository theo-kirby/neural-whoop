---
node_id: 48738153-26ba-5c70-9d57-3ecfccff1a88
slug: wild-bird-1554
title: 'Dual-scale tanh target encoding (PufferLib import): 3.203→3.990 s best lap, +25% — RED for racing'
created_at: '2026-07-02T09:45:41.732376+00:00'
parents:
- dawn-field-3426
summary: 'PufferLib''s dual-scale tanh gate-vector encoding (obs 14→17, faithful 0.1/10.0 scales) on gate_race_air65: best lap 3.203→3.990 s (+24.6% SLOWER), laps/ep −24%, completion +1.1 pt — RED for racing; it''s a hover-precision encoding that kills the speed gradient. Full pack attached.'
origin:
  backend: flywheel
  node_id: 48738153-26ba-5c70-9d57-3ecfccff1a88
  slug: wild-bird-1554
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
PufferLib's dual-scale target encoding — replace the raw body-frame gate vector with [tanh(0.1·v), tanh(10·v)] coarse+fine channels — improves gate precision and therefore lap time on gate_race (idea #1 from the comparison node long-fog-2207).

## Setup
`configs/gate_race_air65_dstanh.yaml` = gate_race_air65 + `task.dual_scale_obs: true` (only knob changed; obs 14→17). Implementation: `tasks/gate_race.py` `dual_scale_obs`/`ds_coarse`/`ds_fine` config fields, encoding applied after detector noise, obs-v4 untouched when off (commit 84f6fc2). 120M steps, seed 0, full DR, same PPO. Eval: standard no-DR pack, seed 12345, n_envs 2048 vs seed-matched parent `runs/gate_race_air65`.

## Results (Δ vs parent baseline gate_race_air65)
- **best_lap_time 3.990 s vs 3.203 s — +24.6% SLOWER** (last lap 3.999 vs 3.246; oracle 3.48)
- laps/episode 0.97 vs 1.27 (−24%); mean reward 0.205 vs 0.290 (−29%)
- lap_completion_rate 93.7% vs 92.6% (+1.1 pt); crash rate 6.6e-5 vs 8.2e-5 per step (−20%)
- Training curve plateaued at ~4.07 s best lap (ep_ret 105 but that reflects more surviving steps, not speed).

## Verdict / Honesty
**RED for time-optimal racing.** The encoding trades away exactly what racing needs: tanh(10·v) saturates beyond ±10 cm (dead gradient at speed), and tanh(0.1·v) compresses long-range distance information the progress reward rides on. The policy flies noticeably safer-but-slower (small completion/crash win). This coheres with where the idea comes from: PufferLib's hover task rewards centimeter station-keeping (their hover EMA dist 4 cm) — it's a precision encoding, not a speed encoding. Faithful-import caveat: scales were PufferLib's (0.1/10.0), not adapted to our 4.5 m arena / 0.45 m gates; a re-scaled variant (e.g. ds_fine≈2) plus keep-raw-channel variant is staged as follow-up but expected marginal for lap time. Possible future use: hover/follow/formation tasks where terminal precision is the metric.

## Lineage
Child of control dawn-field-3426 (PufferLib idea-import experiments). Idea source: analysis node long-fog-2207 idea #1. Code: neural-whoop 84f6fc2 (impl) / 6111e68 (HEAD at eval).