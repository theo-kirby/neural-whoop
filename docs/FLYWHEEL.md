# Flywheel: how neural-whoop maps onto the research graph

This project is developed autonomously on [Flywheel](https://flywheel.paradigma.inc): every
experiment is a node in a research DAG, and the graph is the durable, post-hoc audit trail of what
was tried and what it bought. This doc defines the graph structure and the run contract. The
operating loop for the agent is in `AGENTS.md`.

## Setup (one-time, interactive — needs the user)

Flywheel MCP is not connected by default. To enable it:

```bash
npx --yes @paradigma-inc/flywheel setup --mode mcp
# then authenticate in the browser at flywheel.paradigma.inc
```

Verify with the `flywheel_auth_status` MCP tool. **This step is interactive** (browser / API-key
auth); the autonomous agent cannot complete it — the user must. Until it's done, training/eval/
export all work locally; only the graph recording is gated.

## Graph structure

```
[root: neural-whoop]                      project objective + locked decisions + repo + TASK_CATALOG
   │
   └─[control node]                       the durable run controller (flywheel-auto contract)
        │   objective: optimize whoop RL + discover novel policies across the catalog,
        │              starting from time-optimal gate racing, expanding to swarms
        │   decision criterion: per-task metric (racing → lap time ↓)
        │   budget: training-step / wall-clock (LOCAL)
        │   compute approval cap: managed compute DISABLED (local 5090 only)
        │   lookahead n=1, frontier width k=1; terminal condition + stop_reason
        │
        ├─[empirical: gate_race baseline]  ← start node (this handoff)
        │     hypothesis: PPO over batched DiffAero whoop learns near-oracle racing
        │     artifacts: training curve, eval JSON (lap time), rollout, policy.onnx
        │     verdict: ~3.87 s best lap vs 3.47 s oracle, ~91% completion (DR-off)
        │
        ├─[empirical: <reward refinement>]   (agent-generated branches)
        ├─[empirical: <curriculum>]
        ├─[empirical: <SHAC vs PPO>]
        └─[empirical: <next catalog task>]   ...
```

### Root node `neural-whoop`
Project objective, the three locked decisions (DiffAero substrate / racing beachhead / local-only
autonomy), repo location, and a link to `docs/TASK_CATALOG.md`.

### Control node
The run controller per the `flywheel-auto` contract:
- **Objective:** optimize whoop RL and discover novel/creative policies across the catalog.
- **Decision criterion:** per-task metric (racing → lap time ↓; later tasks define their own).
- **Start node:** the gate-racing baseline.
- **Budget ceiling / unit:** training-step / wall-clock, **LOCAL**.
- **Compute approval cap:** managed compute **DISABLED** — local 5090 only, no budget approval.
- **Lookahead `n` / frontier width `k`:** start `n=1`, `k=1`.
- **Terminal condition + `stop_reason`** field on every resolved node.

### Empirical nodes (one experiment each)
Hypothesis → run → artifacts → verdict (see `AGENTS.md` step list). Each records the exact config +
git SHA and is marked terminal with a `stop_reason` (improved / no-effect / regressed / diverged).
Commit code only after a terminal verdict, with the node id in the message.

## Execution model

Local hardware only. The agent runs `scripts/train.py` on the 5090 and attaches **artifacts** to
the empirical node:

- the **standard visual pack** (`scripts/viz.py`) — `replay.json.gz` (portable telemetry),
  `trajectory.png` (flown path + gate-loop reference), `fpv_*.png` (synthetic onboard view),
  `training_curves.png`, `eval.json`, and a parent `comparison.png` + leaderboard `table.csv`. This
  is auto-attached to every empirical node, public (see `AGENTS.md` step 3 and
  `docs/VISUAL_CONTRACT.md` for the artifact-type mapping);
- exported `policy.onnx` — the deployable tiny policy.

The honest depth-render rollout (real pixels) remains a later hook via the `render_depth` seam; the
analytic synthetic FPV in the pack covers the FPV artifact until then.

**Explicitly:** do **not** request budget approval or acquire managed compute. The budget is the
local training-step / wall-clock ceiling on the control node.

## Baseline node payload (the handoff)

The first empirical node is the green baseline produced by this scaffold:

- config: `configs/gate_race.yaml`; task `gate_race`; 4096 envs; ~40 M steps.
- result: ep-return −12 → +85; best lap 3.87 s vs 3.47 s oracle; ~91 % lap-completion; near-zero
  crash rate (DR-off eval); actor ~5.4 k params.
- artifacts: `runs/gate_race_baseline/` checkpoints + TensorBoard, eval JSON, `policy.pt`,
  `policy.onnx`.

From here the agent advances the frontier (see `docs/TASK_CATALOG.md` for directions).
