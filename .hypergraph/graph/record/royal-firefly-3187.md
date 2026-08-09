---
node_id: 8403a22c-8ed4-528f-b6ed-efa3163caa17
slug: royal-firefly-3187
title: 'DR-on reliability re-measured: completion 0.92->0.80 at the 120M baseline — reliability is now the binding constraint (measurement)'
created_at: '2026-06-26T16:22:28.579591+00:00'
parents:
- shrill-limit-5398
summary: 'RESOLVED, measurement hop (stop_reason=measured). Re-measured the [128,128]@120M baseline with seam DR ENABLED (wind/rate-gain/thrust/latency/obs-noise), the realistic deployability condition. DR-on multi-seed n=3: best_lap 2.665s (vs DR-off 2.600s, only ~2.5% slower — SPEED is DR-robust) but completion DROPS 0.919->0.804 and crash/step ~2.7x (1.7e-4->4.6e-4), with large seed spread (s0 0.891 vs s1/s2 0.75-0.77). Much better than hop-3''s old-baseline DR-on 0.68 (the bigger+longer-trained net hardened robustness too), but RELIABILITY — not lap-time — is now the binding deployability constraint. Pivots the frontier from speed to robustness. No code change.'
origin:
  backend: flywheel
  node_id: 8403a22c-8ed4-528f-b6ed-efa3163caa17
  slug: royal-firefly-3187
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 47b7761e-0983-5df4-931f-9aacc3c9c460
  slug: jolly-shape-9257
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 7eadcfd430da83d1e50731425dc77200d20d650d1f03d9dc46c0502d77d64a73
---
# Hop-9 — DR-on reliability at the [128,128]@120M baseline (RESOLVED, measurement hop)

## Lineage
- **builds-on:** `8db85abb` (shrill-limit-5398, hop-8, [128,128]@120M, DR-off best_lap 2.600s / completion 0.919). This is the first DR-on re-measurement since hop-3 flagged DR-on completion ~0.68 at the *old* [64,64]@40M baseline — never re-checked after the capacity (hop-6) + training-budget (hop-7/8) wins.

## Hypothesis / question
Single-drone PPO racing has hit its practical speed floor (sf ~0.89; budget/capacity/reward/exploration all exhausted). The honest next question is **deployability under the seam DR the policy actually trains against**: does the new baseline still lose reliability when wind/rate-gain/thrust-scale/action-latency/obs-noise are active? hop-3's 0.68 was the last datapoint, on a much weaker policy.

## What was run (no training; eval 2048x1500, seed 12345)
Evaluated the three 120M [128,128] training seeds with **DR ENABLED** (config `dr` block: wind 1.5 m/s², rate-gain 15%, thrust 10%, action-latency 1 step, obs-noise 0.01) and compared against the identical-protocol DR-off hop-8 numbers.

| seed | DR | best_lap (s) | completion | crash/step | sf (feasible 2.324) |
|---|---|---|---|---|---|
| s0 | off | 2.501 | 0.938 | 1.5e-4 | 0.929 |
| s0 | **on** | 2.561 | **0.891** | 2.8e-4 | 0.908 |
| s1 | off | 2.655 | 0.902 | 2.1e-4 | 0.875 |
| s1 | **on** | 2.722 | **0.754** | 5.7e-4 | 0.854 |
| s2 | off | 2.644 | 0.917 | 1.6e-4 | 0.879 |
| s2 | **on** | 2.712 | **0.768** | 5.2e-4 | 0.857 |
| **multi-seed off** | | **2.600** | **0.919** | 1.7e-4 | 0.894 |
| **multi-seed on** | | **2.665** | **0.804** | 4.6e-4 | 0.872 |

## Verdict (measurement): speed is DR-robust; reliability is the binding constraint
- **Speed survives DR.** best_lap 2.600 → 2.665 s (~2.5% slower under the full seam DR) — the flown line barely changes; the policy holds its pace through wind/latency/noise.
- **Reliability does not.** completion **0.919 → 0.804**, crash/step **~2.7×** (1.7e-4 → 4.6e-4), and the seed spread blows out (s0 0.891 vs s1/s2 ~0.76). One in five laps is lost under realistic disturbances, and which seed you trained matters a lot.
- **But the trend is up.** hop-3 measured DR-on completion **0.68** on the old [64,64]@40M policy; the bigger ([128,128]) and longer-trained (120M) baseline pulls that to **0.80** — capacity+budget hardened robustness as a side effect, not just speed. The residual gap is real but smaller than it was.

**Conclusion:** the deployability bottleneck has moved. Lap-time is near its floor *and* DR-robust; **reliability under the seam (completion/crash) is now the metric that matters** for putting this on the real ~32 g whoop.

## Artifacts
`hop9_summary.json` (full DR-on vs DR-off per-seed + multi-seed table); DR-on trajectory of the s0 hero; DR-on-vs-DR-off comparison.png; DR-on s0 aggregate eval json; per-seed leaderboard table.json; portable DR-on replay (`replay_dron.json.gz`, kept separate from the canonical DR-off baseline replay). Measurement hop — no training_curves, no code change (per convention 5).

## Stop reason: measured (reliability gap quantified)

## Next frontier (replan — n=1)
Reliability is the new frontier (decision metric shifts to **DR-on completion UP / crash DOWN**, lap-time as guardrail). Candidate hop-10 directions: (a) **harden robustness** — DR curriculum (ramp wind/latency/noise over training) and/or a reliability-weighted reward (penalize near-misses), retrain [128,128]@120M, re-measure DR-on completion; target >0.90 DR-on without losing the 2.6s pace; (b) **latency-aware / history policy** — the action-latency-1 seam is a known completion killer; a short obs history or explicit latency compensation may recover most of the gap at tiny MCU cost; (c) **pivot to the first n_agents>1 SWARM task** — the other half of the objective, if racing reliability is deemed 'good enough' at 0.80. Recommend (a)/(b) first: the reliability gap is now quantified and directly actionable, and hardening the single-drone policy is a prerequisite for trustworthy swarms.