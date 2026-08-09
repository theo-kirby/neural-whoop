---
node_id: 0114e441-13fc-5890-969d-57f15f3b45e5
slug: spring-violet-3051
title: 'R3 (AR(1)-colored honest noise, one factor vs R1) RED: M1 still 0% — the modeled spectrum (ρ 0.9/0.8) does not rescue the trim, though it slows the sink 1.75× and gives the best attitude on record (0.71°)'
created_at: '2026-07-06T20:17:05.698589+00:00'
parents:
- muddy-brook-9314
- quiet-bonus-7296
summary: 'R3 (configs/hover_blind_air65_r3.yaml, commit ace5821) = R1 changing exactly one factor: the honest per-channel noise becomes marginal-preserving AR(1)-colored (rho 0.9 attitude / 0.8 gyro — MODELED, unvalidated; no flight logs on this box), same stds. 3.2B steps. Result: M1 clean-trim pure-hold survival still 0.0% — H1 refuted at this rho — but the spectrum change is not a no-op: median time-to-floor 2.96→5.18 s (1.75× slower sink), no-DR sink rate 0.48→0.28 m/s, and no-DR tilt 0.71° is the best attitude on record (baseline 1.68°). M2-colored 3.2%, M2-white 0.0% (white-trained R1 gets 4.0% on white: training against the harder white spectrum generalizes better), M4 3.1%. With H3 (R1) and H1 (R3) both refuted, the attribution square closes: the v2 sink is caused by the honest noise AMPLITUDE itself (2.5 rad/s ≈ 143°/s SD gyro) — PPO cannot converge an open-loop hover trim under it in this recipe, regardless of trim DR or modeled spectrum. R2 (colored + poisons kept) skipped as strictly-harder/non-discriminating. Last pre-authorized lever: H2 privileged decoupling reward (−0.5|vz| ground-truth + −0.1(Δthrust)², commit 856457d), arm R4 training. rho measurement from calm-hover logs remains the honest gate on any final spectrum claim. Baseline cold-night-8900 remains the policy of record.'
origin:
  backend: flywheel
  node_id: 0114e441-13fc-5890-969d-57f15f3b45e5
  slug: spring-violet-3051
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 62e24327-a747-5285-93b5-372724b9401f
  slug: blue-surf-5530
  revision: 0
  pushed_at: '2026-08-09T21:27:34+00:00'
  content_sha256: 771799f6e93f0323f8685c1209f20e55123ee9104fa2f7982ee2a32a937b1ab6
---
# R3: does coloring the honest noise (the spectrum fix) recover the open-loop trim? No — but it measurably helps.

**Hypothesis tested (quiet-bonus-7296, H1).** The honest gyro noise sank v2/R1 *because it was modeled white*; the real Betaflight-filtered stream (`gyroADCf`) is time-correlated, and a marginal-matched AR(1) should let PPO converge the trim. Prediction: R3 ≥ R1 on M1, ideally ≥ 91.6%. **Refuted at the modeled ρ.**

**Setup.** `configs/hover_blind_air65_r3.yaml` (commit ace5821) = R1 changing EXACTLY ONE factor: `obs_noise_ar_channels [0.9, 0.9, 0.8, 0.8, 0.8]` (marginal-preserving AR(1); same stds 0.02/0.02/2.5/2.2/1.5). τ ≈ 190 ms attitude / 90 ms gyro at 50 Hz. **ρ is MODELED — no calm-hover flight logs on this box; unvalidated.** Seam: `randomization.py` `step_noise()` advanced once per env step (`base.py`), pure-read `add_obs_noise`, stationary-marginal reset; unit-tested (Var=σ², acf(1)=ρ, no terminal-step double-advance). 3.2B steps @ ~1.02M sps (~6% seam cost). NOTE: plan sketch said obs_stack 2 for R3; kept 3 so R3−R1 stays one-factor.

**Results (30 s pure-hold survival, 2048 drones, deterministic mean).**

| metric | R3 (colored) | R1 (white) | baseline `long` | bar |
|---|---|---|---|---|
| **M1** clean-trim no-DR | **0.0%** (exit **5.18 s**) | 0.0% (exit 2.96 s) | 91.6% | ✖ |
| **M2** calibrated-trim, colored noise | 3.2% (exit 2.02 s) | — | — | ✖ |
| **M2** calibrated-trim, white noise | 0.0% (exit 2.54 s) | 4.0% (exit 2.66 s) | 0.1% | ✖ |
| **M4** full-DR (unwinnable) | 3.1% | 4.2% | — | report-only |

Deterministic eval: no-DR tilt **0.71°** (best on record, beats _novz's 0.69 within noise and baseline's 1.68), speed 0.276 m/s (vs R1 0.480 — a ~40% slower sink); DR-on (own colored noise) tilt 23.7°, speed 0.912.

**Δ vs R1 / decode.**
- **H1 refuted at ρ = 0.9/0.8:** the spectrum change moves median time-to-floor 2.96 → 5.18 s and the sink rate 0.48 → 0.28 m/s — a real, directionally-as-predicted improvement — but survival stays exactly 0%: every drone still integrates to the floor within 30 s. Coloring makes the noise *more learnable* (attitude 2.14° → 0.71° no-DR) yet the thrust trim still does not converge.
- **Spectrum-generalization asymmetry:** the colored-trained R3 scores 0.0% under the *white* M2 (white is strictly harder — more high-frequency power for the same marginal) while white-trained R1 scores 4.0%; under its own colored M2 R3 reaches 3.2%. Training against the harder (white) spectrum is the conservative choice if anything ever clears the bar.
- **With H3 (R1) and H1 (R3) both dead, the attribution square is closed:** the sink is caused by the honest noise *amplitude* itself — 2.5 rad/s ≈ 143°/s SD on the gyro channels — under which PPO cannot converge a deterministic open-loop hover thrust in this recipe ([64,64], 3.2B steps), regardless of trim DR or (modeled) spectrum.

**Verdict.** **RED** (M1 0% < 85%). R2 (colored + trim poisons kept) is **skipped**: it is strictly harder than R3 and can no longer discriminate anything — running it would burn an hour to learn nothing. The last pre-authorized lever is **H2 (privileged decoupling reward)**: −k·|vz| on ground-truth vertical velocity (a direct PPO gradient against the sink needing no noisy estimate) + −k·(a_t[0]−a_{t−1}[0])² thrust-constancy (decouple throttle from gyro jitter) — arm **R4** (= R3 + vz 0.5 / thrust_const 0.1, single unswept point, commit 856457d) is training now.

**Honesty.**
- ρ unvalidated: a much higher ρ (or the real aliased-vibration spectrum, which is narrowband, not AR(1)) could behave differently; measuring lag-1 autocorrelation from calm-hover `flight_*.csv` on the deploy box remains the honest gate before any spectrum conclusion is final.
- The 0.71° no-DR tilt is a *record*, and the 1.75× slower sink is real — this is a nuanced RED: spectrum matters, it just doesn't matter *enough* at the measured amplitude.
- M2-colored for R3 vs M2-white for R1 are different test conditions; both are reported to keep the comparison honest.
- `hover_blind_air65_long` (cold-night-8900) remains the policy of record.

**Lineage.** Tests the H1 branch of **quiet-bonus-7296**; one-factor fork of **muddy-brook-9314** (R1). AR seam + tests: commit ace5821. Child: R4 (H2 arm).