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

### ✅ `target_follow` — standoff keep-in-view of a moving target through a noisy detector
- **Metric:** `time_in_view_rate` ↑ + `mean_track_error` (|distance − d*|) ↓ (both from ground truth).
- **Status:** implemented (`tasks/target_follow.py`, `configs/target_follow{,_clean}.yaml`). Standoff
  keep-in-view (hold d*=1.5 m, target centered in a 110° FOV) over an orbit/lissajous mover; obs-v4
  unchanged (target estimate replaces the gate vector), run through the perception oracle + the
  `DetectorNoise` seam (bearing/range/FOV/dropout + stale-hold). `target.py` supplies the batched
  motion field. **First empirical result (Flywheel `cool-resonance-0983`, MIXED/Pareto):**
  detector-training gives condition-invariance + ~65× fewer crashes under noise, but bought it by
  backing off (2.17 m vs d*=1.5 m); the naive oracle policy does *not* lose the target under noise
  (in-view 0.996) — the gap is crash-rate, not tracking. The tighter-standoff-reward follow-up
  (`old-leaf-3989`) was **refuted** (`royal-wildflower-3231`, RED): tightening only nudged standoff
  2.17→1.97 m and only by spending crash-robustness (~8×) — the back-off is a genuine
  **robustness↔accuracy frontier set by the perception, not a reward artifact** (same shape as the
  racing tight↔big Pareto). The **detector-regime sweep** (`nameless-bar-9184`, measurement/RED)
  then localized *which* perception axis: sweeping dropout {0→0.10} and FOV {110→150°} with the
  reward held identical leaves standoff **flat at ~2.2–2.5 m** (zero-dropout sits at 2.47 m, *farther*
  than the 0.05 anchor) — the back-off is **insensitive to detection availability** and is driven by
  per-fix **bearing/range precision** (3° / 10%, present on every fix); only removing the detector
  entirely recovers d* (the clean policy, at 10–60× the crash rate). So the lever is **not**
  dropout-coasting memory but precision-*filtering* (EMA/Kalman on the noisy fix) or a better onboard
  detector. **That precision-filtering lever LANDED (`long-tree-2976`, GREEN):** an in-place **EMA**
  on the body-frame estimate (`estimate_ema_alpha`; obs stays 11 / MCU-clean) averages successive
  noisy fixes → standoff **2.17→1.54 m** (track_err 0.91→0.25, ≈ the clean policy) at crash 8.7e-5 —
  **5.6× safer than the brittle clean policy** and below the racing reliability bar, condition-invariant.
  A new Pareto-dominant corner (accurate *and* robust); the EMA is a reusable perception primitive for
  any detector-fed task. The α-sweep follow-up (`flat-waterfall-0121`) found a **threshold**: α=0.85 is
  the *robust* operating point (both seeds hold d*, dominating 0.7), α=0.7 is seed-fragile (1/2 seeds
  back off — the original single-seed GREEN sat on the knife-edge), α=0.5 too weak; the recommended
  default is **0.85** (`configs/target_follow_ema.yaml`). Honest camera-only eval via the DiffAero
  depth render remains a later hook.
- **Sim2real basis:** the render-free seam + detector-error DR is exactly the lab's validated Phase-8
  trick; a cheap onboard blob/depth detector closes the loop on hardware.

### ✅ `hand_follow` — close-follow a jerky hand target through a noisy detector (Flywheel hop-23)
- **Metric:** `follow_hold_rate` ↑ (frac of steps within `hold_tol` of d* — responsiveness) +
  `mean_track_error` ↓ + `time_in_view_rate` ↑ (all ground truth).
- **Status:** implemented (`tasks/hand_follow.py`, subclasses `target_follow`; `configs/hand_follow_*.yaml`).
  Close-follows (d*=0.8 m) a **`KIND_ZIGZAG`** triangle-wave hand mover (sharp, abrupt direction
  reversals — the closed-form stand-in for a held hand), through the same detector seam. **Result
  (Flywheel `<hand_follow>`, GREEN):** the clean policy follows the jerky hand at hold **0.996**
  (track_err 0.11, ~0 crash); detector noise degrades it (hold 0.996→**0.630**, backs off 0.8→1.05 m);
  the **EMA(0.85) primitive RECOVERS it on abrupt motion** (hold 0.630→**0.985**, standoff back to
  ≈d*). The lag concern (EMA failing on sharp reversals) did **not** materialize at target_speed 1.8 —
  variance-reduction still outweighs lag, so the EMA's validated envelope (smooth `target_follow`)
  **extends to jerky motion**. A gesture channel (stop/come) can be added to the obs later.
- **Basis:** same perception seam; the "target" is a hand-held marker. The `KIND_ZIGZAG` mover is the
  first non-smooth motion in `target.py`.

### ✅ `gesture_follow` — command-conditioned hand following (STOP/GO gesture channel) (Flywheel hop-25)
- **Metric:** `follow_hold_rate` (frac of GO steps within `hold_tol` of d*) + `stop_compliance` (frac
  of STOP steps with speed < `stop_speed_thresh`) — a good policy scores high on **both**.
