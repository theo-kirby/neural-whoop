# Hypergraph onboarding — neural-whoop

This project keeps its memory as two graphs of markdown files committed in this repo.
They travel with the checkout, offline, and they are the source of truth about what
this project has tried and what is true now.

- **Record graph** — `.hypergraph/graph/record/`. Append-only. Everything that
  happened, one node per unit of work, causally parented.
- **State graph** — `.hypergraph/graph/state/`. Distilled. What is true *now*:
  architecture, statuses, negative knowledge, and the frontier of open / broken /
  blocked work. Written only by a reconcile pass.
- **`STATE.md`** (repo root) — a generated snapshot of the state graph. Never
  hand-edit it.
- **`.hypergraph/config.yml`** — the roots, the adoption epoch, and the archive.

The protocol itself is `SPEC.md` in the hypergraph-protocol repo; the invariants it
enforces are I1–I8.

## This project's coordinates

| | |
|---|---|
| record root | `morning-feather-7342` — *neural-whoop: GPU-parallel, swarm-capable whoop RL lab* |
| state root | `dusty-pine-0511` |
| adoption epoch marker | `wandering-water-2720` (2026-08-09) |
| legacy nodes imported | 189 (2026-06-26 → 2026-08-08) |
| state nodes | 16 — six architecture components, ten frontier claims |
| archive | Flywheel, root `morning-feather-7342`, node_id `51aabea1-f793-534d-a0a7-bc9b1e368bbb` |

## The four non-negotiables

### 1. Orient on arrival

Run the `hypergraph-orient` skill, or read `STATE.md`. The **Frontier** section is
what matters: it lists every state node whose status is not `working`.

On this project that frontier is not decorative. Before you touch anything:

- **`lucky-lodge-5696`** (`broken`) — the shipped 1.0 m hover setpoint sits outside
  the ToF sensor's trusted band and crashed every real flight that reached it. The
  mechanism is measured. Do not fly at 1.0 m.
- **`autumn-bell-7061`** (`broken`) — `scripts/exit_probe.py` was structurally unable
  to report the vertical exits it was quoted for, so several published numbers in
  `docs/TASK_CATALOG.md` and `docs/SIM2REAL.md` were unearned. The fixed tool has not
  been re-run across the earlier ladder arms. Do not quote a probe number without
  checking when it was measured.
- **`modest-raven-7153`** (`broken`) — the deploy bench is down; the airframe needs
  rewiring after the last session's crash.

### 2. Record every unit of work

Run the `hypergraph-record` skill when you finish a meaningful unit — a feature, a
fix, an experiment, a dead end, a decision. One record node, causally parented, with
a `## State Impact` section (SPEC I1/I2). A new direction with no work behind it yet
is still recorded, as a decision node.

Work that exists only in the working tree is invisible to the project's memory. The
checker cannot see it locally, though `hypergraph check --since <ref>` catches it
across a branch.

**How this maps onto the discipline this project already had.** `docs/FLYWHEEL.md`
and `AGENTS.md` codified a good node discipline for the Flywheel graph. Keep it:

| Flywheel convention | now |
|---|---|
| hypothesis → setup → results → verdict/honesty → lineage | write it as `## What` / `## Why` / `## Method` / `## Result` |
| summary = change-vs-parent + metric Δ + verdict | still exactly right; the node's `summary:` field |
| true multi-parent lineage, not a chain | `--parent` is repeatable; use it |
| record negative and refuted results | the highest-value cargo there is |
| commit only after a terminal verdict, node id in the message | still right; the id is the record node's slug |
| `≥1 finalized artifact` per empirical node | **node files hold no artifacts.** Build the standard visual pack (`scripts/viz.py`), keep it under `runs/`, and name the path in `## Method` |
| `kind:` / `outcome:` / `cluster:` tags | **gone.** Say GREEN / RED / NO-GO in the title and summary, the way the archive's own titles do |
| `flywheel_get_node` verify-after-commit | `hypergraph check` |

### 3. Never write state nodes

Declare `## State Impact` lines on your record node and stop there (SPEC I3). Only
the `hypergraph-reconcile` skill folds them into the state graph, and it is the
single writer. Never hand-edit `STATE.md` — it is generated.

Record on any branch; reconcile only on `main`. Record nodes are one file each and
merge without conflict, so recording is always safe. The state graph has one writer,
so a reconcile on a side branch makes two.

### 4. Verify before finishing

```bash
uv run python scripts/env_check.py
uv run pytest -q
hypergraph sync --config .hypergraph/config.yml
```

`sync` re-exports (so `check` sees the current graph, which matters most right after
a merge), regenerates `STATE.md`, and checks. `check` must exit 0. It is **in
addition to** this project's existing foundation gate, not instead of it.

If `check` reports that this project's copies are behind the CLI, run
`hypergraph upgrade` — the skills and the `AGENTS.md` block are copies in this repo,
and `uv tool upgrade` cannot see them.

## The archive

The 189 record nodes dated 2026-06-26 to 2026-08-08 are **imported legacy history**.
They predate the epoch marker `wandering-water-2720`, so `check` exempts them from I2
(they carry no `## State Impact` section, and never will). Everything at or after the
marker is held to the full protocol — including anything you write.

Each imported node file carries its archive identity under `origin:`. The hosted
Flywheel graph is **frozen and read-only**: never create, edit, tag or re-parent
anything on it.

**Artifacts did not travel.** 765 artifacts across 137 of the 189 nodes — the standard
visual packs (`replay.json.gz`, `trajectory.png`, `fpv_*.png`, `training_curves.png`,
`comparison.png`, `table.csv`, `eval.json`, `run.json`) and exported policies — stayed
on the archive. The `archive:` block in `.hypergraph/config.yml` is the only pointer
to them, at flywheel.paradigma.inc. Every claim in the state graph is therefore backed
by a node *body*, not by a re-openable artifact.

**Tags did not travel either.** The `kind:` / `outcome:` / `cluster:` /
`★ studio-baseline` taxonomy defined on the Flywheel root has no counterpart in a node
file. Where a cluster mattered, its meaning is now in the state graph:
`cluster:deploy-hw` → `modest-raven-7153` and its children, `cluster:perception` →
`strong-spire-1133`, `cluster:swarm` → `peaceful-mist-1317`, `cluster:agility` →
`loyal-wood-6029`, `cluster:tooling-viz` → `lawful-nest-5138`, and the racing clusters
→ `autumn-stream-8410`.

## How this state graph was built, and what it is missing

The adoption pass on 2026-08-09 distilled 16 state nodes from the 189 imported node
bodies, the twelve documents in `docs/` and at the repo root, and the git history.

**The author interview did not happen.** The `hypergraph-adopt` skill's step 3 is an
interview with the project's author, and it was not run — the author was not available
and no brain-dump, notes file or message substituted for it. Nothing in the state graph
is author-informed. Claims that would have needed the author's intent are phrased as
claims about the evidence, or marked `open`.

Concretely, this state graph can tell you what was tried, what the numbers were, and
what was refuted. It cannot tell you which decisions the author would relitigate, what
he is deliberately not doing, or what only exists in his head. If you are the author:
the adoption handed over a list of the questions the evidence could not settle, and
answering them into record nodes is the highest-value thing you can do to this graph.
