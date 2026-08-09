---
node_id: 928fcf2c-136d-5d2c-bb32-08a8deb292d1
slug: throbbing-firefly-2363
title: 'Method: deploy the clipped-Gaussian effective mean E[clip(N(μ,σ))] — the trim-bias fix; 0→57% pure-hold survival on the old checkpoint with no retraining'
created_at: '2026-07-05T15:01:13.010000+00:00'
parents:
- still-bird-0492
summary: 'All deterministic policy paths (evaluate, evaluate_and_record, Studio Live, DeployPolicy export) now output the closed-form clipped-Gaussian effective mean E[clip(N(μ,σ),−1,1)] (erf/exp only, ONNX/TorchScript-clean; σ baked into exports as a buffer) instead of the raw clamped mean — the fix for still-bird-0492''s finding that PPO optimizes the sampled-then-clamped policy, so raw-mean deployment is biased on any channel trained near a clip bound (hover_blind thrust trim 12% low → sink). Validated: unit tests vs Monte Carlo + deploy≡eval parity (suite 133 green); on the unchanged 40M hover_blind checkpoint, pure-hold 30 s survival 0%→57% (median floor-exit 4.0→18.1 s) with no retraining. Chosen over a tanh-squashed head: no algorithm change, retroactive to every checkpoint, and →identity as σ anneals to 0. Commit 5c735cd.'
origin:
  backend: flywheel
  node_id: 928fcf2c-136d-5d2c-bb32-08a8deb292d1
  slug: throbbing-firefly-2363
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 81d88863-b0de-5687-a6db-4179cb02d24f
  slug: bitter-bar-3315
  revision: 0
  pushed_at: '2026-08-09T21:27:05+00:00'
  content_sha256: 8183779baecaed309b7cf6c7f7e2eefd9a2d14124e43eb41fe976dda739c44a8
---
# Effective-mean deterministic deployment (the clipped-Gaussian trim-bias fix)

**What.** All deterministic policy paths now output the closed-form **effective mean E[clip(N(μ,σ), −1, 1)]** — the quantity PPO actually optimizes when it samples Gaussian actions that the env clamps — instead of the raw clamped mean μ. Implemented as `training/ppo.py::clipped_gaussian_mean()` (pure erf/exp — TorchScript- and ONNX-clean) + `ActorCritic.act_deterministic()`; routed through all four call sites: `eval/rollout.py::evaluate` and `::evaluate_and_record`, `studio/live.py` (Live tab), and `training/export.py::DeployPolicy` (the trained per-channel σ is baked into the export as a buffer, so `policy.pt`/`policy.onnx` carry the correction standalone).

**Why.** Parent node still-bird-0492: the hover_blind 40M checkpoint deployed a thrust trim 12% under hover and sank — with final thrust σ=0.478, the clamp at −1 truncates the low tail, so the sampled (training-time) behavior had E[clip] ≈ hover while the raw deterministic mean sat at −0.562. Generic: any action channel whose absolute level matters open-loop is biased at deterministic deployment when μ sits within ~2σ of a bound.

**Validation.**
- Unit tests: closed form vs 2M-sample Monte Carlo (atol 2e-3) across interior/near-bound/outside-bound means; deploy path ≡ eval path bit-for-bit; TorchScript round-trip. Suite 133 green.
- Empirical, on the UNCHANGED 40M `hover_blind_air65` checkpoint: pure-hold 30 s survival **0% → 57.1%** (median floor-exit 4.0 s → 18.1 s), no retraining. Matches the +0.0463 constant-offset probe from the parent node (59%) — the state-dependent correction reproduces the E[clip]-gap arithmetic.
- The residual (57% vs the +0.0616 empirical-trim 100%) is the policy's own effective trim sitting ~1.5% low — a training-quality issue, attacked by the 3.2B-step long run (child node).

**Design notes.** Chosen over the tanh-squashed action head because it is (a) exactly the expectation PPO optimized — no algorithm change, no retraining required, applies retroactively to every existing checkpoint; (b) closed-form and export-clean. As exploration σ anneals → 0 the correction smoothly becomes the identity, so it is safe as the permanent default for every task family (verified: gate-race-style channels with μ deep inside the bounds are numerically unchanged). Commit `5c735cd` (fix + tests + `configs/hover_blind_air65_long.yaml`).