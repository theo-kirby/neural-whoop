# The visual contract (replay schema / pack / artifacts)

The visual contract is to *seeing a policy fly* what `docs/CONTRACT.md` is to the obs/act seam:
a versioned, self-describing record that stays stable across this repo, the lab's Three.js
viewer, and any other consumer. Today the lab is numbers-only; this contract makes every rollout
reconstructable, plottable, and comparable — without a heavy video pipeline.

The durable artifact is the **replay document**: a single self-describing JSON file (gzipped) that
carries the full per-step telemetry plus the contract metadata needed to interpret it. A pure
recorder produces it (`src/neural_whoop/viz/replay.py`, stdlib `json`+`gzip`+numpy — no simulator,
no torch, no viz extra). A lazily-imported renderer turns it into PNG/CSV artifacts
(`src/neural_whoop/viz/render.py`, the `viz` extra: matplotlib + Pillow + tbparse). The training
path stays render-free; viz is opt-in.

## The replay document (`format="neural-whoop-replay"`, `version=2`)

```jsonc
{
  "format": "neural-whoop-replay",
  "version": 2,                         // bump on a breaking schema change
  "meta": { ...run-level contract... },
  "episodes": [ { ...one hero flight, or one swarm group... } ]
}
```

> **v2 (additive, backward-compatible):** an episode may carry an optional `drones[]` list — a
> **swarm group** of several drones flying ONE shared course (recorded for `n_agents > 1` tasks so
> the viewer can render them coexisting). The episode-level `drone`/`dr`/`summary`/`frames` mirror
> the lead drone (`drones[0]`), so a v1 reader still sees a valid single-drone episode. v1 documents
> (no `drones` key) remain valid.

### `meta` — the self-describing contract block
A consumer needs no external doc; everything to interpret the frames is here.

| key | meaning |
|-----|---------|
| `config` | experiment / run name |
| `policy` | human-readable label (param count + source checkpoint) |
| `task` | registry task name (e.g. `gate_race`) |
| `obs_version` / `action_version` | `"obs-v4"` / `"act-v2"` (see `docs/CONTRACT.md`) |
| `substrate` | `"diffaero"` |
| `control_hz` / `sim_hz` | policy decision rate / physics rate (`control_hz * n_substeps`) |
| `dt` | control timestep (s) |
| `coordinate_frame` | world: RH, **Z-up**, m; body: +x fwd / +y left / +z up; quat **xyzw**; rad |
| `state_layout` | per-frame pose-block layout (+ that `vel` is world, `angvel` is body) |
| `action_layout` | act-v2 + `action_diffaero` semantics |
| `action_limits` | the `ActionLimits` the env mapped the action onto (4 floats) |
| `unity_hint` | Z-up RH → Unity Y-up LH conversion hint (verify against your rig) |
| `scene_info` | **(v2, optional)** static descriptors for the `scene` channel — see below |

### `episodes[]` — one recorded **hero** flight (or one swarm group) each
Recording is **hero-subset**: full per-step frames are kept only for a small set of hero drones;
aggregate metrics still cover the full population. Each hero records its **first** episode — from
rollout start to its first `done` (crash / time-limit) or the window end. Tensors accumulate on GPU
and move to CPU once.

Hero selection depends on the task: **single-drone** tasks use `select_heroes` (default 4, spread
across the population — diverse courses, one solo drone each). **Swarm** tasks (`n_agents > 1`) use
`select_swarm_heroes` — **all agents of one env**, which share a course — and record them as a
single **group episode** (`drones[]`) so the racers render together. (Spreading across the flat
`n_envs*n_agents` index instead would grab unrelated solo drones from different courses — which is
exactly why an early swarm replay rendered as one lonely drone.)

| key | meaning |
|-----|---------|
| `index` | 1-based hero / group number |
| `drone` | flat drone index this episode recorded (lead drone for a group) |
| `gates` | this episode's course: `[{"pos":[x,y,z], "radius":r}, ...]` |
| `dr` | live per-drone domain-randomization params, or `null` (DR off) |
| `oracle_lap` | speed-oracle target lap time (s) for this course |
| `summary` | `steps, total_reward, laps, best_lap, gates_passed, num_gates, ended` |
| `drones` | **(v2, optional)** swarm group: `[{drone, dr, summary, frames}, ...]` sharing `gates` |

### `frames[]` — one control step each

| key | frame / units | notes |
|-----|---------------|-------|
| `t`, `step` | sim time (s), 1-based step index | |
| `pos` | world m `[x,y,z]` | |
| `quat` | `[qx,qy,qz,qw]` (**xyzw**) | matches DiffAero / the contract |
| `rpy` | world rad | |
| `vel` | **world** m/s | named `vel` for viewer compatibility |
| `angvel` | **body** rad/s | the gyro signal (`[p,q,r]`) |
| `action` | act-v2 CTBR normalized `[-1,1]` | what the policy output |
| `action_diffaero` | DiffAero CTBR `[normed_thrust, wx, wy, wz]` | via `contract.action_to_diffaero` |
| `reward`, `cum_reward` | step / cumulative episode reward | |
| `gate_idx` | next gate to pass | |
| `dist_to_gate` | distance to that gate's center (m) | |
| `laps` | laps completed so far | |
| `passed`, `crashed` | per-step bool flags | |
| `obs` | optional flat observation vector | `--record-obs` |
| `scene` | **(v2, optional)** per-drone world-frame markers for **gateless** tasks | see below |

