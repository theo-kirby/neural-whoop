---
node_id: 69c82afe-b1f5-595e-8690-5cb5bab582d3
slug: sparkling-limit-8154
title: 'Capacity probe: [128,128] policy unlocks ~12% lap time (3.29 -> 2.91s) — NEW BASELINE (GREEN)'
created_at: '2026-06-26T13:26:27.810962+00:00'
parents:
- morning-base-2167
- square-cake-5756
summary: 'RESOLVED GREEN / improved — first real lap-time gain since hop-1. Hop-5 showed the ~37% headroom isn''t reward/exploration; this probe asked: optimization-budget/capacity limit, or the control problem? Answer: substantially CAPACITY. Bigger policy [128,128] vs [64,64] (40M steps, tp=0.05): best_lap multi-seed n=3 mean 2.907s (2.774/3.073/2.874) vs baseline 3.289s = ~12% faster, clears seed sigma ~0.25; completion held 0.847->0.827; feasible-oracle speed_factor 0.73->~0.80. Longer training (80M, [64,64]) also helps: 3.039s + completion 0.941. The [64,64] MLP was too small to represent the faster control policy. Promoted [128,128] to the baseline; committed 88ddf5d. Deploy tradeoff: actor ~5.4k->~19k params (~75KB f32/~19KB int8, ONNX round-trips 2.38e-7) -- still tiny+quantization-friendly/MCU-deployable, flagged. stop_reason=improved.'
origin:
  backend: flywheel
  node_id: 69c82afe-b1f5-595e-8690-5cb5bab582d3
  slug: sparkling-limit-8154
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Capacity probe: bigger policy + longer training (empirical node, RESOLVED — GREEN, NEW BASELINE)

## Lineage (DAG merge)
- **builds-on:** `e4a66478` (tp=0.05 GREEN baseline, [64,64], 3.13–3.19s) — the validated state probed on top of.
- **informed-by:** `08c0c825` (hop-5 RED / exploration) — its finding (the headroom is a control/algorithm limit, not reward or exploration) is *why* this hop probes optimization-budget/capacity to disambiguate before a large SHAC build.

## Hypothesis / question
Hop-4 measured ~37% lap-time headroom; hop-3 (reward) and hop-5 (exploration) both failed to unlock it. Question: is the limit the **optimization budget / model capacity** (the [64,64] MLP / 40M steps can't represent or find the faster policy) or the **control problem itself** (PPO+CTBR cannot safely fly faster)? Probe both cheaply (pure config) before committing to a SHAC implementation.

## What was run (tp=0.05; eval DR-off 2048x1500 seed 12345)
| variant | best_lap (s) | completion | crash/step | laps_mean |
|---|---|---|---|---|
| baseline [64,64] 40M (control) | 3.185 (ms **3.289**) | 0.847–0.866 | 2.3e-4 | 1.23 |
| longer: [64,64] **80M** (seed0) | 3.039 | **0.941** | 0.7e-4 | 1.32 |
| bigger: **[128,128]** 40M (seed0) | **2.774** | 0.875 | 2.1e-4 | 1.61 |
| **[128,128] 40M multi-seed n=3** | **2.907 mean** (2.774/3.073/2.874) | 0.827 mean (0.875/0.810/0.796) | ~2.7e-4 | — |

## Verdict: GREEN / improved — the headroom was substantially CAPACITY-limited
**[128,128] is a clear, multi-seed-confirmed win:** best_lap **3.289 → 2.907 s mean (~12%)**, clearing the ~0.25 s seed sigma (all three seeds below the baseline mean), with completion held within noise (0.847 → 0.827) and the **feasible-oracle speed_factor up 0.73 → ~0.80** (closing a third of the headroom hop-4 measured). The [64,64] MLP was simply too small to represent the faster control policy. Longer training (80M) independently helps too (3.04 s and completion 0.94), so more optimization budget also pays. This is the **first real lap-time improvement since hop-1** and refines hop-5's reading: exploration is the wrong knob, but the limit is **not** purely the control problem — capacity matters.

## Action taken — NEW BASELINE
Promoted `configs/gate_race.yaml` `ppo.hidden_sizes [64,64] → [128,128]`; committed **88ddf5d**. 46 pytest green. **Deploy tradeoff (LOCKED MCU constraint):** the actor grows ~5.4k → ~19k params (~75 KB f32 / ~19 KB int8); ONNX round-trips at 2.38e-7 (`policy.onnx` attached). Still tiny and quantization-friendly / MCU-deployable, but a 3.5× size increase — **flagged for human review**; an intermediate width (e.g. [96,96]) may capture most of the gain at lower cost (a candidate follow-up).

## Artifacts
hop6_summary.json (full probe + deploy sizes); standard visual pack on the [128,128] seed-0 winner (2.774 s) vs the [64,64] tp=0.05 baseline parent (trajectory / comparison / fpv; leaderboard table; eval json; portable replay); policy.onnx (+ external data) — the deployable [128,128] winner.

## Stop reason: improved

## Next frontier (replan — n=1 from here)
Capacity pays and ~0.80 of the feasible pace is now reached. Candidate hop-7: (a) **[128,128] + longer training (80M)** — stack the two wins that each helped independently (cheapest, high-confidence next gain); (b) **width sweep** [96,96]/[160,160] to find the speed/size knee under the MCU constraint; (c) **DiffAero SHAC/BPTT** to chase the residual ~20% gap with differentiable-dynamics control; (d) re-establish a tighter multi-seed baseline at [128,128] and consider the feasible oracle as the training yardstick. Recommend (a) first (stacks two validated levers, pure config).