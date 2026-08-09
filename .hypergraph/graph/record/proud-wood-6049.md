---
node_id: 0bd2cc36-bf70-52b0-8deb-f830ea81760f
slug: proud-wood-6049
title: 'Swarm density curve: lap_completion COLLAPSES super-linearly with n_agents (3->4->6) — shared-fate amplification, n=3 is the ceiling (NO-GO to scale)'
created_at: '2026-06-28T00:07:09.589686+00:00'
parents:
- cool-union-2681
- flat-dew-5721
summary: 'Hop-14b traces the swarm_race density curve the hop-14a NO-GO pointed to (completion is congestion-capped). Scaled n_agents 3->4->6 on the SAME 4.5m arena, holding n_drones=12288 constant (n_envs 4096/3072/2048) so it isolates density from training amount; [128,128]@120M seed 0, eval 2048 envs x1500 seed 12345. RESULT: lap_completion COLLAPSES super-linearly — DR-off 0.34 (n3) -> 0.073 (n4) -> 0.007 (n6); DR-on 0.21 -> 0.058 -> 0.002. Crucially collision/step stays ~FLAT (0.0020->0.0033->0.0030, not saturating) and best_lap is preserved (2.83-2.92s) — so this is NOT collision-collapse. It is shared-fate AMPLIFICATION: with more agents per env, the probability that SOME drone fails early (collision or out-of-arena) and ends the whole env episode rises steeply, so far fewer drones survive long enough to complete a lap, even though the ones that lap stay fast. CONCLUSION: n=3 is already near the density ceiling for this arena+shared-fate; scaling agents-per-course is NO-GO for throughput. The real levers for more swarm throughput are a BIGGER arena (lower density) or true per-drone fate decoupling (an env-layer change), not more agents on the same loop. Configs 1b176e9 (recipe).'
origin:
  backend: flywheel
  node_id: 0bd2cc36-bf70-52b0-8deb-f830ea81760f
  slug: proud-wood-6049
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 6cbb31f8-9969-5379-89e4-2c5e1dbf4d3b
  slug: shy-cherry-2312
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: b7832b0e476faae635e723093567d0467d7460d4bfdf706250fa3b7d4b47161a
---
## Setup
The hop-14a NO-GO (`ffc5d9e4`) showed swarm completion is capped by track CONGESTION, not the shared-fate rule. This hop traces the **density curve** to find where coordination/throughput breaks. Scale `n_agents` 3->4->6 on the **same** 4.5 m arena, **holding `n_drones` = 12288 constant** (`n_envs` = 4096/3072/2048) so the comparison isolates *density* (agents sharing one course) from training amount (same updates, same 120M-step budget, same per-update batch). [128,128]@120M, seed 0, full seam DR. Eval each at its own density, 2048 envs x 1500 steps, seed 12345, deterministic. Configs `configs/swarm_race_n{4,6}.yaml` (committed 1b176e9); n=3 = the hop-13 baseline (`4b21d59b`).

## Results
| n_agents | condition | lap_completion | collision/step | best_lap (s) | crash/step |
|---|---|---|---|---|---|
| 3 (baseline) | DR-off | **0.34** | 0.0020 | 2.83 | (low) |
| 4 | DR-off | **0.073** | 0.0033 | 2.825 | 3.85e-4 |
| 6 | DR-off | **0.007** | 0.0030 | 2.919 | 2.44e-4 |
| 3 (baseline) | DR-on | 0.21 | 0.0021 | 2.89 | (low) |
| 4 | DR-on | 0.058 | 0.0032 | 2.881 | 5.80e-4 |
| 6 | DR-on | 0.002 | 0.0031 | 2.953 | 3.57e-4 |

## Findings
1. **Completion COLLAPSES super-linearly with density:** 0.34 -> 0.073 -> 0.007 (DR-off) — ~5x drop from 3->4, ~50x from 3->6. The same shape DR-on.
2. **It is NOT collision-collapse.** collision/step stays ~flat (0.0020 -> 0.0033 -> 0.0030) and does not saturate; the drones aren't crashing into each other more per-step.
3. **Speed is preserved** — best_lap holds at 2.83-2.92 s across all densities. The drones that DO complete a lap are just as fast.
4. **Mechanism = shared-fate amplification.** A collision OR any drone leaving the arena ends the *whole env episode*. With more agents per env, P(at least one drone fails early) rises steeply, so episodes are cut short before most drones can finish a lap — completion craters while per-step collision rate barely changes. The binding constraint is the *coupling* of fate across a denser pack, not the per-encounter collision likelihood.

## Verdict
**Measurement; outcome NO-GO for scaling density, stop_reason=regressed.** n=3 is already near the density ceiling for this 4.5 m arena under shared-fate; adding agents-per-course collapses throughput. The decision metric (lap_completion at bounded collision) degrades monotonically with n_agents. Configs kept as the reproducible density recipe; no code change, baseline unchanged.

## What this means for swarm throughput
The two ways to actually raise swarm throughput, given this curve:
- **Lower the density** — a bigger arena / longer course for the same agent count (more room to deconflict), or simply accept ~3 agents/loop as the sweet spot and scale by adding *parallel* courses.
- **Decouple fate** at the env layer — a true per-drone reset (only the failing drone resets, the env keeps running) rather than the per-env shared-fate termination. hop-14a showed the *task-only* soft-cost version doesn't work (it just makes collisions cheap); a real per-drone-reset env hook is the heavier but correct intervention. This is the env-change candidate.
- `swarm_formation` sibling (drones hold relative offsets instead of racing one shared line) sidesteps the shared-track congestion entirely.

## Honesty / limits
Single seed per density; the effect is enormous (50x) so seed-robust, but the exact ceiling location (is it 3, or 3-4?) would want a seed or two. n=3 baseline numbers are the recorded hop-13 values (same protocol). mean_separation didn't surface in the eval JSON for these runs (not load-bearing; the completion/collision split carries the conclusion).

## Lineage
- **builds-on** `4b21d59b` (hop-13 swarm_race): extends it across the density axis.
- **informed-by** `ffc5d9e4` (hop-14a NO-GO): its 'congestion is the ceiling' finding motivated mapping the density curve; this confirms + quantifies it.

## Artifacts
density_curve.png (completion + collision vs n_agents), density_table.json (full DR-off/DR-on matrix).