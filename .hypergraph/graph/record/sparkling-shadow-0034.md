---
node_id: 89ee2d8b-dfd3-5fda-a6cb-0ee5065abea2
slug: sparkling-shadow-0034
title: 'Reference maneuver: a hand-authored, deterministic flip — the trajectory we WANT, derived not guessed (drift 0.180 m, peak climb +0.617 m, open-loop replay 2.15 cm)'
created_at: '2026-07-31T23:48:19.677765+00:00'
parents:
- wispy-wood-0453
- square-smoke-0918
- hidden-field-0837
- soft-sky-1694
summary: 'New pure-numpy `reference/` package + `scripts/reference_flip.py`: the repo''s first artifact stating what the drone SHOULD do rather than grading what it did. Differential flatness derives attitude/rates/thrust for the powered beats; the flip''s boundary conditions are closed by a damped-Newton shoot (residual 9e-8). Measured vs the acro_flip v1 baseline this replaces as a target (0.672 m drift, 0.410 m dropped, 0.000 m climbed): max_lateral_drift 0.672 -> 0.180 m (-73%), altitude_loss 0.410 -> 0.0002 m, peak_climb 0.000 -> +0.617 m, settle_pos_error 0.000 m, flip 0.968 s, all inside the act-v2 envelope with 5.0%/3.0% thrust/rate headroom. Open-loop replay through WhoopDynamics: 2.15 cm / 0.45 deg over 6.17 s. GREEN as tooling+target. Three structural findings changed the design: flatness CANNOT author the flip (it would demand negative thrust through inversion, so position is an output and the return is a shooting problem); the binding constraint is the rate loop''s 16/s bandwidth, not the 12 rad/s ceiling, so omega(t) is authored as the lag RESPONSE and u = omega + omega_dot/K emitted; and the replay''s action must be an IMPULSE-MATCHED hold (108 cm drift -> 2.15 cm). Honest negatives recorded: stage-2 ''return to the point'' does not converge and the obstruction is structural, not numerical; the sim''s drag is ~8x a real whoop''s and dominates the shape (zero drag doubles the apex, triples the drift); and the motors-off coast has EXACTLY zero control-allocation margin for 10% of the flight — the AIRMODE flip-stall failure in miniature — so --deployable is the variant to score against.'
origin:
  backend: flywheel
  node_id: 89ee2d8b-dfd3-5fda-a6cb-0ee5065abea2
  slug: sparkling-shadow-0034
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Hypothesis

Not a hypothesis so much as a gap. Everything this repo renders is a **policy rollout**: we watch what the drone did and grade it. Nothing said what it *should* do. `acro_flip` v2 (parent `cc831803`) is aimed at a shape described in prose — *straight up, a burst of thrust with a nudge of off-centredness at the end of it, coast around the rotation, catch it level at roughly the same point in space*. Prose is not a target.

Claim under test: **the maneuver can be authored exactly, by hand, with every physical quantity derived rather than guessed** — and the result can be made a literal number the RL is graded against.

The framing worth stating: working out the motor thrust is *not* a job for RL for the powered, level-ish parts of a flight. It is algebra. Differential flatness says a quadrotor's position trajectory determines its attitude, body rates and thrust exactly. Author the path, and the thrust falls out.

## Setup

New **pure numpy + stdlib** package `src/neural_whoop/reference/` (importable without torch, testable without the simulator — the `contract`/`course`/`reward` convention), driven by `scripts/reference_flip.py`. Signs taken from the vendored dynamics (`quadrotor.py:111-142`), not a textbook.

Phase program, psi == 0 throughout: `CLIMB / HOVER / POP / ROLL-IN / COAST / CATCH / RECOVER / LAND`. Powered path beats are flatness-authored septics (8 coefficients, matching {p, p', p'', p'''} at both ends — a quintic makes the emitted body rate jump at every seam, because the flatness map consumes jerk). The flip is command-authored and forward-integrated.

Emits two artifacts, and it matters which is which: `replay.json.gz` (50 Hz) is the **video** artifact — `--preset hero` (parent `86970b83`) renders it with **no changes to the capturer** — and `reference.json` (1 kHz) is the **data** artifact. Two files because 50 Hz aliases this maneuver: the rate brake is under two control steps and the thrust cut is exactly one.

Two variants generated: motors-off (the aesthetic ideal, default for the video) and `--deployable` (coast at the 0.25 throttle floor).

## Results

### The three structural findings, each of which changed the design

