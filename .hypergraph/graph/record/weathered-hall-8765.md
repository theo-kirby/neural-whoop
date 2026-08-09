---
node_id: eaf77e58-a720-5828-b4a5-6f5a250fbd66
slug: weathered-hall-8765
title: 'Hypothesis: per-drone (not shared-fate) reset lifts swarm completion at bounded collisions'
created_at: '2026-06-27T15:03:32.825977+00:00'
parents:
- cool-union-2681
summary: 'swarm_race (4b21d59b) posts a structurally low completion (0.34 DR-off) because a collision OR any drone leaving the arena ends the WHOLE env episode — a clean drone is punished for a teammate''s failure, shortening every drone''s episode. Hypothesis: replacing shared-fate per-env termination with per-drone reset (or a soft collision cost, no termination) lifts lap_completion_rate materially while keeping collision_rate_per_step bounded, since coordination already emerged (mean sep >1.1m, >4x the 0.25m radius). This is the staged hop-14(a). Untested.'
origin:
  backend: flywheel
  node_id: eaf77e58-a720-5828-b4a5-6f5a250fbd66
  slug: weathered-hall-8765
  revision: 8
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Status: OPEN HYPOTHESIS (staged hop-14a, not yet run)

## Where it comes from
`4b21d59b` (swarm_race GREEN) established that n_agents=3 coordinated shared-track racing EMERGES — collisions are rare (0.002/step) at mean separation >1.1 m (>4x the 0.25 m collision radius). But completion is only 0.34 (DR-off), and the honest read there is that this is **structural, not collapse**: shared-fate per-env termination resets the whole env when ANY of the 3 coupled drones collides or leaves the arena, so a clean drone's episode is cut short by a teammate's failure.

## The hypothesis
The low completion is a **reward/termination-structure artifact**, not a coordination failure. Decoupling failure should recover throughput:

- **Per-drone reset**: only the failed (colliding / out-of-bounds) drone resets; clean drones keep flying. Needs a small env hook (per-drone reset within an env, vs today's per-env done).
- **Or, cheaper first**: a **soft collision cost** with NO termination (task-only, no env change) — penalise contact but never end the episode.

**Prediction:** lap_completion_rate rises materially (0.34 -> ?) while collision_rate_per_step stays bounded (coordination is already learned, so removing the shared-fate guillotine shouldn't unleash collisions). GREEN = completion up at bounded collisions; RED = collisions blow up once the shared-fate pressure is removed (i.e. shared-fate WAS the thing holding separation).

## How to test
- Start with the soft-collision-cost variant (task-only): set collision to a penalty without `done`, retrain [128,128]@120M, eval swarm throughput + collision rate.
- If promising, add the per-drone-reset env hook and compare.

## Lineage
- builds-on `4b21d59b` (swarm_race — the task whose shared-fate termination this relaxes).