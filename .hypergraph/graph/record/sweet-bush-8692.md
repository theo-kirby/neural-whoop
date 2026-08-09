---
node_id: bcee9cf6-6d79-5a90-ac03-525c6a877527
slug: sweet-bush-8692
title: 'Perception-aware formation (GREEN): noisy anchor DETECTION halves formation quality, the EMA primitive RECOVERS it — the perception + swarm branches compose'
created_at: '2026-06-28T02:57:14.005440+00:00'
parents:
- raspy-moon-0909
- flat-waterfall-0121
summary: 'First cross-branch synthesis: applies the EMA precision primitive (validated in target_follow: long-tree-2976/flat-waterfall-0121) to the swarm_formation task (raspy-moon-0909). Made swarm_formation perception-aware — each drone observes the formation ANCHOR through the DetectorNoise seam (3deg bearing / 10% range / 5% dropout / 110-deg FOV) instead of ground truth (its own slot offset stays known; reward still uses the TRUE slot so noise can''t be gamed). n_agents=3 r=1.0, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT GREEN: noisy anchor DETECTION degrades formation hard — ground-truth 0.169m/0.997 hold -> noisy-detector 0.392m/0.574 hold (error 2.3x, hold -42pts). The EMA(0.85) filter on the noisy anchor estimate RECOVERS most of it -> 0.277m/0.862 hold (error -29%, hold +50% relative, +29pts absolute), ZERO collisions throughout. So the EMA precision primitive proven in the perception branch COMPOSES with the swarm formation task: drones hold formation from only a noisy DETECTION of the anchor, and the filter recovers a large fraction of what detection noise costs (same envelope as target_follow — reduces, doesn''t fully eliminate the per-fix penalty). This is a deployable-direction capability (formation-keeping from a realistic onboard anchor estimate) and the graph''s first node bridging cluster:perception and cluster:swarm. Promoted (backward-compatible: detector-off == ground truth; estimate_ema_alpha default 0.0); code ad9a6f5, 83 pytest green.'
origin:
  backend: flywheel
  node_id: bcee9cf6-6d79-5a90-ac03-525c6a877527
  slug: sweet-bush-8692
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Idea (cross-branch synthesis)
Two of this run's main results were a **reusable EMA precision primitive** (perception branch: noisy detector estimate -> EMA(0.85) filter closes the target_follow standoff back-off, `long-tree-2976` / `flat-waterfall-0121`) and a **scalable formation task** (swarm branch: `swarm_formation` holds a ring around an anchor, scales to 24 drones, `raspy-moon-0909` / `summer-wave-6268`). Both used the anchor/target via GROUND TRUTH. This hop asks the composition question: **if the formation anchor is only NOISILY DETECTED (a realistic onboard sensor), does formation hold — and does the EMA primitive help?**

## Change (task-layer, backward-compatible)
Made `swarm_formation` perception-aware: each drone observes the **anchor** through the `DetectorNoise` seam (bearing/range/FOV/dropout + stale-hold) when the seam DR detector is on, then `estimate_ema_alpha` applies the EMA filter to that estimate; the drone's own slot offset is always known, so `slot_est = anchor_est + offset`. The **reward still uses the TRUE slot** (so detection noise can't be gamed), exactly like target_follow. Detector-off reduces to the ground-truth slot vector (no behaviour change to the existing GREEN formation runs). Code `ad9a6f5`; 83 pytest green.

## Setup
`swarm_formation_percep_{det,ema}.yaml`: n_agents=3, formation_radius=1.0, detector ON (3deg / 10% / 5% dropout / 110-deg FOV), `estimate_ema_alpha` = 0.0 (no filter) vs 0.85 (EMA). [128,128]@120M, seed 0, full seam DR. Eval at own regime, 2048 envs x 1500 steps, seed 12345. Clean ref = `raspy-moon-0909` (ground-truth anchor).

## Results
| anchor source | filter | formation_hold_rate | mean_formation_error (m) | collision/step |
|---|---|---|---|---|
| ground truth (clean) | — | 0.997 | 0.169 | 0.0 |
| noisy detector | none | **0.574** | **0.392** | 0.0 |
| noisy detector | **EMA 0.85** | **0.862** | **0.277** | 0.0 |

## Findings
1. **Noisy anchor DETECTION hurts formation.** Replacing the ground-truth anchor with a noisy detection drops hold_rate 0.997 -> 0.574 and roughly doubles formation error (0.169 -> 0.392 m). Detection quality matters for formation-keeping — the anchor estimate is the formation's reference.
2. **The EMA primitive RECOVERS most of it.** EMA(0.85) on the anchor estimate lifts hold_rate 0.574 -> **0.862** (+50% relative) and cuts error 0.392 -> 0.277 m (-29%). The same filter that closed the target_follow back-off transfers directly to the swarm task.
3. **ZERO collisions throughout** — the slots stay well-spaced (r=1.0), so detection noise perturbs slot-tracking, not separation.
4. **Composition confirmed.** The EMA precision primitive is task-agnostic: it filters any noisy body-frame target/anchor estimate. It improves perception-aware formation just as it improved perception-aware following — the perception and swarm branches genuinely compose.

## Verdict
**GREEN (cross-branch composition), stop_reason=improved.** Formation-keeping survives noisy onboard anchor detection, and the EMA primitive recovers a large fraction of the detection-noise penalty (hold 0.57 -> 0.86). A deployable-direction result: a swarm could hold formation from a cheap noisy anchor estimate. Promoted (default-off detector path; backward-compatible).

## Honesty / limits
Single seed; EMA recovers but does NOT fully restore the clean 0.997 (lands at 0.862) — the same residual per-fix penalty seen in target_follow (`wandering-mode-7957`); a predictive filter (Kalman) or better detector would close the rest. n=3 only here (the scaling result `summer-wave-6268` is ground-truth; perception-aware scaling is the natural follow-up). The anchor is the single shared reference — a per-drone noisy NEIGHBOUR estimate (vs the perfect neighbour obs used now) is a separate, harder perception-swarm question.

## Lineage
- **builds-on** `7cd41adf` (swarm_formation): adds the perception seam to the task it introduced.
- **informed-by** `3db0af65` (flat-waterfall-0121, EMA alpha-sweep): applies its validated EMA(0.85) precision primitive; this node is the bridge between cluster:perception and cluster:swarm.

## Artifacts
percep_formation.png (clean vs noisy vs noisy+EMA on hold_rate + error), percep_formation_table.json. Code ad9a6f5.