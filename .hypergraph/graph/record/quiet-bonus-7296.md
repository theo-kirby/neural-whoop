---
node_id: 6d13e410-ea22-55ac-9a52-f2c8348ab61b
slug: quiet-bonus-7296
title: 'Hypothesis: the v2 RED''s attribution is confounded — the unobservable trim-poison DR (thrust 0.12 + ±2° attitude bias), not the honest gyro noise, sank the arms; white-noise modeling of the LPF-filtered gyro is also spectrally dishonest'
created_at: '2026-07-06T18:24:37.834908+00:00'
parents:
- muddy-hill-9397
- orange-art-0247
summary: 'The v2 sweep''s RED verdict (''honest gyro-noise DR re-breaks the open-loop trim'') is confounded: the decisive _noiseonly control changed 5 factors at once vs the surviving baseline — gyro noise 0.01→2.5 rad/s white, attitude noise ×2, NEW per-episode ±2° attitude + ±0.05 rad/s gyro bias, thrust_scale 0.05→0.12, latency 3→5, obs_stack 1→3. The ±2° attitude bias and ±12% thrust scale are unobservable trim poisons that integrate to a bound independent of gyro noise, so the true culprit is unknown. Two code facts: (1) the deployed gyro is Betaflight-LPF-filtered (pilot.py gyroADCf) while the sim injects the same amplitude as i.i.d. WHITE noise — right marginal, wrong spectrum, maximally hostile to a memoryless MLP; (2) DR-on survival with thrust_scale>0 is physically unwinnable open-loop, so the metric must split into M1 clean-trim (bar ≥91.6%) / M2 calibrated-trim honest-noise (bar ≥80%) / M4 full-DR (reported, labeled unwinnable). New control measurement (commit a16db65): baseline long ckpt under the M2 config = 0.1% survival, median exit 2.14 s (vs 91.6% clean) — zero honest-noise robustness even with perfect trim. Ladder: R1 (config-only, keeps white 2.5 rad/s noise, drops thrust to 0.05 + zeroes attitude bias + curriculum 0.5) tests H3 trim-poison; R2/R3 AR(1)-colored noise tests H1 spectrum; R4 privileged vz/thrust-constancy reward only if a sink remains. Prediction: R1 recovers M1 and most of M2; the flow-deck redirect is not yet forced by evidence.'
origin:
  backend: flywheel
  node_id: 6d13e410-ea22-55ac-9a52-f2c8348ab61b
  slug: quiet-bonus-7296
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Reframing the v2 post-mortem: what actually sank the arms is unknown — the ablation was not one-factor

**The claim being challenged.** muddy-hill-9397 / orange-art-0247 concluded "the honest-noise DR package itself re-breaks the open-loop trim" and redirected to the flow deck. But the decisive control `_noiseonly` changed **five** factors at once vs the surviving baseline (cold-night-8900, 91.6% clean survival):

| factor | baseline `long` (survived) | `_noiseonly` (sank) |
|---|---|---|
| gyro obs noise | white sd 0.01 (all chans) | white sd **2.5/2.2/1.5** rad/s |
| attitude obs noise | white sd 0.01 | white sd 0.02 |
| **per-episode obs bias** | **none** | **±0.035 rad (2°) attitude + ±0.05 rad/s gyro** |
| **thrust_scale_frac** | **0.05** | **0.12** |
| action_latency_steps | 3 | 5 |
| obs_stack | 1 | 3 |

An unobservable **±2° attitude bias** and **±12% thrust scale** each bias the open-loop mean hover thrust and integrate straight to a bound — they are altitude poisons *independent of gyro noise*. The v2 decode attributed the sink to the noise because noise was the headline change; the trim poisons rode along in every arm.

**Two code facts sharpen this:**
1. **The deployed gyro is already Betaflight-LPF-filtered** (`pilot.py:145-150`: MSP_RAW_IMU returns `gyroADCf`, post-filter/post-notch). The sim injects the measured amplitude as **fresh i.i.d. white noise every step** (`randomization.py` obs-noise seam) — the marginal matches but the *spectrum is wrong*, and white noise is maximally hostile to a memoryless MLP that couples thrust to gyro.
2. **DR-on survival with thrust_scale>0 is physically unwinnable** for open-loop altitude — so the v2 sweep's DR-on numbers never could discriminate; the metric must be split (below).

**New control measurement (this node, commit a16db65).** The baseline `long` checkpoint cross-evaled under the new **M2 config** (`hover_blind_air65_m2_honest_stack1.yaml`: thrust_scale 0 = bench-calibrated trim, but honest white noise + gyro bias + latency 5 + gusts ON): **survival 0.1%, median exit 2.14 s** (vs 91.6% clean). The policy of record has essentially zero robustness to the honest noise even with perfect trim — the gap a hardened flagship must close is total, and any M2 win will be unambiguous.

**Hypotheses, ranked by cost:**
- **H3 (trim-poison, cheapest):** the sink was thrust 0.12 + attitude bias, not gyro noise. Test = **R1** (`hover_blind_air65_r1.yaml`): `_noiseonly` recipe keeping the honest WHITE 2.5 rad/s noise, but thrust 0.05, attitude bias 0, dr_curriculum 0.5. Config-only.
- **H1 (spectrum):** honest gyro noise is harmful *only because modeled white* instead of Betaflight-correlated. Test = **R2/R3**: AR(1)-colored per-channel obs noise (marginal-preserving, ρ from calm-hover logs or swept {0.6,0.8,0.9} labeled unvalidated).
- **H2 (privileged decoupling reward):** ground-truth vz→0 + thrust-constancy terms clean the throttle. Only as **R4** if a residual sink remains.

**Metric split (the honesty contract for all R-ladder nodes):** M1 = clean-trim survival `--no-dr`, bar ≥91.6% (non-regression). M2 = calibrated-trim honest-noise survival (`_m2_honest*` configs, `--dr`), bar ≥80%. M3 = DR-on tilt ≤~2°, speed ≤~0.1 m/s. M4 = full-DR survival incl. thrust_scale — report but label as the open-loop ceiling that cannot be won.

**Prediction.** R1 recovers M1 ≥ 91.6% (the trim poisons were the sink) and gains substantial M2; if M2 still falls short of 80%, the residual is the white-noise spectrum (H1) and the AR(1) seam is warranted.

**Lineage.** Reframes the verdicts of **muddy-hill-9397** and **orange-art-0247** (parents) without disputing their data — only the attribution. Baseline of record + bars: **cold-night-8900**. The flow-deck redirect (bitter-fire-0679 Stage-1) stays valid strategically but is NOT yet forced by the evidence; the hardware constraint for this line is stock Air65 II, IMU-only.