### `scene` — what a gateless follow/formation policy is tracking (v2, additive)

Gate tasks need nothing extra: their geometry travels in the episode's `gates`. The follow/perception
thread (`target_follow` → `hand_follow` → `gesture_follow` → `command_follow`) and `swarm_formation`
have **no gates** — they chase a moving target/anchor instead — so each frame carries an optional
`scene` dict of **per-drone, world-frame** markers, populated by the task's
`DroneTask.scene_objects(env)` hook and recorded alongside the pose. Values are either a world-frame
**vector** `[x,y,z]` or a **scalar** (the command channel):

| key | tasks | meaning |
|-----|-------|---------|
| `target` | the four `*_follow` tasks | world position of the moving target the drone follows |
| `command` | `gesture_follow` (0/1), `command_follow` (0/1/2) | raw command index — label via `scene_info.command_labels` |
| `anchor` | `swarm_formation` | world position of the shared moving anchor (same for the env's agents) |
| `slot` | `swarm_formation` | this drone's assigned ring slot (world position) |

`meta.scene_info` carries the static descriptors a viewer needs to label/scale those markers without
hardcoding task names: `standoff` / `fov_deg` (follow), `command_labels` (e.g. `["STOP","NEAR","FAR"]`),
`d_near` / `d_far` (command_follow), `formation_radius` (swarm_formation). Both viewers
(`web/studio/` + `nw-viz`) draw `target`/`anchor` as a sphere (cyan/amber), `slot` as a faint ring,
tint the target by `command`, and show a command chip from the labels. Gate tasks emit neither key.

> **Frame-name note.** `vel`/`angvel` keep the lab's exact wire names so the existing
> `web/replay-viewer/` Three.js viewer consumes new-repo rollouts unchanged. Their *frames* (world
> vel, body angvel) are documented in `meta.state_layout` — the schema is self-describing, the names
> are stable. The terminal/reset step is not recorded (its state is already the next spawn); the
> crash/timeout is captured in `summary.ended`.

Read a file back with `neural_whoop.viz.replay.load_run` (gzip-transparent). Build `meta` from a
live env with `build_meta(env, config=..., policy=...)`.

## The standard per-node visual pack

`scripts/viz.py` (and `scripts/eval.py --viz`) run a recording rollout and emit a pack to an out
dir — exactly what the autonomous loop uploads to a Flywheel node:

| file | content | Flywheel artifact type |
|------|---------|------------------------|
| `replay.json.gz` | the replay document (portable, durable) | `json` |
| `eval.json` | aggregate metric dict | `json` |
| `trajectory.png` | top-down + side flown path, gates, gate-loop reference, laps | `image` |
| `fpv_*.png` | synthetic onboard keyframes (start / gate passes / end) | `image` |
| `fpv.gif` | optional stitched FPV loop (`--gif`, needs `imageio`) | `binary` |
| `training_curves.png` | TB curves (return / best-lap / completion / KL), if events exist | `image` |
| `comparison.png` | lap-time bars + trajectory overlay vs a baseline (`--baseline`) | `image` |
| `table.csv` | leaderboard (this vs baseline) | `table` |
| `pack_manifest.json` | `{filename: artifact_type}` map | `json` |

Renderers degrade gracefully: no TB events → no curves; no baseline → no comparison; no `imageio`
→ no GIF (PNGs are the durable artifact).

## Artifact-type mapping + naming (Flywheel)

Upload via the standard prepare → PUT → finalize flow. Map by extension/role:
`*.png` → `image`, `*.json` → `json`, `*.json.gz` → `json` (gzipped payload) or `binary`,
`table.csv` → `table`. An interactive trajectory could later be `plotly_html`. Keep the filenames
above stable so a node's pack is self-describing and diffable across hops.

## The `render_depth` future seam

`render.render_depth(...)` is a documented **stub** (raises `NotImplementedError`). The honest
camera-only path — rendering real depth/RGB from the DiffAero scene — is deferred (locked decisions
#1/#2: the tiled-camera path is Blackwell-broken today). When it lands it replaces the analytic
`render_fpv` overlay with rendered pixels and feeds the camera tasks' obs. Until then the analytic
FPV (pinhole projection of gate geometry onto a synthetic horizon, no pixels rendered from the sim)
is the FPV artifact.

## Versioning

Bump `version` only on a **breaking** schema change (a removed/renamed field a consumer relies on).
Additive fields (new optional per-frame keys) are forward-compatible and do not bump it. Document
any change here and in `CLAUDE.md`, mirroring the obs/act versioning discipline in `docs/CONTRACT.md`.

- **v2** — added the optional `episodes[].drones[]` **swarm group** (multiple drones on one shared
  course). Additive and backward-compatible (the lead drone is mirrored at the episode level), but
  the version was bumped so the self-describing document advertises the capability honestly.
- **(v2, no bump)** — added the optional per-frame `scene` dict + `meta.scene_info` for gateless
  follow/formation tasks (moving target/anchor/slot + command channel). Purely additive optional
  fields, so the version **stays at 2** per the rule above; old replays and the matplotlib pack are
  unaffected.
