---
node_id: 841dade5-635a-5780-9a39-8b8cf4e4687e
slug: holy-sky-9094
title: 'Idea/setup: spread-out gate courses — gate spacing becomes a config knob + ARENA_PRESETS + gate_race_spread (training set up, not yet run)'
created_at: '2026-06-27T11:15:10.627598+00:00'
parents:
- wispy-dust-3157
- shrill-limit-5398
summary: 'Idea/setup that makes gate spacing a first-class config knob: previously the inter-gate hop was hardcoded tight (1.5–2.8 m) and not even surfaced by the task config, so courses could not be spread out. This adds step_min/step_max/max_turn_deg config fields (threaded into ArenaSpec), course.ARENA_PRESETS packaging matched radius+hop sets (tight/spread/big/giant), seeded shareable courses, and a configs/gate_race_spread.yaml for far-apart gates. It opens the generalization thread — does a tiny [128,128] policy still find a fast line when gates are far apart? Status: set up and launch-verified only (not trained to convergence); the actual spread run is performed in the scale-generalist child node.'
origin:
  backend: flywheel
  node_id: 841dade5-635a-5780-9a39-8b8cf4e4687e
  slug: holy-sky-9094
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f97beb81-01f5-505d-a86c-a3128c3e1d03
  slug: winter-breeze-6580
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: a4b4797df4eb47b7b3edc3c98d140ccbb78640c7bcff9b8bef07a5946e1040e0
---
## The gap (why this was needed)
Every course this repo ever generated was tight by construction: `ArenaSpec` defaulted `step_min/step_max = 1.5/2.8 m`, and `GateRaceConfig` didn't even surface those knobs — so the gate hop fell back to the ArenaSpec default regardless of arena size. There was literally no config that could place gates farther apart. The user wants bigger, more spread-out courses (and to watch policies fly them in the Studio `e0d57844`).

## What changed (the lever)
- **Config knobs**: `GateRaceConfig` + `SwarmRaceConfig` gain `step_min`/`step_max`/`max_turn_deg`, now threaded into the `ArenaSpec` they build (previously silently dropped). Additive, defaults unchanged -> zero behavior change for existing runs (the 120M baseline `8db85abb` is untouched).
- **`course.ARENA_PRESETS`**: `tight` (=default) / `spread` (r=8, hop 3.0–5.5) / `big` (r=12, hop 4.5–7.5) / `giant` (r=18, hop 6–10) — matched radius+hop+z sets so a generated walk clears the arena and stays flyable. `scripts/seed_courses.py` bakes 5 shareable courses from these into `assets/courses/*.yaml`.
- **`configs/gate_race_spread.yaml`**: gate_race with `step 3.0–5.5`, `arena_radius 8`, crash bounds widened to `bound_xy 10 / bound_z_max 5`, 6 gates, `episode_len 900` (18s; longer legs -> longer laps). Same `[128,128]@120M` net/budget as the racing baseline.

## Measured (the spread is real)
- Seeded courses report min inter-gate hop **3.76–6.17 m** (vs the tight 1.5–2.8 m).
- `spread` preset: min hop >3 m, mean hop >1.5 m larger than `tight` on the same seed (unit-tested).
- Train launch (`gate_race_spread`, 8 updates @ 1024 envs): runs clean, **oracle lap ~6.9s** vs ~3–4s on tight courses — confirming the gates demand real cruise legs between them. No laps completed yet (untrained).

## Status / next (honest)
**Set-up only**, per the locked decision with the user: configs + seed courses + a launch-verified spread config; the full 120M run is NOT done. Open question for the autonomous loop: does the tiny [128,128] policy still find a fast racing line when consecutive gates are far apart (a real cruise+brake problem) rather than tight back-to-back turns? A tight-trained policy visibly crashes early on big/giant courses in the Studio, so spread courses likely need their own training (or a curriculum) — this node sets that branch up.

## Commits
- `1973083` course knobs + ARENA_PRESETS + seed_courses + assets/courses
- `709da4a` configs/gate_race_spread.yaml + docs