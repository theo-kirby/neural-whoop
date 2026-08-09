---
node_id: 529e526d-7efd-58a4-8da4-abf9b85dc7f6
slug: loyal-grove-4659
title: Training, evaluation and the export path to a deployable policy
created_at: '2026-08-09T18:42:31+00:00'
parents:
- dusty-pine-0511
summary: Torch-native PPO over the batched env, deterministic eval, and TorchScript / ONNX / dependency-free C export. Working, with a measured C-export budget of 79.3 KB flash and 1.0 KB RAM. Carries the clipped-Gaussian deployment-bias finding.
---
Status: working

## Current

`training/ppo.py` is a torch-native PPO over the batched env (GAE with time-limit
bootstrap, TensorBoard, checkpoints); `eval/rollout.py` does deterministic rollout
plus per-task metrics; `training/export.py` emits TorchScript and ONNX. Policies are
kept tiny and export-clean on purpose — the racing actor is about 5.4 k parameters
and the shipped hover policy 23.3 k [rec: white-rice-3299].

The C export path is measured rather than projected: the real `gate_race_air65`
policy exports to dependency-free C with 4.8e-7 parity, needs 79.3 KB flash and
1.0 KB RAM on a Cortex-M4, and projects about 0.55 ms per inference on the Air65 II's
own STM32G473 [rec: sparkling-shadow-2507].

The optimiser is a live variable rather than a settled one. Muon at lr 2.5e-3 took
best lap 3.203 to 2.461 s (-23%) but cost 6.6 points of completion
[rec: black-silence-5752]; that collapse turned out to be an interaction with
offboard action latency, and under the onboard split Muon is both faster and more
robust [rec: muddy-mouse-2952].

## Negative knowledge

- [scope: any open-loop channel level learned through clamped Gaussian exploration | confidence: high | evidence: throbbing-firefly-2363] PPO optimises the *sampled* policy, so a clamp at the action bound raises the effective sampled mean above the deterministic one. On the blind-hover policy the deterministic thrust trim came out 12% below hover and a pure-hold spawn sank. The fix is to output the closed-form effective mean E[clip(N(mu,sigma))] on every deterministic path; that alone took 30 s pure-hold survival from 0% to 57% with no retraining. A parent task with velocity feedback masks the same bias entirely.
- [scope: the PPO exploration knob on gate_race | confidence: high | evidence: square-cake-5756] An ent_coef sweep is RED / no-effect: the remaining lap-time headroom is a control limit, not an exploration one.
- [scope: importing PufferLib's obs encoding | confidence: high | evidence: wild-bird-1554] Dual-scale tanh target encoding regressed best lap 3.203 to 3.990 s, +25% — RED for racing.

## Provenance

- sparkling-shadow-2507 — the measured C-export flash, RAM and inference budget
- throbbing-firefly-2363 — the clipped-Gaussian effective-mean fix and its measured effect
- black-silence-5752 — the Muon speed win and its completion cost
- muddy-mouse-2952 — Muon's DR collapse localised to action latency, and the 3-seed recipe
- square-cake-5756 — the exploration lever, refuted
- wild-bird-1554 — the imported encoding, refuted
