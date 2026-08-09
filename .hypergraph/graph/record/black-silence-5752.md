---
node_id: 0ee38197-aab6-5360-8717-c3a19fb171ed
slug: black-silence-5752
title: 'Muon optimizer on gate_race_air65: 3.203→2.461 s best lap (−23%) at lr 2.5e-3 — big speed win, completion −6.6 pt'
created_at: '2026-07-02T09:52:01.619420+00:00'
parents:
- dawn-field-3426
summary: 'Muon (PufferLib port) vs Adam on gate_race_air65 at equal 120M steps: best lap 3.203→2.461 s (−23%, lr 2.5e-3; −11% at lr 1e-2), laps/ep +28%, mean reward +45% — but completion 92.6→86.0% and 4× crash rate. Strong speed Pareto shift, mixed verdict; staged follow-up: Muon + reliability shaping. Packs attached.'
origin:
  backend: flywheel
  node_id: 0ee38197-aab6-5360-8717-c3a19fb171ed
  slug: black-silence-5752
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
Swapping Adam for Muon (Newton-Schulz orthogonalized momentum, PufferLib idea #3 from long-fog-2207) improves gate_race training at equal steps — PufferLib trains its whole drone suite on Muon.

## Setup
`training/muon.py` ported from PufferLib 4.0 (MIT) + `ppo.optimizer: adam|muon` knob (commit 84f6fc2). Two single-knob forks of gate_race_air65 (Adam lr 3e-4 baseline): `gate_race_air65_muon25` (lr 2.5e-3, Muon's default) and `gate_race_air65_muon100` (lr 1e-2, near PufferLib's swept 9.5e-3). 120M steps, seed 0, full DR, linear lr anneal retained. Eval: standard no-DR pack (seed 12345, n_envs 2048) vs seed-matched parent `runs/gate_race_air65`.

## Results (Δ vs baseline: best lap 3.203 s, completion 92.6%, laps/ep 1.27, crash 8.2e-5, reward 0.290)
| variant | best lap | Δ | completion | laps/ep | crash/step | mean reward |
|---|---|---|---|---|---|---|
| muon lr 2.5e-3 | **2.461 s** | **−23.2%** | 86.0% (−6.6 pt) | 1.63 (+28%) | 3.4e-4 (4.1×) | 0.421 (+45%) |
| muon lr 1e-2 | 2.858 s | −10.8% | 88.3% (−4.3 pt) | 1.51 (+19%) | 1.8e-4 (2.2×) | 0.339 (+17%) |

Training-time best_lap at end of run: 2.82 s (muon25) — the eval-course best of 2.461 s is the fastest lap this task family has produced to date (prior record ~2.9 s class).

## Verdict / Honesty
**Large Pareto shift toward speed, not a clean GREEN.** Both Muon lrs dominate baseline on lap time, laps/episode and mean reward at equal steps; both pay reliability (completion −4–7 pt, crash rate 2–4×). Under this control run's pre-registered criterion (lap improves AND completion not degraded) neither variant strictly passes — so no outcome tag; recording as a strong mixed result. The speed magnitude (−23%) is far beyond typical reward-shaping deltas in this graph, so the follow-up is obvious and staged: **Muon lr 2.5e-3 + reliability shaping (boundary_penalty / crash_penalty bump) to buy completion back** — if even half the speed survives, that's a new studio-baseline candidate. Caveats: single seed; lr grid of 2; reliability cost may partly be the aggressive-flight consequence of faster policies rather than optimizer noise.

## Lineage
Child of control dawn-field-3426. Idea source: analysis node long-fog-2207 idea #3 (PufferLib trains on Muon; their muon.py is the port source). Code: 84f6fc2; HEAD at eval 6111e68. Artifacts: full muon25 pack + muon100 eval/comparison.