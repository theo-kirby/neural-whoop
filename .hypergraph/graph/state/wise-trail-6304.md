---
node_id: f31d5a48-5da9-506e-8471-2b96dafa0dbe
slug: wise-trail-6304
title: 'Simulation substrate: the vendored DiffAero dynamics core'
created_at: '2026-08-09T18:42:31+00:00'
parents:
- dusty-pine-0511
summary: Vendored, patched DiffAero pure-torch dynamics core running on Blackwell. Working. Carries the 2026-08-01 rate-loop frame-bug fix and the standing consequence that non-planar measurements predating it were made on a divergent substrate.
flywheel:
  node_id: 17fc86fc-24ee-52c7-9f0b-530c49201d34
  slug: plain-cell-1990
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: b0580aa85ea545c4ce6e9561110ab5a8305fb669f08601dbf4bed80c4fd065bb
---
Status: working

## Current

The simulator is a vendored fork of DiffAero (BSD-3) under `third_party/diffaero`,
pinned at upstream `291ea14` and patched so its pure-torch dynamics core runs on
Blackwell / sm_120 without the rendering stack (pytorch3d, taichi, open3d)
[rec: morning-feather-7342]. Only `dynamics/`, `utils/math.py` and
`utils/randomizer.py` are used; DiffAero's env, algorithm and rendering layers are
not installed, and the only dependencies it brings are `torch` and `omegaconf`.

Five local patches carry the fork [rec: morning-feather-7342] (`CLAUDE.md`, *Vendored DiffAero edits*): a
pure-torch `quaternion_to_matrix` / `quaternion_raw_multiply` shim replacing four
pytorch3d import sites, lazy subpackage imports, a dropped hydra `Logger` import, a
clamped `asin` argument in `quaternion_to_euler` (a real NaN bug at near-vertical
pitch that poisoned the policy), and per-step saturation of body rates and velocity.

The rate-loop frame bug was found and fixed on 2026-08-01. `RateController` used
`R_i2b @ w` as the *measured* body rate while `w` is already body-frame, so the
closed loop was `omega_dot = K(u - R*omega)` with eigenvalues `-K` and
`-K*exp(+-i*theta)` — real part `-K*cos(theta)`, positive and therefore divergent
past 90 degrees of attitude. The eigenvalues were built and read directly rather
than cited [rec: solitary-sun-6456]. The fork now reads `actual_angvel_b = w`, which
took the orbit reference from 17.65 m of open-loop error to 1.80 cm / 0.65 degrees —
matching the pre-registered control-arm prediction to three significant figures — and
both arms are pinned in `tests/test_reference_sim.py` via `_legacy_rollout` so the
fix cannot silently regress [rec: bitter-rain-0437].

## Negative knowledge

- [scope: any non-planar measurement made in this simulator before 2026-08-01 | confidence: high | evidence: solitary-sun-6456, bitter-rain-0437] Results predating the rate-loop fix were measured on a divergent substrate whenever the maneuver was non-planar. Planar results stand: a planar body rate lies on R's own rotation axis (alignment measured 1.000000000), the eigenvalue that stays -K, while the orbit's does not (0.000584). Every gate_race, hover, flip and swing policy this lab trained is unaffected; only the orbit exposed it.
- [scope: DiffAero as vendored upstream | confidence: high | evidence: morning-feather-7342] DiffAero defines state bounds but never applies them. A whoop's tiny inertia makes the RK4 rotational dynamics go unstable past the rate limit unless the fork saturates body rates and velocity every step.
- [scope: Isaac Lab as an alternative substrate | confidence: high | evidence: morning-feather-7342] Isaac Lab's tiled-camera path hangs on Blackwell, which is why DiffAero was chosen and Isaac deferred rather than benchmarked against.

## Provenance

- morning-feather-7342 — the locked substrate decision, the upstream pin, and the patch inventory
- solitary-sun-6456 — the rate-loop instability, derived from eigenvalues and verified numerically
- bitter-rain-0437 — the fix, its measured effect, and the regression test that pins both arms
