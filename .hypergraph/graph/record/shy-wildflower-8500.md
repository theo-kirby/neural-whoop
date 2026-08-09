---
node_id: 33021e6e-bb4e-57df-9591-391314201268
slug: shy-wildflower-8500
title: 'Scale-generalist gate racing: range-training generalizes across course scale (GREEN)'
created_at: '2026-06-28T21:13:11.523363+00:00'
parents:
- shrill-limit-5398
summary: 'Scale-generalist [128,128]: per-episode range-training (arena radius 4.5→12 m) generalizes across course scale. The tight-only [128,128]@120M baseline COLLAPSES with scale — lap_completion 0.95→0.21 (tight→giant) — while the generalist degrades gracefully 0.906→0.569 (−0.04 tight, +0.36 giant; giant best_lap 7.01→5.23 s, crash 1.09→0.66e-3). One tiny policy flies the whole scale range, paying ~4 pts at tight for 22–36 pts at big/giant. GREEN — opens cluster:generalization. Honest caveat: fixed capacity spreads thinner (tight tax); whether capacity recovers it is the next hop.'
origin:
  backend: flywheel
  node_id: 33021e6e-bb4e-57df-9591-391314201268
  slug: shy-wildflower-8500
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 196485ec-7af6-509b-be55-671807c8166c
  slug: floral-frost-4509
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 5890306ea3804c6f35b90362d4eaaa620f41640da58c17d9029a75b5832467f5
---
# Scale-generalist gate racing — range-training generalizes across course scale (empirical, RESOLVED — GREEN)

## Lineage
- **builds-on:** `8db85abb` ([128,128]@120M racing baseline, DR-off 2.60 s / completion 0.92 on the TIGHT track — the exhausted single-scale *speed* baseline). This hop changes the QUESTION from "how fast on one fixed track" to "how robust across track SCALES".
- **opens** the **cluster:generalization** workstream (anchor node).

## Hypothesis
The tight-only baseline overfits its arena size. Training a single [128,128] policy across a *range* of arena scales (per-episode randomized radius 4.5→12 m, gate-hop ratio 0.34–0.62, z_max 2.3–3.5) yields one policy that flies tight→giant courses — trading a little tight-course performance for large gains as courses grow.

## Setup
- Config `configs/gate_race_general.yaml`: task `gate_race`, `scale_randomize: true`, radius **4.5→12 m**, [128,128], 120M steps, 4096 envs, seed 0. Same seam DR + budget as the baseline; only per-episode scale sampling is added.
- Eval: deterministic, **DR-off**, on four fixed `ARENA_PRESETS` — tight / spread / big / giant — 2048 envs, the canonical cross-scale bench (`eval_scales.json`).
- Reference: the tight-only [128,128]@120M baseline evaluated on the SAME four presets.

## Result (lap_completion_rate by scale; DR-off)
| scale | tight-only baseline | generalist | Δ | gen best_lap (s) |
|---|---|---|---|---|
| tight | 0.95 | 0.906 | −0.044 | 3.25 |
| spread | 0.76 | 0.848 | +0.088 | 3.84 |
| big | 0.49 | 0.714 | +0.224 | 4.57 |
| giant | 0.21 | 0.569 | +0.359 | 5.23 |

Crash rate also falls at scale (giant 1.09e-3 → 0.66e-3); best_lap at giant 7.01 → 5.23 s.

## Verdict: GREEN
The tight-only baseline **collapses** as courses grow (0.95→0.21 completion) — it overfit its arena. The range-trained generalist **degrades gracefully** (0.906→0.569), giving up ~4 pts at tight to gain **+22–36 pts** at big/giant. A single tiny export-clean policy now flies the whole scale range. **Honest caveat:** generalization is not free — the fixed-capacity net spreads thinner, so tight drops slightly; whether more capacity recovers the tight tax (and the range can be pushed to *giant*) is the next hop.

## Artifacts
`cross_scale_comparison.csv` (the verdict table), `comparison.png` (vs baseline replay), `trajectory.png`, `training_curves.png`, `table.csv` (leaderboard), `run.json` (repro manifest), `replay.json.gz` (portable record).

## Reproduce
`uv run python scripts/train.py --config configs/gate_race_general.yaml` ; eval across the four ARENA_PRESETS DR-off.

## Stop reason: improved (GREEN) — opens cluster:generalization; next = capacity recovery + extend range to giant.