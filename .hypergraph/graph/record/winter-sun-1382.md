---
node_id: ff881809-9b7d-5ee7-bb4e-1675f4de75ce
slug: winter-sun-1382
title: 'gate_race baseline: PPO over batched DiffAero whoop reaches near-oracle lap time'
created_at: '2026-06-26T09:11:17.412355+00:00'
parents:
- jolly-paper-6314
summary: 'First empirical node (start of the frontier). Hypothesis: torch-native PPO over the batched DiffAero whoop env learns time-optimal gate racing near the speed oracle. Verdict: GREEN. 40M steps in ~90s on the RTX 5090 (4096 envs, ~444k env-steps/s); ep-return -12 -> +85; DR-off eval best lap 3.87s vs 3.47s oracle (~11% off optimal), 91% lap-completion, ~0 crashes; ~5.4k-param actor; ONNX round-trips at 3.6e-7.'
origin:
  backend: flywheel
  node_id: ff881809-9b7d-5ee7-bb4e-1675f4de75ce
  slug: winter-sun-1382
  revision: 25
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: bd8c2c87-7f2e-5f1b-b24b-d1bf0d904421
  slug: tiny-flower-3383
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: 45838583a7cbb61b499086c6a37a56266bdbff6649258bed9e38d1ae3a903a79
---
# gate_race baseline (empirical node)

## Hypothesis
A torch-native PPO loop over the batched, GPU-resident DiffAero whoop env (obs-v4 + next-gate lookahead -> act-v2 CTBR, full sim2real DR seam) learns single-drone time-optimal gate racing at a lap time close to the point-mass speed oracle, with a tiny export-clean policy.

## Setup
- Config: configs/gate_race.yaml; task gate_race (5 gates, episode_len 600 @ dt=0.02s); n_envs 4096; commit 1394e9a.
- Substrate: vendored DiffAero QuadrotorModel (RK4, drag/inertia/gyroscopic, CTBR RateController), whoop-scale params (~32 g), airframe + seam DR (wind / rate-gain / thrust / latency / obs-noise). Detector noise OFF (state-based beachhead).
- Algo: PPO, num_steps 24, lr 3e-4, gamma 0.99, lambda 0.95, 4 epochs, 8 minibatches, clip 0.2, KL target 0.03; GAE with time-limit (truncation) value bootstrap, crashes not bootstrapped. Actor = TinyPolicy (2x64 tanh, output none) ~5380 params + small critic.
- Hardware: 1x RTX 5090 (32 GB, sm_120), torch 2.11.0+cu128. LOCAL only.

## Result (verdict: GREEN / improved over random init)
- Training: ~40M env steps in ~90 s (~444k env-steps/s end-to-end). Episodic return -12 -> +85; lap times appear and fall as laps start completing; KL stable ~0.003.
- Eval (DR OFF, 2048 envs x 1500 steps, deterministic): best_lap 3.868s, last_lap 3.875s, oracle_lap 3.475s (within ~11%); laps_completed_mean 0.93; lap_completion_rate 0.908; crash_rate_per_step 8.6e-5; gates_passed_total 73746.
- Export: TorchScript + ONNX deploy policy round-trips (max abs diff 3.6e-7); ~5.4k-param actor, MCU-deployable.

## Interpretation
The substrate + env + PPO stack is sound and fast; a tiny policy flies procedurally-randomized gate courses near time-optimal under domain randomization. This is the handoff/start node for the autonomous frontier. Two genuine numerical bugs were fixed to get here (asin NaN in DiffAero quaternion_to_euler; missing state-bound saturation under the whoop's tiny inertia) -- see CLAUDE.md / NEURAL_WHOOP_FORK.md.

## Reproduce
uv run python scripts/env_check.py; uv run python scripts/train.py --config configs/gate_race.yaml --tensorboard; python scripts/eval.py --config configs/gate_race.yaml --from runs/gate_race_baseline/ckpt_final.pt --no-dr --export

## Artifacts
Attached: eval.json (lap-time metrics), TensorBoard event file (training curves), policy.onnx (deployable). See node artifacts.

## Next (frontier)
Better speed oracle (accel/turn-limited), racing-line reward, curriculum, SHAC vs PPO, n_envs scaling, then the next catalog task. See control node + AGENTS.md.