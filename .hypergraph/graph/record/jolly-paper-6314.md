---
node_id: 4b5c1e17-0401-596d-b705-021edd553d1f
slug: jolly-paper-6314
title: 'Control node: neural-whoop autonomous run controller (flywheel-auto)'
created_at: '2026-06-26T09:10:47.838968+00:00'
parents:
- morning-feather-7342
summary: 'Autonomous whoop-RL frontier controller. Objective: optimize RL + discover novel policies (racing -> swarms -> perception -> generalization). Budget LOCAL; managed compute DISABLED. n=1,k=1; PUBLIC; DAG. 7 tasks. RACING exhausted on speed; SWARM race caps n=3 / formation scales to 24; PERCEPTION target_follow SOLVED (EMA 0.85), 4 follow tasks. SCALE-GENERALIST arc COMPLETE (cluster:capacity-budget, 4 nodes A/B/C/D): range-training generalizes tight->giant (GREEN), curriculum NO-GO, [256,256] is the capacity knee (GREEN -> studio-baseline; [384] turns over), importance-sampling is a clean giant<->tight Pareto dial. BACKLOG remaining (git af3ed31..d76ed4a, packs on disk): hover task + Studio Live -- staged next.'
origin:
  backend: flywheel
  node_id: 4b5c1e17-0401-596d-b705-021edd553d1f
  slug: jolly-paper-6314
  revision: 60
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 834a962b-727d-58c8-814a-f75d893d5d56
  slug: patient-scene-7188
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: abb1b9679455b6e38da3bf783c6636d355e6cc7568969fd0a420b1676f53eeb4
---
# Control node (flywheel-auto run contract)

Durable controller for autonomous neural-whoop development. Continue graph-locally from this contract.

## Objective
Optimize whoop RL + discover novel policies across the catalog: gate racing -> swarms -> perception-in-the-loop -> generalization.

## Decision criterion (per task)
gate_race -> lap time DOWN + guardrails (cross-scale: lap_completion_rate across ARENA_PRESETS). swarm_race -> lap_completion_rate + bounded collision_rate + best_lap. target_follow/hand_follow -> follow accuracy (track_err/hold) UP at bounded crash. gesture/command_follow -> per-command compliance. swarm_formation -> mean_formation_error DOWN + formation_hold_rate UP at bounded collision_rate. hover -> hold_rate UP + pos_error DOWN at zero crash under disturbance. New tasks define their metric in DroneTask.metrics()/docs/TASK_CATALOG.md.

## Start node: gate_race baseline empirical node (child of this control node).

## Budget
training-step / wall-clock, LOCAL. swarm 120M ~2.5min/run; target/hand_follow 120M ~5min/run; gate_race generalist 120M ~90s-2min/run. Compute approval cap: managed compute DISABLED -- local 5090 only, NO approval, do NOT acquire managed/cloud compute.

## Frontier control
Lookahead n=1, width k=1; widen as productive directions appear. Terminal condition: budget ceiling OR no measurable progress; each resolved node carries a stop_reason.

## Operating loop (see AGENTS.md)
One experiment -> one empirical node: hypothesis -> run -> attach visual pack + parent comparison -> verdict -> commit code only after terminal verdict (GREEN promoted; refuted/no-go NOT promoted but default-off tooling kept; measurement/nuanced/Pareto hops = analysis; nuanced new-task infra kept). VERIFY instantiated config params before trusting a run. Keep env_check + pytest green. MCU LOCKED: tiny export-clean policies; flag obs_dim/param growth. ARTIFACTS: CSV tables upload as artifact_type=text (type=table 422s on raw CSV bytes).

## Graph & sharing conventions
1. PUBLIC every new node immediately. 2. DAG not a chain: builds-on = current best baseline; informed-by = a failed/sibling branch whose lesson shaped this. 3. Only durable relationships become edges. 4. State each node's lineage in its body. 5. Visual pack: prepare -> raw-PUT (Content-Type + X-Flywheel-Artifact-Filename) -> finalize; replay/ONNX -> binary type, CSV -> text type. 6. CLUSTER tags must form a CONNECTED subgraph -- the scale-generalist arc lives in cluster:capacity-budget (connected to budget-knee 8db85abb), NOT cluster:generalization (members in another branch, topologically disjoint). OPS: stage-lease TTL SHORT (~15s) -- issue acquire + commit BACK-TO-BACK in the SAME turn to beat expiry. commit_node REQUIRES repo_context.

---

## Run progress (graph-local frontier log)

**RACING BASELINE = [128,128]@120M -> DR-off 2.60s/0.92** (0933f70). EXHAUSTED on speed (~37% honest-oracle headroom is a CONTROL limit; ent_coef sweep RED 08c0c825).
**SWARM BRANCH (cluster:swarm) = 2 tasks.** swarm_race hop13 (4b21d59b) GREEN; density (0bd2cc36) NO-GO caps n=3. swarm_formation hop15 (7cd41adf) GREEN; hop17 scaling (e3519636) GREEN: formation holds n=6/12/24.
**PERCEPTION BRANCH (cluster:perception) = SOLVED + 4 follow tasks:** EMA(0.85) best (3db0af65); predictive NO-GO (da87e550,85c7aa87); hand_follow GREEN (bfdbedd7); speed-env breaks ~4.5 m/s (c92c91db); gesture_follow GREEN 2-way (82dca633); command_follow nuanced 3-way (5a0515b2). HEAD-of-perception 4fc5046.
**CROSS-BRANCH:** hop18 perception-aware formation (bcee9cf6) GREEN: EMA recovers hold 0.574->0.862; multi-seed (c31b8155) ~0.84 moderate / ~0.51 tight.

