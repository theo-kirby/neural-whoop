---
node_id: 217e8514-01c6-5f76-bb8e-36cdf70ef616
slug: lively-dawn-5118
title: 'PufferLib drone env on the 5090: install + full training run — 6.4M SPS, 88.6M steps in 14 s'
created_at: '2026-07-02T09:07:14.555938+00:00'
parents:
- icy-feather-6323
summary: 'Installed PufferLib 4.0 drone env on the 5090 (zig-cc + pip-nvcc toolchain workaround) and ran the stock 88.6M-step hover+race training: 6.4M SPS, done in ~14 s, race perf 0.876 (9.0/10 rings), hover EMA dist 4 cm — ~15× our torch PPO''s 437k SPS on the same GPU. GREEN measurement.'
origin:
  backend: flywheel
  node_id: 217e8514-01c6-5f76-bb8e-36cdf70ef616
  slug: lively-dawn-5118
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9b3078c1-f12c-563d-aab3-91a411845c16
  slug: fragrant-rice-1272
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: d1b89d19d5aeb13054d4e5f0b8ed2ac856ccd29bc57ab06187c09be47b66cf61
---
## Hypothesis
None — characterization. Install PufferLib 4.0's Ocean `drone` env locally and measure what its stack actually delivers on our hardware (RTX 5090), as evidence for the system comparison.

## Setup
- PufferAI/PufferLib @ `7b11311` (2026-07-01) cloned to /home/theo/pufferlib, own uv venv (py3.12, torch 2.12.1+cu130).
- The default trainer backend is `_C`: the whole PPO loop (rollout storage, puff-advantage kernel, Muon optimizer) compiled C++/CUDA; env is CPU-side SIMD C (8-lane vectors). Build requires clang + nvcc; this box has neither, so: `zig cc` (pip `ziglang`) shimmed as clang (with `-fopenmp` stripped — config runs num_threads=1 so OpenMP is inert), pip-wheel nvcc (`nvidia-cuda-nvcc` 13.3.73 + `nvidia-cuda-cccl`), a fake `CUDA_HOME` assembled from the torch cu13 wheel libs + driver `libnvidia-ml.so`, stub headers for `omp.h`/`nvml.h`/`cuda_profiler_api.h`, and `libomp5 → libgomp` alias. `./build.sh drone` then builds `pufferlib/_C.cpython-312-x86_64-linux-gnu.so` cleanly. No system CUDA toolkit or clang needed — recipe in the attached run log header.
- Run: `puffer train drone` — stock `config/drone.ini`: 88.6M steps, 2048 agents (32 env instances × 64 drones), multi-task hover(55%)+race(45%), 26.2K-param 64×2 GELU MLP, horizon 64, minibatch 16384, replay_ratio 2.25, DR ±5%.

## Results
- **6.4M steps/s sustained; 88.6M steps in ~14 s wall-clock.** GPU 93% busy, 1.4 GB VRAM, 1.0 GB RAM.
- Final eval-phase metrics: **race perf 0.876** (rings_passed 8.96/10, 47.8% of episodes complete all 10 rings, 4.43 ring-edge collisions/ep, 11.5% OOB), **hover EMA dist 0.040 m**, EMA vel 0.095 m/s, 0% hover OOB.
- Checkpoints saved as raw float .bin (loadable by their dependency-free C `puffernet` — the same format their Crazyflie firmware compiles in) under /home/theo/pufferlib/checkpoints/drone/1782982752665/.
- **Δ vs our stack on the same GPU: our torch PPO sustains ~437k SPS** (charts/SPS from runs/gate_race_general_air65 and gate_race_air65) → **~15× slower per env-step**; a 120M-step run costs us ~4.6 min vs their ~19 s equivalent.

## Verdict / Honesty
GREEN as a measurement: the 10,000×-marketing headline is real in the useful sense — a full drone RL experiment in 14 s on stock config. Not apples-to-apples with our 437k SPS: they run 21-dim obs, CPU SIMD dynamics (RK4 @ 500 Hz with motor-lag — fidelity is NOT lower than ours on the axes they model), fused CUDA trainer, no wind/latency/obs-noise DR, no differentiability, no replay recording. Their race metric is rings-passed on random courses, not lap time — no direct task-quality comparison to our gate_race is possible from this run.

## Lineage
Child of the control node (icy-feather-6323) for the PufferLib competitive deep-dive; evidence feeding the analysis node. Repo doc: docs/COMPARISON_PUFFERLIB.md @ 58e2dc9.