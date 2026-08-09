---
node_id: ffc5d9e4-cfdd-579e-97e7-f94dd33b3771
slug: flat-dew-5721
title: Relaxing swarm shared-fate (soft collision cost) does NOT lift completion (NO-GO) — shared-fate was a useful collision deterrent
created_at: '2026-06-27T23:36:49.136818+00:00'
parents:
- cool-union-2681
summary: 'Hop-14(a) tests whether swarm_race''s shared-fate termination (a collision ends the whole env episode) caps lap_completion by punishing clean drones for a teammate''s collision. Added a task-only knob collision_terminates (default True=unchanged); set False so collisions are a per-step SOFT cost (collision_penalty still applies) but only out-of-arena crash terminates. swarm_race n_agents=3 [128,128]@120M seed 0, eval vs the hop-13 baseline (node 4b21d59b/cool-union-2681). RESULT: completion did NOT improve — DR-off 0.34->0.322, DR-on 0.21->0.206 (flat) — while collision_rate ROSE ~2.5x (0.002->0.0053 DR-off, 0.0021->0.0048 DR-on) and best_lap got slower (2.83->3.16s) with higher crash (1.3e-3). REFUTED: shared-fate termination was NOT the binding constraint on completion; removing it just made collisions cheaper so the policy tolerated ~2.5x more of them, and track congestion still capped lapping. The ~0.34 completion ceiling is set by congestion / episode length, not the termination rule — and shared-fate was doing useful work as a collision deterrent. NO-GO; knob kept default-on (True), not promoted.'
origin:
  backend: flywheel
  node_id: ffc5d9e4-cfdd-579e-97e7-f94dd33b3771
  slug: flat-dew-5721
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9324466f-4252-5c88-bd82-b61835992b33
  slug: lucky-mode-4417
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: 183a78b1f620accc89e624e58a56269fd4ff09b4d094283253cdec3323a20be8
---
## Hypothesis (from hop-13's staged hop-14a)
`swarm_race` (hop-13, `4b21d59b` / cool-union-2681) ends the whole env episode on ANY drone's collision (`drone_fail = crashed | collided`, shared fate), so a clean drone is reset for a teammate's collision — suspected to cap `lap_completion_rate` at 0.34. **Predicted:** relaxing shared-fate (collisions become a per-step soft cost, not fatal) lengthens clean drones' episodes → higher completion, with `collision_rate` staying bounded (the per-step `collision_penalty` still deters).

## Setup
Task-only knob `collision_terminates` (default **True** = unchanged hop-13 behaviour). Set **False**: `drone_fail = crashed` only; a collision still costs `collision_penalty=10`/step but doesn't terminate. `configs/swarm_race_softcol.yaml`, otherwise identical to `swarm_race.yaml` (n_agents=3, [128,128]@120M, full seam DR, seed 0). Eval DR-off + DR-on; baseline = the recorded hop-13 numbers (node `4b21d59b`, same protocol; its run dir was gitignored/cleaned so a fresh re-eval wasn't possible — noted for honesty).

## Results
| metric | condition | hop-13 baseline (shared-fate ON) | hop-14a softcol (OFF) |
|---|---|---|---|
| lap_completion | DR-off | 0.34 | **0.322** |
| lap_completion | DR-on | 0.21 | **0.206** |
| collision/step | DR-off | 0.0020 | **0.0053** |
| collision/step | DR-on | 0.0021 | **0.0048** |
| best_lap (s) | DR-off | 2.83 | 3.156 |
| best_lap (s) | DR-on | 2.89 | 3.216 |
| crash/step | DR-off | (low) | 1.28e-3 |

## Findings
1. **Completion did NOT improve** — flat-to-slightly-worse on both conditions (0.34->0.322, 0.21->0.206). The pre-registered win did not appear.
2. **Collisions rose ~2.5x** (0.002->0.0053). With collisions no longer fatal, the shared policy tolerates far more of them — the soft per-step penalty doesn't deter as strongly as termination did.
3. **Lap time and crash got worse** (best_lap 2.83->3.16s; out-of-arena crash up). More mid-pack congestion = messier racing.
4. **Mechanism:** shared-fate termination was NOT the binding constraint on completion — it was doing useful work as a hard collision deterrent. The ~0.34 completion ceiling is set by track congestion + episode length (3 drones, one tight shared loop, 12s), which removing the termination rule doesn't relieve; it just trades the deterrent for more collisions at the same completion.

## Verdict
**NO-GO (stop_reason=no-effect on completion + regressed collisions).** Relaxing shared-fate is not the lever for swarm throughput. Knob `collision_terminates` kept (default **True**, unchanged); the False mode is the tested-and-rejected variant + reproducible recipe (`configs/swarm_race_softcol.yaml`). Not promoted.

## Honesty / limits
Single seed; baseline from the recorded hop-13 node (run dir cleaned, no fresh re-eval). collision_penalty held at 10 (a clean single-variable A/B on termination); a much larger soft penalty MIGHT recover the deterrent without termination, but that converges back toward the baseline's behaviour. The real swarm-throughput levers are elsewhere.

## Next (the throughput levers that remain)
- **Scale n_agents** 3->4->6 at fixed arena — trace the collision/throughput-vs-density curve (where does coordination break?).
- **Density curriculum** (tighter arena / more drones over training).
- **swarm_formation** sibling (relative-offset targets vs a shared track).
Congestion is the real constraint; a bigger arena or fewer-drones-per-loop is more likely to lift completion than reward/termination tweaks.

## Lineage
- **builds-on** `4b21d59b` (hop-13 swarm_race): tests its staged hop-14a (relax shared-fate); refutes that shared-fate caps completion.

## Artifacts
softcol_compare.png (baseline vs softcol bars, DR-off), softcol_table.json (full DR-off/DR-on matrix).