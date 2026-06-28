# neural-whoop Studio

An interactive browser viewer: pick a saved policy, a course, and a drone count, hit **Run**, and
watch the policy fly that course with playback controls (3D wide shot + **per-drone onboard-FPV**
and top-down insets, play/pause/scrub). The successor to `neural-whoop-lab`'s studio, ported onto
this repo's DiffAero env and the v2 group-replay contract. The UI is a flat 2D style (custom-styled
selects, rounded panels); the drag-to-place gate Editor is deferred.

The sidebar surfaces a **policy** panel (task, creation date, training steps, obs/act dims, eval
metrics) and a collapsible **training charts** panel (2D line plots parsed straight from the run's
TensorBoard event file). The PiP camera frames are **movable** (drag the header) and **resizable**
(drag the corner); FPV is split into **one box per drone** so multi-drone runs show every onboard
view at once.

## Run it

```bash
uv pip install -e '.[studio]'          # FastAPI + uvicorn (one-time)
uv run python scripts/seed_courses.py  # (once) seed bigger assets/courses/*.yaml
uv run python scripts/serve.py         # -> http://127.0.0.1:8000
```

Flags: `--host`, `--port`, `--device` (`cuda` default; `cpu` works for small rollouts), `--reload`.

Open the URL, choose:
- **policy** — any `runs/*/ckpt_final.pt` (labelled with its task + best lap if an `eval.json` is
  present; picking one fills the policy metadata panel and loads its training charts);
- **course** — a seeded `assets/courses/*.yaml` track, or an arena **preset** (`preset:tight` /
  `spread` / `big` / `giant`) that generates a fresh random course of that geometry;
- **drones** — how many to fly (1–16); **gates** — gate count for preset courses; **DR** — toggle
  seam domain randomization.

Hit **Run**: the server runs the rollout on the GPU and streams back a replay the viewer plays.
Transport: play/pause, scrub, speed, follow-cam, per-drone FPV insets, top-down inset, trail toggle.
The FPV/top-down frames can be dragged (by their header) and resized (corner grip).

## Drone-count semantics

Drone-count maps to the substrate per the policy's **task family** (the env flattens
`(n_envs, n_agents)` → `n_drones`):

| family (task)                         | gated? | mapping                                  | meaning |
|---------------------------------------|--------|------------------------------------------|---------|
| **gate** (`gate_race`)                | yes    | `n_envs = drone_count`, `n_agents = 1`   | N **independent** racers sharing one fixed course (ring-spread spawns) |
| **gate_swarm** (`swarm_race`)         | yes    | `n_envs = 1`, `n_agents = drone_count` (≥2) | collision-aware shared-track swarm (neighbour obs) |
| **follow** (`target/hand/gesture/command_follow`) | no | `n_envs = drone_count`, `n_agents = 1` | N independent followers, each chasing its **own** moving target |
| **formation** (`swarm_formation`)     | no     | `n_envs = 1`, `n_agents = drone_count` (≥2) | a ring formation around one shared moving anchor |

The drones are recorded as a single **v2 group episode** (`episodes[].drones[]`), so the viewer
renders them coexisting, tinted per drone. Gated families fly the **one** chosen course (broadcast
via `env.fixed_course`). The **gateless** families (follow/formation) have no course: the
`/api/policies` `needs_course`/`family` flag tells the frontend to **hide the course + gates
selectors** for them, the task supplies its own arena, and the replay's `scene` channel carries what
each policy tracks (moving target/anchor/slot + STOP/GO/NEAR/FAR command) — drawn as a cyan target
sphere / amber anchor / faint slot ring, the target tinted by command, with a command HUD chip (see
`docs/VISUAL_CONTRACT.md`). The hero drone for a gateless run is the one that tracks its target/slot
closest (lowest mean distance), since there are no laps to rank by.

## Endpoints (`src/neural_whoop/studio/server.py`)

| route                    | method | returns                                                            |
|--------------------------|--------|--------------------------------------------------------------------|
| `/api/policies`          | GET    | `[{path, name, run, task, family, needs_course, obs_dim, act_dim, step, created, best_lap, eval, has_scalars}]` from `runs/*/ckpt_final.pt` (`family`/`needs_course` drive the gateless-course UI; `created` = ckpt mtime epoch; `eval` = full `eval.json` when present) |
| `/api/policies/{run}/scalars` | GET | `{run, tags: {tag: {steps, values}}}` — TensorBoard scalar curves for the run (downsampled; `{}` if no event file) |
| `/api/courses`           | GET    | `{courses: [seeded YAML], presets: [arena presets]}`               |
| `/api/rollout`           | POST   | `{policy, course, drone_count, dr, max_steps, n_gates, seed}` → run summary (sim-backed; single-flight, HTTP 409 if busy) |
| `/api/runs/{path}`       | GET    | the replay `.json.gz` (octet-stream, path-jailed to `runs/`)       |
| `/`                      | GET    | the static `web/studio/` frontend                                  |

A module-level lock serializes rollouts (the batched GPU sim is not re-entrant). The GET listing
routes import without torch/sim; only `/api/rollout` reaches the sim stack (lazily). The scalars
route uses `studio/tbscalars.py`, a dependency-free TFRecord/protobuf scalar reader (validated
against `tbparse`) — so charts need no extra deps beyond the `studio` extra.

## Frontend (`web/studio/`)

Static ES modules; three.js + OrbitControls load from a jsDelivr **importmap** (no Node toolchain in
this repo). `scene.js`/`geometry.js`/`drone-model.js` are ported near-verbatim from the lab;
`playback.js` is adapted to the v2 `drones[]` group (one tinted actor per drone, **each with its own
onboard FPV camera**; a hero actor drives the HUD + top-down cam — the same approach as
`../nw-viz/src/viewer.js`); `main.js` wires the selectors, the Run button, the transport, the policy
metadata panel, the canvas line charts (from `/api/policies/{run}/scalars`), and the
movable/resizable PiP frames (one FPV box per drone, built on each run).

## Courses on disk

Seeded courses (`assets/courses/*.yaml`) use the schema `{name, gates: [{pos:[x,y,z], radius}]}` —
the same shape `env.fixed_course` consumes. `scripts/seed_courses.py` (re)generates a curated set
from `neural_whoop.course.ARENA_PRESETS` with fixed seeds, so the repo ships shareable,
bigger-than-default base courses.
