# neural-whoop Studio

An interactive browser viewer with four tabs:

- **Bench** — the **always-on real-drone dashboard**. Open the page and the bench controller is
  already connected to the Air65 II over the WiFi MSP bridge; click **Start** to run the
  3·2·1 → liftoff → hover → land sequence on the *real* drone, watch live telemetry + flight metrics
  + a real-drone attitude glyph, and optionally toggle a **parallel CPU-torch sim** of the same
  policy flying beside it. See below.
- **Player** — pick a saved policy, a course, and a drone count, hit **Run**, and watch the policy
  fly in a **hero-layout viewport that matches the exported MP4**: a wide 3/4 main shot fills the
  view, with three fixed 4:3 cells stacked down the left edge — **FPV** (top), **top-down** (middle),
  **stats HUD** (bottom). If you like what you see, **Export hero MP4** renders the byte-identical
  clip server-side.
- **Live** — connect to a policy and **interact with it in real time** over a websocket: blow **wind**
  at it (a top-down direction pad + a vertical slider), **Push** it (a one-shot shove), **Drop block**
  on it (a modeled impulse + body-rate tumble), and — for a `hover` policy — **click the floor to
  relocate its hover point** and watch it fly there and re-settle. Plus pause/reset/speed. See below.
- **Editor** — author a gate course directly in a 3D scene (click the ground to drop a gate, drag a
  translate gizmo to move it incl. height, edit a numeric gate list), with **live flyability
  validation**, **Save** to `assets/courses/_web/`, and **Save & fly** to test it immediately.

The successor to `neural-whoop-lab`'s studio, ported onto this repo's DiffAero env and the v2
group-replay contract. The UI is a flat 2D greyscale style (custom-styled selects, rounded panels).

The Player sidebar surfaces a **policy** panel (task, creation date, training steps, obs/act dims,
eval metrics) and a collapsible **training charts** panel (2D line plots parsed straight from the
run's TensorBoard event file).

## Hero-layout viewport

The viewport is a single canvas composited like `../nw-viz/`'s hero MP4 (`web/studio/layout.js` ports
`nw-viz/src/layout.js` verbatim): `view.render()` draws the wide main shot full-frame, then the FPV
and top-down cells are drawn over it via scissor viewports (`scene.js::renderInset`), and DOM overlay
boxes (borders/labels + the stats HUD) track the same layout rects so they line up on resize. The
orbit camera is **initialized to nw-viz's fixed 3/4 framing** each run (`web/studio/cameras.js`) so
the on-screen wide shot matches the export — but stays fully orbitable for inspection (the canonical
fixed framing is reproduced exactly at capture time by nw-viz). With one drone the FPV cell shows its
onboard view full-cell; with **N drones the FPV cell splits into a near-square grid** (hero first,
capped at 6 — a `+N more` chip notes the overflow). The **FPV box** / **top-down box** toggles in the
playback section show/hide those cells.

## Run it

```bash
uv pip install -e '.[studio]'          # FastAPI + uvicorn (one-time)
uv run python scripts/seed_courses.py  # (once) seed bigger assets/courses/*.yaml
uv run python scripts/serve.py         # -> http://127.0.0.1:8000
```

Flags: `--host`, `--port`, `--device` (`cuda` default; `cpu` works for small rollouts), `--reload`,
`--bridge HOST[:PORT]` (the XIAO bridge for the **Bench** tab; default `$NW_BRIDGE`; pass `fake` or set
`NW_FLIGHT_FAKE=1` to run the self-driving fake bridge with **no hardware**), `--flight-weights` (the
deploy `policy_weights.json` the Bench dashboard flies).

Open the URL, choose:
- **policy** — any `runs/*/ckpt_final.pt` (labelled with its task + best lap if an `eval.json` is
  present; picking one fills the policy metadata panel and loads its training charts);
- **course** — a seeded `assets/courses/*.yaml` track, or an arena **preset** (`preset:tight` /
  `spread` / `big` / `giant`) that generates a fresh random course of that geometry;
- **drones** — how many to fly (1–16); **gates** — gate count for preset courses; **DR** — toggle
  seam domain randomization.

Hit **Run**: the server runs the rollout on the GPU and streams back a replay the viewer plays in the
hero layout. Transport: play/pause, scrub, speed, follow-cam, FPV box, top-down box, trail toggle.

## Bench — the real-drone dashboard (Bench tab)

The **Bench** tab unifies the Studio with the offboard pilot (`scripts/pilot.py`): one always-on page,
served from the Mac bench controller, that flies the *real* Air65 II. Serve with a bridge:

