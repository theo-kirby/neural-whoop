---
node_id: 94f3ea78-ead9-54a9-a438-c8ac3595d554
slug: solitary-sun-6456
title: DiffAero's vendored rate loop is UNSTABLE past 90° of attitude — eigenvalues −K·e^{±iθ}, so real part −K·cosθ. The flip survives only because its ω is on R's fixed axis (alignment 1.000000000)
created_at: '2026-08-01T01:50:34.153250+00:00'
parents:
- ancient-river-4144
- sparkling-shadow-0034
summary: 'controller.py:93 computes the MEASURED body rate as `R_i2b @ w`, but `w` is already body-frame (quadrotor.py uses q̇ = ½q⊗[w,0] and M = τ − w×Jw, both body-frame), and the controller''s own ω×Jω term cancels the rigid body''s exactly. So the closed loop is ω̇ = K(u − R·ω), not ω̇ = K(u − ω). R''s eigenvalues are 1 and e^{±iθ} with θ the attitude''s rotation angle from identity, so the loop''s are −K and −K·e^{±iθ}: REAL PART −K·cosθ, negative below 90° of attitude and POSITIVE above it. Verified directly by building −K·R and reading its eigenvalues, not cited. The 90° threshold alone is NOT the answer and the flip is the proof: a roll flip spends 6% of its frames past 90° and tracks to 2.15 cm anyway, because R''s eigenvector for eigenvalue 1 is its own ROTATION AXIS, where the loop eigenvalue stays −K regardless of θ — and a planar maneuver''s ω lies exactly on it. Measured ω-to-fixed-axis alignment: flip 1.000000000, swing 1.000000000, orbit 0.000584. Control experiment on the orbit, identical 50 Hz command stream: DiffAero as vendored 17.65 m / 180°, an identical loop with R_i2b removed 1.80 cm / 0.65°. Flat across control rates (17.65 / 17.87 / 17.65 m at 20 / 5 / 1 ms), so it is instability and not discretization; onset at 0.78 s into the maneuver matches the predicted 90° crossing. RED: it refutes the standing claim in this repo''s docstrings that the frame bug is a harmless no-op — it is a no-op only for maneuvers whose ω is on R''s fixed axis, which every maneuver flown here so far happens to have been. Correction to my own earlier note: it does NOT reach NaN. WhoopDynamics saturates rate and velocity every step, so the blow-up is bounded and the output still LOOKS like a finite trajectory. REPORTED, NOT FIXED per the project decision: the vendored fork is untouched. What is blocked is training to, or evaluating against, any non-planar maneuver in this simulator — including the orbit reference. verify.check_rate_loop_stability now ships the verdict AND its reason in every maneuver''s verify.json.'
origin:
  backend: flywheel
  node_id: 94f3ea78-ead9-54a9-a438-c8ac3595d554
  slug: solitary-sun-6456
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: a572a876-da5f-59a6-8074-79be366db263
  slug: plain-scene-6357
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: 16cb61426b128910ac31a2478bf420f2d62b5c3ac506e4a4c83f6fdd8f6c4c80
---
## Hypothesis

This is not a maneuver result, which is why it is not folded into its parent. The reference package's docstrings have carried a standing claim since the flip landed: DiffAero's `RateController` frame bug is *a no-op for our maneuvers*, because for a rotation about the same axis the rate is on, `R_i2b @ w == w` exactly. That claim was never tested against a maneuver that violates it, because until the orbit there wasn't one.

So: **is the frame bug harmless, or is it harmless-so-far?**

## Setup

`third_party/diffaero/dynamics/controller.py:93`:

```python
actual_angvel_b = torch.bmm(R_i2b, w.unsqueeze(-1)).squeeze(-1)      # R_i2b @ w
angvel_err = desired_angvel_b - actual_angvel_b
```

But `w` is **already body-frame** — `quadrotor.py` integrates `q̇ = ½q⊗[w,0]` and applies `M = τ − w×Jw`, both body-frame. The controller's own `ω×Jω` term cancels the rigid body's exactly, so DiffAero's rotational dynamics reduce to `ω̇ = K(u − ω_measured)` and the *only* defect is the `R_i2b` that should not be there.

Three measurements, deliberately independent of each other:

1. **The eigenvalue argument, verified rather than cited.** Build `−K·R` for 20 random rotations and read off its eigenvalues (`tests/test_reference.py`).
2. **The ω-to-fixed-axis alignment**, measured per maneuver on the shipped references (`verify.check_rate_loop_stability`).
3. **A control experiment**: push the identical impulse-matched 50 Hz command stream through DiffAero as vendored *and* through an identical loop with `R_i2b` removed — a local re-implementation in `tests/test_reference_sim.py`, not a patch to the fork.

## Results

### The eigenvalue argument

The closed loop is

```
ω̇ = K(u − R·ω)          instead of          ω̇ = K(u − ω)
```

`R` is a rotation, so its eigenvalues are `1` and `e^{±iθ}` with `θ` the attitude's rotation angle from identity. The loop's eigenvalues are therefore `−K` and `−K·e^{±iθ}`, whose **real part is `−K·cos θ`**:

