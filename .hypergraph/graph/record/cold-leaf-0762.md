---
node_id: e2567af4-444b-590d-9333-2061b3f9bcd1
slug: cold-leaf-0762
title: 'acro_flip_pitch: the roll→pitch axis ablation — a forward loop emerges just as cleanly (flip_success 0.840 vs roll 0.845, GREEN)'
created_at: '2026-07-12T14:36:29.885520+00:00'
parents:
- shiny-violet-1747
- billowing-paper-5404
summary: 'roll→pitch axis flip: the clean single-factor axis ablation of shiny-violet-1747 (axis roll→pitch, the reward now integrates body-rate q; obs/reward/DR/whoop/ppo otherwise identical). flip_success_rate 0.840 vs roll 0.845 (−0.005, statistically flat), crash_rate 0.000, post_recovery_tilt 4.0°, mean_completion 0.58 s. Deterministic no-DR eval: flip_success 0.835, rotation_frac 0.921, altitude_loss 0.12 m. Verdict GREEN: the task is genuinely axis-parameterized — a pitch loop is discovered by reward shaping as reliably as the roll barrel roll, on the same obs-7/act-v2 contract with zero code change (config-only). Both axes are now trained + JSON-exported for the pilot flip harness.'
origin:
  backend: flywheel
  node_id: e2567af4-444b-590d-9333-2061b3f9bcd1
  slug: cold-leaf-0762
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: ed71a880-cafd-545c-b541-e53d8032e97f
  slug: gentle-frog-6607
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: c0a613e8fe1f71d677462e4a0b99e21eb2d96b624b6c01374b0d976c354497bd
---
# acro_flip_pitch — the roll→pitch axis ablation

**Hypothesis.** `acro_flip` is genuinely *axis-parameterized*, not roll-specific: flip a single factor (maneuver axis roll→pitch — so the reward integrates body-rate `q` instead of `p`, a forward/back loop instead of a barrel roll) and the same tiny policy discovers the pitch maneuver by reward shaping alone, as reliably as roll, with no code change.

**Setup.**
- Config `configs/acro_flip_pitch.yaml` — **one factor** vs `configs/acro_flip.yaml`: `axis: pitch`. obs (obs-7 `[gravity_body(3), p, q, r, rotation_remaining]`), reward (rotation-progress + completion bonus + gated recover + privileged altitude-keep − smoothness − crash), DR (per-channel IMU noise/bias incl. gravity_body, action_latency 2), whoop band (~30 g), and PPO ([64,64] tanh, 400M steps, n_envs 8192, lr 3e-4, target_kl 0.03) are **byte-identical** to roll. No env/dynamics/contract change.
- ~976k sps, ~7 min wall on the RTX 5090. Milestone-0 env_check GREEN first.

**Results.**
- Training (final, DR-on): flip_success_rate **0.840**, post_recovery_tilt **4.6°**, ep_ret 92.8, mean_completion_time 0.591 s, crash_rate **0.000**, KL ~0.
- Deterministic **no-DR** eval (2048 drones, 1500 steps): flip_success_rate **0.835**, post_recovery_tilt **4.0°**, mean_completion_time 0.578 s, rotation_frac **0.921**, altitude_loss 0.12 m, crash_rate_per_step **0.000**.
- Full standard visual pack built + baselined against roll (`--baseline runs/acro_flip/replay.json.gz`); `comparison.png` overlays pitch vs the roll barrel roll.
- JSON deploy weights exported (`policy_weights.json`, obs_dim 7, base_obs_dim 7) — feeds the pilot flip harness (`--axis pitch`).

**Δ vs parent.** flip_success_rate **0.840 (pitch) vs 0.845 (roll)** = **−0.005**, i.e. statistically flat; crash 0.000 both; altitude_loss slightly higher (0.12 vs 0.10 m — a forward loop dumps marginally more height than a barrel roll, expected). The axes are equivalent to within seed noise.

**Verdict / Honesty.** **GREEN.** The one-factor ablation confirms the task is axis-parameterized: a pitch loop is as learnable as a roll roll from pure reward shaping, config-only. Honest caveats inherited from roll: (1) single-rotation, `success_tilt_deg=15°` — the easy end of acro; multi-rotation and yaw untested. (2) ~16% miss the success gate (tail uncharacterized). (3) A new-axis capability, so the metric stands on its own; the only Δ that matters is *vs roll*, and it's flat — which is the whole point of an ablation.

**Lineage.** Parents: **shiny-violet-1747** (the roll `acro_flip` GREEN this is the direct axis ablation of — it explicitly flagged 'pitch variant config exists, unrun' as the next hop) and **billowing-paper-5404** (the idea that blind acro is shippable now: train both axes + build the pilot harness — this is the training half). Sibling of the pilot flip harness node (the deploy half). Stays in **cluster:agility**.