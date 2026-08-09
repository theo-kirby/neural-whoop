---
node_id: 900c7626-91e8-5452-9c9f-6aded5cf7b11
slug: plain-block-5937
title: 'Viz/bugfix: swarm renders as a coexisting group (replay v2 group episodes) — the first real swarm hero video'
created_at: '2026-06-27T10:29:48.729208+00:00'
parents:
- square-smoke-0918
- lucky-bush-5765
- cool-union-2681
summary: Diagnosed why the swarm_race hero MP4 showed only one drone, then fixed the recorder + replay schema + nw-viz viewer so n_agents>1 tasks render as N drones racing one shared course. swarm_race_s1 now renders 3 racers (best laps 2.38/2.82/3.40s) on one course.
origin:
  backend: flywheel
  node_id: 900c7626-91e8-5452-9c9f-6aded5cf7b11
  slug: plain-block-5937
  revision: 23
  exported_at: '2026-08-09T18:23:28+00:00'
---
## What this is
A viz/checkpoint + bugfix node: the swarm_race hero video showed a single lonely drone, and this makes the swarm actually render as the coexisting group it is. First true visual confirmation of multi-agent shared-track racing.

## The bug (honest diagnosis)
The swarm replay was faithful to what was recorded — the recording was wrong. `select_heroes` spread its 4 hero drones across the **flat** `n_drones = n_envs*n_agents = 12288` index via `linspace`, so the heroes landed in 4 *different* envs, each with its own procedurally-generated course. For a swarm task that means it captured 4 unrelated **solo** drones (confirmed: 4 episodes, 4 distinct gate-course hashes), never the 3 agents that actually share a track. nw-viz then renders one episode -> one drone. Neither layer ever had a co-located multi-drone path.

## Fix (additive, backward-compatible)
- **Recorder** (`select_swarm_heroes`): for `n_agents>1`, record **all agents of one env** (env-major flat indices `[0..n_agents-1]`), which share a course.
- **Replay schema v1->v2** (`replay.py`): optional `episodes[].drones[]` track list (a swarm **group episode**). The lead drone is mirrored onto the episode-level `drone`/`dr`/`summary`/`frames`, so v1 readers and the matplotlib pack still work. v1 documents stay valid.
- **nw-viz viewer**: one actor (glyph + trail) per track; each swarm drone gets a distinct identity tint + solid trail (single-drone keeps its turbo speed-trail). FPV camera + HUD follow the best 'hero' drone; only the hero glyph is hidden in the FPV pass so neighbours stay visible. Cameras frame the bbox over every path; capture spans the longest track.

## Result
`swarm_race_s1` re-recorded -> 1 group episode, 3 co-env drones (flat idx 0,1,2) on one course (gate hash b0114de9), all 232 frames. Per-drone best laps 2.38s / 2.82s / 3.40s vs oracle 3.48s. Rendered hero MP4 shows three trails (blue/red/yellow) racing through the shared gates in the wide shot, top-down, and FPV insets. Single-drone gate_race path verified unchanged; full pytest green.

## Commits
- neural-whoop `d606a93` (recorder + schema v2 + VISUAL_CONTRACT doc)
- nw-viz `b088262` (multi-drone viewer)

## Caveat / next
This is single-seed visual (only swarm_race_s1 had a recorded replay; s0/s2 were never `--record`ed — their multi-seed metrics back the GREEN claim though). The matplotlib `trajectory.png` still shows only the lead drone (it reads the v1-mirror); extending render.py to overlay the group is a possible follow-up.