```bash
export NW_BRIDGE=<xiao-ip>            # or pass --bridge <ip>
uv run python scripts/serve.py --device cpu --bridge $NW_BRIDGE
#   no hardware?  uv run python scripts/serve.py --bridge fake   (self-driving fake bridge)
```

On startup the server spins up an always-on **`FlightManager`** (`studio/flight.py`) on a background
thread: it connects to the bridge (retrying if it's down), runs the extracted flight engine
(`neural_whoop.pilot.FlightController` — the same 3·2·1 → liftoff → hover → land state machine
`pilot.py fly` runs), and publishes a telemetry frame ~50 Hz over **`/ws/flight`**. This path imports
**zero torch/numpy** and is **not** wrapped in the GPU sim's `ROLLOUT_LOCK` (the MSP link is a
different resource; several viewers may watch one flight).

Open the Bench tab and:
- The **link** line + **ARMED** / **OVERRIDE** dots show the radio state live.
- **Start** is a **software clock only**, and is **enabled only when telemetry shows the drone ARMED
  + MSP-OVERRIDE engaged** on the Pocket radio. The radio still owns **enable + instant kill**:
  dropping override or disarming aborts instantly via Betaflight's ~300 ms MSP-freshness handback.
  Software **never** writes arm/aux — stopping the RC stream is the only "stop". Click **Start** to
  run the countdown → liftoff → hover → land on the real drone.
- **Abort** stops the stream (releases to the radio) at any time. The **phase** chip walks
  `waiting → countdown → seek/rise → hover → land → released`.
- The **telemetry HUD** shows tilt°, vz-estimate, thrust, throttle µs, link age, battery V, RPM, with
  a rolling **tilt/vz trend**. **Flight params** (mode: ground-takeoff / hand-launch / none; seconds;
  hz; hover µs) default to the safe CLI values and ride along with **Start**.
- **parallel sim (CPU torch)** — an opt-in toggle that opens a `/ws/live` session flying the **same
  deployed policy** in sim (a cyan twin beside the real drone), so you can watch the real and
  simulated hover side-by-side. Off by default so the real-flight path stays pure-stdlib; it needs a
  CPU torch wheel on the Mac (`pip install torch`).
- On a **completed** flight (RELEASED, not a mid-air abort) the manager auto-runs
  `scripts/flight_report.py` on the flight's CSV in a detached process and surfaces a **flight report
  ready** panel (hover-tilt median, vz-rail flags, link p99, battery sag) with a link to the CSV.

The whole backend is exercised headlessly by the fake bridge (`tests/test_flight_ws.py`,
`tests/test_flight_controller.py`): Start-gating interlock, phase walk, abort, link-down, and the
auto-report — all with no drone.

## Live interaction (Live tab)

Where the Player records a whole rollout and plays it back, the **Live** tab steps a policy in real
time and lets you disturb it. Pick a **policy** (the picker floats `hover` policies first — the
family this is built for) and a **drone** count, then **Connect**. The browser opens a websocket to
`/ws/live`; the server builds a `LiveSession` (the same `build_session` substrate as a rollout) and
streams a frame per control step at ~50 Hz. The frame wire-format is the **same per-frame replay
schema** (`pos`/`quat`/`vel`/`scene`, see `docs/VISUAL_CONTRACT.md`) — the live and recorded paths
share one extractor (`eval/rollout.py::hero_pose_snapshot`) so they can't drift.

Controls:
- **Wind** — a top-down direction pad (drag to set the horizontal wind vector, center = calm) plus a
  **vertical** slider. Continuous; the policy leans in and holds.
- **Push** — a one-shot velocity shove on the selected drone (watch it arrest the velocity).
- **Drop block** — a modeled dropped block: a downward + lateral velocity kick **and** a body-rate
  tumble (impulse-only, no real collision). Watch it recover from the spin.
- **Click the floor** (hover policies) — raycasts onto the hover-altitude plane and relocates the
  **setpoint**; the drone flies there and re-settles. The setpoint rides the same `target` scene
  marker the follow tasks use.
- **Target drone** selector (which drone push/drop/click apply to; or *all*), **Pause/Reset**, **speed**.

All disturbances ride the **same physics seam the policy trained against** — wind, push, and the
dropped-block tumble are impulses through `WhoopDynamics.add_velocity`/`add_body_rate`, the very seam
`randomization.py` drives during training (`impulse_dv`/`impulse_dw`). So what the editor throws is
exactly what the `hover` policy was hardened to reject. The GPU sim isn't re-entrant, so a live
session and `/api/rollout` are mutually exclusive via a shared single-flight lock (either rejects the
other with 409 / a socket error); disconnecting frees the session.

## Course editor (Editor tab)

Author a gate course in the same shared 3D scene the player uses (so placement matches the replay
exactly). Workflow:

