---
node_id: a410560a-6f62-58cc-8d1f-36871eec41f1
slug: long-fog-2207
title: 'System comparison: PufferLib drone (tensaur) vs neural-whoop — architecture, sim2real, transferable ideas'
created_at: '2026-07-02T09:09:29.438748+00:00'
parents:
- icy-feather-6323
- lively-dawn-5118
summary: 'Deep-dive of PufferLib''s drone stack vs ours: end-to-end per-motor-RPM actions (no rate loop, motor lag modeled), 21-d non-heading-invariant obs with dual-scale tanh target encoding, fused CUDA PPO (V-trace-clipped GAE + prioritized replay + Muon, 15× our SPS), thin ±5% DR, and a PROVEN onboard-LSTM Crazyflie sim2real path. 9 concrete idea imports ranked (obs encoding, trainer tricks, recurrent system-ID, sweep harness); our edge stays robustness-DR, swarm coupling, lap-time rigor, visual contract.'
origin:
  backend: flywheel
  node_id: a410560a-6f62-58cc-8d1f-36871eec41f1
  slug: long-fog-2207
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 8dca4cf0-2c9c-51fa-b2d1-e21474948e57
  slug: polished-block-1621
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: e1b65887d716f0692f40b54696d0d5ee54848f8bb480c67a23f2d972d8fe4959
---
## Hypothesis
Framing/analysis node — what does the closest open competitor system do differently, and which of their choices should flow into neural-whoop?

## Setup
Source-level deep-dive of PufferLib 4.0's Ocean `drone` env (`ocean/drone/*`, ~1.5k lines C), its trainer (`src/pufferlib.cu`, `pufferlib/torch_pufferl.py`), and the upstream tensaur/drone project (Sam Turner & Finlay Sanders): the Crazyflie out-of-tree firmware controller, the sim2real video, and their summit-26 lessons deck. Evidence run = parent measurement node (6.4M SPS on our 5090). Full document: docs/COMPARISON_PUFFERLIB.md @ 58e2dc9 (also attached).

## Results — what they do differently (condensed)
- **Actions**: per-motor target RPMs (end-to-end, NO inner rate loop), mapped so action 0 = hover; first-order motor lag (k_mot 0.15 s) modeled. vs our act-v2 CTBR through DiffAero's rate controller.
- **Obs (21-d)**: body-frame vel/rates + FULL world quaternion (not heading-invariant, unlike obs-v4) + body-frame target vector encoded at TWO tanh scales (coarse ±10 m + fine ±10 cm) + ring normal + task one-hot.
- **Sim**: CPU SIMD C (8 float lanes, SoA), RK4 500 Hz ×5 substeps → 100 Hz control, Crazyflie 2.1 params (27 g — our weight class), per-substep vel/ω clamping (they hit the same RK4 instability we fixed in whoop.py). No wind / no obs noise / no latency; DR = flat ±5% on all params.
- **Tasks**: multi-task single policy via one-hot — hover + race (10 random rings, rings-passed metric, +2.45/ring + delta-distance shaping) + static formation slots (sphere/cube/flag — no inter-drone physics).
- **Trainer**: whole PPO loop fused in C++/CUDA — 'puff advantage' (GAE with V-trace ρ/c clipping), advantage-prioritized minibatches, replay_ratio 2.25, Muon optimizer, 26.2K-param 64×2 GELU MLP; every hyper machine-tuned by their gpytorch Pareto sweep with priors declared in drone.ini.
- **Sim2real (PROVEN)**: LSTM policy runs ONBOARD the Crazyflie's 168 MHz Cortex-M4 at 100 Hz (pure-C puffernet, weights bin2h-compiled into firmware), obs from Flow-Deck+IMU Kalman estimator, direct motor writes at 1 kHz, ground-station param toggles RL↔PID as failsafe. Their deck: 3 months of failed transfer; what mattered = rotor spin directions, exact control-frequency match, coordinate frames; LSTM memory as implicit system-ID on top of DR.

## Better / worse (for our purposes)
They win: wall-clock iteration (~15× measured), proven MCU deploy path, sweep discipline, trainer sample-reuse tricks. We win: robustness DR (wind/latency/obs-noise — they have none; our offboard link forces latency modeling), heading-invariant contract, real swarm coupling (their formations are independent agents at static slots), lap-time rigor + course authoring + curriculum, the visual contract (they have only a live raylib viewer), differentiable dynamics option, camera-perception door.

## Verdict / idea flow (each → candidate follow-up node)
1. Dual-scale tanh target encoding → obs-v5 EXPERIMENT (gate precision at range).
2. puff-advantage (V-trace-clipped GAE) + advantage-prioritized minibatches + replay_ratio≈2 in our torch PPO → EXPERIMENT (candidate 1.5–3× wall-clock-to-quality).
3. Muon on TinyPolicy → cheap EXPERIMENT.
4. Tiny recurrent core (minGRU) as implicit system-ID under DR → HYPOTHESIS (they prove MCU-deployable; free for our offboard host).
5. Bounded hover-score reward shape → EXPERIMENT for hover/follow.
6. Sweep harness with declared priors in config → METHOD for the autonomy loop.
7. Motor-lag (k_mot) modeling/DR → CHECK what DiffAero's motor model does; add if absent.
8. Control-frequency match discipline → CHECK/pin our offboard loop rate in docs/CONTRACT.md.
9. Hover-centered action mapping + per-substep state clamping → already ours; independent confirmation.
Honesty: their thin-DR success does NOT refute our heavier DR — they compensate with onboard low-latency inference + memory; our offboard architecture cannot.

## Lineage
Child of the control node (icy-feather-6323, run contract) and the 5090 measurement node (lively-dawn-5118, evidence). References: github.com/PufferAI/PufferLib @ 7b11311; github.com/tensaur/drone (firmware + summit-26.pdf lessons deck); Eschmann et al. 'Learning to Fly in Seconds' / RAPTOR; Kaufmann et al. champion racing. Related clusters: reliability-dr (DR philosophy contrast), capacity-budget (26.2K-param evidence), deploy-hw (onboard C inference path).