**1. Flatness cannot author the flip.** The map inverts `p(t) -> (attitude, thrust)` only while thrust is positive. Through inversion the required specific force still points *up* while the body's thrust axis points *down*, so the map would demand negative thrust. It has no solution there. **Position is an OUTPUT of the flip, not an input** — so "hard-code the path" holds for climb/recover/land, but through the flip we hard-code the *commands* and the path is what physics returns. Getting back to the start therefore stops being an interpolation and becomes a **shooting problem**.

**2. The binding constraint is the rate loop's bandwidth, not the 12 rad/s ceiling.** DiffAero's `RateController` is exactly first order for a single-axis rotation from psi=0: `omega_dot = K(u - omega)`, K = 16/s (`controller.py:82-104`). At omega=11 the largest achievable omega_dot is 16 rad/s^2. A hand-drawn smoothstep *rate command* is simply un-trackable — **and the replay would not show it**: the reference would look perfect and lag reality by ~60 ms. Fixed by authoring omega(t) as the lag **response** and emitting `u = omega + omega_dot/K`, exact and in-limits by construction. The roll-in uses the true exponential lag response, so its command comes out *exactly constant* — the fastest in-limits ramp there is.

**3. The replay's action must be an impulse-matched hold.** A replay frame's action is what a consumer actually *sends*, and DiffAero (like the real FC) holds it for the whole step. Measured open-loop through `WhoopDynamics`:

| command sampled as | 50 Hz | 100 Hz | 400 Hz |
|---|---|---|---|
| instantaneous at t_k | 108 cm | 12 cm | 9 cm |
| instantaneous at midpoint | 84 cm | 60 cm | 5 cm |
| **step mean (shipped)** | **2.15 cm** | **2.30 cm** | **2.20 cm** |

The left-edge hold is first-order and blows up exactly where the maneuver lives (the thrust cut is one control step wide). The step mean is **rate-independent** — the signature of having removed the discretization error rather than shrunk it. Without this the artifact would have quietly drifted a metre while every other check passed.

### The maneuver (roll, Omega=9 rad/s, z_entry 1.2 m)

| metric | v1 flip (parent `cc831803`) | **reference, motors-off** | reference, --deployable |
|---|---|---|---|
| `max_lateral_drift` | 0.672 m | **0.180 m** (-73%) | 0.255 m |
| `altitude_loss` | 0.410 m | **0.0002 m** | 0.0002 m |
| `peak_climb` | 0.000 m | **+0.617 m** | +0.680 m |
| `settle_pos_error` | — | **0.000 m** | 0.000 m |
| `flip_duration_s` | — | 0.968 s | 0.983 s |
| peak thrust / rate cmd | — | 3.80/4.0, 11.64/12.0 | same |

Metrics carry **the same names `AcroFlipTask.metrics()` computes**, over the same window, so "this is the one we want" is a literal number the RL can be graded against.

**Omega=9 over Omega=11, measured not asserted:** peak climb +0.617 vs +0.495 m, and lateral drift **0.180 vs 0.891 m (5x worse)**. Omega=11 also forces an alternate parameterization (the pop pins at its lower bound) so it cannot have a distinct pop beat at all.

### Verification

| check | result |
|---|---|
| flatness round trip, 10k random (a,v,psi) | acc **1e-14**, jerk 1e-13, psi exact |
| hover fixed point | thrust == 1.0, omega == 0, imu == (0,0,+9.81) exactly |
| singularity guards | raise on free fall **and** terminal-velocity descent |
| quaternion hygiene | unit norm, **0 sign flips**, monotone through the flip, ends at 2pi +/- 1e-9 |
| limits | 5.0% thrust / 3.0% rate headroom |
| shoot residuals | phi 0.0, z 2.7e-8, vz -8.6e-8 |
| dynamics residual | vel rms **3.1e-4** @1 kHz vs 7.9e-2 @50 Hz = **254x** fall (expect ~400x for second order) |
| planarity (generator AND sim) | omega_z, off-axis rate **exactly 0.0** |
| open-loop sim replay | **2.15 cm / 0.45 deg** over 6.17 s |

The residual is measured at **two rates on purpose**: a second-order difference must improve ~400x, and if it were flat the bug would be in the flatness map rather than the sampling. Masking is derived from structure (every authored command seam, 14 of 6170 frames, all listed in `verify.json`) and `classify_breaks` measures **exactly two** acceleration steps — ROLL-IN->COAST (-3.80 collective, 37.3 m/s^2) and COAST->CATCH (+2.70, 26.5 m/s^2) — which is the "C1 position with two intentional C2 breaks" claim, verified rather than asserted.

