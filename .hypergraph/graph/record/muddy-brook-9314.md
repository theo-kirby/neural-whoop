---
node_id: d1d1bc85-c24a-5ddc-a6a0-bedc815b9980
slug: muddy-brook-9314
title: 'R1 (trim poisons removed, honest WHITE noise kept) RED: still 0% clean survival — H3 refuted, the white 2.5 rad/s gyro noise itself re-breaks the open-loop trim; spectrum (H1) is the remaining suspect'
created_at: '2026-07-06T19:20:32.213641+00:00'
parents:
- cold-night-8900
- orange-art-0247
- quiet-bonus-7296
summary: 'R1 (configs/hover_blind_air65_r1.yaml, 3.2B steps, commit a16db65) = _noiseonly minus ONLY the trim-poison DR group (thrust 0.12→0.05, ±2° attitude bias→0, curriculum 0.3→0.5), honest WHITE per-channel noise kept. Result: M1 clean-trim pure-hold survival 0.0% (median exit 2.96 s; bar 91.6%) — H3 REFUTED: the trim poisons were NOT what sank v2; the honest white 2.5 rad/s gyro noise itself re-breaks the open-loop thrust trim. M2 (calibrated-trim honest-white-noise, new honesty-split metric) 4.0% vs _noiseonly 3.1% (indistinguishable at n=2048) vs un-hardened baseline 0.1% — noise-training buys a 40× relative robustness gain that is still uselessly far from the 80% bar. M4 full-DR 4.2% (reported as the unwinnable open-loop ceiling). DR-on tilt 16.0° (M3 fail). Verdict RED; attribution now isolated to the noise itself, and the remaining testable hypothesis is its SPECTRUM (H1): the deployed gyro is Betaflight-LPF-filtered (gyroADCf) so real noise is time-correlated, while the sim injects i.i.d. white — right marginal, wrong spectrum. AR(1) colored-noise seam committed (ace5821) with marginal-preserving per-channel rho, once-per-step advance, unit tests; R3 (R1+colored, one-factor) training, R2 (_noiseonly+colored) queued. rho 0.9/0.8 modeled, unvalidated. Baseline cold-night-8900 remains the policy of record.'
origin:
  backend: flywheel
  node_id: d1d1bc85-c24a-5ddc-a6a0-bedc815b9980
  slug: muddy-brook-9314
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# R1: the cheapest arm of the attribution ladder — does removing the trim-poison DR rescue the trim? No.

**Hypothesis tested (quiet-bonus-7296, H3).** The v2 sink was caused by the unobservable trim-poison DR (thrust_scale 0.12 + ±2° per-episode attitude bias), not the honest gyro noise. Prediction: R1 recovers M1 ≥ 91.6%. **Refuted.**

**Setup.** `configs/hover_blind_air65_r1.yaml` (commit a16db65) = `_noiseonly` (orange-art-0247) changing ONLY the trim-poison group: thrust_scale_frac 0.12→0.05, attitude obs_bias 0.035→0 (gyro bias 0.05 stays), dr_curriculum_frac 0.3→0.5. Honest WHITE per-channel noise kept (gyro 2.5/2.2/1.5 rad/s, attitude 0.02 rad), obs_stack 3, latency 5, old reward, [64,64] tanh, 3.2B steps (~52 min @ ~1.04M sps). Eval per the metric split defined in quiet-bonus-7296.

**Results (30 s pure-hold survival probe, 2048 drones, deterministic mean).**

| metric | R1 | _noiseonly (R0) | baseline `long` | bar |
|---|---|---|---|---|
| **M1** clean-trim no-DR | **0.0%** (exit 2.96 s) | 0.0% (exit 3.98 s) | **91.6%** | ≥91.6% ✖ |
| **M2** calibrated-trim, honest white noise | **4.0%** (exit 2.66 s) | 3.1% (exit 2.88 s) | 0.1% (exit 2.14 s) | ≥80% ✖ |
| **M4** full-DR (unwinnable ceiling) | 4.2% | — | — | report-only |

Deterministic eval (2048×1500): no-DR tilt 2.14°, speed 0.480 m/s (the sink rate); DR-on tilt 16.0°, speed 0.741 (M3 ✖).

**Δ vs parents / decode.**
- **H3 refuted cleanly:** removing the trim poisons and doubling the curriculum ramp changed *nothing that matters* — M1 stays 0.0%, M2 moves 3.1→4.0% (noise-level). The v2 post-mortem's suspicion of thrust 0.12 / attitude bias as the sink is wrong: with them GONE and the white noise KEPT, the policy still cannot converge an open-loop hover trim.
- **The white 2.5 rad/s gyro noise is now the isolated culprit** for the clean-trim regression (91.6% → 0%): it is the only remaining v2 factor group in R1 (plus stack/latency, which the gate_race line already showed are benign — wandering-shadow-3679).
- **Noise-hardening does buy honest-noise robustness relative to the baseline:** under M2 the un-hardened baseline is 0.1% while noise-trained arms reach 3–4% — a 40× relative gain that is still catastrophically short of the 80% bar. Training against white noise at the measured amplitude neither preserves the trim nor delivers usable robustness.

**Verdict.** **RED** (M1 0% < 85%): the trim-poison factor is exonerated; the responsible factor is the honest white gyro/attitude noise itself. The remaining *testable* hypothesis is **H1 (spectrum)**: the deployed gyro is Betaflight-LPF/notch-filtered (`pilot.py` gyroADCf), so its real noise is time-correlated — injecting the measured amplitude as i.i.d. white noise matches the marginal but not the spectrum, and white noise is maximally hostile to thrust–gyro coupling in a memoryless MLP.

**Honesty.**
- R1's M1 median exit (2.96 s) is *shorter* than _noiseonly's (3.98 s) — removing the poisons did not even slow the sink; possibly the longer curriculum (more clean-phase training) is offset by the sharper noise onset.
- The M2 numbers carry ±~0.9% binomial error at n=2048 — the R1 vs _noiseonly M2 difference (4.0 vs 3.1%) is not meaningful.
- Per the metric split, M4 is reported but cannot discriminate (open-loop physics).
- `hover_blind_air65_long` (cold-night-8900) **remains the policy of record**; do not deploy R1.

**Next (already in flight).** AR(1) marginal-preserving colored-noise seam committed (`ace5821`: `obs_noise_ar_channels`, once-per-step `step_noise()` advance, unit-tested Var=σ² / acf(1)=ρ / no terminal-step double-advance). Arms: **R3** = R1 + colored (one-factor spectrum delta, training now), **R2** = _noiseonly + colored (spectrum with poisons kept). ρ = 0.9 attitude / 0.8 gyro is **modeled, unvalidated** (no calm-hover flight logs on this box).

**Lineage.** Tests + refutes the H3 branch of hypothesis **quiet-bonus-7296**; forks config/checkpoint lineage of baseline **cold-night-8900** (whose bars it fails); one-factor comparison against control **orange-art-0247**.