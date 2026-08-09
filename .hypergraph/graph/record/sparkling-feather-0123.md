---
node_id: cb954865-7158-584e-b472-76d86b2fa0b8
slug: sparkling-feather-0123
title: 'Control: scale-generalization frontier (flywheel-auto run)'
created_at: '2026-06-28T15:15:26.008890+00:00'
parents:
- damp-wood-7079
- holy-sky-9094
summary: 'COMPLETE flywheel-auto run (8 runs, stop_reason=no_viable_branch). Closed the tight->giant overfit gap: capacity ([256,256] on a giant-extended scale range) is the lever — new studio-baseline purple-base-8302 dominates the original baseline at every scale (giant 0.21->0.69). Mapped the curriculum (no help), capacity curve (knee at 256), and a tight<->giant Pareto dial (scale_sample_weight). In-envelope levers exhausted.'
origin:
  backend: flywheel
  node_id: cb954865-7158-584e-b472-76d86b2fa0b8
  slug: sparkling-feather-0123
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1613bf65-0898-5c60-8599-768a48bdda4f
  slug: polished-hill-4085
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 661dd3f862a890263e5ece8aeafca214de16bb12e7cd21ee89f5887bc0fd25db
---
## Run contract

- **Objective:** Train a course-scale-GENERALIST `gate_race` policy that holds high lap completion across the full scale range (tight->giant), closing the overfit gap of the tight 120M baseline (0.95/0.76/0.49/0.21; parent `damp-wood-7079`).
- **Decision criterion:** `scripts/eval_scales.py` cycled regime (4096 envs, steps 1500, episode_len 600, DR off, gate_radius 0.45, n_gates 5) over tight/spread/big/giant. GREEN if big>=0.75 & giant>=0.55 while tight>=0.90; move `★ studio-baseline` only to a best-overall candidate.
- **Start nodes:** `damp-wood-7079` (overfit measurement) + `841dade5` (spread-out-courses setup).
- **Budget ceiling:** ~12 local 120M runs (~5 min each); **8 spent.** **Budget unit:** local 5090 runs (NO managed compute, locked decision #3). **Compute approval cap:** N/A.
- **Lookahead depth:** n=2. **Frontier width:** k=1 (single GPU).
- **Terminal condition:** `no_viable_branch` OR ceiling, whichever first.
- **Stop reason:** **`no_viable_branch`** — stopped at 8/12 runs. The in-envelope levers (curriculum ordering, scale-range extension, network capacity, distribution reweighting) are all mapped and exhausted; every remaining lever is out of this pass's scope: gate-radius randomization needs a code change (no `scale_gate_radius` knob exists), and lifting the whole Pareto front needs a relaxed compute budget (more steps) or bigger-than-deployable nets. None justifies the remaining budget over the duplication risk.

## Progress log — 8 runs, the full arc

| # | node | change vs parent | verdict |
|---|---|---|---|
| B1 | `empty-firefly-1882` | flat scale-rand U[4.5,12], [128,128] | **GREEN** giant 0.21->0.57, big +0.22; tight -0.04 |
| B2 | `orange-pond-7208` | + tight->big curriculum ordering | **NO-GO** flat-or-worse; giant -0.11 |
| B3 | `dawn-hill-4820` | extend range to giant U[4.5,18], [128,128] | **Pareto** big/giant up, tight 0.91->0.84 (capacity signal) |
| B4 | `purple-base-8302` | + capacity [256,256] on giant range | **GREEN, new studio-baseline** dominates ALL scales (0.95/0.89/0.84/0.69) |
| B5 | `wild-tree-5582` | B4 seed-1 replicate | nuanced: tight/spread/big robust, **giant seed-fragile** (0.69 vs 0.51) |
| B6 | `patient-dew-6473` | capacity [384,384] | **NO-GO** regresses; capacity knee = [256,256] at 120M |
| B7 | `silent-wood-5878` | giant-importance sampling w=0.5 | **Pareto** giant 0.60->0.84 (best ever); confirms giant = training-MASS problem |
| B8 | `snowy-boat-4105` | dial midpoint w=0.7 | **Pareto** smooth front; no setting clears all gates |

## Headline result

**Capacity unlocks scale generalization.** The original tight baseline overfit course geometry (giant 0.21). The new studio-baseline `purple-base-8302` ([256,256], scale-randomized to radius 18, same 120M budget) **Pareto-dominates it at every scale** (tight 0.95, spread 0.89, big 0.84, giant 0.69) with ~4x lower giant crash rate. Two clean mechanism findings fell out: (1) the [128,128] net was capacity-bound (knee at [256,256] at this budget; [384,384] under-trains); (2) giant's residual weakness is a training-MASS problem, dialable via `scale_sample_weight` along a smooth tight↔giant Pareto front — no free-lunch point clears tight>=0.90 AND a strong giant within the fixed budget.

## Open threads (for a future pass, all out of THIS envelope)

- **Deployability:** the winning [256,256] (~70k params) exceeds the ~19k MCU target. The shippable path is distillation/quantization of `purple-base-8302` down toward the [128,128] B1 footprint — the B1 flat generalist remains the size-appropriate fallback.
- **gate_radius randomization** (the other geometry axis, fixed at 0.45 throughout) — needs a `scale_gate_radius_min/max` knob wired into the `scale_randomize` reset path.
- **Lift the whole Pareto front:** longer training (giant converges slowest) or a giant-only fine-tune, to clear all gates at once. Both need a relaxed step budget.
- **DR-on robustness** of the winner (all evals here were DR-off, matching the baseline table).

## Continuation rule (graph-local)

A later pass reads THIS node first. Current best = `purple-base-8302` (holds `★ studio-baseline`). The four in-envelope levers are resolved (children below); resume only via the open threads above, each of which needs code or a bigger budget.