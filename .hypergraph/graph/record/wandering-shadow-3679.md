---
node_id: 35f51233-0594-5be0-8acf-bb3632870a71
slug: wandering-shadow-3679
title: 'Latency-aware policy (frame stacking obs_stack=3): DR-on completion FLAT — NO-GO; 3rd reliability lever exhausted'
created_at: '2026-06-26T18:34:28.526870+00:00'
parents:
- shrill-limit-5398
- aged-term-6809
summary: 'RESOLVED no-go (stop_reason=no-effect). Tried a latency-aware policy (env.obs_stack=3: the policy sees the last 3 obs frames, obs_dim 14->42) to compensate for the action-latency-1 seam, the failure mode hops 10-11 implicated. It did NOT lift the primary metric: DR-on completion 0.804->0.790 (flat/slightly worse), crash ~flat; DR-off completion dipped 0.919->0.890 (the 42-dim input is a harder learning problem); speed preserved (DR-on 2.64s). Adding observation information didn''t help -- velocity is already in obs-v4, so the residual DR-on gap is disturbance MAGNITUDE, not missing info. THREE single-drone reliability levers now exhausted (curriculum RED hop-10, reward no-go hop-11, obs/latency no-go hop-12): the ~0.80 DR-on gap is robust to schedule/reward/observation at this scale -> PIVOT to swarm. Baseline unchanged; frame-stacking kept default-off tested env infra (committed fe9cc3f).'
origin:
  backend: flywheel
  node_id: 35f51233-0594-5be0-8acf-bb3632870a71
  slug: wandering-shadow-3679
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: db7f6be0-d809-5a02-bc3d-d948dfc89afc
  slug: tiny-hill-3015
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 5a9ec010b21afbbd9ab1571b000a4ca0e0aa1c2ed9efdd7bd12b3170cda44e7a
---
# Hop-12 — latency-aware policy via frame stacking (RESOLVED, NO-GO)

## Lineage
- **builds-on:** `8db85abb` (hop-8, [128,128]@120M baseline, full DR).
- **informed-by:** `7a7e6be5` (hop-11) — the near-miss reward was a no-go and **reframed** the gap as not-crash-limited (timeouts/missed-gates under the action-latency-1 seam + wind). This hop attacks that reframing directly: add *information*, not reward.

## Hypothesis
Hops 10–11 implicated the **action-latency-1** seam (sense->infer->actuate delay) in the DR-on completion gap. A **latency-aware policy** that sees the last k observation frames can infer the lag (and finite-difference dynamics) it can't see in one frame, and compensate — lifting DR-on completion toward the DR-off 0.92 **without** the speed cost the reward lever paid.

## Mechanism (committed fe9cc3f, default-off)
`env.obs_stack=k`: the env keeps the last k observation frames and feeds their concatenation to the policy (obs_dim 14 -> 14k). Correct auto-reset/bootstrap semantics (done drones start a fresh history; the terminal frame is stacked for value bootstrapping). **`obs_stack=1` (default) is an exact no-op** — all prior tests pass; +3 new (no-op dim, reset repeats the frame, step shifts newest-last). Experiment used **k=3** (obs_dim 42).

## What was run (obs_stack=3; [128,128]@120M full-DR, 3 seeds; eval 2048x1500 seed 12345, latency config)
| metric | latency-aware (n=3) | baseline (hop-8/9) | Δ |
|---|---|---|---|
| **DR-on completion** (primary) | **0.790** | **0.804** | **flat / slightly worse** |
| DR-on crash/step | 5.3e-4 | 4.6e-4 | ~flat |
| DR-on best_lap | 2.639 s | 2.665 s | ~1% faster (no cost) |
| DR-off completion | **0.890** | 0.919 | **slightly worse** |
| DR-off best_lap | 2.596 s | 2.600 s | flat |

## Verdict: NO-GO — more observation didn't buy reliability
Frame stacking **did not lift the primary metric** (DR-on completion 0.804 -> 0.790) and **slightly hurt DR-off completion** (0.919 -> 0.890, the larger 42-dim input being a harder learning problem). Speed was preserved (unlike the reward lever), but that doesn't matter when completion didn't rise. **Why it failed:** obs-v4 **already carries body velocity and rates**, so the last-k frames add little genuinely new signal; the policy can already see its motion. The residual DR-on non-completion is therefore **disturbance magnitude** (wind/rate-gain occasionally pushing the drone off-line through a gate or into divergence), which no amount of *observation* fixes.

## Conclusion — the single-drone reliability thread is exhausted
Three mechanistically distinct levers have now failed to lift DR-on completion off ~0.80:
- **schedule** — DR curriculum (hop-10, RED: regressed to 0.67),
- **reward** — near-miss penalty (hop-11, no-go: safer but flat completion + slower),
- **observation** — latency-aware frame stacking (hop-12, no-go: flat).
The ~0.80 DR-on gap is **robust to schedule, reward, and observation** at this net/budget. It is not cheaply closable; further single-drone reliability work is low expected value. The honest next move is to **pivot to the swarm frontier** (the core objective expansion). A fundamentally different attack on reliability (DiffAero SHAC/BPTT differentiable-physics, or simply accepting 0.80 + reducing the DR seam magnitudes to the real airframe's measured spread) is possible but deprioritized.

## Action taken
**Do NOT promote** (fails the GREEN bar). Baseline `configs/gate_race.yaml` unchanged (`obs_stack` stays 1). Frame stacking **kept as default-off, tested env infra** (a clean general feature; env_check + 58 pytest green). `configs/gate_race_latency.yaml` retained as the reproducible recipe (header marked NO-GO). Committed **fe9cc3f**.

## Artifacts
`hop12_summary.json` (latency-aware vs baseline, per-seed DR-on/DR-off + the 3-lever conclusion); DR-on trajectory of the best seed (s2, 2.65s/0.818); comparison vs the baseline DR-on replay; DR-on s2 eval json; per-run leaderboard table.json; portable DR-on replay. No training_curves (render-free).

## Stop reason: no-effect (DR-on completion flat; reliability thread exhausted)

## Next frontier (replan — n=1): PIVOT to the first swarm task
The reliability sub-thread is thoroughly explored (1 measurement + 3 negatives) and the gap is characterized as disturbance-magnitude-bound. **hop-13 = the first n_agents>1 SWARM task** — the core objective expansion ('discover novel/creative policies', expand to swarms). A new `DroneTask` subclass with a swarm metric (e.g. formation-keeping or multi-drone gate racing with collision avoidance); raise env `n_agents`; collisions and relative observations already live in our env/task layer per CLAUDE.md. Accept DR-on 0.80 as the deployable single-drone racing baseline. Deprioritized single-drone options if we ever return: DiffAero SHAC/BPTT (reserved `--algo shac`); re-scoping the DR seam magnitudes to the real airframe's measured spread; width knee.