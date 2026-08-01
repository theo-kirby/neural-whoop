# Flywheel: how neural-whoop maps onto the research graph

This project is developed autonomously on [Flywheel](https://flywheel.paradigma.inc): every
experiment is a node in a research DAG, and the graph is the durable, post-hoc audit trail of what
was tried and what it bought. This doc defines the graph structure and the run contract. The
operating loop for the agent is in `AGENTS.md`.

## Setup (one-time, interactive — needs the user)

Flywheel is not connected by default. It installs in one of **two modes**, and which one you get
decides how the agent talks to the graph:

```bash
npx --yes @paradigma-inc/flywheel setup --claude --mode mcp   # MCP tools (flywheel_get_node, ...)
npx --yes @paradigma-inc/flywheel setup --claude --mode cli   # the `flywheel` CLI + skills
# then authenticate in the browser at flywheel.paradigma.inc (or supply --api-key)
```

**Both modes work; the `flywheel_*` tool names used throughout these docs assume `--mode mcp`.**
Under `--mode cli` there are no MCP tools — `claude mcp list` will not show Flywheel — and every
mutation goes through the `flywheel` binary instead. The mapping is one-to-one:

| doc says (MCP) | CLI equivalent |
|---|---|
| `flywheel_auth_status` | `flywheel auth:status` |
| `flywheel_get_node` (`projection=full`) | `flywheel nodes:get --node_id <id> --projection full` |
| create a node | `flywheel nodes:commit-new --payload_json=@payload.json` |
| prepare → PUT → finalize | `flywheel artifacts:upload --node_id <id> --expected_revision <r> --items=@items.json` |
| set tag assignments | `flywheel tags:assign --node_id <id> --tag_ids a,b,c --expected_revision <r>` |

Verify with `flywheel auth:status` (or the `flywheel_auth_status` tool). **This step is
interactive** (browser / API-key auth); the autonomous agent cannot complete it — the user must.
Until it's done, training/eval/export all work locally; only the graph recording is gated.

**Gotchas found the hard way (2026-08-01), all of them silent failures:**

- **`setup` is per-host.** Installing for a different host (e.g. `--openclaw`) leaves Claude Code
  with nothing. Pass `--claude` explicitly. Switching an already-installed host between modes needs
  `--force` and tears down the other mode, so decide once.
- **`nodes:get --projection core` reports `artifacts_total: 0` even when artifacts are attached.**
  Verify with `--projection full` (or `artifacts:list`), or a correct upload looks like a failure.
- **`nodes:parents` / `nodes:children` return their rows under `edges`**, not `items`/`parents` —
  parsing the wrong key makes a correctly-wired DAG look edgeless.
- **Artifact type/media-type is validated and the batch is atomic.** Use `binary` +
  `application/gzip` for `replay.json.gz` (**not** `json` — it is gzipped, and `json` 422s), `json`
  for plain `.json`, `image` for `.png`, `binary` + `video/mp4` for clips. The `table` type rejected
  a `text/csv` upload; ship tabular results as `json`. One bad item fails the whole batch with a
  bare `422`, so mirror the types an existing node already uses.

## Graph structure

The graph is a **branchy, multi-parent DAG**, not a chain. The spine is
`root → control node → gate_race baseline`; from the baseline the frontier fans into parallel,
cross-linked workstreams (the `cluster:` tags), each its own thread of experiments / measurements /
ideas / hypotheses that re-converge through multi-parent edges:

```
[root] → [control node] → [gate_race baseline]
                                 ├─ reward-shaping     time_penalty(GREEN) → racing-line(RED) → honest oracle
                                 ├─ capacity-budget    [128,128] capacity → 80M → 120M knee (lever exhausted)
                                 ├─ reliability-dr      DR-on measurement → DR curriculum(RED) → reliability reward(NO-GO)
                                 ├─ generalization      overfit-geometry measurement → scale-generalist (★ studio-baseline)
                                 ├─ swarm               swarm_race(GREEN) → density(NO-GO) → swarm_formation(GREEN) → N-scaling
                                 ├─ perception          detector-hardening → EMA precision filter(GREEN) → filtering thread
                                 ├─ follow (perception) target_follow → hand_follow → gesture_follow → command_follow
                                 └─ tooling-viz         replay seam → nw-viz → Studio → scene channel  (parents many threads)
```

Threads genuinely interweave — e.g. the EMA perception primitive composes with the swarm thread
(perception-aware formation), and the tooling-viz nodes parent on every thread they render. **Use
multi-parent edges for true lineage** (a node that builds on several results gets several parents;
branch off a shared baseline when probing alternatives; parent a refutation on the hypothesis it
tests). Periodic **synthesis nodes** (`kind:method`/`idea`, multi-parent onto each cluster's current
best) act as navigational "state-of-the-frontier" anchors — what won, which levers are exhausted,
where the open frontier is.

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
git SHA and is marked terminal with a `stop_reason`. Commit code only after a terminal verdict, with
the node id in the message. The conventions every node must satisfy are below.

## Node conventions / definition of done

These are the rules that make the graph a trustworthy audit trail — they own the conventions
referenced from `CLAUDE.md` and `AGENTS.md`.

**Cardinal rule — no empty nodes.** Every **empirical** node (an experiment or measurement) carries
**≥1 finalized artifact** *and* a written summary. The artifact is the standard visual pack
(`scripts/viz.py` → `replay.json.gz`, `trajectory.png`, `fpv_*.png`, `training_curves.png`,
`comparison.png` + `table.csv`, `eval.json`, **`run.json`**; see `docs/VISUAL_CONTRACT.md`). *If it
isn't backed by an artifact and a written result, it didn't happen.* Non-empirical nodes (idea /
hypothesis / pure method/tooling) need the summary + tags but not a metric artifact.

**Summary discipline.** The summary states the **change vs the parent**, the **metric Δ**, and the
**verdict** — reproducible from the text alone (e.g. "[128,128] policy: 3.29→2.91 s best lap, −12 %,
GREEN"). A bare title is not a summary.

**Body skeleton.** **Hypothesis → Setup → Results (with the Δ vs parent/baseline) → Verdict /
Honesty → Lineage.** Negative/refuted results use the same shape — be honest, an RED/NO-GO that
closes a branch is real progress. Canonical exemplar: the `time_penalty` node (`morning-base-2167`).

**`stop_reason` vocabulary** (every resolved empirical node; the one definition — `AGENTS.md` and
`CLAUDE.md` point here):

| `stop_reason` | meaning | typical `outcome:` tag |
|---------------|---------|------------------------|
| `improved` | beat the parent on the decision metric | `GREEN` |
| `no-effect` | within noise of the parent | `NO-GO` |
| `regressed` | worse than the parent | `RED` |
| `diverged` | training failed / unstable | `RED` |

Mixed/Pareto results (a genuine trade, not a clean win) may carry no `outcome:` tag — an honest
signal that it's nuanced — but still state the trade in the summary.

**Tag every node** (taxonomy + the connected-subgraph rule for `cluster:` tags live in `CLAUDE.md`):
one `kind:`, an `outcome:` if it has a verdict, ≥1 `cluster:`. Untagged nodes vanish from zoomed-out
views.

**Definition of done / verify.** After committing a node, **re-read it** (`flywheel_get_node`,
`projection=full`) and confirm: artifacts attached (`artifacts_total > 0` for empirical nodes) +
summary written + tags set. Apply this to your own work — it's the same "verify after commit" step
the rest of the lab uses.

## Execution model

Local hardware only. The agent runs `scripts/train.py` on the 5090 and attaches **artifacts** to
the empirical node:

- the **standard visual pack** (`scripts/viz.py`) — `replay.json.gz` (portable telemetry),
  `trajectory.png` (flown path + gate-loop reference), `fpv_*.png` (synthetic onboard view),
  `training_curves.png`, `eval.json`, the `run.json` reproducibility manifest, and a parent
  `comparison.png` + leaderboard `table.csv`. This is attached to **every empirical node** per the
  cardinal rule above (public; see `AGENTS.md` step 3 and `docs/VISUAL_CONTRACT.md` for the
  artifact-type mapping);
- exported `policy.onnx` — the deployable tiny policy.

The honest depth-render rollout (real pixels) remains a later hook via the `render_depth` seam; the
analytic synthetic FPV in the pack covers the FPV artifact until then.

**Explicitly:** do **not** request budget approval or acquire managed compute. The budget is the
local training-step / wall-clock ceiling on the control node.

## Baseline node payload (the start node)

The **start** node — the first empirical node, the foot of the frontier, **not** the graph's end —
is the green baseline produced by this scaffold:

- config: `configs/gate_race.yaml`; task `gate_race`; 4096 envs; ~40 M steps.
- result: ep-return −12 → +85; best lap 3.87 s vs 3.47 s oracle; ~91 % lap-completion; near-zero
  crash rate (DR-off eval); actor ~5.4 k params.
- artifacts: `runs/gate_race_baseline/` checkpoints + TensorBoard, eval JSON, `policy.pt`,
  `policy.onnx`.

From here the agent has advanced the frontier across every cluster above — reward-shaping → the
120M capacity/budget knee → reliability-dr → the scale-generalist (the current `★ studio-baseline`)
→ swarm → perception → the follow/command thread (see the Graph structure section and
`docs/TASK_CATALOG.md`). The baseline is where the DAG *starts*, not where it stops.
