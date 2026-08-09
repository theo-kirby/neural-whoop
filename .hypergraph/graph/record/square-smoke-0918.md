---
node_id: 563fc6d9-8f44-5263-be12-0065b74a0049
slug: square-smoke-0918
title: 'Tooling: visual observability seam (replay schema + recorder + renderer + standard pack)'
created_at: '2026-06-26T11:42:03.788533+00:00'
parents:
- morning-base-2167
summary: 'Off-frontier infrastructure (no racing-metric change). Adds a versioned, self-describing telemetry/replay contract (neural-whoop-replay v1) so a human can SEE what a policy does and steer: per-step hero telemetry -> portable replay.json.gz -> Flywheel-native artifacts (trajectory + gate-loop reference, synthetic FPV, training curves, parent comparison, leaderboard). Training path stays render-free (viz is an opt-in extra). 39 tests green (25 existing intact); env_check green. Committed 28f896b on scaffold/flywheel-foundation. builds-on e4a66478 (the tp=0.05 baseline code state it extends).'
origin:
  backend: flywheel
  node_id: 563fc6d9-8f44-5263-be12-0065b74a0049
  slug: square-smoke-0918
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 61a636d1-16db-5be9-8a5b-5ae318ea4a47
  slug: odd-wildflower-1328
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: b468a235c15887f01243f2eabf116cd3741b46ef848c3996962448e0cc006ee1
---
# Visual observability seam (tooling node)

## What & why
The lab was numbers-only (aggregate metrics + tfevents). This adds the durable **visual contract**: a versioned, self-describing replay schema + a pure recorder + a lazy renderer + a standard per-node visual pack, so policies can be SEEN, compared, and reconstructed retroactively, and so the autonomous loop can push visuals the user follows and steers from. No change to the render-free training path or the racing metric — this is infrastructure.

**Lineage:** builds-on `e4a66478` (the GREEN tp=0.05 baseline = the code state this extends). Not an empirical hop — it changes no metric; it equips every future hop with mandatory visuals (control-node convention 5).

## What landed (commit 28f896b)
- `src/neural_whoop/viz/replay.py` — `neural-whoop-replay` schema **v1** + `RunRecorder` + `build_meta` + `load_run`. Pure `json`+`gzip`+numpy (imports without sim/viz extras). Self-describing `meta` grounded in the real contract: obs-v4 / act-v2, `ActionLimits`, control/sim hz, coordinate frame (world Z-up m; body +x fwd/+y left/+z up; quat xyzw). Per-frame: pos/quat/rpy/vel(world)/angvel(body)/action/action_diffaero/reward/cum_reward/gate_idx/dist_to_gate/laps/passed/crashed (+optional obs). Frame keys match the lab's wire format, so `neural-whoop-lab/web/replay-viewer/` (Three.js) consumes new-repo replays unchanged.
- `src/neural_whoop/viz/render.py` — lazy renderer (Agg + Pillow + tbparse, the `viz` extra): `plot_trajectory` (flown path + gate-loop reference overlay = the 'optimal path through gates'), `render_fpv`/`render_fpv_keyframes` (analytic pinhole FPV via ported `project_points` — no sim pixels), `plot_training_curves` (tbparse over tfevents), `plot_time_trial_comparison` + `write_leaderboard`, `plot_swarm_snapshot`, and `render_depth` (documented **stub** for the future DiffAero Taichi renderer — deferred, Blackwell camera path).
- `src/neural_whoop/eval/rollout.py` — `evaluate_and_record` (+ `select_heroes`): hero-subset capture (full per-step frames for a few drones; aggregate metrics still over the full population) returning a **byte-identical** aggregate dict to `evaluate()`. Fast path unchanged.
- `src/neural_whoop/eval/pack.py` + `scripts/viz.py` + `scripts/eval.py --record/--viz/--baseline` — the **standard visual pack**: `replay.json.gz`, `trajectory.png`, `fpv_*.png` (+optional `fpv.gif`), `training_curves.png`, `eval.json`, `comparison.png` + leaderboard `table`.
- `docs/VISUAL_CONTRACT.md` (schema/pack/artifact-mapping spec) + CLAUDE.md / AGENTS.md / docs/FLYWHEEL.md updates. `pyproject` `viz` extra: matplotlib/pillow/tbparse (core deps unchanged).

## Verification
- `uv run pytest -q` = **39 pass** (new test_replay schema round-trip/leak/completeness + test_render projection determinism & headless plot smoke; the 25 pre-existing tests unchanged). `uv run ruff check` clean. `scripts/env_check.py` green (training path untouched).
- End-to-end on real checkpoints (canonical eval: DR-off, 2048x1500, seed 12345): tp=0.05 winner pack vs the gate_race baseline parent (3.87s). Artifacts attached here and on `e4a66478`.

## Artifact-type mapping (validated against the Flywheel artifact validator)
`*.png` -> `image`; `eval.json` -> `json`; leaderboard -> `table` as **JSON rows, media application/json** (the `table` validator rejects raw CSV bytes); `replay.json.gz` -> `binary` (gz is not valid JSON). Upload PUT needs raw bytes + `Content-Type` matching the prepared media_type + an `X-Flywheel-Artifact-Filename` header, and ALL prepared items staged before finalize. Encoded in control-node convention 5.

## Attached pack (this node)
trajectory.png (racing line vs gate-loop reference), comparison.png (vs baseline), training_curves.png, fpv_03.png (synthetic onboard), table.json (leaderboard), eval.json (metrics), replay.json.gz (portable telemetry).

## Status
Merged to `scaffold/flywheel-foundation` @ 28f896b (pushed). Not terminal for the frontier — the staged racing hop `5fcc1b12` (stronger pass-gated lap bonus) is unaffected and resumes next, now obligated to attach the standard pack + parent comparison per convention 5.