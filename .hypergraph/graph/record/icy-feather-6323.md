---
node_id: ae4658be-0b27-5582-8c80-381b4dbd1313
slug: icy-feather-6323
title: 'Control: PufferLib drone-env competitive deep-dive'
created_at: '2026-07-02T08:50:51.437256+00:00'
parents:
- morning-feather-7342
summary: 'CLOSED (objective_met): PufferLib drone deep-dive complete — measurement node (6.4M SPS run on the 5090, ~15× our PPO) + analysis node (full comparison + 9 ranked idea imports) + repo doc @ 58e2dc9; ~0.5 h of the 4 h local budget used, 0 credits.'
origin:
  backend: flywheel
  node_id: ae4658be-0b27-5582-8c80-381b4dbd1313
  slug: icy-feather-6323
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 03d671c3-bd9d-555f-af20-fdddb36f7921
  slug: calm-dust-1866
  revision: 0
  pushed_at: '2026-08-09T21:26:19+00:00'
  content_sha256: 47a68c97c907b621cea23905cd43bec03acd18f6e14b35179d54cc9e88e23c76
---
## Run contract

- Objective: Install PufferLib (PufferAI/PufferLib @ 7b11311, July 2026) and its `drone` Ocean environment locally; produce a thorough competitive/system analysis vs neural-whoop covering: architecture, dynamics model, obs/action contract, task designs, reward shaping, perception model, domain randomization & sim2real story, trainer (PPO variant), measured throughput + a real training run on the 5090, where they perform better/worse than us, and a concrete list of transferable ideas (each with adopt/defer/reject rationale).
- Decision criterion: analysis is done when every axis above is backed by source-level evidence or a local measurement, and the ideas list is specific enough to spawn follow-up experiment nodes.
- Start nodes: morning-feather-7342 (root, 51aabea1-f793-534d-a0a7-bc9b1e368bbb).
- Budget ceiling: 4
- Budget unit: hours of local wall-clock on the single RTX 5090 (this session)
- Compute approval cap: 0 Flywheel credits — locked decision #3: local-only, no managed cloud compute. Terminal condition derived: budget ceiling reached (or objective met earlier).
- Lookahead depth: 1
- Frontier width: 1
- Terminal condition: comparison analysis node(s) committed with artifacts + ideas recorded, or 4 h wall-clock reached.
- Stop reason: **objective_met** (2026-07-02, ~0.5 h wall-clock of the 4 h budget used; 0 credits spent; no managed compute acquired).

## Outcome

All deliverables committed:
- Measurement node lively-dawn-5118 (217e8514): PufferLib drone installed + built on the 5090 (no-sudo toolchain: zig-cc-as-clang + pip-wheel nvcc + fake CUDA_HOME); stock 88.6M-step hover+race run at **6.4M SPS, done in ~14 s** (race perf 0.876, hover EMA dist 4 cm) vs our torch PPO's ~437k SPS — ~15×. Artifacts: run dashboard + drone.ini.
- Analysis node long-fog-2207 (a410560a): full system comparison (actions: per-motor RPM end-to-end w/ motor lag; obs: 21-d dual-scale tanh, not heading-invariant; thin ±5% DR, no wind/latency/noise; fused CUDA PPO w/ V-trace-clipped GAE + prioritized replay + Muon; PROVEN onboard-LSTM Crazyflie sim2real at 100 Hz) + 9-item ranked idea-import list. Artifact: COMPARISON_PUFFERLIB.md (also committed to repo @ 58e2dc9).
- Repo doc: docs/COMPARISON_PUFFERLIB.md (neural-whoop @ 58e2dc9, pushed).

Follow-up frontier (staged as ideas inside the analysis node, not yet separate nodes): dual-scale tanh obs-v5; puff-advantage + prioritized replay port; Muon on TinyPolicy; minGRU implicit system-ID; sweep harness; motor-lag k_mot check in DiffAero; control-frequency pinning in docs/CONTRACT.md.

## Rationale / plan (as executed)

User directive (2026-07-02): set up https://puffer.ai/?env=drone, full walkthrough — what the architecture does differently, choices made, what we can learn, better/worse, ideas, tasks, perception, sim2real. Branch/tag as system comparison / pufferlib / competitive analysis.

Executed: (1) cloned + installed PufferLib into /home/theo/pufferlib (own uv venv); (2) source-level deep dive of ocean/drone/* (C SIMD env), config/drone.ini, src/pufferlib.cu, pufferlib/{models,torch_pufferl}.py, plus upstream tensaur/drone (firmware controller, summit-26 lessons deck, sim2real video); (3) ran `puffer train drone` on the 5090; (4) committed measurement + analysis nodes, all tagged cluster:system-comparison + topic:pufferlib.

No managed compute was acquired; all execution was local Bash on the workstation.