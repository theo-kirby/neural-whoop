---
node_id: 395342d7-21b4-5cfe-97cc-1b97f45f34ab
slug: orange-art-0247
title: 'Ablation _noiseonly (honest-noise DR ONLY, baseline reward, no vz): the decisive control — still sinks 0% clean survival, so the honest gyro-noise DR itself re-breaks the open-loop trim'
created_at: '2026-07-06T17:19:43.581627+00:00'
parents:
- shiny-mountain-6946
summary: 'The decisive control arm of the hover_blind_air65_v2 sweep (full decode in muddy-hill-9397). _noiseonly = honest per-channel noise+bias DR + obs_stack 3 + thrust 0.12 + latency 5, but the BASELINE reward (upright_sigma 0.5, smoothness 0.004) and obs-5 (no vz). 3.2B steps. Result: no-DR pure-hold 30 s survival 0.0% (vs baseline 91.6%), a vertical sink (median time-to-floor 3.98 s — the LONGEST of the three arms), no-DR tilt 1.96°, speed 0.366. Because it carries the baseline reward and no vz yet STILL sinks, this pins the root cause on the honest-noise DR package itself (2.5 rad/s gyro floor + ±1.5 m/s vz bias + wider thrust 0.12 + latency 5), NOT the reward steepening and NOT the vz channel (those only shorten the sink: _novz 2.74 s, flagship 1.70 s). DR-on survival 1.27%. This is the clean localization that makes the sweep''s RED interpretable: more DR is the wrong lever; blind IMU-only vertical hover needs the flow deck. Config hover_blind_air65_v2_noiseonly.yaml.'
origin:
  backend: flywheel
  node_id: 395342d7-21b4-5cfe-97cc-1b97f45f34ab
  slug: orange-art-0247
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
---
# _noiseonly: honest-noise DR with the BASELINE reward — the control that localizes the sink.

Sibling ablation in the `hover_blind_air65_v2` sweep; shared decode + RED verdict in **muddy-hill-9397** (flagship). This is the **decisive control**.

**What it isolates.** `_noiseonly` = honest per-channel `obs_noise_std_channels` (gyro 2.5 rad/s) + `obs_bias_channels`, obs_stack 3, thrust_scale_frac 0.12, action_latency 5 — but with the **baseline reward** (upright_sigma 0.5, smoothness 0.004) and **no vz** (obs-5). 3.2B steps. It strips BOTH the reward steepening and the vz channel from the flagship, leaving only the noise-hardening DR package. `_novz − _noiseonly` = the value of the reward steepening; `_noiseonly` vs the baseline = the value of noise-hardening.

**Results (deterministic 2048×1500).**
- **no-DR:** tilt 1.96°, speed 0.366 m/s, pos_err 0.839, crash 0.0046/step.
- **pure-hold survival (no-DR):** **0.0%** (vs baseline 91.6%) — median time-to-floor **3.98 s**, the longest of the three arms (baseline reward sinks slowest).
- **DR-on:** tilt 19.2°, survival 1.27%.

**Why this is decisive.** `_noiseonly` keeps the baseline reward and drops vz, yet **still sinks to 0% clean survival**. So neither the reward steepening nor the vz channel is the root cause — the **honest-noise DR package itself re-breaks the open-loop vertical trim** the baseline (cold-night-8900) had solved. The reward steepening (`_novz`, exit 2.74 s) and the vz channel (flagship, 1.70 s) only *shorten* the sink from this arm's 3.98 s.

**Verdict.** RED (the control that grounds the sweep's RED). The measured 2.5 rad/s gyro floor drowns the fine open-loop thrust trim: under it, PPO can't converge the deterministic trim (and, cross-eval, even the un-hardened baseline collapses DR-on to 0.4%). Conclusion: more DR is the wrong lever for blind hover; closed-loop velocity from the flow deck (Stage-1 of bitter-fire-0679) is the path.

**Lineage.** Tests hypothesis **shiny-mountain-6946**; ablation sibling of the flagship **muddy-hill-9397** (shared decode) and `_novz`. Isolates the noise-hardening lever against baseline **cold-night-8900**.