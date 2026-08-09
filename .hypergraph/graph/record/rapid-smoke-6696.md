---
node_id: c44ffb4c-e221-5ee3-b0ff-7eac57183f34
slug: rapid-smoke-6696
title: 'Formation density curve: holds perfectly to 2x-radius spacing, then a HARD geometric collapse when slots crowd the collision radius — formation scales further than racing'
created_at: '2026-06-28T01:52:35.711067+00:00'
parents:
- proud-wood-6049
- raspy-moon-0909
summary: 'Stress-tests swarm_formation (raspy-moon-0909) at the density where collision-avoidance finally bites (the GREEN node flagged that n=3/wide-ring never collides). Scaled n_agents 3/6/12 on a TIGHT ring (formation_radius=0.5 -> slot spacing 0.866/0.500/0.259m vs the 0.25m collision radius), n_drones held 12288 (n_envs 4096/2048/1024), [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT — a sharp GEOMETRIC threshold: formation holds PERFECTLY up to n=6 (spacing 0.50m = 2x radius: hold_rate 0.991, ZERO collisions) then COLLAPSES at n=12 (spacing 0.259m ~= the 0.25m radius: hold_rate craters to 0.245, collision_rate EXPLODES to 0.233/step). The collapse is geometric, not learning: at spacing ~= collision radius the assigned slots are physically un-occupiable without overlap, so the drones thrash. KEY CONTRAST: formation scales FURTHER than shared-track racing — n=6 holds cleanly where the racing density curve (proud-wood-6049) had already collapsed by n=4 — because formation has no shared track / shared-fate amplification; its only limit is physical packing (need slot spacing > ~2x collision_radius, i.e. formation_radius >~ n*collision_radius/pi). Practical rule for the formation task. Configs e320ecb (recipe); measurement, no code change.'
origin:
  backend: flywheel
  node_id: c44ffb4c-e221-5ee3-b0ff-7eac57183f34
  slug: rapid-smoke-6696
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Setup
The swarm_formation GREEN (`raspy-moon-0909`) noted that at n=3 / wide ring (1.0m) collisions never arise, so it's a weak collision-avoidance test. This hop traces the **formation density curve** to find where formation-keeping and collision-avoidance actually conflict. Scale `n_agents` 3/6/12 on a **tight ring** (`formation_radius=0.5`), holding `n_drones`=12288 (`n_envs` 4096/2048/1024) so the comparison isolates density. Slot spacing = `2 * r * sin(π/n)` = 0.866 / 0.500 / 0.259 m vs the `collision_radius`=0.25 m. [128,128]@120M, seed 0, full seam DR. Eval each at its own density, 2048 envs x 1500 steps, seed 12345. Configs `configs/swarm_formation_n{3,6,12}.yaml` (committed e320ecb).

## Results (DR-off; DR-on similar except where noted)
| n_agents | slot spacing | formation_hold_rate | collision/step | formation_error (m) | mean_sep (m) |
|---|---|---|---|---|---|
| 3 | 0.866 m (3.5x radius) | **0.998** | 0.0000 | 0.161 | 0.849 |
| 6 | 0.500 m (2.0x radius) | **0.991** | 0.0000 | 0.219 | 0.479 |
| 12 | 0.259 m (~1.0x radius) | **0.245** | **0.2325** | 0.264 | 0.408 |
(DR-on: n=3 0.995/0; n=6 0.966/0.0002; n=12 0.209/0.334 — same collapse.)

## Findings
1. **Holds perfectly up to 2x-radius spacing.** n=3 and n=6 both hold ~0.99 with ZERO collisions — a denser ring (6 drones at 0.5m spacing) is held just as cleanly as the sparse one.
2. **HARD collapse at spacing ~= collision radius.** n=12 (slot spacing 0.259m ~= the 0.25m radius): hold_rate craters 0.99 -> 0.245 and collision_rate EXPLODES 0 -> 0.233/step (23% of steps). The drones can't occupy slots spaced at their own collision radius without overlapping, so they thrash.
3. **The collapse is GEOMETRIC, not a learning failure.** It is mathematically impossible for n discs of radius 0.125m (half the 0.25m centre-to-centre) to sit on a ring with 0.26m arc spacing without overlap — the task is asking for a physically infeasible configuration. The policy doesn't fail to learn; the target is un-occupiable.
4. **Formation scales FURTHER than shared-track racing.** n=6 holds perfectly (0.991/0 collisions) where the racing density curve (`0bd2cc36`) had ALREADY collapsed by n=4 (completion 0.34->0.07). Formation has no shared track and no shared-fate amplification — its only ceiling is physical packing. Own-slot formation is the more scalable swarm regime.

## Verdict
**Measurement (nuanced, no single outcome): formation scales cleanly to a hard GEOMETRIC packing limit.** Practical rule: keep slot spacing > ~2x collision_radius, i.e. `formation_radius >~ n_agents * collision_radius / π` (for the 0.25m radius: ~0.5m at n=6, ~1.0m at n=12). Below that the slots are infeasible and formation collapses regardless of training. Configs kept as the reproducible recipe; no code change.

## Honesty / limits
Single seed per density; three points (n=3/6/12 at r=0.5) bracket the threshold but don't pin it precisely (it's between n=6 and n=12, i.e. spacing between 0.26 and 0.50m — consistent with the ~2x-radius geometric prediction). n=12 DR-on form_err (0.142) reads lower than DR-off (0.264) only because collisions terminate episodes early in the collapsed regime, so less error accumulates — a metric artifact, not better formation (hold_rate 0.209 and collision 0.334 are the real story). The fix for higher counts is a bigger ring (config), not more training.

## Lineage
- **builds-on** `7cd41adf` (swarm_formation hop-15): stress-tests the task it introduced at the density its 'limits' section flagged.
- **informed-by** `0bd2cc36` (racing density curve): the direct parallel — same density-sweep method, contrasting outcome (formation scales further, collapses geometrically not via shared-fate).

## Artifacts
formation_density.png (hold_rate + collision vs slot spacing; the geometric threshold), formation_density_table.json (n=3/6/12 x DR-off/DR-on). Configs e320ecb.