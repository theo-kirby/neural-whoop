---
node_id: 002df981-423f-585c-8b52-528f67d2bb0d
slug: long-mountain-5811
title: 'The policy/env contract: obs-v4, act-v2 CTBR, and the domain-randomisation seam'
created_at: '2026-08-09T18:42:31+00:00'
parents:
- dusty-pine-0511
summary: 'obs-v4 (11, body-frame, heading-invariant) and act-v2 (4, CTBR, normalised) plus a two-layer DR seam. Working and stable; the seam is what makes a tiny policy transferable. One long-open gap closed in 2026-08: the sim had no mirror of the pilot''s throttle floor.'
---
Status: working

## Current

The contract is the sim2real seam and is deliberately simulator-independent — pure
batched torch in `src/neural_whoop/contract.py`, unit-tested without DiffAero
(`docs/CONTRACT.md`).

- **obs-v4** [rec: morning-feather-7342], length 11, body-frame and heading-invariant:
  `[target_rel(3), vel_body(3), roll, pitch, p, q, r]`. Absolute yaw is dropped
  because it is not observable without a magnetometer. Tasks append after the 11 —
  `gate_race` adds a 3-vector next-gate lookahead to reach 14.
- **act-v2** [rec: morning-feather-7342], length 4, CTBR normalised to `[-1, 1]`:
  `[collective_thrust, roll_rate, pitch_rate, yaw_rate]`. CTBR is exactly what
  Betaflight's acro rate loop takes, which is the point.
- **Domain randomisation in two layers** [rec: morning-feather-7342]: airframe DR inside DiffAero's
  `QuadrotorModel` (mass, arm, torque constant, inertia, drag) and seam DR in
  `randomization.py` (wind, rate-gain, thrust scale, obs noise, action latency,
  uplink latency and interval, detector noise).

The versioning rule is explicit: change obs/act/DR *semantics* and you bump to
obs-v5 / act-v3 and say why. It has held — obs-v4 and act-v2 are still current after
thirteen tasks.

`ActionLimits.min_thrust_normed` was added on 2026-07-31 as the sim-side mirror of
the pilot's free-flight throttle floor, applied inside `action_to_diffaero` and wired
through an `act:` config section. Default `0.0` leaves every existing task
bit-identical.

## Negative knowledge

- [scope: every hover config trained before 2026-08-08 | confidence: high | evidence: black-salad-4817] The pilot has clamped `min_thrust_frac` at 0.25 in free flight since 2026-07-31 and no hover config mirrored it, so every hover policy in the ladder learned a throttle profile the deploy path silently rewrites. Desk-Hover is the first hover config to set `act.min_thrust_normed: 0.25`.
- [scope: rewards whose optimum is a near-zero-throttle coast | confidence: high | evidence: black-salad-4817] Modelling the floor is insurance, not a guarantee. At idle throttle with no Betaflight AIRMODE the airframe loses rate authority, which the simulator cannot model at all — the v1 flip already stalled on the bench for exactly that reason.

## Provenance

- morning-feather-7342 — the contract as a locked decision and the seam it defines
- black-salad-4817 — the throttle-floor gap, its history, and why the floor is insurance rather than a guarantee
