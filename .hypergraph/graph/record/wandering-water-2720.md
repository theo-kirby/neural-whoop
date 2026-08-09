---
node_id: e6b6216e-3ae2-56bf-a50c-ff9e71fc081f
slug: wandering-water-2720
title: 'Adopted Hypergraph: the 189-node Flywheel graph is imported as the fork; the archive is frozen'
created_at: '2026-08-09T18:43:42+00:00'
parents:
- soft-breeze-8148
summary: 'Mode-A adoption. The whole 189-node Flywheel DAG reachable from morning-feather-7342 (2026-06-26 to 2026-08-08) imported verbatim with import --fork: slugs, node_ids and multi-parent topology preserved, archive identity filed under origin:. Artifacts (765 across 137 nodes) and the kind/outcome/cluster tag taxonomy did NOT travel and stay on the frozen Flywheel archive, which this project never writes to again. Full import rather than epoch-split (189 << 1000), so this marker parents on the newest legacy node rather than becoming a rival root. Seeds a 16-node state graph: 6 architecture components + 10 frontier claims, 4 broken / 3 blocked / 3 open. The author interview was NOT run and no brain-dump substituted for it - every claim here and in the state graph is derived from the imported node bodies, the twelve repo docs and git history alone.'
flywheel:
  node_id: 6903f577-ceaf-5c37-af34-41566cf15063
  slug: round-dust-9846
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: 23286bb729a4b8b293889af95ec6aa207a378f193f253e72086170dc582830fa
---
## What

neural-whoop adopted the Hypergraph protocol on 2026-08-09. The project's existing
Flywheel research DAG — 189 nodes reachable from the root `morning-feather-7342`
(node_id `51aabea1-f793-534d-a0a7-bc9b1e368bbb`), created 2026-06-26 through
2026-08-08 — was imported **verbatim and in full** into `.hypergraph/graph/record/`
with `hypergraph import --fork`. Slugs, node_ids, summaries, bodies and the whole
multi-parent topology travelled unchanged; each node file carries its archive
identity under `origin:`. A state graph was then distilled from the imported graph
and the repo docs, and this node is the epoch boundary between the two regimes.

From this node forward the repo is the continuing graph and owns its whole history.
The Flywheel graph is frozen as the archive and this project never writes to it
again.

## Why

The project already had a real, disciplined research record — the Flywheel DAG that
`docs/FLYWHEEL.md` and `AGENTS.md` mandate — but it lived on a hosted store, its
node discipline was enforced only by prose, and it had no distilled "what is true
now" layer. Everything a newcomer needs to *not* repeat a refuted experiment was
spread across 189 node bodies and 12 docs. Adoption imports that record so it
travels with the repo offline, and adds the state graph the Flywheel record never
had.

Mode A (full import), not epoch-split: 189 nodes is well under the ~1000-node
threshold at which the skill offers to leave older history on the archive, so the
whole graph came across and the marker parents on the newest legacy node
(`soft-breeze-8148`, 2026-08-08) rather than becoming a rival root.

## Method

1. `hypergraph adopt --survey` — 242 commits, 2026-06-26 → 2026-08-09, one effective
   author (`theo-kirby`, 240 of 242 commits), no tags, one continuous era, eleven
   top-level directory births. Highest churn: `docs/SIM2REAL.md` (33),
   `docs/TASK_CATALOG.md` (32), `CLAUDE.md` (29), `scripts/pilot.py` (27).
2. Anchor resolution. The repo names its graph root only as "neural-whoop" in
   `docs/FLYWHEEL.md`; no UUID is written down anywhere in the repo. The root was
   found by listing the account's nodes and taking the single parentless node titled
   `neural-whoop: GPU-parallel, swarm-capable whoop RL lab`. All 36 node slugs cited
   across the repo's docs were verified to fall inside that root's reachable
   subgraph, so the root is the only anchor — no doc declares a separate index node
   as a system of record.
3. `hypergraph mirror pull --record-node-id 51aabea1-… --out-dir .hypergraph/cache`
   → 189 nodes.
4. `hypergraph adopt --init` (config + state root `dusty-pine-0511`), then
   `hypergraph import --record .hypergraph/cache/record.json --fork` → 189 node
   files. The legacy root became the repo's record root.
5. Distillation of the state graph from the imported bodies plus `CLAUDE.md`,
   `AGENTS.md`, `README.md` and the eleven files under `docs/`.

## Result

- **Imported:** 189 record nodes, verbatim, with the original multi-parent topology.
  The graph spans eleven workstreams (`cluster:` tags on the archive):
  deploy-hw (79 nodes), tooling-viz (29), perception (19), agility (17),
  generalization (17), swarm (12), system-comparison (9), capacity-budget (9),
  reward-shaping (6), reliability-dr (4), stability (2). By verdict: 50 GREEN,
  23 RED, 11 NO-GO.
- **Left on the archive:** every artifact. 765 artifacts across 137 of the 189 nodes
  — the standard visual packs (`replay.json.gz`, `trajectory.png`, `fpv_*.png`,
  `training_curves.png`, `comparison.png`, `table.csv`, `eval.json`, `run.json` per
  `docs/VISUAL_CONTRACT.md`) plus exported policies. The node-file storage layer has
  no artifact operation, so the `archive:` block in `.hypergraph/config.yml` is the
  only pointer to them. Every empirical claim in the state graph is therefore backed
  by a node *body*, not by a re-openable artifact.
