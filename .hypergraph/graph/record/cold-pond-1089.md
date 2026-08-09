---
node_id: 92a180c8-769f-55c1-ad64-72e32672f084
slug: cold-pond-1089
title: 'Stack capacity + training: [128,128] @ 80M -> 2.72s (~6.6%) + completion 0.83->0.93 (GREEN)'
created_at: '2026-06-26T13:54:30.149116+00:00'
parents:
- sparkling-limit-8154
summary: 'RESOLVED GREEN / improved. Stacked the two hop-6 levers (bigger net + longer training). [128,128] @ 80M multi-seed n=3: best_lap mean 2.715s (2.687/2.594/2.864) vs the [128,128]@40M parent 2.907s (~6.6%), with completion JUMPING 0.827->0.930 and shrinking variance -- longer training both speeds up AND stabilizes/completes. 120M (seed0) continues to 2.501s / completion 0.939 (~93% of the honest feasible-oracle pace 2.324), so the training-budget curve has not flattened. Cumulative since [64,64]@40M: 3.289->2.715s (~17%) with completion higher. Promoted total_steps 40M->80M (committed 8c1070f); 120M+ multi-seed staged as hop-8. Pure config; baseline policy unchanged ([128,128], ~19k params). stop_reason=improved.'
origin:
  backend: flywheel
  node_id: 92a180c8-769f-55c1-ad64-72e32672f084
  slug: cold-pond-1089
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Stack capacity + training budget: [128,128] @ 80M / 120M (empirical node, RESOLVED — GREEN)

## Lineage
- **builds-on:** `69c82afe` (hop-6, [128,128]@40M baseline, best_lap 2.907s) — the validated state this extends. Single parent: a direct continuation of the capacity win, no informed-by branch needed.

## Hypothesis
Hop-6 found bigger net (-12%) and longer training (80M: 3.04s/0.94) each help independently. Stack them: train the [128,128] policy longer and expect a further lap-time drop (and, from the 80M completion bump, better reliability).

## What was run (tp=0.05; eval DR-off 2048x1500 seed 12345)
| variant | best_lap (s) | completion | crash/step | laps_mean | speed_factor (vs feasible 2.324) |
|---|---|---|---|---|---|
| [128,128] @40M parent (multi-seed) | 2.907 mean | 0.827 | ~2.7e-4 | 1.61 | 0.80 |
| **[128,128] @80M** seed0 | 2.687 | 0.944 | 1.0e-4 | 1.69 | |
| **[128,128] @80M** seed1 | 2.594 | 0.919 | 2.1e-4 | 1.69 | |
| **[128,128] @80M** seed2 | 2.864 | 0.926 | 1.3e-4 | 1.53 | |
| **[128,128] @80M multi-seed n=3** | **2.715 mean** | **0.930 mean** | ~1.5e-4 | — | **0.856** |
| [128,128] @120M seed0 (trend) | **2.501** | 0.939 | 1.5e-4 | 1.79 | **0.929** |

## Verdict: GREEN / improved — capacity and training budget stack, and longer training also fixes completion
80M is a clean multi-seed win over the 40M parent: best_lap **2.907 → 2.715 s (~6.6%)**, all three seeds below the parent mean, variance shrinking (spread 0.27 vs 0.30), and — importantly — **completion jumps 0.827 → 0.930**. So the speed/completion tension hop-3 ran into eases with *training budget*, not reward shaping: a longer-trained bigger net flies both faster and more reliably. 120M (single seed) extends the monotonic trend to **2.501 s / 0.939**, reaching **~93% of the honest feasible-oracle pace** — the residual gap is ~14% at 80M, ~7% at 120M, and the curve has **not** flattened by 120M.

**Cumulative arc:** [64,64]@40M 3.289 → [128,128]@40M 2.907 → [128,128]@80M 2.715 s (**~17% faster than the original baseline**) with completion *higher* (0.847 → 0.930).

## Action taken — NEW BASELINE (training length)
Promoted `configs/gate_race.yaml` `ppo.total_steps 40M → 80M` (the multi-seed-confirmed point); committed **8c1070f**. 46 pytest green. Baseline policy architecture unchanged ([128,128], ~19k params — no new deploy-size tradeoff beyond hop-6). 120M is the single-seed best (2.50 s) and is staged for multi-seed confirmation + a push toward the budget knee.

## Artifacts
hop7_summary.json (full 40M/80M/120M results + cumulative arc); standard visual pack on the [128,128]@80M seed-1 winner (2.594 s) vs the [128,128]@40M parent (trajectory / comparison / fpv; leaderboard table; eval json; portable replay). No training_curves (runs trained render-free without TB). The deployable ONNX is unchanged in architecture from hop-6's attached [128,128] policy (only weights differ); regenerable via `scripts/eval.py --export`.

## Stop reason: improved

## Next frontier (replan — n=1 from here)
The training-budget curve is still descending at 120M and we're at ~0.93 of the (optimistic) feasible pace. Candidate hop-8: (a) **confirm 120M multi-seed + push to 160/200M** to find where the budget curve flattens and how close to the feasible floor PPO can get (cheap, pure config; promote if confirmed); (b) **width knee** [96,96]/[160,160] to trade the deploy-size tradeoff against speed under the MCU constraint; (c) once racing plateaus near the feasible floor, **pivot** to the DR-on reliability gap (re-measure DR-on; 80M DR-off completion is already 0.93) or the first n_agents>1 swarm task. Recommend (a).