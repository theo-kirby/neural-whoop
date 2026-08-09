---
node_id: 28f08813-f6c3-5d0e-8449-820d902be36d
slug: still-bird-0492
title: 'hover_blind_air65: attitude solved (1.14° tilt) but deterministic thrust trim 12% low — clipped-Gaussian exploration bias; one-scalar trim rescues pure-hold 30 s survival 0→100% (no-DR)'
created_at: '2026-07-05T13:50:16.389112+00:00'
parents:
- icy-flower-1085
- young-fire-2086
summary: 'hover_blind (IMU-only obs [roll,pitch,p,q,r], the no-flow-deck first-flight task) trained 40M steps on the hover_air65_bridge recipe with tight thrust(±5%)/mass(28–32 g) DR: attitude is solved (no-DR mean tilt 1.14° vs parent''s 2.7° with velocity obs) but the deterministic checkpoint SINKS — pure-hold spawns floor-exit in median 4.0 s, 100% within 10 s (no-DR). Localized: deterministic mean act[0] −0.562 vs analytic hover −0.500 (thrust 12% low; constant hover action holds Δz=0.000, so dynamics/mapping are unbiased). Cause arithmetically confirmed as clipped-Gaussian exploration bias: with final thrust σ=0.478, E[clip(N(−0.562,0.478))] = −0.515 ≈ hover — PPO optimized the sampled policy, deterministic deployment strips the clamp''s effective thrust. One scalar trim (+0.0616 on act[0], zeroing v_z at nominal) takes pure-hold 30 s survival 0%→100% no-DR; +0.0463 (exactly the E[clip] gap) recovers most of it, confirming mechanism. No constant trim survives full DR (≤9% @30 s — open-loop physics), so deployment MUST bench-calibrate thrust trim around the measured ~1410 µs hover throttle; exported policy.pt/onnx carry the raw biased trim. Mixed verdict (attitude GREEN / raw trim refuted / rescue validated) — no outcome tag. Follow-ups: tanh-squashed action head or E[clip] correction at export. Commits 61e5a2e (task+config), 407acf9 (docs: SIM2REAL Stage 0.5).'
origin:
  backend: flywheel
  node_id: 28f08813-f6c3-5d0e-8449-820d902be36d
  slug: still-bird-0492
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: a362e244-5c0f-5979-9cf0-975fb48aeb76
  slug: restless-wave-9912
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: c375760eed7ca8fbeee1bad64864ebcc0cdf3e1df22f0a345c85e2ed3d97a7df
---
# hover_blind_air65: IMU-only hover training + the deterministic-trim discovery

**Hypothesis** (from the task design, commit `61e5a2e`): with obs = `[roll, pitch, p, q, r]` only — exactly what MSP_ATTITUDE + MSP_RAW_IMU provide over the WiFi bridge today, no flow deck — PPO can learn (a) tight attitude stabilization and (b) a precise open-loop hover-thrust trim in expectation across tight thrust/mass DR: enough for a level, slowly-drifting tethered first flight "good for tens of seconds".

**Setup.** `configs/hover_blind_air65.yaml` = fork of `hover_air65_bridge.yaml` changing: task → `hover_blind` (obs 5, pure observation ablation of `hover`); reward rebalanced for partial observability (upright dominant, vel damping ↑, smoothness ×4, pos terms kept to shape the trim); DR tightened where blindness demands calibration (`thrust_scale_frac` 0.05 anchored at the bench-measured hover ~1410 µs @ 3.6–3.7 V; mass 28–32 g; wind 1.0; 0–60 ms lumped action latency; impulse seam kept); `hold_fraction` 0.5. 40M steps, 4096 envs, [64,64] tanh, ~512k sps (~80 s wall on the 5090). Commits: `61e5a2e` (task+config), `407acf9` (docs + findings).

