---
node_id: e0b06fb5-c2f1-5a40-a67f-1e86f76c550c
slug: hidden-moon-2828
title: 'puff-update port (V-trace-clipped GAE + prioritized segment replay): 3.203→3.440 s, safer but slower — NO-GO at untuned settings'
created_at: '2026-07-02T09:56:17.018306+00:00'
parents:
- dawn-field-3426
summary: 'PufferLib''s puff-update (per-minibatch V-trace-clipped GAE + advantage-prioritized segment replay) ported into our PPO at matched sample reuse: best lap 3.203→3.440 s (+7.4%), but best-in-pass reliability (completion 93.8%, crash −20%) — NO-GO for the lap-time beachhead at untuned settings; mechanism not refuted. Pack attached.'
origin:
  backend: flywheel
  node_id: e0b06fb5-c2f1-5a40-a67f-1e86f76c550c
  slug: hidden-moon-2828
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis
PufferLib's trainer recipe — advantages recomputed per minibatch with V-trace ρ/c clipping from a live importance-ratio buffer, plus advantage-prioritized whole-segment minibatches with (N·p)^−β correction and value refresh — improves wall-clock-to-quality over our vanilla PPO epoch loop at equal sample reuse (idea #2 from long-fog-2207).

## Setup
`ppo.puff_update` mode implemented in training/ppo.py (commit 6111e68): per-minibatch V-trace-clipped GAE (ρ_clip 1.5, c_clip 2.9), prioritized segment draw (α 0.2, β₀ 0.75 annealed), val_buf refreshed in-place, truncation bootstrap folded into rewards, target_kl disabled in-mode. `configs/gate_race_air65_puff.yaml` = gate_race_air65 + puff_update + replay_ratio 4.0 (matching baseline update_epochs=4 reuse so the delta under test is vtrace+prio, not reuse volume). 120M steps, seed 0, Adam lr 3e-4 (unchanged). Standard no-DR eval vs seed-matched parent.

## Results (Δ vs baseline: 3.203 s, 92.6%, laps/ep 1.27, crash 8.2e-5)
- best_lap_time **3.440 s (+7.4% slower)**; laps/ep 1.05 (−17%); mean reward 0.261 (−10%)
- lap_completion_rate **93.8% (+1.2 pt, best of all variants)**; crash rate 6.6e-5 (−20%, tied-best)
- Training was stable throughout (kl ≈ 0.001–0.004, no collapse) — the port is functionally correct, just not faster.

## Verdict / Honesty
**NO-GO at these settings** — not RED: the mechanism isn't refuted, but the faithful-ish port under our baseline hypers trades speed for a small reliability gain, and lap time is the beachhead metric. Key caveats: (1) PufferLib's recipe is inseparable from its swept hyper set (clip 0.051, Muon lr 9.5e-3, horizon 64, minibatch 16k, reward clamp ±1) — we changed only the update rule; (2) prioritized replay may interact badly with our sparse gate/lap bonuses (high-|A| segments = crashes and gate hits, biasing toward caution — consistent with the safest-of-all profile); (3) single seed. Staged follow-ups if ever revisited: puff + Muon combined at their ratios, replay_ratio sweep, prio_alpha→0 ablation to isolate V-trace from prioritization. Also noteworthy: puff produced the most reliable policy of the pass — a candidate lever for reliability-critical tasks rather than racing.

## Lineage
Child of control dawn-field-3426. Idea source: analysis node long-fog-2207 idea #2; reference implementation pufferlib/torch_pufferl.py + src/pufferlib.cu (puff_advantage_row_scalar). Code: 6111e68.