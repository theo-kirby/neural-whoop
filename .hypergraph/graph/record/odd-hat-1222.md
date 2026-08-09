---
node_id: 8b1dae2f-a341-5818-a4ce-3fc493917b07
slug: odd-hat-1222
title: 'Measurement: M2-honest was itself partly unwinnable — impulses+wind cost the blind baseline ~30 points independent of gyro noise; the fair metric is M2-sensor'
created_at: '2026-07-06T21:31:08.133364+00:00'
parents:
- cold-night-8900
- delicate-credit-2979
- quiet-bonus-7296
summary: 'Cross-evaled the flagship (hover_blind_air65_long) under gyro-noise dose-response 0.10x-1.0x in two eval families (commit a6ca7a1). M2-honest (impulses+wind ON) saturates at 15% as noise->0 while M2-sensor (impulses/wind OFF) reaches 44.8% — ~30 points of the old M2 shortfall was unwinnable open-loop kinematics (30 velocity kicks/episode + wind drift), the same fairness class as thrust_scale. Metric v2 = M2-sensor (calibrated trim, no impulses/wind, honest noise+bias+latency), bar 80%. Amplitude attribution stands: sensor-only survival collapses 30.8%->1.8% between 0.25x and 0.5x, and deploy-side reduction alone cannot rescue the baseline (44.8% at 0.10x) — matched-amplitude retraining (d50, running) is necessary. R-ladder M2 numbers were partly impulse physics; re-check under M2-sensor.'
origin:
  backend: flywheel
  node_id: 8b1dae2f-a341-5818-a4ce-3fc493917b07
  slug: odd-hat-1222
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: bd29e82d-9c89-5351-8901-c4006ce5aa03
  slug: young-unit-4988
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 4bfad511b8004128b439d8d3e058cfc71d5ac2846d7b033bf9e1ed8804e183dd
---
# Baseline gyro-noise dose-response + M2 metric decomposition

**Hypothesis being characterized (no verdict, a measurement):** how does the flagship (`hover_blind_air65_long`, trained at obs noise 0.01 scalar / latency 3 / no bias) degrade as the honest gyro-noise amplitude is scaled down toward zero — and does the M2-honest config measure *sensor* robustness at all?

**Setup.** `scripts/survival_probe.py --dr`, 2048 pure-hold drones, 30 s horizon, deterministic mean, baseline ckpt cross-evaled under two eval families (commit a6ca7a1): **M2-honest** (thrust_scale 0; wind 1.0 + impulses 0.02 ON; gyro bias 0.05; latency 5; gyro noise scaled) and **M2-sensor** (same but wind 0, impulses 0).

**Results (30 s survival):**

| gyro noise scale | M2-honest | M2-sensor |
|---|---|---|
| 1.00× (2.5/2.2/1.5 rad/s) | 0.1% | 0.05% |
| 0.50× | 2.4% | 1.8% |
| 0.25× | 12.1% | 30.8% |
| 0.10× | 15.0% | **44.8%** |

**Findings.**
1. **M2-honest saturates at ~15% as noise → 0** — the old metric's ceiling for a blind policy is nowhere near 100%. The residual killers are the inherited kinematic DR: `impulse_prob 0.02` ≈ 30 velocity kicks (≤2.5 m/s) per episode = an unwinnable z random walk + xy drift, and wind = unobservable lateral drift out of the 3.5 m arena. These are the **same fairness class as thrust_scale** (unobservable open-loop disturbances) and must be excluded from the sensor-robustness metric. **Metric v2: M2-sensor** = calibrated trim + no impulses/wind + honest noise/bias/latency. Bar stays 80%.
2. **The amplitude attribution stands**: sensor-only survival still collapses 30.8% → 1.8% between 0.25× and 0.5× — gyro noise is the dominant sensor-channel killer, and the baseline cannot be rescued by deploy-side noise reduction alone (44.8% at 0.10× ≪ 80%): **retraining at the matched amplitude is necessary**, so the running d50 arm is the right next probe.
3. Even at 0.10× noise sensor-only, the baseline reaches only 44.8% — the remaining gap vs its 91.6% clean number is the latency 3→5 + gyro bias 0.05 + attitude noise it never trained against. A matched-training arm (d50) sees all of these in training.
4. **Retroactive honesty note for the R-ladder:** its M2 numbers (4.0/3.2/0.9%) were measured under M2-honest and therefore partly reflect impulse/wind physics, not just noise handling; the monotone-worsening claim needs re-checking under M2-sensor when the next arm's checkpoints are evaluated.

**Verdict/Honesty.** Measurement, no outcome tag. All probes on the baseline checkpoint only; the trained-arm dose-response (d50, running) is the experiment this calibrates. The M2-sensor family keeps gyro bias 0.05 rad/s (a real DC error averaging cannot remove) and latency 5 (real bridge p99) — those stay because they are honest and, unlike impulses, at least partially compensable.

**Lineage.** Parents: quiet-bonus-7296 (origin of the M1/M2 split this refines), cold-night-8900 (the probed checkpoint), delicate-credit-2979 (campaign control). Feeds the d50 gate.