- **Also left behind:** tags. The archive's `kind:` / `outcome:` / `cluster:` /
  `★ studio-baseline` taxonomy (defined on the root, documented in `CLAUDE.md`) has
  no counterpart in a node file and did not travel. The pointer tag
  `★ studio-baseline` sat on `white-rice-3299` at export time; its meaning now lives
  in the state graph instead.
- **Distilled:** 16 state nodes — six architecture components and ten frontier
  claims — with honest statuses, not a template: seven `working`, three `broken`,
  four `open`, two `blocked`. The kebab impact names below map to
  minted slugs as follows:

  | impact name | state slug | status |
  |---|---|---|
  | sim-substrate | `wise-trail-6304` | working |
  | batched-env-and-tasks | `cold-pebble-7468` | working |
  | policy-contract | `long-mountain-5811` | working |
  | training-eval-export | `loyal-grove-4659` | working |
  | viz-studio-capture | `lawful-nest-5138` | working |
  | deploy-pilot-bridge | `modest-raven-7153` | broken |
  | racing-lap-time-frontier | `autumn-stream-8410` | open |
  | swarm-tasks | `peaceful-mist-1317` | working |
  | perception-follow | `strong-spire-1133` | working |
  | agility-maneuvers | `loyal-wood-6029` | open |
  | hover-deploy-operating-point | `lucky-lodge-5696` | broken |
  | tof-calibration | `rapid-hill-4130` | open |
  | espnow-link | `forest-timber-8727` | open |
  | onboard-compute | `northern-rain-9996` | blocked |
  | camera-perception | `vast-dune-7535` | blocked |
  | measurement-and-doc-integrity | `autumn-bell-7061` | broken |
- **One gap the import exposed:** the repo's own contract says "commit only after a
  terminal verdict, with the node id in the message", yet the newest legacy node is
  2026-08-08T16:11 and HEAD is `b9f4ce5` on 2026-08-09 ("viz: the hover setpoint
  marker was a fixed 0.16 m sphere — it swallowed the desk-scale frame"). That
  commit has no node. It is the first thing the new protocol would have caught.

## The author interview did not happen

**The `hypergraph-adopt` interview (step 3) was not run. The author was not
available for this adoption, and no brain-dump, notes file or message was supplied
in its place.** Every claim in this node and in the state graph it seeds is derived
from evidence that was read: the 189 imported node bodies, the repo's twelve
documents, and the git history. Nothing here is author-informed.

What that costs, concretely, is intent. The evidence records what was tried and what
the numbers were; it does not record which of the timeline's boundaries the author
would call an era, which decisions he would relitigate, what he is deliberately not
doing, or what is only in his head. Where a claim in the state graph would have
needed that, it is phrased as a claim about the evidence rather than about the
author's intent, or marked `open`. A list of the questions the evidence could not
settle was handed to the author with this adoption.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: b9f4ce5c4eab2cc614ed34d88a432e2112aed7d7

## State Impact

- target: NEW sim-substrate — the vendored DiffAero dynamics core and this project's patches to it; `working`, with the 2026-08-01 rate-loop frame bug and its consequence for pre-fix non-planar results as negative knowledge
- target: NEW batched-env-and-tasks — `MultiAgentDroneEnv`, the agent-flattened batch, the task registry and the thirteen registered tasks; `working`
- target: NEW policy-contract — obs-v4 / act-v2 CTBR and the two-layer domain-randomization seam; `working`
- target: NEW training-eval-export — torch-native PPO over the batched env, deterministic eval, TorchScript/ONNX/C export; `working`
- target: NEW viz-studio-capture — the replay schema, the renderer, the Studio and the in-repo headless video capturer; `working`
- target: NEW deploy-pilot-bridge — the real-drone path (pilot flight engine, MSP bridge, ToF sensor); `broken`, and the parent of the deploy frontier
- target: NEW racing-lap-time-frontier — `open`: ~37% honest-oracle lap-time headroom remains and five separate levers were exhausted against it
- target: NEW swarm-tasks — `working` with a measured ceiling: shared-track racing collapses past n=3, own-slot formation scales flat to 24
- target: NEW perception-follow — `working`: the EMA precision filter is the lab's reusable perception primitive, with a measured speed envelope
- target: NEW agility-maneuvers — `open`: reward-shaped flip discovery is refuted, reference-tracked swing and orbit are GREEN, the tracked flip is RED
- target: NEW hover-deploy-operating-point — `broken`: the shipped 1.0 m hover setpoint sits outside the sensor's trusted band and crashed every real flight that reached it
- target: NEW tof-calibration — `open`: a pilot-side ToF zero-offset calibration is the named blocking item for a real Desk-Hover flight and does not exist
- target: NEW espnow-link — `open`: implemented end to end, every acceptance gate still unmet, awaiting an in-flight measurement
- target: NEW onboard-compute — `blocked`: the compute budget is measured and comfortable, but nothing has been ordered and the BOM awaits the user
- target: NEW camera-perception — `blocked`: the honest camera-only path is gated on Isaac Lab's Blackwell tiled-camera bug and `render_depth` is still a stub
- target: NEW measurement-and-doc-integrity — `broken`: a metric script was structurally unable to report the failure it was quoted for, and several published doc claims are now false