**Results.**
- Standard deterministic eval (2048 drones × 1500 steps) — no-DR: tilt **1.14°** / speed 0.37 m/s / pos_err 0.83 m / hold 0.19 / crash 0.47 %/step; DR-on: tilt 12.6° / hold 0.18 / crash 0.49 %/step. (Parent bridge s2 no-DR with velocity obs: tilt 2.7°, crash 0.00.)
- **Survival probe** (pure-hold spawns — at rest, level, on setpoint — the actual first-flight scenario): **100% floor exits, median 4.0 s no-DR**, every exit at z→0.15. The policy sinks at a steady ~0.35 m/s.
- **Localization:** a constant analytic hover action (DiffAero thrust 1.0 == act[0] −0.500) holds altitude exactly (Δz +0.000 over 3 s) → dynamics + `action_to_diffaero` mapping unbiased. The policy's deterministic mean is act[0] **−0.562 → thrust 0.877, 12% under hover**.
- **Cause, arithmetically confirmed — clipped-Gaussian exploration bias:** final thrust-channel log_std −0.739 (σ=0.478); E[clip(N(−0.562, 0.478), −1, 1)] = **−0.515 ≈ hover −0.500**. PPO optimized the *sampled* policy — the clamp at −1 truncates the low tail and adds effective thrust; deterministic deployment strips the noise and reveals the low mean. `hover`/`hover_air65_bridge` mask the identical bias via velocity feedback; blind hover exposes it because trim is open-loop.
- **Fix probe** (deterministic offset on act[0]): **+0.0616** (zeroes v_z at nominal) → pure-hold 30 s survival **0% → 100% no-DR** (zero exits). +0.0463 (exactly the E[clip] gap) → 59% @30 s — most of the effect, independently confirming the mechanism. DR-on stays ≤9% @30 s under ANY constant trim — open-loop altitude cannot beat ±5% thrust × ±7% mass; that is physics, not a defect, and is exactly why the bench hover-throttle anchor exists.

**Verdict.** Mixed — deliberately no outcome tag. Attitude objective: confirmed (1.14° clean; tumble-recovery cohort trained). Precise-trim-by-expectation: refuted **as deterministically deployed** — a systematic, now-understood bias, not noise. The first flight remains viable: this checkpoint + a **mandatory bench thrust-trim calibration** (trim until commanded hover matches true hover around the ~1410 µs anchor) is the deployment recipe. Docs updated: SIM2REAL **Stage 0.5**, TASK_CATALOG baseline entry (`407acf9`).

**Honesty.**
- The trim bias is generic and transferable: any action channel whose absolute level matters open-loop is biased at deterministic deployment when trained with clamped Gaussian exploration. Training-side fixes to evaluate next: tanh-squashed action head (the `gate_race_air65_dstanh` precedent) or a per-channel effective-mean correction E[clip(N(μ,σ))] applied at export.
- The task docstring's "good for tens of seconds" was optimistic even post-trim under DR (median ~7 s) — on the real drone the bench trim collapses the thrust_scale axis, but battery-sag thrust drift over a flight remains the open risk.
- The standard eval's crash %/step mixes recovery-cohort spawns with pure hold; the survival probe is the honest first-flight number. The exported `policy.pt`/`policy.onnx` carry the biased raw trim — do not deploy without the trim step.

**Artifacts.** Standard visual pack (no-DR hero rollout vs `hover_air65_bridge` s0 baseline replay): replay.json.gz, trajectory.png, fpv_00/01.png, training_curves.png, comparison.png, table.csv, run.json, eval.json + hero MP4 (nw-viz composite). Probe evidence: probe_results.txt + the two probe scripts (run from repo root).

**Lineage.** Recipe parent: `hover_air65_bridge` **icy-flower-1085** (1:1 config fork, same 40M/[64,64] recipe — this is its observation ablation). Enabler parent: xiao_bridge WiFi MSP link **young-fire-2086** (its ATTITUDE+RAW_IMU telemetry defines the obs contract; its bench ladder measured the hover-throttle anchor and latency band — commits `da0e37a`, `15848e5`, `b5f875b`). Executes the branch-B no-flow-deck first-flight step of the sim2real plan (bitter-fire-0679).