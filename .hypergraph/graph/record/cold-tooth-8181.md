---
node_id: 18736ddc-eb66-5ea1-af7c-6e92964faeb0
slug: cold-tooth-8181
title: 'hover_tof_air65_w128u15_ampc (amp curriculum): RED — nominal collapses (M1-live 1.0× 95.4→69.7%, worst of the line) with no tail gain; the narrow-band early trim is a local optimum the widened band punishes'
created_at: '2026-07-13T18:31:07.643060+00:00'
parents:
- calm-base-6054
summary: 'hover_tof_air65_w128u15_ampc 3.2B (user-chosen arm at the w-ladder regroup; ONE factor vs calm-base-6054''s w128u15: dr.obs_noise_amp_curriculum true — the 0.5–2.0× amp band interpolates from (1,1) over the first half of training via dr_curriculum_frac 0.5; flag + 2 tests in commit 4a12195): REFUTED. Nominal collapsed instead of being protected — M1-live 1.0× 95.4→69.7% (worst of the ENTIRE hover_tof line; the [64,64] baseline holds 75.2%), 0.8× 100→80.2%, no-DR z err 0.047→0.070 m (≤0.05 gate FAILED), tilt 0.22→0.84° — while the tail did NOT improve (1.2× 64.9→62.1%). Sole non-regression: m2sensor 36.5→42.2% (at its bar) and full-DR 18.4→22.1%. Exits 0 floor / 0 ceiling — altitude loop closed as always. Reading: the trim learned on the narrow early band is a local optimum the widened band then punishes; the fixed-spread parent''s amplitude-invariant trim never forms. outcome:RED; the flag stays (tested, default off) but amp curricula on this recipe are a dead end. Commits 4a12195/ce2732e; battery in runs/hover_tof_air65_w128u15_ampc/probes.json.'
origin:
  backend: flywheel
  node_id: 18736ddc-eb66-5ea1-af7c-6e92964faeb0
  slug: cold-tooth-8181
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: c8fc5ef7-589f-5468-9584-448d0dd91bbd
  slug: noisy-pine-6020
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 76d1fcfdbe3d7ab1524c98a313a15421dd64638c72ef82559708fc4cccc6d8d9
---
# hover_tof_air65_w128u15_ampc: easing into the noise makes it worse, not better

**Hypothesis (user-chosen at the w-ladder regroup).** The w-ladder's clean-trim↔noise-robustness frontier exists because the full 0.5–2.0× amplitude spread competes with nominal leveling from step 0. If the amp band itself rides the DR curriculum — (1,1)→(0.5,2.0) over the first half of training — the policy masters the nominal amplitude FIRST and hardens the tail late, escaping the frontier instead of sliding along it.

**Setup.** New seam: `obs_noise_amp_curriculum` flag in `randomization.py` (band edges interpolate with the curriculum scale s: `(1-(1-lo)s, 1+(hi-1)s)`; default off; 2 unit tests) — commit 4a12195. Config `hover_tof_air65_w128u15_ampc.yaml` = w128u15 + the flag (ONE factor); 3.2B steps @ ~1.0M sps (results commit ce2732e). Identical battery, seed 12345.

**Results (Δ vs parent w128u15 = calm-base-6054).**

| metric | w128u15 | ampc | gate | Δ |
|---|---|---|---|---|
| no-DR z err / survival | 0.047 m / 100% | **0.070 m / 100%** | ≤0.05 / 100% | ❌ z-err gate lost |
| no-DR tilt / pos err | 0.22° / 0.394 | 0.84° / 0.688 | — | markedly looser |
| M1-live 0.5× | 100% | 99.9% | — | ≈ |
| M1-live 0.8× | 100% | **80.2%** | — | ❌ −20 pts |
| M1-live 1.0× | 95.4% | **69.7%** | ≥98% | ❌ **worst of the entire line** ([64,64]: 75.2%) |
| M1-live 1.2× | 64.9% | **62.1%** | ≥85% | ❌ no tail gain — the arm's own purpose |
| m2sensor | 36.5% | **42.2%** | ≥42% | ✅ at the bar (+5.7) — sole non-regression |
| full training DR | 18.4% | 22.1% | — | small gain |
| exit probe @1.0× | 0/0/95 xy | **0/0/621 xy, median 1.96 s** | 0/0 | ✅ vertical still closed |

**Decode.**
1. REFUTED, cleanly: the curriculum was supposed to protect nominal; nominal is exactly what collapsed, across every amplitude at or above 0.8× — while the 1.2× tail it was supposed to buy got *worse*. The frontier isn't an artifact of when the spread is introduced.
2. Mechanistic read: the parent (full spread from step 0) is forced to form an amplitude-invariant trim from the beginning — the d50var→s8 lineage's whole discovery. The curriculum instead lets a narrow-band trim consolidate for 1.6B steps; when the band widens, PPO patches around that local optimum rather than rebuilding, and ends up robust nowhere.
3. m2sensor/full-DR ticked up slightly — consistent with generic late-noise exposure — but a 1-in-3 crash rate at the honest noise floor (1.0×) is disqualifying regardless.

**Verdict / Honesty.** **RED** (outcome tag applied — the first unambiguous refutation of the ladder; the three w-arms were genuine mixed trades, this one is a strict loss where it was supposed to win). (1) Same harness/seed as all prior arms. (2) One seed — but the collapse is 25 pts at 1.0× and 20 pts at 0.8×, far beyond the reproducibility jitter seen on this battery (±0.2 pt on repeat probes). (3) The code seam stays (tested, default-off) — the negative result is about this recipe, not the mechanism's implementability.

**Lineage.** Parent: calm-base-6054 (the arm it modifies ONE factor from). This closes the 4-arm hover_tof leveling investigation: [64,64] → w128 → w128u15 → {w192u15, ampc}. Standing frontier: **w128 owns nominal** (1.0× 98.9%), **w192u15 owns robustness** (m2sensor 50.1%), **w128u15 is the best compromise** (95.4% / 36.5% / cleanest hover). Next decision (user's): ship a compromise arm for the first real 1 m ToF flight, or open a genuinely different attack (longer training, distillation, measured-noise recalibration after a real flight).