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
reference/       -> HAND-AUTHORED reference maneuvers (pure numpy): the trajectory we WANT
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
**Studio** (`web/studio/`, served by `scripts/serve.py` — see below) **and** the in-repo **video
capturer**: `web/capture/` + `scripts/capture_video.py` (the `capture` extra: playwright +
imageio-ffmpeg). The capture page is *not* a second renderer — it imports the Studio's own
`scene.js` / `environment.js` / `geometry.js` / `drone-model.js` / `playback.js`, so the video is
the dashboard's look (CAD chassis, greybox room) and cannot drift; what it adds is the cinematic
mode: clean full frame, a precomputed camera track (`--shot fit|tripod|follow`), **true-scale**
airframe (82 mm, vs the Studio's ~7× hero glyph), spinning props, and title/phase captions.
**`--preset hero` is the standardized concept shot** — the same invocation gives the same picture on
any replay, because everything that would otherwise be tuned per clip is derived: `follow` holds a
constant offset from a smoothed subject track (so apparent size and the horizon are fixed *by
construction*, vs a tripod's 3× size swing), `--backdrop floor` swaps the walled box for a fogged
cyclorama (nothing can sweep through frame), the 1 m grid gains a framing-sized fine mesh, and a
steep key puts the shadow under the airframe. The Python
driver serves `web/` on loopback, drives headless Chromium (SwiftShader) with `renderFrame(i)` →
screenshot (the **frame index is the only clock**), and pipes PNGs to ffmpeg — same shape the
sibling `../nw-viz` Node project had, which is now only a fallback. `scripts/viz.py --video` and
the Studio's `/api/export` both route through it. `render_depth` is a documented stub for the
future DiffAero Taichi renderer (deferred — Blackwell camera path).

**Studio (`web/studio/` + `src/neural_whoop/studio/`).** An interactive browser viewer with **two
tabs** (a sim-to-real pair) and a **draggable scene/sidebar divider** (width persisted):
`scripts/serve.py` (the `studio` extra: FastAPI + uvicorn) lists saved policies and courses, runs a
**fixed-course** rollout on demand (`studio/rollout.py` → `evaluate_and_record(group=True)`, the
same v2 group-episode path), and serves the replay to a static Three.js frontend. The
**Simulation** tab plays it back (3D wide + **per-drone** FPV/top-down insets in PiP frames,
play/pause/scrub, plus a policy-metadata panel and TensorBoard training charts parsed via the
dependency-free `studio/tbscalars.py`), and an **✎ Edit course** toggle overlays the gate editor
(author/validate/save a course; `editor.js`) on the *same* scene — Save & fly runs the saved course
without a tab switch. The **Live tab is gone**, but its backend (`studio/live.py` + the `/ws/live`
websocket) is retained: it steps a policy in real time riding the **same impulse seam**
(`add_velocity`/`add_body_rate`) the policy trained against, single-flight with `/api/rollout` via
the shared lock, and now serves the Real tab's **parallel-sim twin**. The env+agent construction is
shared via `studio/rollout.py::build_session`; the live frame schema is the recorder's via
`eval/rollout.py::hero_pose_snapshot`. You pick a **policy**, a **course** (a seeded
`assets/courses/*.yaml` or an arena **preset**), and a **drone count**. Drone-count maps to the
substrate per the policy's **task family**: gated single-drone (`gate_race`) → `n_envs = drone_count,
n_agents = 1` (independent racers on one fixed track); gated swarm (`swarm_race`) → `n_envs = 1,
n_agents = drone_count` (collision-aware shared-track swarm); gateless **follow**
(`target/hand/gesture/command_follow`) → `n_envs = drone_count, n_agents = 1` (independent followers,
each its own moving target); gateless **formation** (`swarm_formation`) → `n_envs = 1, n_agents =
drone_count` (ring around one moving anchor). The gateless families have **no course** (the
`/api/policies` `family`/`needs_course` flag hides the course selector); what they track rides in the
replay's `scene` channel, drawn as a target/anchor/slot marker (+ command chip). The frontend loads three.js from a CDN importmap (no Node toolchain in this
repo); the UI is a flat 2D style (custom-styled selects, rounded panels). The **Real** tab
(`studio/flight.py` + `/ws/flight` + `web/studio/bench.js`) is the always-on **real-drone** dashboard:
it flies the actual Air65 II over the MSP bridge via the stdlib-only flight engine extracted from
`scripts/pilot.py` into `neural_whoop.pilot` (`FlightController`/`config`/`policy`/`telemetry`;
`pilot.py` is now a thin CLI shim). **One exception to "stdlib-only", added with the ESP-NOW link:**
a *serial* bridge spec (the ESP-NOW USB dongle — `serial:/dev/…` or a bare `/dev/…` path, and
`pilot.py --serial`) constructs `MspClient`, which imports **pyserial** lazily; the WiFi/UDP path is
unchanged and still stdlib. `pyserial` is therefore in the `studio` extra as well as `bench`.
An always-on `FlightManager` (a background thread, **zero
torch/numpy**, **not** under `ROLLOUT_LOCK`) runs the `pilot.py fly` 3·2·1→hover→land state machine and
streams telemetry; the software **Start** only sets the flight clock and is enabled **only when
telemetry shows ARMED + MSP-OVERRIDE** on the radio (which still owns enable + instant kill). An opt-in
**parallel CPU-torch sim** (`/ws/live`) flies the same policy beside the real drone, and a completed
flight auto-runs `flight_report.py`. A **⌖ Calibrate** toggle is a Betaflight-setup-style close-up
attitude check: camera zoomed onto the glyph (`cameras.js::frameDrone`), full roll/pitch/yaw
orientation (yaw forwarded from `MSP_ATTITUDE`; gyro-integrated, no magnetometer), a degree readout,
and four rolling sidebar charts (attitude / gyro rates / battery+throttle / link age). A **fake
bridge** (`--bridge fake` / `NW_FLIGHT_FAKE=1`) runs it all with no hardware. See `docs/STUDIO.md`
and `docs/SIM2REAL.md`.

**Key design choice — agent flattening.** Multi-agent envs flatten `(n_envs, n_agents)` into a
single `n_drones = n_envs * n_agents` dynamics batch (DiffAero runs with `n_agents=1` internally).
This sidesteps DiffAero's single-batch rate controller and keeps all multi-agent coupling
(collisions, relative observations) in *our* env/task layer. The baseline runs `n_agents=1`; swarm
tasks just raise it. Each drone is one PPO sample (shared-policy parameter sharing).

**Reference maneuvers (`reference/`, `docs/REFERENCE_MANEUVER.md`).** Everything above renders a
*policy rollout* — what the drone did, which we then grade. `reference/` is the other half: an
artifact saying what it **should** do. A maneuver is authored by hand, deterministically, and every
physical quantity (attitude, body rates, collective, and the IMU's specific force) is **derived**,
not guessed. It is pure numpy + stdlib — no torch, no simulator — the same convention as
`contract`/`course`/`reward`. `scripts/reference_flip.py` emits a 50 Hz `replay.json.gz` (the
**video** artifact — `--preset hero` renders it unchanged) and a 1 kHz `reference.json` (the **data**
artifact), plus `verify.json` and a two-chart pack. Key facts, all measured rather than asserted:
**differential flatness** turns the powered beats into algebra (author `p(t)`, the thrust falls out
— it is not a job for RL), but it **cannot author the flip** (through inversion it would demand
negative thrust), so there we author the *commands* and close the boundary conditions with a damped
Newton **shoot**; the binding constraint is the rate loop's 16 s⁻¹ bandwidth, not the 12 rad/s
ceiling, so `ω(t)` is authored as the lag *response* and `u = ω + ω̇/K` emitted; and the replay's
action is an **impulse-matched** hold (the step mean), without which the emitted stream drifts ~1 m
instead of 2.2 cm. The metrics use `acro_flip`'s own names so the target is a number the RL can be
graded against — but use the `--deployable` variant for that, since the motors-off coast has *zero*
rate authority by construction.

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
  yaw_rate]`. `action_to_diffaero()` maps it to DiffAero's controller (thrust `1.0` == hover), then
  applies `ActionLimits.min_thrust_normed` — a **free-flight throttle floor** mirroring the pilot's
  `min_thrust_frac` clamp, so a task that rewards a coast can't learn a profile deploy rewrites.
  Default `0.0` = no floor; set per-config via an `act:` section (`experiment.py::make_act_limits`).
  `acro_flip` sets `0.25`, the deploy value.
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
# Hero / concept MP4 — the IN-REPO headless capturer (web/capture/ imports web/studio/'s scene
# modules verbatim, so the video is the Studio's look). One-time: playwright install chromium.
uv pip install -e '.[capture]'
# --preset hero is the standardized concept look; run it on ANY replay and get the same picture.
uv run python scripts/capture_video.py --replay runs/<run>/replay.json.gz --out runs/<run>/hero.mp4 \
    --preset hero --width 1080 --height 1080
uv run python scripts/viz.py --config configs/gate_race.yaml --from runs/<run>/ckpt_final.pt --no-dr --video
# The take-off -> hover -> flip -> land concept sequence. BOTH halves are shipped policies: the
# deployed 1.0 m hover_tof policy owns take-off/hover/land, trained acro_flip owns the flip.
# Why `follow` and not a locked-off or tripod camera: a fixed frame holding the whole flight caps an
# 82 mm drone at ~7% of frame height, and a tripod that pans to follow lets it balloon 6.7 -> 20.8%
# while the room corner sweeps past. Every render prints a framing check (worst |NDC|, 1.0 = frame
# edge) AND the apparent-size spread, so both are measured rather than eyeballed.
uv run python scripts/hero_takeoff_flip_land.py --axis roll --out runs/acro_flip/hero_seq
uv run python scripts/capture_video.py --replay runs/acro_flip/hero_seq/replay.json.gz \
    --out runs/acro_flip/hero_seq/takeoff_flip_land.mp4 --preset hero --width 1080 --height 1080

# The HAND-AUTHORED reference maneuver — "this is the one we want", as data, not a rollout
# (docs/REFERENCE_MANEUVER.md). Pure numpy: no policy, no training, no simulator in the loop.
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --out runs/reference/flip_roll
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --deployable \
    --out runs/reference/flip_roll_deployable          # <- use THIS one as an RL/scoring target
uv run python scripts/capture_video.py --replay runs/reference/flip_roll/replay.json.gz \
    --out runs/reference/flip_roll/reference_flip.mp4 --preset hero --width 1080 --height 1080

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

# ESP-NOW link — peer-to-peer replacement for the WiFi/UDP bridge (docs/ESPNOW.md). WiFi stays
# the default build; every host tool takes the dongle's serial port where it took --udp:
cd firmware/xiao_bridge && pio run -e mac_probe -t upload   # once per board -> espnow_config.h
pio run -e espnow_dongle    -t upload                       # desk dongle (USB CDC <-> ESP-NOW)
pio run -e xiao_bridge_espnow -t upload                     # drone side  (rollback: -e xiao_bridge)
python3 scripts/bench.py --port /dev/cu.usbmodemXXX latency --n 500   # THE GATE: air p50/p99
python3 scripts/pilot.py --serial /dev/cu.usbmodemXXX fly --takeoff --ack-props-on
uv run python scripts/serve.py --bridge /dev/cu.usbmodemXXX          # Studio Real tab
```

**Deploy height safety (2026-07-31, `docs/SIM2REAL.md`).** The measured climb overshoots its
setpoint by **~0.37 m**, so a 1.0 m target puts the peak past the VL53L1X's 1.3 m ceiling — the
held `h_err` then pins negative and the policy commands motors-off open-loop until it falls back
into range. **Fly `--target-height 0.7`** (`--flight-target-height` for the Studio). Two guards
now default ON: `--min-thrust-frac 0.25` (free-flight throttle floor — `act[0] = -1` no longer
means motors off) and `--tof-blind-grace 0.2 --tof-blind-fade 0.3` (a stale ToF error fades to
"at target" rather than being held forever). Set `--min-thrust-frac 0` / a huge grace for legacy.

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