61 new tests (28 pure-numpy, 5 open-loop sim); full suite 333 passed.

## Verdict / Honesty

**GREEN** as tooling and as a target. Four things that did *not* go as planned, all recorded in the artifact rather than a footnote:

**Stage 2 (return to the POINT) does not converge, and the obstruction is structural.** The roll-in tilts the thrust axis one way and the catch the other, so the lateral *impulses* cancel essentially for free (v_lateral_end 4e-5 m/s). But the drone drifts monotonically to one side for the whole coast in between, and no powered-phase thrust split undoes that displacement *within the flip*. Closing it needs a deliberate counter-lean **before** the pop — what a freestyle pilot actually does — which is a different maneuver from the one specified. Stage 1 is kept, RECOVER flies out the 0.18 m, and `max_lateral_drift` is a headline number rather than hidden.

**The sim's drag dominates the shape and is ~8x a real whoop's.** D = 0.10 N/(m/s) on 32 g gives a 3.14 m/s terminal velocity where a real 65 mm whoop is 8-12, and it is *linear* where reality is quadratic. Shipped as a column, not a caveat — the same authored commands re-flown:

| drag | terminal v | peak climb | lateral drift |
|---|---|---|---|
| sim (what this IS) | 3.14 m/s | +0.617 m | 0.180 m |
| none | inf | **+1.224 m** | **0.584 m** |
| real_est | 10.0 m/s | +0.926 m | 0.363 m |

Zero drag doubles the apex and triples the drift. The shape is **not** robust to the coefficient.

**The motors-off coast has exactly zero control-allocation margin — for 10% of the flight.** Zero thrust can produce no torque at all, so the airframe has **no rate authority** through the coast and could not correct a disturbance if it had one. This is the AIRMODE flip-stall failure of parent `42ceffce` (3 stalls parked inverted at idle throttle) in miniature, arrived at independently from the allocation algebra. **If this reference is used as an RL target or a scoring reference, use `--deployable`** (`zero_authority_frac` 0.10 -> 0.00). Motors-off stays the default for the video only. Note the catch itself is comfortably feasible (+0.98 margin) — the plan predicted the catch would be the infeasible part; it is not, because authoring the brake as a smoothstep omega(t) rather than a step command asks for far less torque.

**Two corrections to existing claims:**
- `acro_flip`'s docstring did its worked example **without drag** and is off by 25-40% ("falls ~1 m", v_up ~2.4 m/s, "returns at -2.4 m/s", "+0.3 m up, -0.1 m down"). Measured against this airframe: pop to **+3.26 m/s**, return at **-2.19 m/s**, **+0.617 m** climb, **0.000 m** loss. Docstring corrected.
- The coast IMU is a **V** (1.06 g -> 0.09 g at the apex -> 0.7 g), not a flat free-fall null and not a monotone ramp: drag scales with speed, which is large at both ends of a ballistic arc and zero at the top.

**Actionable mismatch found:** the reference's `peak_climb` (0.617 m, 0.680 deployable) **exceeds** `configs/acro_flip_v2.yaml`'s `pop_allow` (0.4 m), so under the current reward the shape we say we want collects a small `rise_scale` penalty. Raising `pop_allow` to ~0.7 is a training decision, so it is flagged, not silently changed.

**Not modeled:** body rate is exactly constant through the coast to machine precision — a property of the simulator (drag applies only to linear velocity; both gyroscopic terms vanish on a symmetric-inertia axis with omega_z=0), not of a real whoop, which would shed 5-15% of its roll rate to blade flapping over 0.6 s.

## Lineage

- `cc831803` **acro_flip v2 setup** — this is the target that retrain is aimed at; its v1 measurements (0.672 / 0.410 / 0.000 m) are the baseline in the table above.
- `563fc6d9` **visual observability seam** — extended with an additive per-frame `imu` channel + `meta.imu_info` (no version bump, per the contract's rule). Body-frame specific force, +1 g on body +z at rest, matching the pilot's `az_ref` calibration, so a real flight log (`analysis/flight_log.py`'s acc_x/y/z) and this reference land in the same slot.
- `86970b83` **--preset hero** — the video rides on it unchanged; framing check reports worst |NDC| 0.47 and apparent size 17.8-20.2% of frame height.
- `42ceffce` **first real blind flip** — its zero-collective rate-authority stall is the same failure the allocation check finds structurally here.

Commit `b1752012a44353c00735ea2ef4ff7f011acbb52e` (branch `reference-maneuver`). Docs: `docs/REFERENCE_MANEUVER.md`.