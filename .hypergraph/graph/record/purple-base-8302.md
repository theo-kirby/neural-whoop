---
node_id: 21fdb62b-6f2d-57e3-902f-c384ff6b3436
slug: purple-base-8302
title: 'Capacity unlocks scale generalization: [256,256] on the giant range DOMINATES all scales — GREEN, new studio-baseline'
created_at: '2026-06-28T16:12:41.677285+00:00'
parents:
- empty-firefly-1882
- sparkling-feather-0123
- dawn-hill-4820
summary: Widening the giant-range generalist [128,128]->[256,256] (same geometry/DR/120M budget) beats EVERY prior policy at EVERY scale. Completion tight/spread/big/giant = 0.954/0.889/0.843/0.694 vs B1 flat 0.906/0.848/0.714/0.569 and vs B3 giant-128 0.844/0.833/0.774/0.635. Clears all gates (tight>=0.90, big>=0.75, giant>=0.55), lowest crash everywhere, even edges the original tight specialist on tight (0.954 vs 0.95) while tripling giant (0.21->0.694). Capacity bottleneck confirmed. Takes the studio-baseline pointer. GREEN.
origin:
  backend: flywheel
  node_id: 21fdb62b-6f2d-57e3-902f-c384ff6b3436
  slug: purple-base-8302
  revision: 7
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
B3 (dawn-hill-4820) showed the [128,128] net traded tight for giant when trained on the full 4.5->18 m range — a **capacity bottleneck**. Prediction: a wider [256,256] net on the SAME giant range holds tight>=0.90 AND keeps the big/giant gains, dominating instead of trading.

## Setup
- **Policy:** `runs/gate_race_general_giant_w256_s0`, `configs/gate_race_general_giant_w256.yaml` (committed `1615bca`). Identical to B3's `gate_race_general_giant` (radius 4.5->18, same bounds, DR, 120M, 4096 envs) except `hidden_sizes` [128,128]->[256,256] (~19k -> ~70k actor params).
- **Eval:** identical `scripts/eval_scales.py` cycled regime (4096 envs, steps 1500, episode_len 600, DR off, gate_radius 0.45, n_gates 5).
- diffaero `291ea14`.

## Results — completion across the full lineage (crash ×1e-3 for B4)
| scale | orig baseline (damp-wood) | B1 flat-128 | B3 giant-128 | **B4 giant-256** | B4 crash |
|---|---|---|---|---|---|
| tight  | 0.95 | 0.906 | 0.844 | **0.954** | 0.064 |
| spread | 0.76 | 0.848 | 0.833 | **0.889** | 0.117 |
| big    | 0.49 | 0.714 | 0.774 | **0.843** | 0.156 |
| giant  | 0.21 | 0.569 | 0.635 | **0.694** | 0.271 |

**Δ:** B4 beats B1 (current studio-baseline) at EVERY scale: tight +0.048, spread +0.041, big +0.129, giant +0.125. It beats B3 at every scale too (+0.11 tight, +0.06 big, +0.06 giant) — so the wider net **eliminated B3's tight regression while keeping its large-course gains**. Mean completion 0.845 (B1 0.759, B3 0.772); curve spread (max-min) 0.261. **Lowest crash rate at every scale** of any policy in the lineage (giant 1.09 baseline -> 0.27e-3, ~4x safer). best_lap competitive (tight 3.44 s, between B1 3.25 and B3 3.62).

## Verdict / Honesty
**GREEN — clean, dominant, and it takes the `★ studio-baseline` pointer** (moved off B1 `empty-firefly-1882`). It meets all three contract gates (tight 0.954>=0.90 ✓, big 0.843>=0.75 ✓, giant 0.694>=0.55 ✓) AND Pareto-dominates every prior policy. The capacity hypothesis from B3 is **confirmed**: [128,128] was the bottleneck; doubling width let one policy hold tight (even beating the original tight specialist, 0.954 vs 0.95) while tripling giant (0.21->0.694). Honest caveats: (1) **single seed (s0)** — a seed-1 replicate (`gate_race_general_giant_w256_s1`) is RUNNING to confirm this isn't seed luck; the dominance margin (+0.04..+0.13 over B1 at all four scales) is large enough that seed noise is unlikely to flip the verdict, but it must be checked. (2) **Deployability:** [256,256] (~70k params) exceeds the ~19k [128,128] MCU target. For on-whoop deployment the flat [128,128] generalist (B1) remains the size-appropriate policy pending distillation/quantization; B4 is the best STUDIO/GPU generalist and the proof that capacity is the lever. (3) DR off in eval, as the whole lineage.

## Lever (next)
- **B5 (running):** seed-1 replicate of B4 — bounds the single-seed caveat that runs through this whole branch.
- **B6 (n=2 lookahead):** map the capacity curve — does [384,384]/[512,512] keep paying, or is [256,256] the knee? Informs the distillation target (how much capacity actually buys, to know what a small deployable net must recover).

## Lineage
Governed by control `sparkling-feather-0123`; extends the giant-range result `dawn-hill-4820` (adds capacity to remove its tight regression); dethrones the prior studio-baseline `empty-firefly-1882`. Artifacts: eval_scales.json (decisive), capacity_sweep.csv (full lineage), visual pack vs B1 replay.