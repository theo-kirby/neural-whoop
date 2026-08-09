---
node_id: 51aabea1-f793-534d-a0a7-bc9b1e368bbb
slug: morning-feather-7342
title: 'neural-whoop: GPU-parallel, swarm-capable whoop RL lab'
created_at: '2026-06-26T09:10:24.314340+00:00'
parents: []
summary: 'Root node. Objective: optimize whoop RL and discover novel, creative drone policies across a broad task catalog, starting from single-drone time-optimal gate racing and expanding to swarms. Built on a vendored DiffAero substrate, trained on one local RTX 5090, developed autonomously on Flywheel.'
origin:
  backend: flywheel
  node_id: 51aabea1-f793-534d-a0a7-bc9b1e368bbb
  slug: morning-feather-7342
  revision: 28
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ebfd638e-3ff8-57e0-9b4a-db221719b1c5
  slug: silent-base-7036
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: 834cac7a2984c87c3f92756f0a093d9a7943fd22c1771ed0d240b2b2f874e457
---
# neural-whoop

GPU-parallel, swarm-capable whoop RL lab and the successor to neural-whoop-lab (single-drone, PyBullet, SB3-PPO). Trains tiny, quantization-friendly policies that fly a real ~32 g tiny-whoop, starting from single-drone gate racing and expanding toward swarms. Repo: git@github.com:theo-kirby/neural-whoop.git (branch scaffold/flywheel-foundation, commit 1394e9a).

## Objective
Optimize the RL and discover novel, creative drone policies across the task catalog, with every experiment recorded as a node in this research DAG. Per-task metric drives decisions (racing -> lap time down).

## Locked decisions (do not relitigate without the user)
1. Substrate = DiffAero, vendored under third_party/diffaero (BSD-3), pinned at upstream 291ea14 and patched to run its pure-torch dynamics core on Blackwell/sm_120 without the rendering stack (pytorch3d/taichi/open3d). Isaac Lab deferred (tiled-camera hangs on Blackwell).
2. First beachhead = single-drone time-optimal gate racing (gate_race), state/oracle-based so it never touches the Blackwell-broken camera path. Metric = lap time.
3. Autonomy = full, local-only. The agent edits code, adds tasks, runs/tunes experiments on the 5090; NO managed cloud compute; bounded by a training-step / wall-clock budget. This graph is the post-hoc audit trail.

## Architecture (see CLAUDE.md)
TinyPolicy (obs-v4 -> act-v2 CTBR) -> MultiAgentDroneEnv (batched, agent-flattened) -> WhoopDynamics (DiffAero QuadrotorModel) + DomainRandomizer + perception oracle + DroneTask. Torch-native PPO over the batched env. Each of n_drones is one PPO sample (shared policy).

## Task catalog (docs/TASK_CATALOG.md)
racing (done) -> camera-only follow -> hand/gesture follow -> alt-sensor module -> mapping/exploration -> swarm formation/coverage -> swarm coop transport -> swarm-vs-swarm. Each with a loose sim2real basis.

Docs: CLAUDE.md (architecture/contract), AGENTS.md (autonomous mandate + bounds), docs/{TASK_CATALOG,CONTRACT,FLYWHEEL}.md.