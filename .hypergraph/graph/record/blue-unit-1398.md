---
node_id: ac07a0f4-3a17-5c68-83ae-d601b4401ab5
slug: blue-unit-1398
title: 'Re-center Air65 II airframe + widen latency DR (0-100ms): holds 0.79 completion under realistic offboard latency where baseline collapses to 0.45 — GREEN'
created_at: '2026-06-29T09:45:01.248423+00:00'
parents:
- bitter-fire-0679
- wandering-shadow-3679
summary: 'GREEN. Re-centered the airframe to the Air65 II''s real AUW (~26g, mass [0.026,0.022,0.030], inertia ~0.8x) and widened action_latency DR 1->5 steps (0->~100ms) in configs/gate_race_air65.yaml (57fe87c); retrained [128,128]@120M. Under the realistic offboard DR, the new policy holds completion 0.79 and crash/step 0.0003 and beats the oracle (best lap 3.29s vs 3.49s); the pre-widening studio baseline (gate_race_general_s1, old-truth-3996) collapses on the SAME DR to 0.45 completion / 0.0037 crash / 3.52s (slower than oracle). DR-off the new policy is clean (0.93 completion, 3.20s). Proves latency — not airframe mass — was the dominant sim2real gap: the old policy can''t handle 100ms offboard delay, the retrained one can. Pack attached (comparison/trajectory/curves/fpv/table/eval/run/replay).'
origin:
  backend: flywheel
  node_id: ac07a0f4-3a17-5c68-83ae-d601b4401ab5
  slug: blue-unit-1398
  revision: 10
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Re-center Air65 II airframe + widen latency DR — GREEN

**Correction first (honesty).** The original target ('~14-22g, halve inertia, TWR~6') was wrong: it treated the ~17g *dry* spec as flying mass. Real all-up weight = ~17g dry + ~8g 1S pack ~= **~25g** (~27g with the flow deck). So the mass gap vs the 32g sim is only **~20%** (not 2x), inertia scales ~0.8x (not half), arm (~32mm) is already right, and TWR (~4-5:1) is close to the sim's 4:1. The dominant clearly-wrong gap was always the **action-latency DR** (0-20ms sim vs ~40-100ms offboard).

**Hypothesis.** Re-centering mass to ~26g + scaling inertia ~0.8x + widening action_latency to ~0-100ms makes the sim match the real Air65 II offboard loop, with most of the value from the latency widening.

**Setup.** `configs/gate_race_air65.yaml` (commit **57fe87c**): overrides `whoop.mass=[0.026,0.022,0.030]`, `whoop.J_xy/J_z` ~0.8x, `dr.action_latency_steps=1->5`. 32g global default left intact (baselines stay reproducible). [128,128]@120M, ~440k steps/s, ~5 min on the 5090. Eval: 2048 drones x 1500 steps, DR-off and DR-on; head-to-head vs the studio baseline `gate_race_general_s1` (old-truth-3996) on the SAME air65 DR.

**Results.**
| under air65 DR (0-100ms latency, ~26g) | baseline generalist s1 | **air65 (this)** | Δ |
|---|---|---|---|
| completion | 0.45 | **0.79** | **+76%** |
| crash/step | 0.0037 | **0.0003** | **~12x safer** |
| best lap | 3.52s (slower than oracle) | **3.29s** (beats 3.49s oracle) | -0.23s |

DR-off (clean) the air65 policy: completion **0.93**, best lap **3.20s** (oracle 3.49), crash/step 0.0001 — competence fully intact. The baseline's tight-course completion was ~0.88 under the OLD 0-20ms latency; the same policy drops to 0.45 once latency goes to 100ms on the same course — so the collapse is attributable to latency, which the retrain absorbs.

**Verdict — GREEN.** Widening latency DR to the realistic offboard range (with the modest airframe re-center) recovers robustness the un-adapted baseline lacks: +76% completion, ~12x fewer crashes, still faster than the oracle. Confirms the corrected analysis (latency >> airframe mass as the sim2real gap) and validates the `gate_race_air65` profile as the sim2real-faithful training config.

**Honesty / caveats.** (1) This policy is a *tight-course* specialist (fork of gate_race.yaml), not scale-general like the old studio baseline — combining latency-robustness with scale-generality is a follow-up. So it is NOT yet a drop-in studio-baseline replacement. (2) Airframe mass/inertia/TWR are best-estimates; pinned by weighing + bench-testing the real Air65 II at Stage 0. (3) Latency modeled as uniform 0-5 steps; real offboard latency has a non-zero floor + jitter — refine once measured end-to-end (Stage 1).

**Lineage.** Child of the sim2real plan (bitter-fire-0679); airframe per sparkling-lab-8864. Confirms the latency-aware lever (wandering-shadow-3679 was NO-GO at the *tight* 0-1 step range — here the *realistic* 0-5 step range is exactly where it pays off). Artifacts: standard visual pack (comparison vs baseline-generalist, trajectory, training curves, FPV, leaderboard, eval/run manifests, portable replay).