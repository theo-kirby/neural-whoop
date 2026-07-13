# CLAUDE.md — neural-whoop working brief

Read this before changing code. It is for humans and agents alike: the architecture, the sim2real
contract, how to run things, and the locked decisions that shaped the design.

## What this is

A GPU-parallel, swarm-capable whoop RL lab on **DiffAero** (vendored pure-PyTorch quadrotor sim),
the successor to `../neural-whoop-lab` (single-drone, PyBullet, SB3-PPO). We train tiny,
quantization-friendly policies that fly a real ~32 g tiny-whoop, starting from single-drone gate
racing and expanding toward swarms. The autonomous-development loop runs on Flywheel (see
`AGENTS.md`).

## Locked decisions (do not relitigate without the user)

1. **Substrate = DiffAero**, vendored under `third_party/diffaero` (BSD-3) and pinned. Our edits
   live in the fork. Isaac Lab is **deferred** to a later Flywheel branch (its tiled-camera path
   hangs on Blackwell today).
2. **First beachhead = single-drone time-optimal gate racing** (`gate_race`), state/oracle-based so
   it never touches the Blackwell-broken camera path. Metric = **lap time**.
3. **Autonomy = full, local-only.** The agent edits code, adds tasks, runs/tunes experiments on the
   5090; **no managed cloud compute**; bounded by a training-step / wall-clock budget. The Flywheel
   graph is the audit trail. Everything lives on this machine; both repos
   (`theo-kirby/neural-whoop`, `theo-kirby/nw-viz`) push to GitHub.

## Autonomy & the Flywheel record

Capture work **as you go, on your own** — don't wait to be asked. After each meaningful unit (a
feature, an experiment result, a tooling addition, a fixed bug, a visualization checkpoint): commit
with a clear message, **push** the affected repo(s), update any docs/this file that drifted, and
write a **Flywheel node** referencing the commit SHA(s). Commit at natural seams, not one big
end-of-session dump.

**Cardinal rule — no empty nodes.** Every empirical node (an experiment or measurement) carries
**≥1 finalized artifact** — the standard visual pack, including the `run.json` reproducibility
manifest (`docs/VISUAL_CONTRACT.md`) — **and** a written **summary** stating the concrete change
vs its parent, the metric number, and the verdict. *If it isn't backed by an artifact and a written
result, it didn't happen.* A bare title is not a summary.

- **Summary discipline:** summary = change-vs-parent + the metric Δ + verdict, reproducible from the
  text alone (e.g. "[128,128] policy: 3.29→2.91 s best lap, −12%, GREEN").
- **Body skeleton:** **Hypothesis → Setup → Results (with the Δ vs parent/baseline) → Verdict /
  Honesty → Lineage.** Record negative/refuted results in the same shape. Canonical exemplar:
  the `time_penalty` reward-shaping node (`morning-base-2167`).
- **Definition of done / verify:** after committing a node, **re-read it** (`flywheel_get_node`,
  `projection=full`) and confirm artifacts attached + summary written + tags set (`kind:` ×1,
  `outcome:` if resolved, `cluster:` ≥1) before moving on. Apply this to your own work.
- **Tooling:** Flywheel mutations go through the MCP tools — artifacts are **prepare → PUT
  bytes (202) → finalize**, done *before* the commit; the `flywheel-auto` / `flywheel-lookahead`
  skills drive the autonomous loop. The operating loop lives in `AGENTS.md`; the graph-shape +
  node conventions in `docs/FLYWHEEL.md` — follow those rather than restating them here.

The Flywheel graph is the point of the project's record: a **very connected, very exploratory, very
honest** account of the R&D process — **not a linear chain** (if it were a chain there'd be no
reason for it to be a graph). So:

- Give each node its **true parents** — multiple parents when work builds on several prior
  results/methods; branch off a shared baseline when probing alternatives; link back to the
  idea/hypothesis a node tests or refutes. Parent on what the work genuinely descends from, not just
  "whatever was latest."
- Use varied node kinds liberally: experiments, results, methods/tooling, **ideas**, **hypotheses**,
  **viz/checkpoint** moments, refutations (RED) and confirmations (GREEN). Cross-link related nodes
  across branches.
