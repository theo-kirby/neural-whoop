---
node_id: f4beb2f9-1ad1-596c-941b-e5c057021be1
slug: shiny-violet-1747
title: 'acro_flip (NEW task, first agility): a single barrel roll emerges from pure reward-shaped discovery — 83% flip success, 2.8° recovery, 0 crashes (GREEN)'
created_at: '2026-07-08T08:07:38.891892+00:00'
parents:
- jolly-pine-3330
- old-violet-0574
summary: 'acro_flip, the lab''s first AGILITY task and a new cluster — no metric-vs-parent because it''s a new capability, not a tuning delta. A single-axis (roll) 360° barrel roll emerges from reward-shaped discovery alone (no reference trajectory), IMU-only obs (obs=7: gravity_body + gyro + rotation_remaining), on the existing act-v2 CTBR contract with zero env/dynamics changes. 400M steps (~7 min @ 985k sps on the 5090). Deterministic no-DR eval: flip_success_rate 0.828, post_recovery_tilt 2.76°, rotation_frac 0.922, altitude_loss 0.10 m, crash_rate 0.000. Trains UNDER DR that corrupts the gravity_body attitude estimate mid-flip (the key acro sim2real risk). Verdict: GREEN — the trick is real, clean, and recovers to level.'
origin:
  backend: flywheel
  node_id: f4beb2f9-1ad1-596c-941b-e5c057021be1
  slug: shiny-violet-1747
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# acro_flip — the first agility task (single barrel roll)

**Hypothesis.** A tiny MLP policy can discover an acro maneuver (a full 360° barrel roll about the body roll axis, then recover to level) from **reward shaping alone** — no reference trajectory, no new hardware, no contract change — using only IMU-derivable observations, and survive DR that corrupts the attitude estimate mid-rotation (the real acro sim2real risk: a fast spin confuses the complementary/Mahony filter).

**Setup.**
- Task: `acro_flip` (new, `src/neural_whoop/tasks/acro_flip.py`, shipped code-only in commit `7aac805`; this is its first real run). Config `configs/acro_flip.yaml`.
- obs=7, IMU-only & deploy-honest: `gravity_body(3) + gyro pqr(3) + rotation_remaining(1)`. Reward = monotone/saturating rotation-progress toward Φ=2π·n_rotations + one-time completion bonus (10) + gated recover (upright bell − spin penalty) + privileged altitude-keep − smoothness − crash (10).
- act-v2 CTBR, unchanged. axis=roll, n_rotations=1.0, episode_len=200.
- PPO: [64,64] tanh, 400M steps, n_envs=8192, num_steps=24, lr 3e-4, target_kl 0.03. ~985k sps, ~7 min wall on the RTX 5090.
- DR ON, incl. per-channel IMU noise/bias — crucially noise+bias on the `gravity_body` channels to model the mid-flip attitude-estimate degradation; gyro stays low-noise (reliable through acro rates); `rotation_remaining` is a clean pilot-clock signal. Airframe/DR band inherited from d50var_s8 (~30 g AUW).
- 13 unit tests (`tests/test_acro_flip.py`) pass on the real torch/5090 stack before the run.

**Results.**
- Training (final, DR-on): flip_success_rate **0.845**, post_recovery_tilt **3.5°**, ep_ret 96.2, crash_rate 0.000, KL ~0. Learning curve is monotone from step 0 (ep_ret −0.03 → 96; tilt 91° → 3.5°) — the recovery term engages cleanly, no reward-hacking signature.
- Deterministic **no-DR** eval (2048 drones, 1500 steps): flip_success_rate **0.828**, post_recovery_tilt **2.76°**, mean_completion_time 0.56 s, rotation_frac **0.922**, altitude_loss 0.10 m, crash_rate_per_step **0.000**.
- TorchScript + ONNX exported (round-trip max diff 1.8e-7) — export-clean for the microcontroller.

**Verdict / Honesty.** **GREEN.** The barrel roll is a genuine emergent trick: >82% of drones complete a full rotation and recover to within a few degrees of level, zero crashes, under DR that degrades the very attitude signal the recovery depends on. Caveats to keep honest: (1) success threshold is `success_tilt_deg=15°` on a single roll rotation — the easiest acro; multi-rotation and pitch/yaw axes are untested here (pitch variant config exists, unrun). (2) ~17% don't hit the success gate; the tail is not yet characterized (likely altitude-loss / incomplete recovery), a future measurement. (3) This is a NEW capability, so there is no parent metric to beat — the number stands on its own, not as a Δ.

**Lineage.** Parents: **hover_blind_air65_long (3.2B)** — the IMU-only, deploy-honest obs philosophy (gravity_body + gyro) and the flagship step-budget this run is sized against (400M = a fast first read vs the 3.2B hover flagship); and **d50var** — the per-episode amplitude DR + the ~30 g airframe/IMU-noise band (d50var_s8) this config inherits. Opens the new **cluster:agility** workstream. Next: multi-rotation, pitch/yaw axes, and a Studio hero-MP4 of the roll.