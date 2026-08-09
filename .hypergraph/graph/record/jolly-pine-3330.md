---
node_id: da2d5e2d-5168-513a-91c5-a2acbc960aeb
slug: jolly-pine-3330
title: 'hover_blind_air65_long (3.2B steps, ~50 min): trim solved — σ_thrust 0.478→0.032, v_z +0.01 m/s, pure-hold 30 s survival 0→91% no-DR — THE first-flight checkpoint (GREEN)'
created_at: '2026-07-05T15:02:48.785465+00:00'
parents:
- still-bird-0492
- throbbing-firefly-2363
summary: 'hover_blind_air65_long: 3.2B steps (80× the 40M parent) / 8192 envs / episode_len 500→1500 (30 s, so residual trim-sink integrates to in-episode floor exits), ~50 min at ~1.06M sps; deployed through the new effective-mean deterministic path (5c735cd). Both hypothesized mechanisms confirmed: exploration σ_thrust annealed 0.478→0.032 (clip bias gone at the source; correction→identity) and the 30 s horizon drove steady-state v_z from −0.356 to +0.010 m/s. Pure-hold 30 s survival (no-DR): 0% (40M raw) → 57% (40M+fix) → 91.3%; eval drift speed 0.370→0.069 m/s; crash 0.47→0.01 %/step; tilt 1.68°. DR-on median exit 3.2→8.7 s (13.8% survive 30 s) — open-loop physics bound, collapsed on real hardware by the bench hover-throttle anchor. Verdict GREEN: ckpt_final.pt + its corrected exports are THE first-flight checkpoint. Honesty: hold_rate/pos_error read worse purely from 3×-longer episodes integrating drift; steps-vs-episode_len not ablated; metrics plateaued ~1.7B (half the budget would have sufficed); 8.7% clean-air tail is near-floor spawns. Commits 5c735cd, a4cf760.'
origin:
  backend: flywheel
  node_id: da2d5e2d-5168-513a-91c5-a2acbc960aeb
  slug: jolly-pine-3330
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 5cd680ea-3499-5313-9154-20e9da6fc692
  slug: white-sun-8065
  revision: 0
  pushed_at: '2026-08-09T21:27:20+00:00'
  content_sha256: 9e96995dc0cc8d64eeed337881d0ed10515275a1e6512e385b6b56303d78aff1
---
# hover_blind_air65_long: the 1-hour "how far can blind hover get" run

**Hypothesis.** Two mechanisms should close the residual trim gap the effective-mean fix left (57% → ~100% pure-hold survival): (1) **80× more optimization anneals exploration σ toward 0**, shrinking the clip bias at the source; (2) **episode_len 500→1500 (30 s)** lets residual trim error integrate to floor exits *within* an episode, giving PPO a direct crash-penalty gradient against the sink (the 10 s horizon never let a slow sink reach the floor from a mid-band spawn).

**Setup.** `configs/hover_blind_air65_long.yaml` = fork of `hover_blind_air65.yaml` changing ONLY: `total_steps` 40M→3.2B, `n_envs` 4096→8192, `episode_len` 500→1500. Reward/DR/airframe/net identical. ~50 min at ~1.06M sps on the 5090 (16,276 updates). Deterministic eval/deploy is the corrected effective-mean path (parent method node, commit `5c735cd`). Commits: `5c735cd` (config), `a4cf760` (docs/results).

**Results** (all deterministic, 2048 drones × 1500 steps; parent = the 40M `hover_blind_air65` run still-bird-0492):

| metric | 40M raw | 40M + fix | **3.2B long (+fix)** |
|---|---|---|---|
| final σ (thrust) | 0.478 | 0.478 | **0.032** |
| steady v_z, pure hold no-DR | −0.356 m/s | — | **+0.010 m/s** |
| pure-hold 30 s survival, no-DR | 0% | 57% | **91.3%** |
| median floor-exit, no-DR | 4.0 s | 18.1 s | (only 8.7% exit) |
| pure-hold median exit, DR-on | 3.2 s | — | **8.7 s** (13.8% survive 30 s) |
| eval drift speed, no-DR | 0.370 m/s | — | **0.069 m/s** |
| eval crash %/step, no-DR | 0.47 | — | **0.01** |
| eval tilt, no-DR | 1.14° | — | 1.68° |

Both hypothesized mechanisms confirmed: σ annealed 15× (log_std thrust −0.74→−3.43; rate channels → ~e⁻⁸) so the clip bias is gone at the source and the effective-mean correction ≈ identity; the 30 s horizon pushed the trim to v_z +0.01 m/s. Training itself was uneventful: DR curriculum completed at 960M steps (tilt 2.4°→5.3° as wind/impulses reached full strength), then flat — the last ~1.5B steps bought trim/σ sharpening, not headline-metric movement.

**Verdict. GREEN** — `runs/hover_blind_air65_long/ckpt_final.pt` (and its corrected `policy.pt`/`policy.onnx` exports) is **THE first-flight checkpoint**: level (1.7°), essentially trim-neutral, drifting at 7 cm/s, 91% survival over a 30 s window in clean air from a pure-hold start. DR-on survival (14% @30 s, median exit 8.7 s) remains bounded by open-loop physics (±5% thrust × ±7% mass) — on the real drone the bench hover-throttle anchor (~1410 µs @ 3.6–3.7 V) collapses that axis; battery sag over a flight is the remaining open risk.

**Honesty.**
- `hold_rate`/`pos_error` read WORSE than the 40M run (0.15 vs 0.19; 0.93 vs 0.83 m) — an artifact of 3×-longer episodes integrating open-loop drift, not a regression; the deployment-relevant numbers (drift speed, crash rate, survival) all improved sharply. Lateral drift is unobservable and stays — blind hover is a trim demo, not a station-hold.
- Two variables changed vs parent (steps, episode_len) plus the eval-path fix — the 0→57% (fix alone, parent method node) vs 57→91% (this run) split is cleanly attributed, but steps-vs-episode_len is not ablated; not worth the compute to separate given both point the same direction.
- Plateau after ~1.7B steps suggests ~half the budget would have landed nearly the same place — useful calibration for future 1 h runs.
- 8.7% still floor-exit in clean air (median 6.6 s): a tail of spawn setpoints near the z-band floor where +1 cm/s drift and the 0.15 m bound leave little margin.

**Artifacts.** Standard visual pack (no-DR hero rollout vs the 40M `hover_blind_air65` baseline replay) + hero MP4 + probe record (`long_probe_results.txt`: σ, v_z, survival tables, eval comparison).

**Lineage.** Parents: the effective-mean deployment fix (method, throbbing-firefly-2363 — this run deploys through it and validates its σ→0 limit) and the 40M trim-bias discovery (still-bird-0492 — config fork parent whose two follow-ups this run executes).