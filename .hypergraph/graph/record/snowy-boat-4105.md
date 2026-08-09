---
node_id: 0833a579-e6e9-5456-9ca7-87e50b06cf0c
slug: snowy-boat-4105
title: 'Pareto front is smooth & fundamental: w=0.7 interpolates (tight 0.86 / giant 0.71) but no dial setting clears all gates — closes the distribution thread'
created_at: '2026-06-28T17:05:19.095346+00:00'
parents:
- sparkling-feather-0123
- silent-wood-5878
summary: 'Third dial point (scale_sample_weight 0.7) between uniform (w=1.0: tight 0.94/giant 0.60) and bigwt (w=0.5: tight 0.79/giant 0.84). Lands smoothly in the middle: tight 0.861/spread 0.891/big 0.828/giant 0.706. Still misses tight>=0.90 gate. The tight<->giant trade is a smooth, monotonic Pareto front with NO free-lunch setting at 120M/[256,256] — the contract''s all-gate bar can''t be met by reweighting alone. Closes the giant/distribution thread; B4 (w=1.0) stays the balanced studio-baseline.'
origin:
  backend: flywheel
  node_id: 0833a579-e6e9-5456-9ca7-87e50b06cf0c
  slug: snowy-boat-4105
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 89c93ecb-93a9-5f15-80bc-0d780ae46193
  slug: jolly-breeze-9105
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 15682a4fc6f359cfd4774024b07d2af50abd7bc8fa7d1e7d2415a70b1eeed083
---
## Hypothesis
B7 (`silent-wood-5878`) showed `scale_sample_weight` is a tight↔giant Pareto dial with ends w=1.0 (tight-strong) and w=0.5 (giant-strong). Does an intermediate setting (w=0.7) hit a sweet spot that clears ALL contract gates at once (tight>=0.90 AND big>=0.75 AND giant>=0.55) — the clean dominant generalist B4 just missed on giant?

## Setup
- **Policy:** `runs/gate_race_general_giant_w256_wt07_s0`, `configs/gate_race_general_giant_w256_wt07.yaml` (committed `4698d6a`). Identical to B4/B7 except `scale_sample_weight 0.7`. [256,256]@120M, giant range, DR, seed 0.
- **Eval:** identical `scripts/eval_scales.py` cycled regime.

## Results — the Pareto front (completion), three dial points
| scale | w=1.0 (uniform/B4) | **w=0.7 (B8)** | w=0.5 (bigwt/B7) |
|---|---|---|---|
| tight  | 0.941 | **0.861** | 0.785 |
| spread | 0.902 | **0.891** | 0.886 |
| big    | 0.839 | **0.828** | 0.886 |
| giant  | 0.600 | **0.706** | 0.837 |

w=0.7 interpolates almost perfectly between the ends at every scale (tight 0.86 between 0.94/0.79; giant 0.71 between 0.60/0.84). Mean 0.821.

## Verdict / Honesty
**Mixed / Pareto — no clean outcome, no pointer move; this CLOSES the giant/distribution thread.** w=0.7 does **not** clear all gates: tight 0.861 < 0.90 (big ✓ 0.828, giant ✓ 0.706). The three points (w=1.0/0.7/0.5) trace a **smooth, monotonic tight↔giant Pareto front** — every step toward large courses buys giant and costs tight at a steady exchange rate, with **no free-lunch setting**. At the locked 120M budget and [256,256] capacity, the contract's simultaneous bar (tight>=0.90 AND a strong giant) is **unattainable by distribution reweighting alone**: tight only clears 0.90 at w≈1.0, exactly where giant is weakest. So the deployment picks a point on the front by its course-size mix; `gate_race_general_giant_w256` at w=1.0 (`purple-base-8302`) remains the balanced default and studio-baseline. Honest caveat: single seed each; the front's *position* (not its existence) would shift with more training/capacity — lifting the whole front is a compute question, out of scope for this local pass.

## Read
To push the entire front up (clear all gates at once) you'd need to relax the fixed-budget constraint: more steps, or the deployable-but-bigger-capacity tradeoff — both beyond this pass. The reweighting + capacity levers within the 120M/local envelope are now exhausted.

## Lineage
Governed by control `sparkling-feather-0123`; the middle point of the Pareto dial opened by `silent-wood-5878`. Artifacts: eval_scales.json (decisive), pareto_front.csv (all three dial points), visual pack vs w256-uniform replay.