- **Status:** implemented (`tasks/gesture_follow.py`, subclasses `hand_follow`; `configs/gesture_follow.yaml`).
  Appends a discrete **STOP/GO command bit** to the obs (**obs_dim 11→12**, the first follow-seam obs
  growth — MCU note: +1 channel); the shared policy follows the jerky hand on GO and hovers in place on
  STOP. The command is a piecewise-constant per-env bit that flips at random, so within one episode the
  policy must read `obs[-1]` and switch behaviours. **Result (Flywheel `gesture_follow`, GREEN):** the
  first **command-conditioned** policy in the lab works — `stop_compliance` **0.947** (hovers on
  command), `follow_hold_rate` **0.583** (follows on command), balanced exposure (go_fraction 0.495),
  crash 1.6e-5 (safest in the catalog). The policy genuinely *uses* the channel (a pure follower scores
  ~0 stop_compliance; a pure hoverer ~0 follow_hold). Honest cost: GO-follow precision drops vs pure
  `hand_follow` (0.583 vs 0.985) — a **re-acquisition tax** (the hand drifts away during each STOP, so
  resumed-GO steps spend time catching up) plus the tiny net splitting capacity across two behaviours.
- **Basis:** the foundation for gesture-controlled flight; a richer gesture vocabulary (come/go/land)
  is a natural extension of the command channel.

### ⚠️ `command_follow` — 3-way command vocabulary (STOP/NEAR/FAR), scales-but-degrades (Flywheel hop-26)
- **Metric:** `stop_compliance` + `near_hold` (d*=0.7) + `far_hold` (d*=1.8) — a command-ignoring policy
  cannot score on both near AND far (non-overlapping bands).
- **Status:** implemented (`tasks/command_follow.py`, subclasses `hand_follow`; `configs/command_follow.yaml`).
  Extends the gesture channel to a 3-way command via one obs scalar (obs_dim 12). **Result (nuanced):**
  the channel SCALES — three distinguishable behaviors emerge (nonzero near 0.307 AND far 0.255 at
  1.1m-apart bands proves the policy reads the command), STOP 0.698, in_view 0.933, crash 2.5e-5 — but
  per-command PRECISION degrades vs the 2-way `gesture_follow` (stop 0.95→0.70, follow 0.58→0.25-0.31).
  A [128,128] net holds a 3-command vocabulary LOOSELY: capacity split 3 ways + compounded
  re-acquisition transients (each command resample jumps the target while the hand keeps moving).
- **Basis:** characterizes how the command-conditioned capability scales with vocabulary size; bigger
  net or curriculum is the lever to tighten the per-command precision.

### ✅ `hover` — auto-stabilization / station-keeping with disturbance recovery
- **Metric:** `mean_pos_error` (|setpoint − pos|) ↓ + `hold_rate` (frac of steps within `hold_radius`)
  ↑ + `crash_rate_per_step` (guardrail); `mean_speed`/`mean_tilt_deg` characterize the hold.
- **Obs/oracle:** obs-v4 (11), unchanged — the body-frame vector to a world-frame **setpoint**
  replaces the gate/target vector; gateless, single-drone, state-based (no pixels).
- **Status:** implemented (`tasks/hover.py`, `configs/hover.yaml`, tiny `[64,64]` net). Reward =
  position bell + upright + velocity/spin damping + alive − smoothness − crash; mixed
  hold/fly-to-point/recover spawns. Trained against **wind + the impulse DR seam** (push + dropped-
  block tumble) so it survives the live Studio editor's disturbances.
- **Baseline (40M):** clean hold `pos_error` 0.15 m / `hold_rate` 0.91 / tilt 1.7°; under full DR
  (wind 2 + impulses) `pos_error` 0.28 m / `hold_rate` 0.75 / ~0 crashes — leans into wind, arrests
  shoves, recovers from dropped-block tumbles. The policy the **Live** Studio tab pokes at.
- **Sim2real basis:** the impulse seam (`add_velocity`/`add_body_rate`) drives both training and the
  editor, so what the editor throws is exactly what the policy was hardened to reject.

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

### ✅ `swarm_formation` — N-drone ring formation around a moving anchor (second swarm task, Flywheel hop-15)
- **Metric:** `mean_formation_error` (dist to assigned slot) ↓ + `formation_hold_rate` (frac within
  `hold_tol`) ↑ at bounded `collision_rate_per_step`.
- **Status:** implemented (`tasks/swarm_formation.py`, `configs/swarm_formation.yaml`). N drones each
  hold their **own** slot on a ring around a slowly-moving anchor (reuses the `target.py` mover);
  shared policy + nearest-neighbour obs (obs 17) + collision penalty; no shared track. **First result
  (Flywheel `raspy-moon-0909`, GREEN):** the ring forms+holds tightly — formation_error 0.17 m,
  hold_rate **0.997**, **ZERO collisions**, DR-robust. Confirms the density-curve prediction
  (`proud-wood-6049`): own-slot formation sidesteps the shared-track congestion that capped
  `swarm_race` (0.34 completion / 0.002 collisions/step). Caveat: collisions don't arise here, so it's
  a weak collision-avoidance stress — that lives in shared-track racing / denser formations.
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
- **Web studio** (`web/studio/` + `src/neural_whoop/studio/`): **shipped** (first cut) — a
  FastAPI + Three.js viewer to watch saved policies fly selectable courses with a chosen drone
  count (`scripts/serve.py`, `docs/STUDIO.md`). The drag-to-place gate **Editor** and **Metrics**
  charts from the lab studio remain deferred.
- **Spread courses**: gate spacing is now a config knob (`step_min`/`step_max`/`max_turn_deg`) +
  `ARENA_PRESETS`; `configs/gate_race_spread.yaml` trains on far-apart gates (oracle lap ~7 s vs
  ~3–4 s tight). Set up for the autonomous loop; not yet run to convergence.

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
