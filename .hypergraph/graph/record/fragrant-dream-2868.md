---
node_id: c99056fb-ded0-5d22-9db0-25ad2d2e61db
slug: fragrant-dream-2868
title: 'Ablation _novz (noise-hardening + steepened reward, NO vz channel): also sinks 0% clean survival — vz is not the root cause, but removing it slows the sink (exit 1.70→2.74 s)'
created_at: '2026-07-06T17:17:21.593704+00:00'
parents:
- shiny-mountain-6946
summary: 'Sibling ablation of the hover_blind_air65_v2 sweep (see muddy-hill-9397 for the full decode). _novz = the flagship recipe MINUS the vz_est channel: obs-5 hover_blind, honest per-channel noise+bias DR, obs_stack 3, thrust 0.12, latency 5, steepened reward (upright_sigma 0.25, smoothness 0.002). 3.2B steps. Result: no-DR pure-hold 30 s survival 0.0% (vs baseline 91.6%) — still a vertical sink to the floor (median time-to-exit 2.74 s). Best absolute attitude on record (no-DR tilt 0.69°). vs the flagship (with vz, exit 1.70 s): removing vz SLOWS the sink by ~1 s and cuts no-DR speed 0.83→0.51 m/s and DR-on tilt 34.0→21.1° — so the vz channel (fed the honest ±1.5 m/s DC bias) is a net aggravant, not a rescue. But _novz still sinks, so vz is NOT the root cause: the honest-noise DR package is. DR-on survival 1.3% (open-loop-physics floored). Config hover_blind_air65_v2_novz.yaml.'
origin:
  backend: flywheel
  node_id: c99056fb-ded0-5d22-9db0-25ad2d2e61db
  slug: fragrant-dream-2868
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# _novz: the flagship recipe minus the vz channel — does removing vz recover hover? No.

Sibling ablation in the `hover_blind_air65_v2` three-way sweep; the shared setup, ablation decode, and RED verdict live in **muddy-hill-9397** (the flagship node). This node records the `_novz` arm.

**What it isolates.** `_novz` = flagship **minus the `vz_est` channel**: task `hover_blind` (obs-5), same honest per-channel `obs_noise_std_channels` (gyro 2.5 rad/s) + `obs_bias_channels`, obs_stack 3, thrust_scale_frac 0.12, action_latency 5, and the **steepened reward** (upright_sigma 0.25, smoothness 0.002). 3.2B steps. `flagship − _novz` = the value of the vz channel.

**Results (deterministic 2048×1500).**
- **no-DR:** tilt **0.69°** (best absolute attitude on record), speed 0.506 m/s, pos_err 0.818, crash 0.0067/step.
- **pure-hold survival (no-DR):** **0.0%** (vs baseline 91.6%) — median time-to-floor **2.74 s**. Still a vertical sink.
- **DR-on:** tilt 21.1°, survival 1.27% (open-loop-physics floored).

**Δ vs flagship (the vz value).** Removing vz **slows** the sink: median exit 1.70 s → **2.74 s**; no-DR speed 0.826 → 0.506 m/s; DR-on tilt 34.0° → 21.1°. So the vz channel — fed the honest ±1.5 m/s DC bias — is a **net aggravant**, the opposite of the closed-loop damping it was added for. But `_novz` **still sinks to 0%**, so vz is not the root cause.

**Verdict.** RED (contributes to the sweep's RED). Removing vz helps at the margin but does not recover hover; the honest-noise DR package (isolated by the `_noiseonly` sibling) is the root cause. Best-in-class attitude (0.69°) confirms the steeper well over-weighted attitude at altitude's expense.

**Lineage.** Tests hypothesis **shiny-mountain-6946**; ablation sibling of the flagship **muddy-hill-9397** (which holds the shared decode) and of `_noiseonly`. Baseline for the sink it re-introduces: **cold-night-8900**.