- Be **honest**: record negative/refuted results too, not just wins.

### Node tags (the kind/outcome/cluster taxonomy)

Flywheel **removed** the typed body fields `kind`/`node_type`/`hypothesis` from the node model — the
canonical way to express what a node *is* is now **graph tags** (created once on the root, then
assigned to nodes). Untagged nodes are invisible to filtered/zoomed-out graph views, so **tag every
new neural-whoop node** with one `kind:`, an `outcome:` if it has a verdict, and ≥1 `cluster:`. The
taxonomy (all defined on the root `morning-feather-7342`):

- **`kind:`** (exactly one) — `experiment` · `measurement` (characterize, no hypothesis) · `method`
  (tooling/infra/viz) · `idea` (framing / north-star / setup) · `hypothesis` (an untested, testable
  prediction).
- **`outcome:`** (empirical nodes) — `GREEN` (confirmed win) · `RED` (refuted) · `NO-GO` (no
  effect / not worth shipping). Mixed/Pareto results may carry none (honest signal that it's nuanced).
- **`cluster:`** (≥1, the workstream) — `reward-shaping` · `reliability-dr` · `generalization` ·
  `swarm` · `tooling-viz` · `capacity-budget`. These are the contract's "cluster tags so zoomed-out
  views stay legible." Add a new cluster when a genuinely new workstream opens.
- **`★ studio-baseline`** — a `one_only=true track_history=true` *pointer* tag marking the current
  recommended studio policy node; moving it records history. Use one_only pointers (not category
  tags) for "current X" markers.

**Hard rule discovered the hard way: a `cluster:` tag's assigned node set must form a CONNECTED
subgraph** (every node carrying it reachable from another via parent/child edges *through other
nodes carrying it*). This applies to **cluster tags only** — `kind:`/`outcome:` tags assign freely to
scattered nodes. Consequences: (1) only tag a node with a `cluster:` if it's adjacent to that cluster's other members
— a reward node living in the reliability branch can't carry `cluster:reward-shaping`; (2) when
building up a cluster, **assign tags sequentially anchor-first**, not in parallel — concurrent
`set_node_tag_assignments` calls race and a child gets rejected as "disconnected" before its parent
is tagged. Tag creation bumps the root revision (sequence creates, incrementing `expected_revision`).

## Architecture

```
policy (TinyPolicy MLP, obs-v4 -> act-v2 CTBR)
   |  action_to_diffaero()  (normalized [-1,1] -> DiffAero CTBR convention)
   v
MultiAgentDroneEnv  (src/neural_whoop/envs/base.py)
   ├─ WhoopDynamics  (dynamics/whoop.py)  -> DiffAero QuadrotorModel (batched, differentiable)
   ├─ DomainRandomizer (randomization.py) -> wind / rate-gain / thrust / action+uplink latency / obs-noise
   ├─ perception oracle (perception/)     -> body-frame target vector (+ optional detector noise)
   └─ DroneTask (envs/registry.py)        -> obs / reward / termination / curriculum / metrics
        └─ gate_race (tasks/gate_race.py)
training/ppo.py  -> torch-native PPO over the batched env
eval/rollout.py  -> deterministic rollout + lap-time metrics (+ evaluate_and_record hero capture)
eval/pack.py     -> standard visual pack assembler (rollout -> replay -> artifacts)
training/export.py -> TorchScript / ONNX deploy policy
viz/replay.py    -> versioned self-describing replay schema + recorder (the "visual contract")
viz/render.py    -> lazy renderer: trajectory / synthetic FPV / training curves / comparison
```

**Visual observability seam (`viz/`).** A versioned replay schema
(`format="neural-whoop-replay"`, `docs/VISUAL_CONTRACT.md`) is the durable record of what a policy
actually did: per-step hero telemetry + the contract metadata to interpret it (gate geometry for
racing tasks; an additive per-frame `scene` channel — moving target/anchor/slot + command — for the
gateless follow/formation tasks, via `DroneTask.scene_objects()`). `viz/replay.py` is
pure stdlib+numpy (imports without the sim/viz extras); `viz/render.py` is lazily-imported (the
`viz` extra: matplotlib + Pillow + tbparse) and turns a replay into Flywheel-native PNG/CSV
artifacts. Recording is **hero-subset** (full frames for a few drones; aggregate metrics over the
full population) and the training path stays render-free. The same JSON shape feeds the in-repo
**Studio** (`web/studio/`, served by `scripts/serve.py` — see below) **and** the sibling
**`../nw-viz/`** project (`theo-kirby/nw-viz`) — a standalone pure-JS/Three.js tool (no Node in this
repo) that renders a replay into a composited **hero MP4**: a fixed wide 3D course shot plus synced
onboard-FPV and top-down picture-in-picture insets, captured headlessly (Playwright + SwiftShader →
ffmpeg). It consumes the locked replay contract unchanged; `scripts/viz.py --video` optionally
shells out to it (non-fatal if absent). `render_depth` is a documented stub for the future DiffAero
Taichi renderer (deferred — Blackwell camera path).

**Studio (`web/studio/` + `src/neural_whoop/studio/`).** An interactive browser viewer:
`scripts/serve.py` (the `studio` extra: FastAPI + uvicorn) lists saved policies and courses, runs a
**fixed-course** rollout on demand (`studio/rollout.py` → `evaluate_and_record(group=True)`, the
same v2 group-episode path), and serves the replay to a static Three.js frontend that plays it back
(3D wide + **per-drone** FPV/top-down insets in movable/resizable PiP frames, play/pause/scrub, plus
a policy-metadata panel and TensorBoard training charts parsed via the dependency-free
`studio/tbscalars.py`). A **Live** tab (`studio/live.py` + `/ws/live` websocket + `web/studio/live.js`)
steps a policy in real time and lets you disturb it from the browser — blow wind, push, drop a
(modeled) block, and click to relocate a `hover` policy's setpoint — all riding the **same impulse
seam** (`add_velocity`/`add_body_rate`) the policy trained against; single-flight with `/api/rollout`
via the shared lock. The env+agent construction is shared via `studio/rollout.py::build_session`; the
live frame schema is the recorder's via `eval/rollout.py::hero_pose_snapshot`. You pick a **policy**, a **course** (a seeded
`assets/courses/*.yaml` or an arena **preset**), and a **drone count**. Drone-count maps to the
substrate per the policy's **task family**: gated single-drone (`gate_race`) → `n_envs = drone_count,
n_agents = 1` (independent racers on one fixed track); gated swarm (`swarm_race`) → `n_envs = 1,
n_agents = drone_count` (collision-aware shared-track swarm); gateless **follow**
(`target/hand/gesture/command_follow`) → `n_envs = drone_count, n_agents = 1` (independent followers,
each its own moving target); gateless **formation** (`swarm_formation`) → `n_envs = 1, n_agents =
drone_count` (ring around one moving anchor). The gateless families have **no course** (the
`/api/policies` `family`/`needs_course` flag hides the course selector); what they track rides in the
replay's `scene` channel, drawn as a target/anchor/slot marker (+ command chip). The frontend loads three.js from a CDN importmap (no Node toolchain in this
repo); the UI is a flat 2D style (custom-styled selects, rounded panels). The gate Editor tab
(author/validate/save a course) and the Live interaction tab are both implemented. A **Bench** tab
(`studio/flight.py` + `/ws/flight` + `web/studio/bench.js`) is the always-on **real-drone** dashboard:
it flies the actual Air65 II over the MSP bridge via the pure-stdlib flight engine extracted from
`scripts/pilot.py` into `neural_whoop.pilot` (`FlightController`/`config`/`policy`/`telemetry`;
`pilot.py` is now a thin CLI shim). An always-on `FlightManager` (a background thread, **zero
torch/numpy**, **not** under `ROLLOUT_LOCK`) runs the `pilot.py fly` 3·2·1→hover→land state machine and
streams telemetry; the software **Start** only sets the flight clock and is enabled **only when
telemetry shows ARMED + MSP-OVERRIDE** on the radio (which still owns enable + instant kill). An opt-in
**parallel CPU-torch sim** (`/ws/live`) flies the same policy beside the real drone, and a completed
flight auto-runs `flight_report.py`. A **fake bridge** (`--bridge fake` / `NW_FLIGHT_FAKE=1`) runs it
all with no hardware. See `docs/STUDIO.md` and `docs/SIM2REAL.md`.

**Key design choice — agent flattening.** Multi-agent envs flatten `(n_envs, n_agents)` into a
single `n_drones = n_envs * n_agents` dynamics batch (DiffAero runs with `n_agents=1` internally).
This sidesteps DiffAero's single-batch rate controller and keeps all multi-agent coupling
(collisions, relative observations) in *our* env/task layer. The baseline runs `n_agents=1`; swarm
tasks just raise it. Each drone is one PPO sample (shared-policy parameter sharing).

**Render-free perception seam.** Primary training feeds the policy the ground-truth body-frame
target vector via `OracleEstimator`, optionally corrupted by a batched `DetectorNoise` model
(bearing/range/FOV/dropout) so the policy survives real detection noise without rendering a pixel.
Honest camera-only eval (DiffAero depth render, Blackwell-OK) is a later hook; photoreal RGB / Isaac
is deferred.

## The contract (sim2real seam)

See `docs/CONTRACT.md` for the full spec. In short:

- **obs-v4** (length 11, body-frame, heading-invariant): `[target_rel(3), vel_body(3), roll, pitch,
  p, q, r]`. `gate_race` appends a 3-vector next-gate lookahead → obs_dim 14.
- **act-v2** (length 4, CTBR, normalized `[-1,1]`): `[collective_thrust, roll_rate, pitch_rate,
  yaw_rate]`. `action_to_diffaero()` maps it to DiffAero's controller (thrust `1.0` == hover).
- The env applies **domain randomization** on top: airframe (mass/inertia/drag, inside DiffAero) +
  seam (wind, rate-gain, thrust scale, action latency, obs noise). Training across these is what
  makes a tiny policy transferable.

## Vendored DiffAero edits (third_party/diffaero)

We patched the fork so its pure-torch dynamics core runs on Blackwell without the heavy rendering
stack:
- `utils/p3d_compat.py` — pure-torch `quaternion_to_matrix`/`quaternion_raw_multiply`; the 4
  pytorch3d import sites now point here (pytorch3d is a compiled CUDA ext that won't build on
  cu128).
- `__init__.py` — lazy subpackage imports (the eager imports dragged in hydra/wandb/taichi/open3d).
- `dynamics/base_dynamics.py` — dropped an unused `Logger` import (hydra).
- `utils/math.py` — clamped the `asin` argument in `quaternion_to_euler` (a real NaN bug at
  near-vertical pitch that poisoned the policy).
- `dynamics/whoop.py` (ours) additionally **saturates body rates/velocity each step** — DiffAero
  defines but never applies its state bounds, and a whoop's tiny inertia makes the RK4 rotational
  dynamics go unstable past the rate limit.

We use **only** DiffAero's dynamics core (`dynamics/`, `utils/math.py`, `utils/randomizer.py`) — its
env/algo/rendering layers are not installed. Deps from DiffAero: just `torch` + `omegaconf`.

## How to run

```bash
uv run python scripts/env_check.py                 # Milestone-0 gate (run first / after env changes)
uv run pytest -q                                   # tests
uv run python scripts/train.py --config configs/gate_race.yaml --tensorboard
python scripts/eval.py --config configs/gate_race.yaml --from runs/<run>/ckpt_final.pt --no-dr --export

