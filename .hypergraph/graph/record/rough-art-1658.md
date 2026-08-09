---
node_id: 4fc89bf0-e979-54de-b4c4-3e3c34c4fed7
slug: rough-art-1658
title: 'R4 (H2 privileged vz + thrust-constancy reward) RED closes the ladder: hold time triples to 12.8 s but survival stays 0% — the attributable cause of the v2 sink is the honest gyro-noise AMPLITUDE itself; baseline remains flagship'
created_at: '2026-07-06T21:09:11.844370+00:00'
parents:
- quiet-bonus-7296
- spring-violet-3051
summary: 'R4 (configs/hover_blind_air65_r4.yaml, commit 856457d) = R3 + H2 privileged decoupling reward: vz_penalty 0.5 on ground-truth |vz| + thrust_const_penalty 0.1 on (Δthrust)² (new HoverConfig fields, default-off, unit-tested; single unswept weight point). Result: M1 clean-trim survival still 0.0% but median time-to-floor 12.84 s — the ladder''s monotone progression (R1 white 2.96 → R3 colored 5.18 → R4 +H2 12.84 s; sink rate 0.48→0.28→0.15 m/s) shows each lever attacks its mechanism yet none reaches the 30 s horizon. The trade is real: DR-on tilt collapsed to 40° (worst of the ladder) and M2 fell to 0.9% colored / 0.0% white — the constancy/vz penalties fight disturbance rejection. LADDER CLOSED: H3 (R1), H1 (R3), H2 (R4) all RED, so the attributable cause of the v2 sink is the honest gyro-noise AMPLITUDE itself (2.5 rad/s ≈ 143°/s SD) — under it PPO cannot converge a deployable open-loop hover trim in this recipe, regardless of trim DR, modeled spectrum, or privileged shaping. The v2 strategic conclusion (IMU-only open-loop altitude cannot survive the real sensor floor; flow-deck velocity is the path) stands with corrected attribution. hover_blind_air65_long (cold-night-8900) remains the flagship: 91.6% clean, 0.1% honest-noise M2 — fragility now quantified. rho still modeled/unvalidated; H2 weights unswept — both flagged.'
origin:
  backend: flywheel
  node_id: 4fc89bf0-e979-54de-b4c4-3e3c34c4fed7
  slug: rough-art-1658
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# R4: the last pre-authorized lever — privileged decoupling reward on top of the colored-noise arm. RED, and the ladder is closed.

**Hypothesis tested (quiet-bonus-7296, H2).** Give PPO a ground-truth training signal against the sink (−k·|vz|) and decouple the throttle from gyro jitter (−k·(a_t[0]−a_{t−1}[0])²) — privileged reward shaping, deployed obs unchanged. **Refuted at the tested weights.**

**Setup.** `configs/hover_blind_air65_r4.yaml` (commit 856457d) = R3 + `vz_penalty 0.5`, `thrust_const_penalty 0.1` (new `HoverConfig` fields, default 0.0 — existing rewards bit-identical, unit-tested). Weights are a **single unswept point**. Colored honest noise (ρ 0.9/0.8, modeled), trim poisons off, obs_stack 3, latency 5, 3.2B steps.

**Results (30 s pure-hold survival, 2048 drones).**

| metric | R4 | R3 | R1 | bar |
|---|---|---|---|---|
| **M1** clean-trim no-DR | **0.0%** (exit **12.84 s**) | 0.0% (5.18 s) | 0.0% (2.96 s) | ✖ |
| **M2** colored / white | 0.9% / 0.0% | 3.2% / 0.0% | — / 4.0% | ✖ |
| **M4** full-DR | 1.0% | 3.1% | 4.2% | report-only |

Deterministic eval: no-DR tilt 1.94°, **sink rate 0.146 m/s** (vs R3 0.276, R1 0.480); DR-on tilt **40.0°**, speed 1.26 — the worst DR-on attitude of the ladder.

**Ladder progression (the one clean quantitative story).** Median no-DR time-to-floor: `_noiseonly` 3.98 → R1 2.96 → R3 **5.18** → R4 **12.84 s**; sink rate 0.48 → 0.28 → 0.15 m/s. Each lever attacks the sink mechanism it targets and roughly doubles the hold — and none reaches the 30 s horizon, so survival stays exactly 0%.

**Decode.**
- **H2 works on its mechanism and fails the metric:** the privileged |vz| gradient produced the slowest sink and longest hold on record for a noise-trained arm, but the residual trim error still integrates out within 13 s.
- **The trade is real:** thrust-constancy + vz penalties pulled reward mass off disturbance rejection — DR-on tilt collapsed to 40° (R3: 23.7°, R1: 16.0°). At these weights H2 is net-negative for a deployable policy even before the sink question.
- **Ladder closed — the attribution:** H3 (trim-poison DR, R1), H1 (white-vs-AR spectrum at modeled ρ, R3), H2 (privileged decoupling reward, R4) are all refuted. The attributable cause of the v2 RED is the **honest gyro-noise amplitude itself** (2.5 rad/s ≈ 143°/s SD): under it, PPO in this recipe ([64,64] tanh, 3.2B steps, obs-5×stack-3) cannot converge an open-loop hover trim that survives 30 s — with calibrated trim OR clean obs at eval.

**Verdict.** **RED.** The corrected final answer to "what sank v2": *the honest noise amplitude, not the trim DR (exonerated by R1), not the white spectrum (exonerated by R3 at modeled ρ), not the reward (H2 helps the sink but cannot close it and costs robustness).* The v2 sweep's strategic conclusion — IMU-only open-loop altitude does not survive the real sensor floor; real velocity feedback (flow deck, Stage-1 of bitter-fire-0679) is the path — **stands, now with clean attribution**. `hover_blind_air65_long` (cold-night-8900, 91.6% clean / 0.1% honest-noise M2) **remains the flagship**, with its honest-noise fragility now quantified and on the record.

**Honesty.**
- H2 weights unswept (single point 0.5/0.1); a sweep might trade better, but the DR-on attitude collapse suggests the lever direction is fundamentally at odds with disturbance rejection at meaningful strengths.
- ρ remains modeled/unvalidated; the monotone hold-time progression (2.96→5.18→12.84 s) hints that stacking measured-ρ noise + swept H2 + more capacity *might* eventually cross 30 s — recorded as a possible future branch, NOT a recommendation: the deploy-relevant M2 numbers got *worse* down the ladder (4.0→3.2→0.9%).
- All numbers deterministic mean, n=2048, seeds fixed; binomial ±~0.9%.

**Lineage.** Tests the H2 branch of **quiet-bonus-7296** (closing it — all three branches now RED); forks **spring-violet-3051** (R3). Reward seam commit 856457d.