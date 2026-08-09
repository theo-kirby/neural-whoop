---
node_id: 8db85abb-1c8d-5214-a2b5-ab54e0418bae
slug: shrill-limit-5398
title: 'Training-budget knee: 120M confirmed (2.715->2.600s multi-seed, GREEN) — 160/200M flat, lever EXHAUSTED'
created_at: '2026-06-26T16:11:47.551356+00:00'
parents:
- cold-pond-1089
summary: 'RESOLVED GREEN/improved (modest). Confirmed the 120M trend multi-seed and pushed past it. [128,128]@120M n=3: best_lap mean 2.600s (2.501/2.655/2.644) vs the 80M parent 2.715s (~4.2%), with TIGHTER variance (spread 0.27->0.15); completion 0.919 (~parent 0.930, within seed noise); sf 0.894 of feasible 2.324s. The headline single-seed 2.501 (sf 0.93) was a lucky seed-0 — multi-seed reality is 2.600. KNEE at ~120M: the seed-0 budget curve TURNS OVER past 120M (80M 2.687 -> 120M 2.501 -> 160M 2.562 -> 200M 2.611), so 160/200M buy nothing. Promoted total_steps 80M->120M (confirmed knee). Training-budget lever now exhausted alongside capacity/reward/exploration on single-drone racing -> PIVOT next. Pure config; policy unchanged ([128,128], ~19k params). stop_reason=improved.'
origin:
  backend: flywheel
  node_id: 8db85abb-1c8d-5214-a2b5-ab54e0418bae
  slug: shrill-limit-5398
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 441492fc-d7f5-530e-bb88-d1b7eff808d1
  slug: broad-tooth-2928
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: 26b2e911c11625182dc57ec09a419b814529faba1b791014c313ae35682cbd46
---
# Hop-8 — confirm 120M multi-seed + push the training-budget knee (RESOLVED, GREEN/improved, modest)

## Lineage
- **builds-on:** `92a180c8` (cold-pond-1089, hop-7, [128,128]@80M, best_lap **2.715s** multi-seed / completion 0.930). Single parent: a direct continuation of the capacity+training-budget arc. The 120M single-seed trend point (2.501s) recorded there is exactly what this node sets out to confirm or refute multi-seed.

## Hypothesis
Hop-7's 120M single-seed (2.501s, ~0.93 of feasible) sat below the 80M multi-seed mean and the budget curve had **not** flattened by 120M. H1: a 120M **multi-seed** mean confirms a real win over 80M. H2: pushing to 160/200M finds where the training-budget curve flattens (the knee) and how close PPO gets to the honest feasible floor.

## What was run (pure config; eval DR-off, 2048x1500, seed 12345; tp=0.05; [128,128])
Trained seeds 1 & 2 at 120M (seed 0 already existed) + 160M and 200M at seed 0. Re-evaluated the three 80M parent seeds under the identical protocol for an airtight comparison.

| variant | best_lap (s) | completion | crash/step | laps_mean | sf (feasible 2.324) |
|---|---|---|---|---|---|
| 80M seed0 | 2.687 | 0.944 | 1.0e-4 | 1.69 | 0.865 |
| 80M seed1 | 2.594 | 0.919 | 2.1e-4 | 1.69 | 0.896 |
| 80M seed2 | 2.864 | 0.926 | 1.3e-4 | 1.53 | 0.812 |
| **80M multi-seed n=3** | **2.715 mean** | **0.930** | ~1.5e-4 | — | **0.856** |
| 120M seed0 (hero) | **2.501** | 0.938 | 1.5e-4 | 1.79 | 0.929 |
| 120M seed1 | 2.655 | 0.902 | 2.1e-4 | 1.69 | 0.875 |
| 120M seed2 | 2.644 | 0.917 | 1.6e-4 | 1.71 | 0.879 |
| **120M multi-seed n=3** | **2.600 mean** | **0.919** | ~1.7e-4 | — | **0.894** |
| 160M seed0 | 2.562 | 0.924 | 1.7e-4 | 1.71 | 0.907 |
| 200M seed0 | 2.611 | 0.935 | 1.6e-4 | 1.73 | 0.890 |

