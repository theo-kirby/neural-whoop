# neural-whoop Studio

An interactive browser viewer: pick a saved policy, a course, and a drone count, hit **Fly**, and
watch the policy fly that course with playback controls (3D wide shot + FPV/top-down insets,
play/pause/scrub). The successor to `neural-whoop-lab`'s studio, ported onto this repo's DiffAero
env and the v2 group-replay contract. The first cut is the **Runs viewer + selectors**; the
drag-to-place gate Editor and Metrics charts are deferred.

## Run it

```bash
uv pip install -e '.[studio]'          # FastAPI + uvicorn (one-time)
uv run python scripts/seed_courses.py  # (once) seed bigger assets/courses/*.yaml
uv run python scripts/serve.py         # -> http://127.0.0.1:8000
```

Flags: `--host`, `--port`, `--device` (`cuda` default; `cpu` works for small rollouts), `--reload`.

Open the URL, choose:
- **policy** — any `runs/*/ckpt_final.pt` (labelled with its task + best lap if an `eval.json` is
  present);
- **course** — a seeded `assets/courses/*.yaml` track, or an arena **preset** (`preset:tight` /
  `spread` / `big` / `giant`) that generates a fresh random course of that geometry;
- **drones** — how many to fly (1–16); **gates** — gate count for preset courses; **DR** — toggle
  seam domain randomization.

Hit **Fly**: the server runs the rollout on the GPU and streams back a replay the viewer plays.
Transport: play/pause, scrub, speed, follow-cam, FPV inset, top-down inset, trail toggle.

## Drone-count semantics

Drone-count maps to the substrate per the policy's task (the env flattens `(n_envs, n_agents)` →
`n_drones`):

| policy task   | mapping                                  | meaning                                              |
|---------------|------------------------------------------|------------------------------------------------------|
| `gate_race`   | `n_envs = drone_count`, `n_agents = 1`   | N **independent** racers sharing one fixed course (no mutual awareness; ring-spread spawns) |
| `swarm_race`  | `n_envs = 1`, `n_agents = drone_count` (≥2) | collision-aware shared-track swarm (neighbour obs)   |

Either way the drones fly the **one** chosen course (broadcast to every env/agent via
`env.fixed_course`) and are recorded as a single **v2 group episode** (`episodes[].drones[]`), so the
viewer renders them coexisting on the same gates, tinted per drone.

## Endpoints (`src/neural_whoop/studio/server.py`)

| route                    | method | returns                                                            |
|--------------------------|--------|--------------------------------------------------------------------|
| `/api/policies`          | GET    | `[{path, name, task, obs_dim, step, best_lap}]` from `runs/*/ckpt_final.pt` |
| `/api/courses`           | GET    | `{courses: [seeded YAML], presets: [arena presets]}`               |
| `/api/rollout`           | POST   | `{policy, course, drone_count, dr, max_steps, n_gates, seed}` → run summary (sim-backed; single-flight, HTTP 409 if busy) |
| `/api/runs/{path}`       | GET    | the replay `.json.gz` (octet-stream, path-jailed to `runs/`)       |
| `/`                      | GET    | the static `web/studio/` frontend                                  |

A module-level lock serializes rollouts (the batched GPU sim is not re-entrant). The GET listing
routes import without torch/sim; only `/api/rollout` reaches the sim stack (lazily).

## Frontend (`web/studio/`)

Static ES modules; three.js + OrbitControls load from a jsDelivr **importmap** (no Node toolchain in
this repo). `scene.js`/`geometry.js`/`drone-model.js` are ported near-verbatim from the lab;
`playback.js` is adapted to the v2 `drones[]` group (one tinted actor per drone, a hero actor drives
the HUD + cameras — the same approach as `../nw-viz/src/viewer.js`); `main.js` wires the selectors,
the Fly button, and the transport.

## Courses on disk

Seeded courses (`assets/courses/*.yaml`) use the schema `{name, gates: [{pos:[x,y,z], radius}]}` —
the same shape `env.fixed_course` consumes. `scripts/seed_courses.py` (re)generates a curated set
from `neural_whoop.course.ARENA_PRESETS` with fixed seeds, so the repo ships shareable,
bigger-than-default base courses.