# Visual observability (the "visual contract" — see docs/VISUAL_CONTRACT.md):
uv pip install -e '.[viz]'                          # renderer deps (matplotlib/Pillow/tbparse); replay itself is core
uv run python scripts/eval.py --config configs/gate_race.yaml --from runs/<run>/ckpt_final.pt --no-dr --record
uv run python scripts/viz.py  --config configs/gate_race.yaml --from runs/<run>/ckpt_final.pt --no-dr \
    --baseline runs/<parent>/replay.json.gz --out runs/<run>/viz   # full standard pack
```

`scripts/train.py` flags: `--config`, `--task`, `--steps`, `--n-envs`, `--seed`, `--name`,
`--tensorboard`, `--export`, `--algo {ppo,shac}` (shac reserved for DiffAero's differentiable RL).
Experiments are configured by YAML (`configs/`); `experiment.py` wires config → env + task + PPO.

`scripts/viz.py` builds the **standard visual pack** (`replay.json.gz`, `trajectory.png`,
`fpv_*.png`, `training_curves.png`, `comparison.png` + `table.csv`) — exactly what the autonomous
loop attaches to each empirical node. `scripts/eval.py --record` writes just the portable replay
(no viz extra needed); `--viz` additionally builds the pack. Renderers degrade gracefully (no TB
events → no curves; no `--baseline` → no comparison).

```bash
# Hero MP4 (3D wide shot + FPV/top-down PiP) via the sibling nw-viz project (one-time: cd ../nw-viz && npm install):
uv run python scripts/viz.py --config configs/gate_race.yaml --from runs/<run>/ckpt_final.pt --no-dr --video
cd ../nw-viz && node capture.mjs --replay ../neural-whoop/runs/<run>/replay.json.gz --out out/<run>.mp4  # or directly

