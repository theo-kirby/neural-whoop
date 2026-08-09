---
node_id: a43af195-1054-56d5-a09e-826384072f94
slug: bitter-rain-0437
title: The rate-loop frame bug is FIXED in the vendored fork — orbit 17.65 m -> 1.80 cm, exactly the number the control arm predicted; non-planar maneuvers become valid RL targets
created_at: '2026-08-01T12:54:43.003079+00:00'
parents:
- solitary-sun-6456
- ancient-river-4144
summary: 'Patched third_party/diffaero/dynamics/controller.py: actual_angvel_b = R_i2b @ w -> w (w is already body-frame per quadrotor.py:123/137). The orbit goes from 14.59 m of open-loop error to 1.80 cm / 0.65 deg — matching the pre-registered control-arm prediction to 3 s.f. The flip reads 2.15 cm under BOTH loops, confirming the mechanism (planar omega sits on R''s fixed axis, alignment 1.000000000; the orbit''s is 0.000584). Both arms kept in tests/test_reference_sim.py via _legacy_rollout so the fix cannot silently regress. 387 tests green. GREEN. Consequence recorded: planar results all stand, but any NON-planar measurement predating 2026-08-01 was made on a divergent substrate.'
origin:
  backend: flywheel
  node_id: a43af195-1054-56d5-a09e-826384072f94
  slug: bitter-rain-0437
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 2f312fa7-912c-5001-9d88-e20e3f47d41a
  slug: little-paper-9495
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 822d9559f2538baf3b805aa528ebe832df7f130d5e7a262604eeeb8d0cb2cc55
---
## Hypothesis

`solitary-sun-6456` measured that DiffAero's vendored `RateController` computes the *measured* body
rate as `R_i2b @ w` while `w` is already body-frame, making the closed loop `omega_dot = K(u - R*omega)`
whose eigenvalues are `-K` and `-K*e^{+-i*theta}` — real part **`-K*cos(theta)`, positive past 90 deg
of attitude**. That node reported the finding and, per the then-standing decision, did **not** patch
the fork; the corrected loop lived only as a local re-implementation used as a measurement.

The prediction under test: **if `R_i2b` is the cause, removing it should make the orbit track — and
it should land at the 1.8 cm the control arm predicted, not merely "better".** A prediction that
names the number is falsifiable in a way that "it should improve" is not.

## Setup

One line in `third_party/diffaero/dynamics/controller.py`: `actual_angvel_b = R_i2b @ w` becomes
`actual_angvel_b = w`. Justified at the call site rather than by preference — `quadrotor.py:123`
applies `M = tau - w x Jw` and `quadrotor.py:137` integrates `q_dot = 1/2 q (x) [w,0]`, both
body-frame conventions, so `w` arriving at the controller is already in the frame the loop needs.

The control experiment is kept with **both arms** in `tests/test_reference_sim.py`: the patched
fork, and `_legacy_rollout`, a numpy re-implementation of the old loop. Keeping the legacy arm is
the point — "the orbit tracks now" on its own would also pass if someone quietly resized the
maneuver below 90 deg of attitude, so only the pairing ties the fix to the cause.

## Results

| orbit, open-loop, 3.85 s | result |
|---|---|
| patched fork (`actual_angvel_b = w`) | **1.80 cm / 0.65 deg** |
| legacy loop (`R_i2b @ w` restored) | **14.59 m** |
| legacy @ 20 / 5 / 1 ms | 14.59 / 14.74 / 14.71 m — flat |
| flip, patched fork | 2.15 cm |
| flip, legacy loop | 2.15 cm — *identical* |

**1.80 cm is exactly the number the control arm predicted**, reproduced to three significant
figures by the real simulator. The flip reads 2.15 cm under *both* loops, which is the mechanism
made visible: a planar maneuver's omega lies on `R`'s own rotation axis (alignment measured
1.000000000), the one eigenvector whose loop eigenvalue stays `-K` regardless of theta. The orbit's
does not (0.000584) and it was the only maneuver in the lab that could see the bug.

Full suite green (387 tests) on an RTX 4070.

## Verdict / Honesty — GREEN (`stop_reason: improved`)

The substrate is corrected and **non-planar maneuvers are now valid RL targets** (see the
`reference_track` orbit result that descends from this).

Honest caveats:

- **`_legacy_rollout` reads 14.59 m where `solitary-sun-6456` reported 17.65 m.** Not a discrepancy
  in the finding: that figure was measured through the real `WhoopDynamics`, which saturates body
  rate and velocity every step, while this re-implementation is pure numpy without those clamps, so
  a *bounded* blow-up settles at a different magnitude. The assertion is on `> 1.0 m` rather than
  either number, because the exact magnitude of an unstable mode is not the result.
- **What this means for prior work, stated rather than buried:** every policy this lab has ever
  trained — gate_race, hover, the flip, the swing — is *planar*, so all of them sat on the stable
  eigenvalue and their numbers stand. Any **non-planar** measurement dated before 2026-08-01 was
  made on a divergent substrate. `verify.check_rate_loop_stability` now answers "would the *legacy*
  loop have tracked this" and ships `substrate_rate_loop_fixed` alongside it, so an artifact's own
  `verify.json` says which simulator it was flown on. `vendored_loop_stable` is retained as a
  back-compat alias so pre-fix artifacts stay readable against the same key.
- This reverses a standing project decision ("reported, not fixed"). Reversed deliberately, with
  the user, because the alternative was leaving a known-divergent substrate under every future 3D
  maneuver.

## Lineage

Resolves the RED measurement in `solitary-sun-6456`. The maneuver that found the bug
(`ancient-river-4144`'s orbit) is the one that could not be trained until it was fixed — this node
closes that loop and unblocks the orbit arm of `reference_track`.
