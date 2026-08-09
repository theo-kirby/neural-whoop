---
node_id: 212308e5-d723-518f-ad35-80c3160074eb
slug: muddy-hill-9397
title: 'hover_blind_air65_v2 sweep REFUTED (RED): honest-noise DR re-breaks the open-loop vertical trim — all 3 arms sink to 0% clean 30 s survival (baseline 91%); blind IMU-only vertical needs the flow deck'
created_at: '2026-07-06T17:10:02.036392+00:00'
parents:
- shiny-mountain-6946
- cold-night-8900
summary: 'The three-way 3.2B-step sweep (flagship vz+noise+steepR / _novz noise+steepR / _noiseonly noise+baseR) forking from cold-night-8900 (91.6% clean pure-hold 30 s survival) is REFUTED. All three arms SINK to the floor in ~2–4 s — no-DR pure-hold survival 0.0% for every arm (vs baseline 91.6%), the drift is vertical (replay zmin hits the 0.16 floor, horizontal <0.13 m). Attitude actually IMPROVED (no-DR tilt 1.25° flagship / 0.69° _novz / 1.96° _noiseonly vs baseline 1.68°) — the steeper upright well pulled reward mass onto attitude and the honest 2.5 rad/s gyro-noise DR destroyed the open-loop thrust trim the baseline had solved. Ablation decode (median time-to-floor, no-DR): noise DR alone breaks it (_noiseonly baseline-reward still 0%, exit 3.98 s), reward steepening aggravates (_novz 2.74 s), the vz channel aggravates most (flagship 1.70 s) — each lever monotonically WORSENS survival. vz did NOT provide the closed-loop vertical damping it was added for: its input carries the honest ±1.5 m/s DC bias, so the leaky acc-integrated estimate is unusable. Cross-eval: the un-hardened baseline ALSO collapses under the honest noise floor DR-on (tilt 28.7°, survival 0.4%), while noise-hardened _noiseonly/_novz hold attitude better under noise (19–21°, survival 1.3%) — so the recipe bought attitude-robustness-under-noise but traded away clean-air hover, and under honest noise open-loop physics floors everyone to <1.3%. Verdict RED / NO-GO: more DR is the wrong lever; the honest gyro floor makes open-loop IMU-only vertical infeasible — confirming the hypothesis''s own fallback that blind hover needs the flow deck (real closed-loop velocity), not an acc-integrated vz. Configs hover_blind_air65_v2{,_novz,_noiseonly}.yaml; committed survival probe scripts/survival_probe.py (84dd91e).'
origin:
  backend: flywheel
  node_id: 212308e5-d723-518f-ad35-80c3160074eb
  slug: muddy-hill-9397
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
# hover_blind_air65_v2: does honest-noise DR + vz + a steeper well beat the baseline? No — it re-breaks the trim.

**Hypothesis (shiny-mountain-6946).** Under the measured Air65 II sensor floor the trim-fixed baseline (cold-night-8900, 91.6% clean pure-hold survival) should degrade, and the flagship should hold attitude AND damp vertical closed-loop via `vz_est`, beating it. **Refuted.**

**Setup.** Three 3.2B-step arms (8192 envs, obs_stack 3, action_latency 5, thrust_scale_frac 0.12, honest per-channel `obs_noise_std_channels`/`obs_bias_channels` — gyro 2.5 rad/s SD, attitude 0.02 rad, vz 0.15 m/s scatter; per-episode bias ±0.035 rad roll/pitch, vz ±1.5 m/s DC):
- **flagship** `hover_blind_air65_v2` — task `hover_blind_v2` (obs-6, +`vz_est`), upright_sigma 0.25, smoothness 0.002.
- **_novz** `_v2_novz` — obs-5, same steepened reward.
- **_noiseonly** `_v2_noiseonly` — obs-5, **baseline reward** (upright_sigma 0.5, smoothness 0.004).
Eval: deterministic 2048×1500, no-DR + DR-on standard metrics; committed pure-hold survival probe (`scripts/survival_probe.py`, 84dd91e) no-DR + DR-on; viz pack vs the baseline replay.

**Results (no-DR = clean deployment; the honest first-flight number).**