# Interactive Studio (browser viewer: pick policy + course + drone count, watch it fly) — docs/STUDIO.md:
uv pip install -e '.[studio]'                       # FastAPI + uvicorn
uv run python scripts/seed_courses.py               # (once) seed bigger assets/courses/*.yaml
uv run python scripts/serve.py                      # -> http://127.0.0.1:8000

# Flight-log analysis (turn a real pilot flight CSV into a Flywheel-native pack) — docs/SIM2REAL.md:
uv run python scripts/flight_report.py --flight runs/pilot/<flight>.csv --out runs/pilot/<flight>_report
#   -> flight_telemetry.png / link_histogram.png / flight_summary.json / flight_metrics.csv /
#      replay.json.gz (Studio-playable; z = measured bridge-ToF height when logged, ∫vz stub
#      otherwise) / run.json  (viz PNGs need '.[viz]')
python3 scripts/sim_vs_real.py --flight runs/pilot/<flight>.csv --weights runs/<run>/policy_weights.json
#   -> offline action MAE (predicted vs logged): the quantitative "policy is faithful in-flight" check
#      (pure stdlib + scripts/pilot.py — no torch/numpy, runs on the bench Mac)
```

**Course geometry knobs.** `gate_race`/`swarm_race` configs now surface `step_min`/`step_max`
(inter-gate hop, m) + `max_turn_deg` alongside `arena_radius`/`z_*`/`bound_*`. Defaults (1.5/2.8 m)
reproduce the tight indoor track; raise them with a bigger `arena_radius`/`bound_xy` for spread-out
courses (`configs/gate_race_spread.yaml`). `neural_whoop.course.ARENA_PRESETS`
(`tight`/`spread`/`big`/`giant`) packages matched radius+hop sets for the Studio + `seed_courses.py`.

## Adding a task (the main extension point)

Subclass `DroneTask` in `src/neural_whoop/tasks/<name>.py`, implement `reset / observe /
reward_and_done / metrics`, decorate with `@register_task("<name>")`, import it in
`tasks/__init__.py`, add a `configs/<name>.yaml`. No env changes needed. See `docs/TASK_CATALOG.md`
for the roadmap and each task's loose sim2real basis.

## Conventions

- Everything batched and GPU-resident; **no per-step `.item()`/CPU syncs in the hot path** (metrics
  are computed at log cadence via `task.metrics()`).
- Quaternions are real-last (xyzw), matching DiffAero. Body frame: +x forward (camera), +y left,
  +z up.
- Keep policies tiny and export-clean (the whoop runs them on a microcontroller).
- Pure modules (contract, course, reward, perception, target) carry the validated sim2real design
  and are unit-tested without the simulator.
