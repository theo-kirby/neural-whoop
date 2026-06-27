# Task catalog (roadmap)

The backlog of policies/tasks the autonomous agent grows, each a `DroneTask` in
`src/neural_whoop/tasks/`. Tasks are ordered roughly by build-up of capability (single-drone →
perception → swarm). Each has a **metric** (what to optimize) and a **loose sim2real basis** (why it
plausibly transfers to a real whoop). Difficulty is relative to the green baseline.

A task is "in the catalog" when it has a registered `DroneTask`, a config, and an eval metric. The
agent picks the next item, opens a Flywheel branch, and iterates (see `AGENTS.md`).

## Status legend
✅ done · 🔜 next · ⬜ planned · 🧊 deferred (Isaac/photoreal RGB)

---

### ✅ `gate_race` — time-optimal single-drone gate racing
- **Metric:** lap time ↓ (guardrails: lap-completion rate, crash rate).
- **Obs/oracle:** obs-v4 + next-gate lookahead; state-based speed oracle (point-mass timing). No
  rendering — avoids the Blackwell camera path.
- **Sim2real basis:** CTBR + body-frame obs + airframe/seam DR; the most-studied transfer regime
  for FPV quads.
- **Baseline:** ~3.87 s best lap vs 3.47 s oracle, ~91 % completion (DR-off eval).

### 🔜 `gate_race` refinements (no new task; pure optimization)
- Better speed oracle (accel/turn-rate-limited point mass → tighter lap-time target).
- Racing-line reward (velocity-direction / minimum-jerk terms), DR/curriculum schedules.
- SHAC/BPTT via DiffAero's differentiable path; compare to PPO at equal wall-clock.

### ⬜ `target_follow` — camera-only / oracle pursuit of a moving target
- **Metric:** time-in-view + mean tracking distance ↓.
- **Obs/oracle:** pursuit obs (movable-target estimate); train render-free via the perception oracle
  + detector noise, **eval** honestly with DiffAero depth render (Blackwell-OK). `target.py` provides
  the batched motion field (static/orbit/lissajous/mixed).
- **Sim2real basis:** the render-free seam + detector-error DR is exactly the lab's validated Phase-8
  trick; a cheap onboard blob/depth detector closes the loop on hardware.

### ⬜ `hand_follow` — follow a held hand / gesture target
- **Metric:** tracking distance ↓ + responsiveness to direction changes.
- **Basis:** same perception seam; the "target" is a hand-held marker. A gesture channel (stop/come)
  can be added to the obs later.

### ⬜ `alt_sensor` — alternative-sensor module (e.g. range/flow/lidar-lite)
- **Metric:** task metric under a degraded/alternative sensor suite.
- **Basis:** swap the perception front-end (the seam is explicitly swappable); tests robustness to
  the sensor a given whoop build actually carries.

### ⬜ `explore_map` — mapping / exploration / coverage
- **Metric:** coverage fraction ↑ within a time budget (collision-free).
- **Basis:** DiffAero's depth/LiDAR render (Blackwell-OK) for the occupancy signal; render-free
  proxy oracle for fast training.

### ✅ `swarm_race` — multi-drone shared-track gate racing (first swarm task, Flywheel hop-13)
- **Metric:** swarm lap throughput at a bounded collision rate — `lap_completion_rate` ↑ +
  `collision_rate_per_step` bounded + `best_lap_time` ↓ (guardrail: out-of-arena crash rate).
- **Obs:** the single-drone racing obs (14) + nearest in-env neighbour's body-frame relative
  position (3) and velocity (3) → obs_dim 20 (MCU deploy-size flag). The neighbour channel is what
  lets the tiny shared policy keep separation.
- **Coupling:** `n_agents` drones share one course; a collision (centre-to-centre < `collision_radius`)
  penalizes the involved drones and ends the env episode (shared fate). Pure task-layer — no env
  changes (agent-flattened dynamics; collision/relative-obs in the task).
- **Sim2real basis:** same CTBR + body-frame obs + airframe/seam DR as `gate_race`; a real cheap
  range/relative-bearing estimate stands in for the neighbour vector. Shared policy across agents.

### ⬜ `swarm_formation` — N-drone formation / coverage
- **Metric:** formation error ↓ + inter-agent collisions → 0.
- **Basis:** exercises the `n_agents>1` path (agent-flattened dynamics; relative-observation coupling
  in the task layer). Shared policy across agents. The relative-position-target sibling of
  `swarm_race` (track a desired offset instead of racing a shared track).

### ⬜ `swarm_transport` — cooperative transport / shepherding
- **Metric:** payload/target delivered ↓ time, cooperation required.
- **Basis:** multi-agent coordination with a shared objective; tests emergent cooperation under the
  same tiny per-agent policy.

### ⬜ `swarm_vs_swarm` — competitive multi-agent (self-play)
- **Metric:** win rate vs a population / league.
- **Basis:** self-play over the batched env; the most open-ended discovery target.

### 🧊 Deferred branches
- **Photoreal RGB / Isaac Lab** vision: revisit when Isaac's tiled-camera Blackwell bug (#4951) is
  fixed. Until then, camera tasks train render-free and eval on DiffAero depth.
- **Web studio** (`web/`, `api/` from the lab): a later branch; not needed for the RL loop.

---

## Adding a task

1. `src/neural_whoop/tasks/<name>.py`: subclass `DroneTask`, set `n_agents` / `obs_dim` /
   `episode_len`, implement `setup / reset / observe / reward_and_done / metrics`, decorate with
   `@register_task("<name>")`.
2. Import it in `src/neural_whoop/tasks/__init__.py`.
3. Add `configs/<name>.yaml`.
4. `uv run python scripts/train.py --config configs/<name>.yaml --tensorboard`, then eval, then open
   a Flywheel node with the artifacts.

The env (`MultiAgentDroneEnv`) needs no changes — it's task-agnostic. Use `env.to_agents` /
`env.to_drones` to reshape between the flat-drone and `(env, agent)` views when a swarm task needs
inter-agent structure.