## Verdict: GREEN / improved (modest), and the budget knee is found
**H1 confirmed (modestly).** 120M multi-seed mean **2.715 -> 2.600 s (~4.2%)**, all three seeds at/below the 80M mean, and variance **tightens** (spread 0.269 -> 0.154) — longer training also stabilizes the training process. Completion 0.919 vs 0.930 is a wash (within the ~0.25s/seed-scale noise; crash rate unchanged, guardrail intact). **Honest caveat:** the eye-catching 2.501s / sf 0.93 is a *lucky seed-0*, not the typical outcome — multi-seed reality is **2.600 s / sf 0.894**. The control node's 'multi-seed any apparent winner' rule earned its keep here.

**H2 — knee found.** The seed-0 training-budget curve **turns over past 120M**: 80M 2.687 -> **120M 2.501** -> 160M 2.562 -> 200M 2.611. 160/200M buy nothing (and seed-0 regresses, within noise). So the training-budget knee is **~120M**; further budget is wasted spend. Combined with the multi-seed mean plateauing at 2.600, single-drone PPO racing is **near its practical floor (~0.89 of the optimistic feasible oracle)**.

**Cumulative arc:** [64,64]@40M 3.289 -> [128,128]@40M 2.907 -> [128,128]@80M 2.715 -> **[128,128]@120M 2.600 s** (~21% faster than the original baseline) at completion ~0.92.

## Action taken — NEW BASELINE (training length)
Promoted `configs/gate_race.yaml` `ppo.total_steps 80M -> 120M` (the confirmed knee). env_check + pytest green. Policy architecture unchanged ([128,128], ~19k params — no new MCU/deploy-size tradeoff). Deployable `policy.onnx` regenerated from the 120M hero (TorchScript/ONNX export-clean, max abs diff 2.98e-07).

## Lesson for the frontier — the four single-drone levers are now spent
- **capacity** (hop-6 [128,128], GREEN) — exhausted (width knee remains as an MCU-tradeoff option).
- **training budget** (hop-7 80M GREEN, **hop-8 120M GREEN, knee found**) — exhausted past 120M.
- **reward shaping** (hop-1 tp GREEN; hop-2/hop-3 RED) — saturated.
- **exploration** (hop-5 ent RED) — wrong knob.
The residual ~11% gap to the (optimistic) feasible oracle is a **control/optimization-method** gap, not an exploration or capacity gap. PPO is near its floor here.

## Artifacts
`hop8_summary.json` (all 8 runs + both multi-seed means + the seed-0 budget curve); standard visual pack on the 120M seed-0 hero (2.501s) vs the 80M parent hero (trajectory / comparison / fpv; leaderboard table.json; eval json; portable replay); deployable `policy.onnx` (+`.data`). No training_curves (runs trained render-free, no TB), consistent with hop-7.

## Stop reason: improved (knee found)

## Next frontier (replan — n=1, PIVOT)
Budget/capacity/reward/exploration are all explored on single-drone racing; the curve has flattened at ~0.89 of feasible. Per the control contract, **pivot off pure lap-time**. Candidates: (a) **DR-on reliability gap** — re-measure the new 120M baseline with seam DR enabled (hop-3 saw DR-on completion ~0.68 at the old baseline; this is the real deployability metric and the honest sim2real story); (b) **first n_agents>1 swarm task** — the biggest expansion of the objective, novel-behavior territory (collisions/relative-obs already in our env layer); (c) **DiffAero SHAC/BPTT** (`--algo shac`, currently reserved/unimplemented) to attack the residual control gap with a differentiable-physics method PPO can't reach; (d) width knee [96,96]/[160,160] under the MCU constraint. Recommend (a) first (cheap, honest, informs whether to harden racing or move to swarms), then (b).