| attitude `θ` | real part | |
|---|---|---|
| 0° | −16.0 1/s | stable, and the bug is a literal no-op |
| 69° (the swing's peak) | −5.65 1/s | stable |
| **90°** | **0.0** | **the boundary** |
| 180° | **+16.0 1/s** | divergent with the loop's own bandwidth |

Asserted numerically for 20 random `(axis, θ)` pairs to 1e-9, including that the sign flip happens exactly at `π/2`.

### The 90° threshold is NOT the answer, and the flip is the proof

A roll flip spends **6% of its frames past 90°** of attitude, reaches 179.9°, and tracks to **2.15 cm** anyway. If the threshold were the whole story it would be unflyable, and it is not.

The missing piece is the third eigenvalue. `R`'s eigenvector for eigenvalue `1` is its own **rotation axis**, and there the loop eigenvalue stays `−K` no matter what `θ` is. A planar maneuver's `ω` lies exactly on that axis, so it never excites the two `−K·e^{±iθ}` modes at all. Measured on the three shipped references:

| | max attitude from identity | **ω-to-fixed-axis alignment** | vendored loop, open-loop |
|---|---|---|---|
| `flip` | 179.9° | **1.000000000** | **2.15 cm** — stable |
| `swing` | 69.3° | 1.000000000 | 0.29 cm — stable twice over |
| `orbit` | 179.9° | **0.000584** | **17.65 m** — divergent |

The flip and the orbit reach the *same* attitude excursion, so "how rotated is it" cannot be what separates them. The alignment can, and does.

**This is a sharper statement of why `ψ ≡ 0` is load-bearing** than the one the docstrings carried. It is not that a planar rotation makes `R_i2b @ w == w` — that is true but incidental. It is that a planar maneuver only ever excites the eigenvalue the bug cannot destabilize.

### The control experiment

Identical command stream, one line of the controller changed:

| orbit, open-loop, 3.85 s | position error | attitude error |
|---|---|---|
| **DiffAero as vendored** | **17.65 m** | 180° |
| **identical loop, `R_i2b` removed** | **1.80 cm** | 0.65° |

Both halves are required. Asserting only "the orbit diverges" would still pass if the *reference* were wrong — a garbage trajectory diverges too. Asserting only "the corrected loop tracks" would not establish that anything is wrong with the substrate. Changing exactly one thing between two otherwise identical runs is what isolates the cause.

### It is instability, not discretization

| control rate | vendored-loop error |
|---|---|
| 20 ms | 17.65 m |
| 5 ms | 17.87 m |
| 1 ms | **17.65 m** |

**Flat.** A discretization error shrinks with the step; a positive eigenvalue does not. Without this the obvious reading of a blown-up trajectory is "the control rate is too low", which would send the next person to tune `dt` instead of reading `controller.py:93`.

The **onset matches the prediction** too: attitude crosses 90° at 0.78 s into the maneuver, and divergence appears between 0.4 s and 1.2 s.

## Verdict / Honesty

**RED** — it refutes the standing claim, carried in this repo's own docstrings since the reference flip, that the frame bug is a harmless no-op. It is a no-op only for maneuvers whose `ω` lies on `R`'s fixed axis, which every maneuver flown here so far happens to have been. That is luck with a reason, not safety.

**Correction to my own earlier note: it does not reach NaN.** I had recorded "NaN, 13.4 m before it blows". `WhoopDynamics` saturates body rate and velocity every step (`dynamics/whoop.py` — DiffAero defines state bounds but never applies them, and we added the clamp because a whoop's tiny inertia makes the RK4 rotational dynamics go unstable past the rate limit), so the blow-up is **bounded** at 17.65 m and the output still *looks* like a finite trajectory. That is worse than a NaN, not better: nothing downstream would flag it. Every assertion in the tests is therefore on error magnitude, never on `isfinite`.

**Reported, not fixed**, per the project's decision. The vendored fork is deliberately untouched and the corrected loop exists only inside a test as the control arm of this measurement. The hand-authored references and their videos are unaffected either way — they are authored, not simulated.

**What this actually blocks**, stated precisely so it is not over- or under-claimed:

- **Blocked:** training a policy to, or evaluating one against, any maneuver that takes the attitude past 90° with off-axis `ω`. That includes the orbit reference, and it would include any future cinematic yaw sweep.
- **Not blocked:** everything shipped to date. Gate racing, hover, follow, formation and the flip all keep `ω` on `R`'s fixed axis or stay well under 90°. `acro_flip` is fine, and its measured 2.15 cm open-loop tracking is the evidence rather than an assumption.
- **Unknown, and worth a follow-up:** whether any *trained* policy has been quietly exploiting the wrong loop. A policy trained against `ω̇ = K(u − Rω)` has learned that dynamics, so fixing the fork would be a sim2real change, not just a bug fix — which is a real argument for the decision to leave it alone rather than merely a convenient one.

**Two limits of this measurement:**

- The corrected loop is a **local re-implementation**, not the patched fork run in place. It is faithful (same drag law, gravity sign, thrust convention, RK4, substep count; only `R_i2b` differs) but it is not the same code path, so its 1.80 cm is a *bound* on what a fix would achieve rather than the fix's own number.
- **Only one non-planar maneuver was tested.** The eigenvalue argument predicts the behaviour for any of them, and the alignment measure is general, but the empirical half of this node rests on a single trajectory.

## Lineage

- `ancient-river-4144` **the swing + orbit** — the orbit is the maneuver that exposed this, and the only reason the question could be asked at all. This node exists separately because the finding is about the *substrate*, not about those videos; burying it there would lose it.
- `sparkling-shadow-0034` **the reference flip** — whose docstrings carry the claim this refutes, and whose measured 2.15 cm through 180° of inversion is the evidence for the fixed-axis exemption.

`verify.check_rate_loop_stability` reports `max_attitude_from_identity_deg`, `frac_above_90deg`, `worst_offaxis_eigenvalue_real_part_per_s`, `min_omega_fixed_axis_alignment`, `omega_on_fixed_axis`, `vendored_loop_stable` and a `stability_reason` string on **every** maneuver, so this stays visible in each artifact rather than only here. Commits `3ad9b7f`, `793b3a9`, `a3d3ce8` on branch `reference-maneuver`; the argument is written up in `docs/REFERENCE_MANEUVER.md`.