---
node_id: b4b7bcbf-f3e6-53b3-9fc0-ff76aee6027c
slug: misty-paper-7383
title: 'hover: auto-stabilization / station-keeping policy + reusable impulse DR seam (GREEN)'
created_at: '2026-06-28T18:46:58.584156+00:00'
parents:
- aged-rice-2283
summary: 'First implementation of the auto-stability branch (aged-rice-2283): a `hover` DroneTask + a reusable impulse DR seam (push/dropped-block kicks via add_velocity/add_body_rate). Tiny [64,64] policy trained 40M steps against wind+impulses holds a world-frame setpoint and recovers from shoves/tumbles — clean hold pos_error 0.15 m / hold_rate 0.91; under full DR pos_error 0.28 m / hold_rate 0.75 / ~0 crashes (1.5e-5/step). GREEN: the branch''s hover_hold objective realized; the policy the new live Studio editor pokes at.'
origin:
  backend: flywheel
  node_id: b4b7bcbf-f3e6-53b3-9fc0-ff76aee6027c
  slug: misty-paper-7383
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
A tiny policy trained with disturbance rejection as the *objective* (hold a setpoint, recover from impulses) — not as a DR side-effect — will hold station and re-stabilize from arbitrary shoves/tumbles, and survive being poked by hand in the Studio, **iff it trains against the very impulse seam the editor will drive**.

## Setup
- **New `hover` DroneTask** (`tasks/hover.py`): gateless, single-drone, obs-v4 (11) unchanged — the body-frame vector to a world-frame **setpoint** replaces the gate/target vector (rides the reused `target` scene marker, no contract change). Reward = position bell `exp(-(d/σ)²)` + linear pull-in `−kd·d` + upright + velocity/spin damping + alive − smoothness − crash. Mixed spawns: 35% on-setpoint (hold), 65% offset + perturbed in vel/tilt/body-rate (fly-to-point + recovery).
- **Reusable impulse DR seam** (`randomization.py`): `impulse_dv()`/`impulse_dw()` — per-step Bernoulli kicks, curriculum-scaled, default off; new `WhoopDynamics.add_body_rate` mirrors `add_velocity`. Applied in `env.step` right after wind — the SAME pathway the live Studio editor drives.
- **Config** (`configs/hover.yaml`): [64,64], wind 2 m/s² + impulse_prob 0.02 / vel 2.5 m/s / rate 4 rad/s, dr_curriculum_frac 0.3, 40M steps on the RTX 5090 (~487k env-steps/s, ~80 s wall).
- **Reward iteration (honest)**: the first reward (narrow bell σ=0.45, vel_penalty 0.05) sat level-and-still at ~0.9 m offset — the bell is flat far out (no approach gradient) and the velocity penalty made staying put cheaper than flying in. Fix: dominant position (pos_scale 1→2), a linear pull-in (gradient at any range), lower vel_penalty (0.05→0.02).

## Results (Δ vs parent)
Parent `aged-rice-2283` was a placeholder branch (no task, no number). This delivers the first hover policy + the first stability metric:
- **Clean (no DR)**: mean_pos_error **0.15 m**, hold_rate **0.91** (within 0.35 m), tilt 1.7°, speed 0.10 m/s.
- **Full DR (wind 2 + impulses)**: mean_pos_error **0.28 m**, hold_rate **0.75**, tilt 13.6°, crash_rate **1.5e-5/step** (≈0).
- **Live (via `/ws/live`, hand-poked)**: push peak 2.16→0.18 m/s (velocity **arrested**); dropped-block tumble peak spin 4.38→0.15 rad/s + pos err 0.18 m (**recovered**); setpoint move → flew there, err 0.22 m (**arrived**).

## Verdict / Honesty
**GREEN** — disturbance rejection as a first-class objective works: the policy holds station, leans into wind, arrests shoves, and recovers from dropped-block tumbles without crashing. Caveats: (1) under full DR the steady tilt (13.6°) and speed (0.51 m/s) are high — it's constantly fighting wind+kicks, not a dead-still hover; (2) the hold_rate metric averages over the fly-to-point transient, understating the steady hold; (3) tagged `cluster:stability` (the branch's own cluster, connected via this parent), not reliability-dr, which would be a disconnected cluster node here. Position hold assumes a position estimate (mocap/VIO) — the sim2real caveat the branch flagged.

## Lineage
- realizes **`aged-rice-2283`** (the auto-stability / hover-hold branch — its first task + number).
- the impulse seam is the shared external-wrench primitive the interactive-perturbation Studio idea (`floral-sunset-3918`) called for; the live Studio method node builds on this policy.
- commits af3ed31 (task+seam), 89d2252 (reward tuning); repo d76ed4a.