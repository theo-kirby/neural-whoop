---
node_id: e0d57844-6217-5f9d-9ef9-9429504544dc
slug: wispy-dust-3157
title: 'Tooling: neural-whoop Studio — interactive browser viewer (pick policy + course + drone count, watch it fly)'
created_at: '2026-06-27T11:14:45.031284+00:00'
parents:
- square-smoke-0918
- lucky-bush-5765
- plain-block-5937
- cool-union-2681
summary: 'The neural-whoop Studio: an interactive in-browser viewer (FastAPI backend + Three.js frontend) where you pick a saved policy, a course (seeded YAML or arena preset), and a drone count, hit Fly, and watch a fresh fixed-course rollout play back — 3D wide shot plus per-drone FPV/top-down picture-in-picture, with play/pause/scrub. Drone count maps to the substrate per the policy''s task (gate_race -> N independent racers; swarm_race -> a collision-aware shared swarm), recorded as one v2 group episode; it reuses the existing group-replay path with no training-path changes. Shipped as a first-cut Runs viewer + selectors (gate Editor and Metrics charts deferred); spawned the swarm-group viz, UX-overhaul, and dynamic-DR/perturbation idea branches.'
origin:
  backend: flywheel
  node_id: e0d57844-6217-5f9d-9ef9-9429504544dc
  slug: wispy-dust-3157
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
## What this is
A **method/tooling** node: an interactive in-browser Studio for this repo, the successor to neural-whoop-lab's studio. Where nw-viz (`6f89cea9`) renders a *fixed* replay to an MP4 headlessly, the Studio lets you **drive the sim on demand** — pick a saved policy, a course, and a drone count, hit Fly, and watch the resulting rollout play back (3D wide + FPV/top-down PiP, play/pause/scrub). It closes the loop from the visual-observability seam (`563fc6d9`) + v2 group replay (`900c7626`) into a live, exploratory viewer.

## What it does (the new capability)
- **Fixed-course rollout.** The env gained an optional `fixed_course` (gate_pos, gate_rad) broadcast to ALL envs in `GateRaceTask`/`SwarmRaceTask.reset` instead of per-env `random_courses`. Everything downstream (oracle_lap, spawn-facing-gate-0, prev_dist) keys off the resulting gates unchanged.
- **Drone-count -> substrate mapping** (per the policy's task; the env flattens (n_envs,n_agents)->n_drones): `gate_race` -> n_envs=count, n_agents=1 (N independent racers sharing ONE fixed track, ring-spread spawns); `swarm_race` -> n_envs=1, n_agents=count (collision-aware shared swarm, reuses the neighbour obs from `4b21d59b`). Either way the flown drones are recorded as one v2 **group episode** so the viewer renders them coexisting on the same gates.
- **Studio rollout helper** (`studio/rollout.py`): reads ckpt meta, resolves the course, builds the env with the right mapping + matched obs_stack, sets `fixed_course`, runs `evaluate_and_record(group=True)` -> saves `runs/studio/<...>.json.gz`. Pure reuse of `load_agent` + `evaluate_and_record` + `RunRecorder` + `build_meta` — NO training-path changes.

## Backend / frontend
- **FastAPI** (`studio/server.py`, `studio` extra): GET `/api/policies` (runs/*/ckpt_final.pt + meta + best_lap), GET `/api/courses` (seeded YAML + named presets), POST `/api/rollout` (single-flight lock; HTTP 409 if busy; sim offloaded off the event loop), GET `/api/runs/{path}` (path-jailed), static mount of `web/studio/`. `scripts/serve.py` is the uvicorn entrypoint. GET routes import without torch/sim.
- **Frontend** (`web/studio/`, ported from the lab Runs tab): static ES modules, three.js via a jsDelivr importmap (no Node in this repo). `playback.js` adapted to the v2 `episodes[].drones[]` group — one tinted actor per drone, a hero actor (laps->gates->length) drives the HUD + cameras (same approach as nw-viz `900c7626`). Selectors: policy / course (seeded + presets) / drone-count / gates / DR + a Fly button; transport with follow/FPV/top-down cameras.

## Verification (honest)
- pytest green incl. new `tests/test_studio.py`: gate_race (n_envs=count) AND swarm (n_agents=count) rollouts each produce a v2 replay whose drones share ONE course (identical gate hashes) with frames per drone.
- Live GPU: studio_rollout of the 120M baseline laps the `tight` preset at 2.53s, completion 1.0; full HTTP path (POST rollout + GET replay) works; server lists 46 policies + 5 seeded + 4 preset courses.
- env_check green; no regression to the existing single-drone path.

## Scope / deferred
First cut = **Runs viewer + selectors** only. The drag-to-place gate **Editor** (`TransformControls`) and **Metrics** charts from the lab studio are deferred. Note: a tight-trained policy crashes early on big/giant courses (expected — not trained for spread) — which motivates the sibling spread-course training setup.

## Commits
- `1973083` studio sim core + FastAPI backend (course knobs, fixed_course, presets, studio/*, seed_courses, tests)
- `0a930a4` browser frontend (web/studio)
- `709da4a` spread training config + Studio docs (docs/STUDIO.md)