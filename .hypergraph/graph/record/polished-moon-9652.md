---
node_id: f761cff7-7eb7-59b0-84c1-6cdcade3be5a
slug: polished-moon-9652
title: 'd50 (0.5× gyro-noise dose-response) RED on the bars — but 6× sensor-survival gain confirms dose-response, and the M1-live diagnostic exposes the real enemy: the learned trim is a steep function of noise amplitude (81%→43%→0.3% at 0.8×/1.0×/1.2×)'
created_at: '2026-07-06T22:21:07.879851+00:00'
parents:
- odd-hat-1222
- muddy-brook-9314
- shiny-firefly-6661
summary: 'd50 (configs/hover_blind_air65_d50.yaml, commit ad7e8a1, 3.2B steps) = R1 with gyro noise halved to 1.25/1.1/0.75 rad/s (one factor; models the L1 bridge-oversampling deploy scenario). RED on bars: M1 0.0% (exit 4.7 s), M2-sensor@own-amplitude 22.0% (bar 80%) — but that is 6× R1''s 3.8%, confirming dose-response. Load-bearing finding (M1-live diagnostic, clean world + live sensors, commit a626471): survival is 81.4% / 43.0% / 0.3% at 0.8×/1.0×/1.2× of the trained amplitude, and 0% at zero noise — the learned thrust trim is a steep function of input-noise amplitude (Jensen through tanh), so every fixed-amplitude-trained arm (incl. the whole R-ladder, whose M1 0%s are partly this artifact) is deployment-brittle under ±20% amplitude mismatch. Indicated fix: amplitude-randomized noise DR (per-episode scale U[0.5,1.5]×) to force an amplitude-invariant/adaptive trim — next arm d50var. R-ladder re-check under fair M2-sensor@1.0×: R1 3.8%, R3 0%, R4 0% (REDs stand).'
origin:
  backend: flywheel
  node_id: f761cff7-7eb7-59b0-84c1-6cdcade3be5a
  slug: polished-moon-9652
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# d50: is half the measured gyro-noise amplitude below the learnability ceiling σ*? No — and here is why nothing on the fixed-amplitude ladder could ever pass

**Hypothesis tested (shiny-firefly-6661, prediction 1).** Training the R1 recipe at 0.5× amplitude (the L1 bridge-oversampling deploy scenario) recovers M1 ≥ 91.6% and M2(σ_train) ≥ 80%. **Refuted — but the diagnostic that explains the failure redirects the whole campaign.**

**Setup.** `configs/hover_blind_air65_d50.yaml` (commit ad7e8a1) = R1 changing ONE factor: gyro obs-noise sd 2.5/2.2/1.5 → 1.25/1.1/0.75 rad/s (attitude noise 0.02 and gyro DC bias 0.05 unchanged — averaging cannot remove bias). 3.2B steps, 8192 envs, [64,64] tanh, obs_stack 3, ~60 min. Evals per the M2-sensor metric v2 (odd-hat-1222); probes = 2048 pure-hold drones, 30 s, deterministic mean.

**Results.**

| metric | d50 | R1 (@ its own 1.0×) | bar |
|---|---|---|---|
| M1 clean no-DR | **0.0%** (median exit 4.7 s) | 0.0% (2.96 s) | ≥91.6% ✖ |
| M2-sensor @ trained amplitude | **22.0%** | 3.8% | ≥80% ✖ |
| M2-honest @ trained amplitude (old metric) | 8.3% | 4.0% | — |
| M2-sensor @ full 1.0× amplitude | 0.0% | 3.8% | reference |

**The M1-live diagnostic (the load-bearing result).** M1's zero-noise world is unphysical for a vibration-driven gyro, so we probed "clean world, live sensors": ONLY obs noise on (thrust 0, wind 0, impulses 0, bias 0, rate_gain 0, latency 0; configs `m1live_d50_s{080,100,120}`, commit a626471), scaling the noise around the trained amplitude:

| eval amplitude vs trained | survival | median exit |
|---|---|---|
| 0.8× | **81.4%** | 13.4 s |
| 1.0× | 43.0% | 16.5 s |
| 1.2× | **0.3%** | 15.1 s |
| 0.0× (= old M1) | 0.0% | 4.7 s |

**Decode.**
1. **Dose-response confirmed:** halving amplitude took own-amplitude sensor survival 3.8% → 22.0% (×6), and the near-clean M1-live@0.8× hits 81.4% — the amplitude mechanism is real and graded, exactly as the hypothesis predicted.
2. **But the trim is amplitude-locked, not amplitude-robust.** The policy's effective thrust trim shifts with input-noise sd (Jensen through the tanh net + clipped-Gaussian head): eval below the trained amplitude → trim reads high → survives; above → sinks immediately; at zero → sinks (that is why M1 = 0% on every noise-trained arm — **the R-ladder's M1 failures were partly this artifact**, not pure trim breakage). A ±20% amplitude mismatch swings survival 81% → 0.3%. Real vibration amplitude varies with throttle, battery, prop wear — so ANY fixed-amplitude-trained policy is deployment-brittle even if it aced its own amplitude.
3. **σ* still unresolved below 1.25 rad/s** for the bars-as-written, but the bars themselves now need the M1-live form (zero-noise M1 is unfair to noise-trained arms; kept for continuity).
4. R-ladder re-check under M2-sensor@1.0× (fair metric): R1 3.8%, R3 0.0%, R4 0.0% — their REDs stand under the corrected metric.

**Verdict.** **RED** on the campaign bars; **GREEN on mechanism discovery**: the binding constraint is not σ* alone but **trim amplitude-sensitivity**. The indicated fix is **amplitude-randomized noise DR** — per-episode noise scale ~U[0.5, 1.5]× so PPO can only converge a trim that is invariant across amplitudes; with obs_stack 3 the noise level is estimable from frame-to-frame variance, so an adaptive trim is representable. That is the next arm (d50var), small code in the DR seam.

**Honesty.** (1) The 0.5× amplitude models 200 Hz bridge oversampling with inter-sample independence — both unvalidated until bench-measured. (2) M1-live@0.8× 81.4% is NOT a pass of any bar: it is a diagnostic at a favorable amplitude with bias/latency/rate-gain off. (3) Binomial error at n=2048 is ±~0.9%; the 22.0 vs 3.8% and 81.4 vs 43.0% gaps are far outside it. (4) White-noise spectrum assumption unchanged from the R-ladder (ρ still unmeasured).

**Lineage.** Tests prediction 1 of **shiny-firefly-6661**; one-factor config fork of **muddy-brook-9314** (R1); evaluated under the M2-sensor metric defined by **odd-hat-1222**. Next: d50var (amplitude-randomized DR) forks from here.