---
node_id: af4bc6f6-259c-53ba-aa60-7ca2bd3051fd
slug: peaceful-mist-1317
title: 'Swarm: own-slot formation scales flat to 24 drones, shared-track racing caps at three'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- cold-pebble-7468
summary: 'Two swarm tasks, both GREEN, with a sharply measured boundary between them: shared-track racing collapses super-linearly past n=3 while own-slot formation holds flat to 24 drones on one tiny shared policy. Untouched since 2026-06-28.'
---
Status: working

## Current

Both swarm tasks exercise the `n_agents > 1` path with no env change — collisions and
relative observations live in the task layer.

- `swarm_race` [rec: cool-union-2681]: coordinated shared-track racing emerges from a shared policy
  [rec: cool-union-2681].
- `swarm_formation` [rec: raspy-moon-0909]: N drones each hold their own slot on a ring around a slowly
  moving anchor. Formation error 0.17 m, hold rate 0.997, **zero collisions**, and
  DR-robust [rec: raspy-moon-0909]. One tiny shared policy holds a **24-drone** ring
  flat [rec: summer-wave-6268] — roughly eight times the shared-track ceiling.

The honest caveat on the formation result is recorded in its own node: collisions do
not arise there, so it is a weak collision-avoidance stress. That lives in
shared-track racing and in denser formations.

Nothing in this cluster has moved since 2026-06-28. `swarm_transport` and
`swarm_vs_swarm` are catalogued in `docs/TASK_CATALOG.md` and unimplemented.

## Negative knowledge

- [scope: shared-track swarm racing | confidence: high | evidence: proud-wood-6049, flat-dew-5721] Lap completion collapses super-linearly with n_agents from 3 to 4 to 6 — shared-fate amplification. Relaxing shared fate with a soft collision cost does NOT lift it, so shared fate was a useful constraint rather than the cause.
- [scope: ring formation density | confidence: high | evidence: rapid-smoke-6696] The formation holds perfectly down to 2x-radius slot spacing and then collapses hard and geometrically once slots crowd. The flat N-scaling is a property of spacing, not of N.
- [scope: composing the perception primitive with formation | confidence: high | evidence: divine-mud-3368, mute-block-8299] A perception-aware formation does NOT inherit the clean flat scaling: noisy anchor detection degrades and destabilises it across N, and the n=6 versus n=12 gap was confirmed multi-seed as real rather than training variance.

## Provenance

- cool-union-2681 — the first swarm task
- proud-wood-6049 — the shared-track density collapse
- flat-dew-5721 — relaxing shared fate, refuted
- raspy-moon-0909 — the formation task and its numbers
- rapid-smoke-6696 — the formation density curve and its hard edge
- summer-wave-6268 — 24-drone flat scaling
- divine-mud-3368 — perception-aware formation does not inherit flat scaling
- mute-block-8299 — the multi-seed confirmation