| arm | tilt° | speed | pure-hold surv (no-DR) | median exit | surv (DR-on) | DR-on tilt |
|---|---|---|---|---|---|---|
| baseline cold-night-8900 | 1.68 | 0.069 | **91.6%** | — | — | — |
| flagship (vz+noise+steepR) | 1.25 | 0.826 | **0.0%** | 1.70 s | 0.0% | 34.0° |
| _novz (noise+steepR) | 0.69 | 0.506 | **0.0%** | 2.74 s | 1.3% | 21.1° |
| _noiseonly (noise, baseR) | 1.96 | 0.366 | **0.0%** | 3.98 s | 1.3% | 19.2° |

**Δ vs baseline / ablation decode.**
- **The failure is a vertical sink, not horizontal drift.** Hero replays: v2 arms hit the 0.16 m floor (zmin 0.16) in ~90–144 steps while moving <0.13 m horizontally; the baseline holds altitude (zmin 0.83) for 865+ steps. The v2 recipe **re-broke the open-loop thrust trim the baseline had fixed** — mean_speed 0.37–0.83 m/s is the sink rate.
- **Attitude improved while altitude regressed:** the steeper upright well (σ 0.5→0.25) drove tilt to 0.69–1.25° (better than baseline 1.68°) but pulled reward mass off altitude-hold.
- **Each lever monotonically worsens survival** (no-DR median time-to-floor): noise DR alone (_noiseonly, baseline reward) already sinks (3.98 s); + reward steepening (_novz) → 2.74 s; + vz (flagship) → 1.70 s. So the **root cause is the honest-noise DR package** (2.5 rad/s gyro floor + ±1.5 m/s vz bias + wider thrust 0.12 + latency 5), not the reward and not vz — those only aggravate.
- **vz did not rescue vertical.** It was added to close the loop on altitude, but its input carries the honest ±1.5 m/s DC bias, so the leaky acc-integrated estimate is unusable — the flagship sinks *fastest*.
- **Cross-eval (baseline under the honest noise floor, matched stack-1):** un-hardened baseline DR-on collapses too (tilt 28.7°, survival 0.4%); noise-hardened _noiseonly/_novz hold attitude better under noise (19–21°, 1.3%). So noise-hardening bought *attitude*-robustness-under-noise — but under honest noise **open-loop altitude physics floors everyone to <1.3%**, and in clean air the hardened policies sink where the baseline holds.

**Verdict.** **RED / NO-GO.** The v2 recipe is a net regression: it trades the baseline's deployable clean-air hover (91.6% → 0%) for modestly better attitude-under-noise that still cannot hover. More DR is the wrong lever. The honest 2.5 rad/s gyro floor makes **open-loop IMU-only vertical hover infeasible**, and an acc-integrated `vz_est` with realistic DC bias does not close the loop — this confirms the hypothesis's own stated fallback: **blind hover needs the flow deck (real, low-bias closed-loop velocity)**, which is exactly the Stage-1 pipeline of the sim2real plan (bitter-fire-0679).

**Honesty.**
- The result is nuanced, not a pure failure: noise-hardening genuinely improved attitude-under-noise (28.7°→19° DR-on) and the steeper well gave the best absolute attitude on record (0.69°). The RED is specifically about *deployable hover* (altitude), the metric that matters.
- DR-on survival (<1.3% for all, incl. baseline 0.4%) is floored by open-loop physics (±thrust×±mass over 30 s) — it does NOT discriminate the recipes; the no-DR clean survival (91.6% vs 0%) is the discriminator and the headline.
- `_noiseonly` vs baseline bundles four changes (honest noise+bias, obs_stack 1→3, thrust 0.05→0.12, latency 3→5); the honest gyro noise is the prime suspect but the wider thrust DR also taxes the open-loop trim. A follow-up that varies only the noise channels (holding thrust/latency/stack) would fully isolate it.
- The exported flagship `policy_weights.json`/`policy_ref_outputs.json` (n_params 5636) carry a **sinking** trim — do NOT deploy; the baseline cold-night-8900 remains the first-flight checkpoint of record.

**Lineage.** Tests hypothesis **shiny-mountain-6946**; forks the checkpoint + config of baseline **cold-night-8900** (which it cross-evals against and fails to beat). Siblings: the `_novz` and `_noiseonly` ablation nodes (this node carries the shared decode). Redirects to Stage-1 flow-deck velocity of the sim2real plan **bitter-fire-0679**.