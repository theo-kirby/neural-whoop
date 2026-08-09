---
node_id: fe78365c-8dab-5c21-9f0f-dd2eb71c947f
slug: noisy-disk-9080
title: DR curriculum (ramp seam DR 0->full) REFUTED — DR-on reliability REGRESSED 0.80->0.67 (RED)
created_at: '2026-06-26T16:54:19.256286+00:00'
parents:
- shrill-limit-5398
- royal-firefly-3187
summary: 'RESOLVED RED / regressed (stop_reason=regressed). Tested a seam-DR curriculum (dr_curriculum_frac=0.5: ramp wind/rate/thrust/latency/obs-noise 0->full over the first half of training) to close the hop-9 DR-on reliability gap. It made reliability WORSE: DR-on completion 0.804->0.671, crash ~2.3x (4.6e-4->1.06e-3), best_lap 2.665->2.849s; DR-off also dipped (0.919->0.894, 2.600->2.718s); seed-0 collapsed (DR-on 0.586). Refutes ''learn-task-first-then-harden'' for this seam/budget — the curriculum trades away full-DR training time (baseline trains against full DR for all 120M) and lets the policy settle into the easy regime. Full-strength DR from step 0 (the baseline) is better. Baseline unchanged; curriculum mechanism kept default-off as tested infra (committed af908be); config retained as the reproducible RED recipe.'
origin:
  backend: flywheel
  node_id: fe78365c-8dab-5c21-9f0f-dd2eb71c947f
  slug: noisy-disk-9080
  revision: 24
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Hop-10 — DR curriculum for DR-on reliability (RESOLVED, RED / regressed)

## Lineage
- **builds-on:** `8db85abb` (hop-8, [128,128]@120M baseline).
- **informed-by:** `8403a22c` (hop-9 / royal-firefly-3187) — quantified the DR-on reliability gap (completion 0.80, crash 4.6e-4) that this hop tries to close, and pivoted the frontier from speed to reliability.

## Hypothesis
The baseline trains against **full seam DR from step 0**. Standard wisdom: a **curriculum** (learn the task first under easy conditions, then ramp disturbances in) recovers reliability. H: ramping the seam DR (wind/rate-gain/thrust/latency/obs-noise) 0->full over the first 50% of training lifts DR-on completion toward the DR-off 0.92 without losing the ~2.6s pace.

## Mechanism (committed af908be, default-off)
`DomainRandomizer.scale` ∈ [0,1] multiplies every seam-DR magnitude (continuous ones directly; latency by *incidence*; obs-noise per-step). `ppo.dr_curriculum_frac` ramps it `scale = min(1, step/(frac*total_steps))` each update; `env.set_dr_scale` drives it. **Default `dr_curriculum_frac=0.0` reproduces full-DR-from-step-0 exactly** (4 new unit tests assert scale=1.0 == baseline envelope, scale=0 == DR-off). A documented fork point per ppo.py.

## What was run (frac=0.5; [128,128]@120M, 3 seeds; eval 2048x1500 seed 12345)
| metric | curriculum (n=3) | baseline (hop-8/9) | Δ |
|---|---|---|---|
| **DR-on best_lap** | 2.849 s | 2.665 s | slower |
| **DR-on completion** | **0.671** | **0.804** | **WORSE** |
| **DR-on crash/step** | 1.06e-3 | 4.6e-4 | **~2.3x WORSE** |
| DR-off best_lap | 2.718 s | 2.600 s | slower |
| DR-off completion | 0.894 | 0.919 | worse |

Per-seed DR-on completion: 0.586 / 0.733 / 0.694 (seed-0 collapsed). Every seed is below the baseline DR-on 0.80.

## Verdict: RED / regressed — the curriculum HURTS reliability
The curriculum is **worse on its own target metric** and on the speed guardrail. The hypothesis is **refuted** for this seam and budget. Mechanistic read: a fixed 120M budget split as 'ramp then full' gives the policy **less full-strength-DR training time** than the baseline (which sees full DR for all 120M), and the easy early phase lets it settle into a low-disturbance regime it doesn't fully un-learn. For this seam, **constant full DR from step 0 is the better schedule** — the baseline was already doing the right thing.

## Action taken
**Do NOT promote.** Baseline `configs/gate_race.yaml` unchanged (`dr_curriculum_frac` stays at its 0.0 default). The curriculum **mechanism is kept** (small, default-off, tested — a legitimate reusable fork point; env_check + 50 pytest green); `configs/gate_race_drcurric.yaml` retained as the reproducible RED recipe (header marked REFUTED). Committed **af908be**.

## Artifacts
`hop10_summary.json` (curriculum vs baseline, per-seed DR-on/DR-off); DR-on trajectory of the best curriculum seed (s1, 2.66s/0.733); comparison vs the baseline DR-on replay; DR-on s1 eval json; per-run leaderboard table.json; portable DR-on replay. No training_curves attached (runs trained render-free).

## Stop reason: regressed

## Next frontier (replan — n=1)
One reliability lever (curriculum) is refuted; the binding constraint (DR-on completion ~0.80) stands. Two honest continuations: (a) **reliability-weighted reward** — a mechanistically *different* lever: add a survival/near-miss term (penalize proximity-to-crash or reward staying alive under DR) so the policy trades a little speed for completion, retrain [128,128]@120M full-DR, eval DR-on; (b) **PIVOT to the first n_agents>1 SWARM task** — the core objective expansion ('discover novel/creative policies', expand to swarms), accepting DR-on 0.80 as good-enough for now (new DroneTask + metric; collisions/relative-obs already in our env layer). Recommend (a) first — stay disciplined on the identified binding constraint with a fresh lever before abandoning it; keep (b) staged as the ready pivot. Deprioritized: latency-aware/obs-history policy (MCU deploy-size cost); width knee.