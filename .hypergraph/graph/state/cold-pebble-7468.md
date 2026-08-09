---
node_id: 27ef5043-607a-53cb-836f-1e49fd8cdce6
slug: cold-pebble-7468
title: Batched environment and the task registry
created_at: '2026-08-09T18:42:31+00:00'
parents:
- dusty-pine-0511
summary: 'MultiAgentDroneEnv: a batched, GPU-resident, agent-flattened env with a task registry. Thirteen tasks registered. Working. Measured at ~444k env-steps/s, which a CPU-vectorised competitor beats by ~15x.'
flywheel:
  node_id: b55692c7-1c02-5c6f-93fe-2a5a4733757d
  slug: yellow-star-4139
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: db219723c3bce5ebaee21f369dd44793cea883d98f294e60621efe14f192123d
---
Status: working

## Current

`MultiAgentDroneEnv` (`src/neural_whoop/envs/base.py`) flattens `(n_envs, n_agents)`
into a single `n_drones = n_envs * n_agents` dynamics batch, so DiffAero always runs
with `n_agents = 1` internally and every multi-agent coupling — collisions, relative
observations — stays in this project's task layer. Each drone is one PPO sample under
a shared policy [rec: morning-feather-7342]. That choice is what let both swarm tasks
be added with no env change at all.

Thirteen tasks are registered [rec: wandering-water-2720] (`@register_task`, `src/neural_whoop/tasks/`):
`gate_race`, `swarm_race`, `swarm_formation`, `target_follow`, `hand_follow`,
`gesture_follow`, `command_follow`, `hover`, `hover_blind`, `hover_blind_v2`,
`hover_tof`, `acro_flip`, `reference_track`. Adding one needs a subclass, a config
and an import — `docs/TASK_CATALOG.md` is the roadmap and each entry carries its
metric and its sim2real basis.

Throughput [rec: winter-sun-1382]: ~444k env-steps/s end to end on one RTX 5090 at 4096 envs, i.e. 40 M
steps in about 90 s (`README.md`).

## Negative knowledge

- [scope: this env's throughput vs a CPU-vectorised alternative | confidence: high | evidence: lively-dawn-5118, long-fog-2207] PufferLib's CPU drone env was installed and run on the same 5090 and measured 6.4 M steps/s against this env's ~437 k — roughly 15x. The gap is real and was measured rather than argued; the system-comparison branch exists because of it. What did NOT transfer is the reason to switch: their env has no path to camera or depth observations.

## Provenance

- morning-feather-7342 — the agent-flattening design decision and its rationale
- lively-dawn-5118 — the PufferLib throughput measurement on the same machine
- long-fog-2207 — the architecture comparison and what is and is not transferable
