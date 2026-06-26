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

## Architecture

```
policy (TinyPolicy MLP, obs-v4 -> act-v2 CTBR)
   |  action_to_diffaero()  (normalized [-1,1] -> DiffAero CTBR convention)
   v
MultiAgentDroneEnv  (src/neural_whoop/envs/base.py)
   ├─ WhoopDynamics  (dynamics/whoop.py)  -> DiffAero QuadrotorModel (batched, differentiable)
   ├─ DomainRandomizer (randomization.py) -> wind / rate-gain / thrust / latency / obs-noise
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
actually did: per-step hero telemetry + the contract metadata to interpret it. `viz/replay.py` is
pure stdlib+numpy (imports without the sim/viz extras); `viz/render.py` is lazily-imported (the
`viz` extra: matplotlib + Pillow + tbparse) and turns a replay into Flywheel-native PNG/CSV
artifacts. Recording is **hero-subset** (full frames for a few drones; aggregate metrics over the
full population) and the training path stays render-free. The same JSON shape feeds the lab's
`web/replay-viewer/` Three.js viewer **and** the sibling **`../nw-viz/`** project
(`theo-kirby/nw-viz`) — a standalone pure-JS/Three.js tool (no Node in this repo) that renders a
replay into a composited **hero MP4**: a fixed wide 3D course shot plus synced onboard-FPV and
top-down picture-in-picture insets, captured headlessly (Playwright + SwiftShader → ffmpeg). It
consumes the locked replay contract unchanged; `scripts/viz.py --video` optionally shells out to it
(non-fatal if absent). `render_depth` is a documented stub for the future DiffAero Taichi renderer
(deferred — Blackwell camera path).

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
```

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
