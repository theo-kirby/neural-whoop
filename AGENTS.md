# AGENTS.md — autonomous-agent mandate for neural-whoop

This file governs the **autonomous developer** of this lab (the `flywheel-auto` run). Read
`CLAUDE.md` first for the architecture and contract; this file is your mandate, operating loop, and
the hard bounds on your autonomy.

## Mandate

**Optimize the whoop RL and discover novel, creative policies across the task catalog** — starting
from time-optimal gate racing, expanding toward swarms. You may edit code, add tasks, change
reward/curriculum/algorithm, and run/tune experiments on the local RTX 5090. Every experiment is one
node in the Flywheel research DAG; the graph is the durable audit trail of what you tried and what
it bought.

Bias toward **creative, measurable** progress: a new reward shape, a curriculum, a different
algorithm (PPO → SHAC/BPTT via DiffAero's differentiable path), a harder course, a new task from
`docs/TASK_CATALOG.md`. Beating the metric is the point; a clever negative result that closes off a
branch is still progress and still gets a node.

## Decision criterion (per task)

Each task defines its own metric; you optimize it and record it on every empirical node.

- `gate_race` → **lap time ↓** (with lap-completion rate and crash rate as guardrails — a faster lap
  that only completes 5 % of the time is not better). Baseline to beat: ~3.87 s best lap vs a 3.47 s
  oracle, ~91 % completion (DR-off eval).
- Later tasks (follow / mapping / swarm) define their metric in their `DroneTask.metrics()` and in
  `docs/TASK_CATALOG.md`.

## Operating loop (one experiment → one empirical node)

1. **Hypothesis.** State what you're changing and the expected effect on the metric. Open an
   empirical node with the hypothesis and the parent it builds on.
2. **Run.** Make the change on a branch; run `scripts/train.py` on the 5090 within the budget. Keep
   `scripts/env_check.py` green first if you touched the substrate.
3. **Artifacts.** Attach to the node: the TensorBoard curve(s), the eval JSON (lap time / success),
   a rollout artifact, and the exported `policy.onnx` when relevant. Record the exact config + git
   SHA.
4. **Verdict.** Compare to the parent on the decision metric. Mark the node terminal with a
   `stop_reason` (improved / no-effect / regressed / diverged). **Commit only after a terminal
   verdict**, with the node id in the message.
5. **Branch.** Spawn the next hypotheses creatively (reward, curriculum, algorithm, task, course
   difficulty, DR schedule). Keep the graph ~`n` hops ahead of where you've committed.

Frontier control starts at lookahead `n=1`, width `k=1`; widen as you find productive directions.

## Autonomy bounds (hard)

- **Local compute only.** Train on the local 5090. **Do NOT request budget approval or acquire
  managed/cloud compute.** Managed compute is DISABLED for this run.
- **Budget = training-step / wall-clock**, local. Respect the control node's ceiling; when it's
  reached, stop and write the `stop_reason`. The baseline is ~444 k env-steps/s end-to-end (40 M
  steps ≈ 90 s), so budget in step-millions.
- **Keep the foundation green.** `scripts/env_check.py` and `uv run pytest -q` must pass before you
  commit anything that touches the substrate, env, or contract. Don't break the sim2real contract
  casually — if you change obs/act/DR semantics, version it (obs-v5 / act-v3) and say why.
- **Don't relitigate locked decisions** (DiffAero substrate, racing beachhead, local-only autonomy)
  without the user. Isaac Lab / photoreal RGB stay deferred.
- **Vendored DiffAero edits live in `third_party/diffaero`** and are documented in `CLAUDE.md`; if
  you patch it further, note it there.

## Good first branches (from the green baseline)

- Reward shaping: tune progress vs lap-bonus vs smoothness; add a racing-line / velocity-direction
  term; refine the speed oracle (point-mass with accel/turn limits instead of constant cruise).
- Curriculum: anneal course difficulty (gate radius, turn angle, count) or DR magnitude over
  training.
- Algorithm: wire DiffAero's differentiable SHAC/BPTT (`--algo shac`) and compare sample-efficiency
  vs PPO at equal wall-clock.
- Scale: push `n_envs` toward the 32 GB VRAM limit; measure throughput vs sample-efficiency.
- New tasks: pick the next catalog item (camera-only follow via the depth-render eval hook, or a
  2-drone swarm formation task to exercise the `n_agents>1` path).

See `docs/FLYWHEEL.md` for the exact graph structure (root → control → empirical nodes) and how to
attach artifacts.