- **Add** — click the ground plane to drop a gate at that XY (height = the previous gate's z).
- **Select + move** — click a gate to select it, then drag the **translate gizmo** arrows (including
  up/down for height); or type exact `x/y/z/radius` in the right panel.
- **List** — a scrollable gate list with click-to-select, `↑/↓` reorder, delete, and `+ gate`.
- **Validate** — an **arena preset** select drives the validation bounds (and the dashed arena ring);
  a 250 ms-debounced call to `/api/courses/validate` flags errors (gate outside the arena / height
  out of band / non-positive radius) and warnings (spacing), color-tinting each gate by its worst
  issue. Pure geometry, no sim (`src/neural_whoop/studio/course_validate.py`).
- **Save** — writes `assets/courses/_web/<slug>.yaml` (validated; a 422 rejects an unflyable course)
  and refreshes the Player's course picker, where it appears under **your courses (editor)**.
- **Save & fly** — saves, switches to the Player tab, selects the saved course, and runs it with the
  current policy/drone count.

## Export hero MP4

With a run loaded, **⤓ Export hero MP4** (Player sidebar) POSTs to `/api/export`, which shells out to
the sibling `../nw-viz/capture.mjs` (the proven, committed capture pipeline — byte-identical to
`scripts/viz.py --video`) to render `runs/studio/<stem>.mp4`, then the browser downloads it. It needs
`node` on PATH and `../nw-viz` installed (`cd ../nw-viz && npm install`); if either is absent the
route returns **503** with that guidance instead of hanging. Capture is heavy (headless Chromium +
ffmpeg), so it runs off the event loop under a single-flight lock (HTTP 409 if one is already going).

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
| `/api/courses`           | GET    | `{courses: [seeded + authored YAML, tagged kind file/web], presets: [arena presets]}` |
| `/api/courses/{name}`    | GET    | a single course `{name, gates}` for editing (curated dir or `_web/`, traversal-guarded) |
| `/api/courses/validate`  | POST   | `{name, gates}` (+ `?preset=`) → `{ok, issues}` flyability report (pure geometry, no sim) |
| `/api/courses`           | POST   | `{name, gates}` (+ `?preset=`) → saves to `_web/<slug>.yaml` (422 on an unflyable course) |
| `/api/rollout`           | POST   | `{policy, course, drone_count, dr, max_steps, n_gates, seed}` → run summary (sim-backed; single-flight, HTTP 409 if busy) |
| `/api/export`            | POST   | `{run_path, width?, height?, fps?, crf?}` → `{video_path}` hero MP4 via nw-viz (503 if node/nw-viz absent; single-flight) |
| `/api/runs/{path}`       | GET    | the replay `.json.gz` / exported `.mp4` (octet-stream, path-jailed to `runs/`) |
| `/`                      | GET    | the static `web/studio/` frontend                                  |

Module-level locks serialize rollouts and exports (the batched GPU sim isn't re-entrant; capture is
heavy). The GET listing + course-validate/save routes import without torch/sim; only `/api/rollout`
reaches the sim stack (lazily), and `/api/export` only shells out to node. The scalars route uses
`studio/tbscalars.py`, a dependency-free TFRecord/protobuf scalar reader (validated against
`tbparse`) — so charts need no extra deps beyond the `studio` extra.

## Frontend (`web/studio/`)

Static ES modules; three.js + OrbitControls + TransformControls load from a jsDelivr **importmap**
(no Node toolchain in this repo). `scene.js`/`geometry.js`/`drone-model.js` are ported near-verbatim
from the lab; `layout.js`/`cameras.js` port the hero composition from `../nw-viz/`; `playback.js` is
adapted to the v2 `drones[]` group (one tinted actor per drone, **each with its own onboard FPV
camera**; a hero actor drives the HUD + top-down cam — the same approach as `../nw-viz/src/viewer.js`);
`editor.js` is the unified-3D course editor; `main.js` wires the tab router, the selectors, the Run
button, the transport, the policy metadata panel, the canvas line charts, the **hero compositor**
render loop, and the **export** button.

## Courses on disk

Seeded courses (`assets/courses/*.yaml`) use the schema `{name, gates: [{pos:[x,y,z], radius}]}` —
the same shape `env.fixed_course` consumes. `scripts/seed_courses.py` (re)generates a curated set
from `neural_whoop.course.ARENA_PRESETS` with fixed seeds, so the repo ships shareable,
bigger-than-default base courses. **Browser-authored** courses (from the Editor tab) live under
`assets/courses/_web/<slug>.yaml` — listed in the picker as `kind: "web"`, flyable by stem without a
restart (`resolve_course` checks both dirs), and validated before write so an unflyable course is
never persisted.
