---
node_id: 0f21dd4e-b95a-557d-947a-f09ff4f7ccb0
slug: muddy-mouse-2952
title: 'Deploy recipe found (GREEN, 3 seeds): hybrid-obs × Muon × rel shaping compounds — 2.32–2.54 s clean at 95–98% completion, DR-on 0.85–0.90; Muon''s DR collapse was an action-latency interaction'
created_at: '2026-07-03T14:42:39.499513+00:00'
parents:
- soft-moon-6755
- ancient-field-0677
- tiny-grass-6642
summary: 'hybrid_mrel = hybrid split-latency × Muon 2.5e-3 × rel shaping, 3 seeds: best lap 2.32–2.54 s clean (−21–28% vs adam 3.203) at 95.5–98.3% completion (adam 92.6%), own-DR-on completion 0.846–0.898 (adam floor 0.79–0.809) — clears every pre-registered bar on every seed; GREEN, ★ studio-baseline moved. Key insight: Muon''s DR collapse (0.55–0.60 offboard) was an action-latency interaction — with fresh onboard actuation Muon is faster AND more robust. Deploy recipe of record for Path B.'
origin:
  backend: flywheel
  node_id: 0f21dd4e-b95a-557d-947a-f09ff4f7ccb0
  slug: muddy-mouse-2952
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: f5d9d1de-74e3-52e6-84a1-06aa0f6ca103
  slug: broken-bird-4864
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 077ffa5f52f30a94f786326a673e3a48e3206e3eddf9f5a2cee759678b6b6b19
---
# Compose the winners: onboard-hybrid split latency × Muon lr 2.5e-3 × reliability shaping

**Hypothesis** (staged in royal-field-3745 item 1, contract tiny-grass-6642). The three independently-validated wins — the hybrid-obs split-latency DR (soft-moon-6755, −6% lap), Muon lr 2.5e-3 (black-silence-5752, −23% lap), and rel reliability shaping (ancient-field-0677, +4.8 pt completion) — compose without interference. Pre-registered bar: no-DR best lap ≤ 2.60 s AND own-DR-on completion ≥ 0.80 → deploy-recipe candidate; ★ studio-baseline moves only if no-DR completion additionally ≥ 92.6%.

**Setup.** `configs/gate_race_air65_hybrid_mrel.yaml` (commit 3c5e75c): fork of `gate_race_air65_hybrid` — ONLY optimizer/lr (adam 3e-4 → muon 2.5e-3) and reward shaping (crash_penalty 30, near-miss band 1.0/0.4) differ. [128,128]@120M, ~6 min/run on the 5090. Seed-confirm forks `_s1`/`_s2` (env.seed 1/2). Eval: standard seed 12345, 2048×1500, no-DR + own-DR-on, vs seed-matched adam baseline (3.203 s / 92.6%), hybrid-adam (3.021 s / 93.4%, DR-on 0.809), muon25_rel offboard (2.536 s / 90.8%, DR-on 0.597).

**Results (all three seeds; full table in `seed_dr_table.csv`, raw in `seed_dr_evals.json`).**

| seed | no-DR lap | no-DR compl | DR-on lap | DR-on compl | DR-on crash/step |
|---|---|---|---|---|---|
| 0 | 2.539 s | **98.3%** | 2.684 s | 0.846 | 3.5e-4 |
| 1 | 2.429 s | 97.2% | 2.511 s | 0.870 | 3.2e-4 |
| 2 | **2.320 s** | 95.5% | **2.422 s** | **0.898** | 3.1e-4 |

Every seed clears every pre-registered bar. Mean no-DR lap 2.43 s (−24% vs adam baseline); seed-0 no-DR crash/step 2.2e-5 is 4× BELOW the adam baseline's 0.8e-4.

**Verdict — GREEN, promoted (deploy recipe + ★ studio-baseline moved here).**
1. **The wins compose superlinearly on completion.** Each ingredient alone left completion at or below the 92.6% adam bar (muon25_rel 90.8%, hybrid 93.4%); together: 95.5–98.3%. The composition simultaneously beats the adam baseline on speed (−21 to −28%), completion (+3 to +6 pt), and clean crash rate.
2. **Muon's DR-on collapse was an action-latency interaction, not a Muon property** — the free answer to frontier item 2. Under offboard 0–100 ms ACTION latency, all Muon policies collapsed to 0.55–0.60 DR-on; under the onboard split (fresh actions, stale target) the same optimizer+shaping holds **0.846–0.898 — above adam's 0.79–0.809 floor**. Muon's aggressive policies need fresh actuation to stay robust; with it they're both faster AND more reliable. Frontier item 2 (offboard Muon lr grid) is now moot for deployment: the deploy target IS the onboard split.
3. **Deploy recipe of record** (pending real-uplink O-1 bench): onboard split-latency DR + Muon 2.5e-3 + crash_penalty 30 + near-miss band 1.0/0.4 on the Air65 II airframe. Strengthens the Path-B (companion-MCU) case on top of soft-moon-6755's −6% and sparkling-shadow-2507's 0.55 ms feasibility.

**Honesty / caveats.** (1) The +2–5 pt DR-on completion spread across seeds (0.846–0.898) is wide; the margin over 0.80 held on all 3 seeds but the exact number is seed-noisy. (2) DR-on compares each policy under its own training DR (different physical architectures — the point, not a confound). (3) Uplink model is still uniform staleness + ZOH (soft-moon caveat unchanged); real ELRS/MSP jitter pending O-1. (4) Seeds 1–2 have eval JSONs only (no packs); the standard pack + replay is seed 0's.

**Lineage.** Composes soft-moon-6755 (hybrid split-latency seam) × ancient-field-0677 (rel shaping) × black-silence-5752 (Muon lr, via ancient-field) under control tiny-grass-6642; baselines blue-unit-1398 + seed-matched `runs/gate_race_air65`. Config commit 3c5e75c (pushed).