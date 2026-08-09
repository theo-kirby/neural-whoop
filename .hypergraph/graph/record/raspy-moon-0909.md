---
node_id: 7cd41adf-1529-5e36-8101-3ac6330e795f
slug: raspy-moon-0909
title: 'swarm_formation (hop-15): second swarm task — ring formation around a moving anchor holds tightly with ZERO collisions (GREEN), sidesteps the shared-track ceiling'
created_at: '2026-06-28T01:18:08.438729+00:00'
parents:
- cool-union-2681
- proud-wood-6049
summary: 'The formation half of the swarm catalog, motivated by the density-curve NO-GO (proud-wood-6049) which showed shared-track racing is congestion-capped at n=3. swarm_formation: N drones each hold their OWN assigned slot on a ring around a slowly-moving anchor (reuses the target.py mover) under a shared policy + nearest-neighbour obs (obs 17) + collision avoidance. No shared track, so the only coupling is formation geometry + separation. Pure task-layer (no env changes); reuses swarm_race''s neighbour/collision machinery. [128,128]@120M, n_agents=3, full seam DR, seed 0; eval 2048x1500 seed 12345 deterministic. RESULT GREEN: the ring forms and holds tightly — mean_formation_error 0.169m (DR-off) / 0.174m (DR-on), well within the 0.4m hold tolerance; formation_hold_rate 0.997 / 0.994 (drones on-slot ~all the time); ZERO collisions (0.0000/step) at mean separation 1.7m (>6x the 0.25m radius); DR-robust (DR-off ~= DR-on). This VALIDATES the density node''s hypothesis end-to-end: giving each drone its own slot sidesteps the shared-track congestion that capped swarm_race (0.34 completion / 0.002 collisions/step) — formation gets 0.997 hold / 0 collisions. Promoted: new task + config committed 10a868d, 84 pytest green. obs_dim 17 (MCU deploy-size flag, < swarm_race''s 20).'
origin:
  backend: flywheel
  node_id: 7cd41adf-1529-5e36-8101-3ac6330e795f
  slug: raspy-moon-0909
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 08ce6f4a-5004-5e65-9c94-0d655a0d5315
  slug: odd-morning-5099
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: f86916afb73de217242258890882c7c8c95ea2f444856baa89fb0e5cb118afa8
---
## What it is
The **second swarm task** (the formation half of `docs/TASK_CATALOG.md`), opened because the density curve `proud-wood-6049` showed shared-track racing throughput is congestion-capped at n=3 and flagged a formation task as the way to *sidestep shared-track congestion entirely*.

`n_agents` drones each hold their **own** assigned slot on a ring around a common, slowly-moving **anchor** (anchor motion reuses `neural_whoop.target`, one per env). Slot `i` = `anchor + formation_radius * [cos(2πi/n), sin(2πi/n), 0]`. Under a **shared policy** + nearest-neighbour body-frame rel-pos/vel obs + a collision penalty. **No shared track** — the only coupling is the formation geometry and separation. Pure task-layer (the env flattens `(n_envs,n_agents)->n_drones`; collision/neighbour-obs live in the task), reusing swarm_race's `_nearest_neighbour` machinery. **No env changes.**

- **Obs (17):** obs-v4 (11) with the body-frame vector to the drone's OWN slot replacing the gate vector, + nearest in-env neighbour rel-pos (3) + rel-vel (3). (MCU deploy-size flag: obs 17, < swarm_race's 20.)
- **Reward:** formation-keeping bell `exp(-(slot_err/σ)²)` + alive − collision − smoothness − boundary crash. No time penalty (a holding task).
- **Metric:** `mean_formation_error` (dist to slot) ↓ + `formation_hold_rate` (frac of steps within `hold_tol`=0.4m) ↑, at bounded `collision_rate_per_step`. GREEN = ring forms+holds; RED = can't hold / collapse.

## Result — GREEN (eval 2048 envs x 1500 steps, seed 12345, deterministic; n_drones 6144)
| condition | formation_error (m) | hold_rate | collision/step | mean_sep (m) |
|---|---|---|---|---|
| **DR-off** | **0.169** | **0.997** | **0.0000** | 1.71 |
| **DR-on** | 0.174 | 0.994 | 0.0000 | 1.69 |

- **The ring forms and holds tightly** — 0.17m mean slot error (within the 0.4m tolerance), drones on-slot **99.7%** of steps. ep_ret ~487.
- **ZERO collisions** (0.0000/step) at mean separation 1.7m (>6x the 0.25m collision radius). With each drone on its own well-spaced slot, there is nothing to collide over — the structural opposite of shared-track racing.
- **DR-robust:** DR-off ~= DR-on on every axis (formation seam-invariant, like the racing/follow policies).

## Why it matters (closes the density-node loop)
`proud-wood-6049` (density curve) showed swarm_race completion COLLAPSES with agents-per-course (0.34 -> 0.007 at n=3 -> 6) via shared-fate amplification, and predicted formation would sidestep it. **Confirmed:** swarm_formation at n=3 gets **0.997 hold / 0 collisions** vs swarm_race's **0.34 completion / 0.002 collisions/step**. The coordination is trivially clean because there is no shared resource to contend for — a genuinely different (and easier) swarm regime than shared-track racing. (It also means formation is a poor *stress* test of collision avoidance precisely because collisions don't arise; the hard swarm-coordination problem still lives in shared-track racing / denser formations.)

## Honesty / limits
Single seed; n_agents=3 only (the formation density curve — tighter ring / more agents until slots crowd the collision radius — is the natural follow-up, and is where formation would start to actually exercise collision avoidance). Anchor is slow (1.0 m/s); a fast/agile anchor would stress formation-keeping (cf. the EMA speed-envelope finding `wandering-mode-7957`). policy.onnx exported (obs 17).

## Lineage
- **builds-on** `4b21d59b` (swarm_race hop-13): reuses its shared-policy + nearest-neighbour obs + collision machinery on the [128,128]@120M racing net; the second entry in the swarm catalog.
- **informed-by** `0bd2cc36` (density-curve NO-GO): its 'congestion is the ceiling; formation sidesteps it' conclusion motivated this task; this confirms that prediction.

## Artifacts
formation_compare.png (formation vs racing: 0 collisions/0.997 hold vs 0.002/0.34), formation_table.json (DR-off/DR-on + swarm_race ref), eval JSONs. Code 10a868d; policy.onnx (obs 17).