**SCALE-GENERALIST ARC (cluster:capacity-budget) -- COMPLETE (4 nodes), noded 2026-06-28 from a discovered backlog (git f53c671..4698d6a committed but had been UN-NODED):** off the budget-knee baseline 8db85abb.
- A `33021e6e` (shy-wildflower-8500) GREEN: range-train radius 4.5->12 generalizes across course scale -- tight-only baseline COLLAPSES 0.95->0.21 (tight->giant completion) vs generalist 0.906->0.569.
- B `ab7db544` (weathered-wildflower-1251) NO-GO: scale CURRICULUM no gain + hurts giant (0.461 vs 0.569); flat uniform sampling wins.
- C `04e3221c` (snowy-sun-6709) GREEN + STUDIO-BASELINE: [256,256] on giant range (4.5->18) flies tight->giant 0.954/0.889/0.843/0.694 (seed0), recovers the tight tax AND beats the tight-only specialist; [384,384] TURNS OVER (knee at [256]); giant seed-sensitive (0.51-0.69, mean 0.60).
- D `accf5145` (snowy-rice-0635) Pareto: importance-sampling (scale_sample_weight 1.0/0.7/0.5) is a clean monotonic giant<->tight DIAL -- giant 0.600/0.706/0.837 vs tight 0.941/0.861/0.785. No dominating point; capacity is the ceiling. Studio default stays the uniform [256].

DAG (swarm): 8db85abb -> 4b21d59b -> {ffc5d9e4, 0bd2cc36 -> {7cd41adf -> c44ffb4c -> e3519636}}. Bridge: bcee9cf6 -> 07c7a70e -> c31b8155.
DAG (perception): 3db0af65 -> {8c66efec -> {da87e550 -> 85c7aa87, c92c91db}, bfdbedd7 -> {c92c91db, 82dca633 -> 5a0515b2}}; 3db0af65 -> bcee9cf6.
DAG (scale): 8db85abb -> 33021e6e(A) -> {ab7db544(B NO-GO), 04e3221c(C GREEN studio-baseline) -> accf5145(D Pareto)}.

### Verdicts
Swarm: racing caps n=3; clean formation scales to 24. Perception: EMA(0.85) best (<=3 m/s; predictive NO-GO; residual=detector info limit); command channel 2-way clean, scales-but-loosens 3-way (capacity). Generalization/capacity: range-training generalizes across course scale; curriculum NO-GO; [256,256] is the capacity knee; giant<->tight is an importance-sampling Pareto dial; capacity is the ceiling. Studio default now the full-range [256] generalist.

### Next staged (k=1) -- FINISH THE BACKLOG (committed in git, packs on disk, not yet noded):
- **E: hover task** (NEW task #8, cluster:reliability-dr/stability; runs/hover_base: hold_rate 0.91 / pos_err 0.15 m / mean_tilt 1.66deg / 0 crash; replay+pack+live_verification.json exist; config hover.yaml [64,64] + impulse DR seam): auto-stabilization + disturbance rejection; basis for Studio Live. GREEN-shaped. TOP PICK.
- **F: Studio Live tab** (cluster:tooling-viz; git 74fdf8c+d76ed4a): real-time impulse-seam disturbance demo (wind/push/drop/click-to-move) on add_velocity/add_body_rate; method node; builds-on hover (E).
- Then: gesture_follow precision tuning (return-to-last-seen, cluster:perception); detector-quality sweep. DEFERRED (USER sign-off): swarm per-drone-reset env-change. Deprioritized: DiffAero SHAC/BPTT.

## Stop reason (latest pass): non-terminal -- scale-generalist capacity arc (A/B/C/D) graphified + studio-baseline promoted; backlog partially closed; frontier replanned
This /loop pass found git af3ed31..d76ed4a (scale-generalist sweep, hover task, Studio Live) committed with NO Flywheel nodes -- the graph had drifted behind the repo. Graphified the whole scale-generalist capacity story as a connected 4-node DAG under cluster:capacity-budget: A range-generalization GREEN (33021e6e), B curriculum NO-GO (ab7db544), C [256,256] capacity-knee GREEN (04e3221c), D importance-sampling Pareto dial (accf5145) -- all PUBLIC, full visual packs (run.json + replay + plots; CSVs as text-type), tagged kind/outcome/cluster. Promoted the [256] full-range generalist to studio-baseline (off the tight-only racing policy). NOT terminal: budget intact, managed compute untouched, repo clean. Resume = node E (hover task, its own cluster) then F (Studio Live) to finish closing the backlog; both packs already on disk.