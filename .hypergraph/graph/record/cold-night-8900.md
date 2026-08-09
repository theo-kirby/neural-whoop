---
node_id: aac3f7fa-c05c-5380-b824-5c23f938e62b
slug: cold-night-8900
title: 'hover_blind_air65_long (3.2B steps, 80× the 40M baseline): the trim-bias fix deployed — pure-hold 30 s survival 0→91% no-DR, thrust σ 0.478→0.032'
created_at: '2026-07-06T14:35:17.844727+00:00'
parents:
- still-bird-0492
summary: 'hover_blind trained 3.2B steps (80× the 40M trim-discovery run 28f08813) with the clipped-Gaussian effective-mean fix now applied at deterministic eval/export, and episode_len 500→1500 (30 s) so residual trim error integrates to floor exits WITHIN the episode and PPO gets a direct gradient against the sink. Result vs parent: the open-loop sink is solved — pure-hold 30 s survival 0%→91% no-DR (commit a4cf760), the thrust-channel log_std collapses σ 0.478→0.032 (the policy stops relying on the clamp''s effective-thrust bias and learns the true trim in the mean), and vz drift +0.01 m/s. Standard deterministic no-DR eval (2048 drones × 1500 steps): tilt 1.68°, speed 0.069 m/s, hold_rate 0.152, crash 7.4e-5/step — note this hold mixes the recovery-cohort spawns with pure hold, so the 91% survival probe is the honest first-flight number. Attitude stays tight (1.68°). Verdict GREEN on the trim fix; the deployable checkpoint no longer needs the deterministic-offset rescue the 40M run required (bench thrust-trim calibration remains the deploy gate under battery-sag drift). This is the direct baseline the 2026-07-06 hover_blind_air65_v2 three-way sweep forks from and cross-evals against. Commits 5c735cd (deploy the clipped-Gaussian effective mean), a4cf760 (docs + 3.2B run). Config configs/hover_blind_air65_long.yaml.'
origin:
  backend: flywheel
  node_id: aac3f7fa-c05c-5380-b824-5c23f938e62b
  slug: cold-night-8900
  revision: 4
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: bfa7f74e-74f9-55f9-84e3-5fbf51875c12
  slug: divine-cell-0538
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 6694fa58bbbbe130dfdfb428493d93d3af3dd6fde7eb91a6397c133dd5733a18
---
# hover_blind_air65_long: how far blind IMU-only hover gets at 80× the budget, with the trim-bias fix

**Hypothesis.** The 40M run (still-bird-0492) proved attitude is solvable but exposed a clipped-Gaussian exploration bias: the deterministic thrust trim sat 12% low (act[0] mean −0.562 vs hover −0.500), so the open-loop checkpoint sank (median 4.0 s to floor). Two changes should convert that mixed result into a deployable blind-hover policy: (1) apply the clipped-Gaussian **effective mean** E[clip(N(μ,σ))] at deterministic eval/export (training/ppo.py + export.py) so what deploys is what PPO actually optimized; (2) stretch episode_len 500→1500 (30 s) so residual trim error integrates to a floor exit *inside* the episode, handing PPO a direct gradient against the sink instead of leaving trim to open-loop luck. Everything else identical to hover_blind_air65 on purpose — this isolates budget + the trim fix.

**Setup.** `configs/hover_blind_air65_long.yaml` = fork of `hover_blind_air65.yaml` changing only: total_steps 40M→**3.2B**, n_envs 4096→8192 (~920k sps on the 5090, ~58 min), episode_len 500→1500. Same task `hover_blind` (obs-5 `[roll,pitch,p,q,r]`), same reward, same DR (thrust_scale_frac 0.05 anchored ~1410 µs, mass 28–32 g, wind 1.0, 0–60 ms lumped action latency, impulse seam on), same [64,64] tanh net. Commits: `5c735cd` (deploy the clipped-Gaussian effective mean — the trim-bias fix), `a4cf760` (docs + this run). git sha at pack build 5c735cd.

**Results.**
- **Survival probe** (pure-hold spawns — at rest, level, on setpoint — the real first-flight scenario): **30 s survival 0%→91% no-DR** (commit a4cf760). The sink the 40M checkpoint needed a +0.0616 deterministic offset to rescue is now learned in-policy.
- **Trim mechanism closed:** thrust-channel log_std collapses **σ 0.478→0.032** — with the effective-mean fix removing the incentive to lean on the clamp's truncated-tail thrust, PPO drives the sampled policy toward the deterministic one, and the mean converges to true hover. Residual vz drift +0.01 m/s.
- **Standard deterministic eval** (2048 drones × 1500 steps, no-DR): tilt **1.68°**, speed 0.069 m/s, pos_err 0.933 m, hold_rate 0.152, crash **7.4e-5/step** (vs the 40M run's 0.47%/step). Attitude stays tight.

**Δ vs parent (still-bird-0492).** Same recipe + 80× budget + the two trim changes: pure-hold survival 0%→91% (no-DR), crash-rate 0.47%→0.0074%/step, thrust σ 0.478→0.032. The 40M run's headline failure (open-loop sink) is resolved without any post-hoc trim offset.

**Verdict.** GREEN on the trim fix — blind IMU-only hover survives 30 s open-loop at 91% clean. The deployable `policy.pt`/`policy.onnx` now carry the *corrected* trim (unlike the 40M export, which shipped the biased raw mean). **Honesty:** (1) the standard-eval hold_rate 0.152 is low because it mixes the tumble-recovery spawn cohort with pure hold — the survival probe is the honest first-flight metric, and it is the 91%. (2) DR-on open-loop altitude still cannot beat ±5% thrust × ±7% mass over 30 s — that is physics, so bench thrust-trim calibration around the ~1410 µs hover anchor remains mandatory before flight, and battery-sag thrust drift over a real flight is the open risk. (3) obs is still IMU-only with no velocity feedback; vertical damping is entirely open-loop trim — the motivation for the v2 vz_est channel that forks from here.

**Lineage.** Recipe + trim-discovery parent: `hover_blind_air65` **still-bird-0492** (1:1 config fork, same [64,64]/DR; this deploys the fix for the exact bias that node localized). Executes the branch-B no-flow-deck first-flight step of the sim2real plan **bitter-fire-0679**. Child: the hover_blind_air65_v2 three-way sweep (vz channel + honest per-channel noise/bias DR + reward steepening) forks from this checkpoint and cross-evals against it.