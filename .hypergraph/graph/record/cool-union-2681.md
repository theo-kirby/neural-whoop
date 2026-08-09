---
node_id: 4b21d59b-de29-5140-b9cc-76301c5c7f42
slug: cool-union-2681
title: 'swarm_race (hop-13): first n_agents>1 swarm task — coordinated shared-track racing emerges (GREEN)'
created_at: '2026-06-27T00:34:37.595162+00:00'
parents:
- shrill-limit-5398
- wandering-shadow-3679
summary: 'The swarm pivot. n_agents=3 drones share one gate course under a shared policy + neighbour obs (14->20) + collision penalty + shared-fate termination; pure task-layer, no env changes. [128,128]@120M full-DR, 3 seeds. GREEN: coordinated racing emerges, collisions rare/bounded (0.002/step, mean sep >1.1m, >4x the 0.25m radius), no collapse. DR-off best_lap 2.83s / completion 0.34; DR-on 2.89s / 0.21. ~9% slower than single-drone (track-sharing cost); lower completion = shared-fate over 3 coupled drones, not collapse. Code b240063.'
origin:
  backend: flywheel
  node_id: 4b21d59b-de29-5140-b9cc-76301c5c7f42
  slug: cool-union-2681
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1f52d4f6-13a0-5861-960e-6613cce8ca67
  slug: broad-dream-4590
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: fd9307d1790987fee6d27c5f318c98459141f63e182a85cb66648cdaa9cfbe8a
---
# Hop-13 — swarm_race: the first multi-drone (n_agents>1) task

**The Flywheel swarm pivot.** Single-drone racing reliability was exhausted (hop-10/11/12 all NO-GO; the ~0.80 DR-on completion gap is disturbance-magnitude-bound). The objective's second half — *discover novel/creative policies, expand to swarms* — opens here. This is the first task where inter-agent coupling is real.

## Lineage
- **builds-on `8db85abb`** (single-drone [128,128]@120M racing baseline): same net, same budget, same DR seam, same racing reward — the swarm reuses all of it.
- **informed-by `35f51233`** (latency-aware NO-GO): closed the single-drone reliability thread, motivating the pivot.

## What it is
`n_agents=3` drones share **one** procedurally-generated closed gate course under a **shared policy** and race it while avoiding each other. Pure task-layer work — the env already flattens `(n_envs,n_agents)->n_drones` and keeps collision/relative-obs coupling in the task, so **no env changes**:
- **Obs 14->20**: appended each drone's nearest in-env neighbour body-frame **rel-pos (3) + rel-vel (3)** — the channel a tiny shared policy needs to keep separation. (MCU deploy-size flag: TinyPolicy 19,716 params vs ~19k single-drone.)
- **Collision penalty** (centre-to-centre < `collision_radius` 0.25 m) on the involved drones.
- **Shared-fate per-env termination** (the env contract returns per-env done): a collision OR any drone leaving the arena ends the *whole env episode*. This is the coordination pressure — a collision is costly for the entire swarm.
- Drones spawn spread on a 0.6 m ring (well above the collision radius), facing gate 0.

## Decision metric (new — first swarm task, no single-drone parent to beat)
Swarm lap throughput at a **bounded collision rate**: `lap_completion_rate` + `collision_rate_per_step` (bounded) + `best_lap_time`. **GREEN = coordinated racing emerges; RED = collision collapse (completion ~0 / collisions saturate).**

## Result — GREEN (deterministic eval, 2048 envs × 1500 steps, seed 12345, n_drones=6144; 3-seed mean)
| | best_lap | completion | collision/step | mean_sep | crash/step |
|---|---|---|---|---|---|
| **DR-off** | 2.83 s | 0.34 | 0.0020 | 1.23 m | 0.0006 |
| **DR-on** | 2.89 s | 0.21 | 0.0021 | 1.14 m | 0.0010 |

- **Coordinated racing emerged, not collapse.** Collisions are rare (~0.2% of drone-steps) and mean nearest-neighbour separation is **>1.1 m — over 4× the 0.25 m collision radius** → genuine learned avoidance. ~272k gate passes; ep_ret strongly positive (~27).
- **Speed is DR-robust** (2.83→2.89 s), like the single-drone policy.
- **Honest read of the gaps:** best_lap ~9% slower than single-drone (2.60 s) = the cost of giving way on a shared track. Completion (0.34 vs single-drone 0.92) is *structurally* lower because shared-fate termination resets the env when **any** of 3 coupled drones fails, shortening every drone's episode — it is NOT collision collapse. This is the new swarm-specific headroom (shared-fate completion / throughput).

## Reproduce
`configs/swarm_race.yaml` · `uv run python scripts/train.py --config configs/swarm_race.yaml --seed {0,1,2} --tensorboard` · eval with `scripts/eval.py --config configs/swarm_race.yaml --from runs/swarm_race_s{seed}/ckpt_final.pt [--no-dr] --seed 12345 --n-envs 2048 --steps 1500`. Code commit **b240063**; 65 pytest green, env_check green.

## Artifacts
`eval.json` (3-seed DR-off+DR-on aggregate), `table.json` (swarm vs single-drone leaderboard), `trajectory.png` / `fpv_00.png` / `training_curves.png` (hero seed 1), `replay.json.gz` (DR-off) + `replay_dron.json.gz` (DR-on) hero replays, `policy.onnx`(+`.data`) deploy policy (obs_dim 20).

## Next frontier (staged)
Swarm-specific headroom now that coordination works: (a) **lift shared-fate completion** — relax termination (only colliders reset / soft collision cost) so a clean drone isn't punished for a teammate's failure; (b) **scale n_agents** (4→6→8) and watch the collision/throughput curve; (c) **density curriculum** (tighter arena / more drones over training); (d) the `swarm_formation` sibling (track relative-offset targets instead of a shared track).