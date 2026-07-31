# The reference maneuver — "this is the one we want", as data

Everything else in this repo renders a **policy rollout**: we watch what the drone did and grade
it. Nothing said what it *should* do. The `acro_flip` v2 retrain is aimed at a shape described in
prose — *straight up, a burst of thrust with a nudge of off-centredness at the end of it, coast
around the rotation, catch it level at roughly the same point in space*. Prose is not a target.

This is that target. The maneuver is **authored by hand**, deterministically, and every physical
quantity — attitude, body rates, collective thrust, and the accelerometer the onboard IMU would
read — is **derived** from it rather than guessed. Nothing here trains or changes a policy: it is a
generator (`src/neural_whoop/reference/`), a CLI (`scripts/reference_flip.py`), a chart pack, and a
set of tests.

```bash
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --z-entry 1.2 \
    --out runs/reference/flip_roll
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --deployable \
    --out runs/reference/flip_roll_deployable

uv run python scripts/capture_video.py --replay runs/reference/flip_roll/replay.json.gz \
    --out runs/reference/flip_roll/reference_flip.mp4 --preset hero --width 1080 --height 1080
```

Two deliverables, and it matters which is which:

- **`replay.json.gz`** (50 Hz) is the **video** artifact — Studio-playable, and `--preset hero`
  renders it with *no changes to the capturer*.
- **`reference.json`** (1 kHz) is the **data** artifact — the fine stream, the model verbatim, the
  shooting record with its final residuals, and the headline metrics.

Two files because **50 Hz aliases this maneuver**: the rate brake is under two control steps and
the thrust cut is exactly one, so anything that finite-differences the replay sees a 250 rad/s²
event as a one-frame spike.

---

## Why thrust is algebra, not RL

You do not search for a quadrotor's thrust profile — you *solve* for it. A quadrotor is
differentially flat in `(x, y, z, ψ)`: the position trajectory **determines** the attitude, body
rates and collective exactly. Author the path and the thrust falls out.

Signs are taken from the vendored dynamics (`third_party/diffaero/dynamics/quadrotor.py:111-142`),
not from a textbook — `G_vec = [0,0,−9.81]`, drag is a **force** `R D Rᵀ v`, quaternions xyzw:

```
f    = p̈ + g·ê_z + (D/m)·ṗ                  [isotropic D → closed form]
normed_thrust = ‖f‖ / g                      [mass cancels — controller.py:102]
z_B  = f/‖f‖ ;  y_B = (z_B × x_C)/‖·‖ ;  x_B = y_B × z_B
ω_x  = −(y_B·ḟ)/‖f‖ ;  ω_y = +(x_B·ḟ)/‖f‖    [exact, not finite-differenced]
```

Because the map consumes **jerk**, powered segments use a **septic** (8-coefficient) polynomial per
axis matching `{p, ṗ, p̈, p⃛}` at both ends. A quintic matches only through acceleration, which makes
the emitted body rate jump at every seam.

### The structural finding: flatness cannot author the flip

The map inverts `p(t) → (attitude, thrust)` only while thrust is positive. Through inversion the
required specific force still points **up** while the body's thrust axis points **down**, so the map
would demand negative thrust. It has no solution there.

So **position is an output of the flip, not an input.** "Hard-code the path" holds for the climb,
recovery and landing; through the flip we hard-code the *commands* and the path is what physics
returns. That is not a compromise — it is the thing itself: once the motors cut, where the drone
goes is gravity's business, not the author's.

Getting back to the starting point therefore becomes a **shooting problem**, not an interpolation.

### The binding constraint is the rate loop's bandwidth, not the 12 rad/s ceiling

DiffAero's `RateController` is exactly first order for a single-axis rotation from ψ = 0:
`ω̇ = K(u − ω)` with `K = 16 s⁻¹` (`controller.py:82-104`). At `ω = 11` the largest achievable `ω̇` is
`16·(12−11) = 16 rad/s²`. **A hand-drawn smoothstep rate profile is simply un-trackable — and the
replay would not show it.** The reference would look perfect and lag reality by ~60 ms.

So the rate segments author `ω(t)` as the **response** and emit `u = ω + ω̇/K`, which is exact and
in-limits by construction rather than by hope. The roll-in uses the true lag response
`ω(t) = u(1 − e^{−Kt})` to a constant command, so `u` comes out *exactly constant* — the fastest
in-limits ramp there is.

---

## The phase program

`ψ ≡ 0` throughout, rotation about the maneuver axis:

| phase | kind | authored | notes |
|---|---|---|---|
| `CLIMB` | `PathSegment` | rest → `z_entry` over 1.4 s | the legible "straight up" |
| `HOVER` | `PathSegment` | hold, 0.4 s | |
| `POP` | `RateSegment` | level, thrust ramps 1.0 → 3.8 | the burst |
| `ROLL-IN` | `RateSegment` | thrust held, `ω → Ω` | the "nudge of off-centredness" |
| `COAST` | `BallisticSegment` | thrust → floor, **zero commanded torque** | |
| `CATCH` | `RateSegment` | brake `ω → 0`, arrest, taper to hover | |
| `RECOVER` | `PathSegment` | null the residual lateral offset, settle | |
| `LAND` | `PathSegment` | `z_entry` → rest over 2.2 s | |

**No "props spooling on the ground" beat.** At rest a `PathSegment` yields `normed_thrust = 1.0`,
which lifts off — the model has no contact. Start at liftoff, end at touchdown, and leave the
spool-up to the video's title card. That is strictly better than
`scripts/hero_takeoff_flip_land.py`'s `ground_contact()` clamp, which exists only because a PD
asymptotes toward its setpoint and never arrives.

### The shoot

`solve_flip` is a damped Newton shoot with a forward-difference Jacobian and bounded unknowns.

**Stage 1 (3×3, required)** — unknowns `(T_pop, T_coast, A_catch)` against residuals
`(φ_end − 2π, z_end − z_entry, vz_end)`. This is a 3×3 rather than the 4×4 you would write if you
authored the rate *command*: because the catch authors `ω(t)` as a profile terminating at exactly
zero, `ω_end = 0` holds **by construction** and is not a free residual. That is strictly better than
solving for it — it cannot be missed by a tolerance. Converges to `‖r‖ ≈ 1e-7` in ~25 iterations.

There is an **alternate parameterization** for high Ω, where `T_pop` pins at its lower bound. That
is a physical statement, not a solver failure: reaching a rate close to the command ceiling takes a
long roll-in (the loop approaches its command asymptotically), and a long roll-in at full collective
already over-delivers the climb. The pop cannot be made shorter, so it is made **weaker** — solve
for `A_rollin` instead. This is what lets Ω = 11 close at all.

**Stage 2 (5×5, attempted)** — adds `(A_rollin, T_hold)` against `(lateral_end, v_lateral_end)` so
the drone returns to the *point*, not just the altitude.

**Stage 2 does not converge, and the reason is structural rather than numerical.** The roll-in tilts
the thrust axis one way and the catch tilts it the other, so the lateral *impulses* can cancel —
`v_lateral_end` comes out at 4e-5 m/s essentially for free. But the drone drifts monotonically to one
side for the whole coast in between, and no choice of powered-phase thrust brings that displacement
back *within the flip*. Closing it would need a deliberate counter-lean **before** the pop (what a
freestyle pilot actually does), which is a different maneuver from the one specified. So stage 1 is
kept, `RECOVER` flies out the 0.18 m offset, and `max_lateral_drift` is reported as a headline
number rather than hidden. The solve records which stage was achieved in `reference.json`.

A silently non-converged solve is the easiest way to ship a wrong reference that looks perfect, so
every unknown is bounded, `φ` is asserted monotone through the flip (it crosses 2π exactly once),
and the final residuals are published.

---

## Measured results (the shipped reference)

`--axis roll --omega 9.0 --z-entry 1.2`, against `RefModel()` (the `randomize_airframe=False`
airframe):

| metric | motors-off | `--deployable` |
|---|---|---|
| `max_lateral_drift` | **0.180 m** | 0.255 m |
| `peak_climb` | **+0.617 m** | +0.680 m |
| `altitude_loss` | 0.0002 m | 0.0002 m |
| `settle_pos_error` | 0.000 m | 0.000 m |
| `flip_duration_s` | 0.968 s | 0.983 s |
| `peak_normed_thrust` | 3.80 / 4.0 (5.0% headroom) | 3.80 |
| `peak_body_rate` | 9.0 rad/s | 9.0 rad/s |
| peak rate **command** | 11.64 / 12.0 (3.0% headroom) | 11.64 |
| `vz` range | −2.19 … +3.26 m/s | −2.18 … +3.38 m/s |
| `T_pop` / `A_catch` | 0.125 s / 2.70 | 0.141 s / 2.70 |

### Why Ω = 9 and not 11

Measured, not asserted — both solve, and the comparison is one-sided:

| | Ω = 9 | Ω = 11 |
|---|---|---|
| peak climb | **+0.617 m** | +0.495 m |
| lateral drift | **0.180 m** | **0.891 m** (5× worse) |
| pop | a real 125 ms burst | pinned to a token 20 ms beat |

Ω = 9 buys a longer, more legible inverted coast, more apex gain that reads on camera, and a fifth
of the lateral excursion. Ω = 11 also forces the alternate parameterization, i.e. it cannot have a
distinct pop beat at all.

### Two variants means two solves, not one stream under two limits

The 0.25 throttle floor puts a quarter g of *downward* thrust on an inverted drone for the whole
coast, so the shoot returns a genuinely different trajectory: `T_pop` 0.125 → 0.141 s, apex +0.617 →
+0.680 m, drift 0.180 → 0.255 m. The artifact names keep them apart.

---

## Verification (`verify.json`)

| check | result |
|---|---|
| flatness round trip, 10k random `(a, v, ψ)` | acc **1e-14**, jerk 1e-13, ψ exact |
| hover fixed point | `normed_thrust == 1.0`, `ω == 0`, `imu == (0,0,+9.81)` — exactly |
| singularity guards | raise on free fall **and** on terminal-velocity descent |
| quaternion hygiene | unit norm, **0 sign flips**, monotone through the flip, ends at 2π ± 1e-9 |
| limits | inside the envelope with 5.0% thrust / 3.0% rate headroom |
| control allocation | feasible; `min_margin_torqued` +0.98 |
| dynamics residual | vel rms **3.1e-4** @ 1 kHz vs 7.9e-2 @ 50 Hz — a **254×** fall |
| planarity | `ω_z` and off-axis rate **exactly 0.0** |
| open-loop sim replay | **2.15 cm / 0.45°** over 6.17 s |

**Why the residual is measured at two rates.** A second-order central difference must improve by
~(20)² = 400× between 50 Hz and 1 kHz. Observing ~254–349× says the residual is dominated by
*sampling*; if it were flat, the bug would be in the flatness map rather than in the discretization.
That is what makes running it twice diagnostic instead of decorative.

**Masking is derived from structure, not from eyeballing the residual.** Frames straddling any
authored command step are excluded (14 of 6170 at 1 kHz, 4.5% at 50 Hz) and listed in `verify.json`,
and `classify_breaks` reports what actually steps at each seam. It measures **exactly two**
acceleration breaks — `ROLL-IN→COAST` (−3.80 collective, 37.3 m/s²) and `COAST→CATCH` (+2.70,
26.5 m/s²) — which is the "C¹ position with two intentional C² breaks" claim, verified.

It is tempting to mask only those two thrust seams, and that was the first attempt. It is not
enough: the **rate command** steps too (`ω̇` jumps 0 → 186 rad/s² when the roll-in's constant command
switches on). `ω` stays continuous there, but a central difference of the quaternion is
second-order only while `ω̇` is, so masking thrust alone left a 2e-2 quaternion residual in plain
sight.

### The replay's `action` is an impulse-matched hold, and that is load-bearing

A replay frame's action is what a consumer actually *sends*, and DiffAero (like the real flight
controller) **holds** it for the whole control step. The reference is a continuous command profile,
so the honest discretization is the **mean over the step**. Measured by replaying the emitted stream
open-loop through `WhoopDynamics`:

| command sampled as | 50 Hz | 100 Hz | 400 Hz |
|---|---|---|---|
| instantaneous at `t_k` | 108 cm | 12 cm | 9 cm |
| instantaneous at midpoint | 84 cm | 60 cm | 5 cm |
| **step mean (what we emit)** | **2.15 cm** | **2.30 cm** | **2.20 cm** |

The left-edge hold is first-order and blows up exactly where the maneuver lives — the thrust cut is
one control step wide, so holding the pre-cut collective for an extra 20 ms injects a velocity error
that never comes back. The step mean is **rate-independent**, which is the signature of having
removed the discretization error rather than merely shrinking it. The instantaneous profile is still
available at full resolution in `reference.json`'s 1 kHz stream.

### `ψ ≡ 0` is a tripwire, not a formality

It is silently load-bearing in three places at once: it makes DiffAero's `RateController` frame bug
(`controller.py:93`, `R_i2b @ w`) an **exact** no-op (identity for a rotation about the same axis the
rate is on); it is what keeps `ω` exactly constant through the coast; and it keeps the heading
construction non-degenerate. A future cinematic yaw sweep breaks all three and **only the first
fails loudly**. So it is asserted, in the generator *and* in the simulator, and both report exactly
`0.0`.

The planarity assertion measures the **quaternion**, not euler yaw: a pitch flip passes through 180°
of pitch, where the ZYX yaw `atan2(R₁₀, R₀₀)` reads exactly π even though the airframe never yawed.

---

## Honest caveats

**The sim's drag is the dominant modeling error and this reference bakes it in.** `D = 0.10 N/(m/s)`
on 32 g gives a **3.14 m/s terminal velocity**, where a real 65 mm whoop is 8–12 m/s — roughly 8×
too much drag at the flip's speeds, and *linear* where reality is quadratic. Coast duration, apex
height, return speed and the entire coast IMU trace are artifacts of **this simulator**. This is
shipped as a column rather than a footnote: the same authored command stream, re-flown under other
drag models —

| drag model | `D` | terminal v | peak climb | lateral drift |
|---|---|---|---|---|
| `sim` (what the reference IS) | 0.100 | 3.14 m/s | +0.617 m | 0.180 m |
| `none` | 0 | ∞ | **+1.224 m** | **0.584 m** |
| `real_est` | 0.031 | 10.0 m/s | +0.926 m | 0.363 m |

Zero drag doubles the apex and triples the drift. The shape is *not* robust to the coefficient, so
the caveat is not overcautious.

**Body rate is exactly constant through the coast, to machine precision** — and that is a property
of the simulator, not an approximation. DiffAero applies drag only to *linear* velocity (there is no
`−Cω` term), and with `ω_z ≡ 0` on a symmetric-inertia axis both gyroscopic terms vanish identically.
A real whoop would shed 5–15% of its roll rate to blade flapping over a 0.6 s coast. **That is not
modeled here.**

**The coast IMU is a V, not a flat free-fall null.** Drag scales with *speed*, which on a ballistic
arc is large at both ends and zero at the apex, so the magnitude runs **1.06 g → 0.09 g → 0.7 g**.
There is a genuine free-fall null, but only for the instant the drone is motionless at the top. The
body-z component also goes strongly negative (≈ −10 m/s²) at coast entry: the drone is climbing fast
along its own +z, drag pushes back along −z, and that is exactly what an accelerometer bolted to the
frame reads. Anyone expecting a flat null will think the generator is broken.

**Control allocation: the interesting number is not the one you expect.** The catch is comfortably
feasible (`min_margin_torqued` +0.98), because authoring the brake as a smoothstep `ω(t)` rather than
a step *command* asks for modest torque. The binding problem is structural and elsewhere: through the
motors-off coast the margin is **exactly 0** — zero thrust demanding zero torque — so for **10% of
the flight the airframe has no rate authority at all** and could not correct a disturbance if it had
one. That is the AIRMODE flip-stall failure of `docs/SIM2REAL.md` in miniature. **If this reference
is ever used as an RL target or a scoring reference, use `--deployable`**, whose 0.25 floor keeps
authority alive throughout (`zero_authority_frac` 0.10 → 0.00). Motors-off stays the default for the
*video*, since it is the aesthetic ideal.

**The landing is slower than you would expect (2.2 s for 1.19 m), and that is the drag again.**
Descending, the simulator's oversized drag holds the airframe up, so a quick landing asks for a
below-singular collective and the flatness map refuses it. A real whoop would need real throttle
there.

---

## Using it as an RL target

The metrics deliberately carry **the same names `acro_flip` computes**
(`AcroFlipTask.metrics()`): `max_lateral_drift`, `peak_climb`, `altitude_loss`,
`settle_pos_error` — measured over the same window (a level hover at `z_entry` through the end of
the recover). So "this is the one we want" is a literal number the RL can be graded against.

Two things worth knowing before wiring it up:

1. **Use `--deployable`.** See the allocation caveat above.
2. **The reference's pop exceeds `acro_flip`'s current free headroom.** `configs/acro_flip_v2.yaml`
   sets `pop_allow: 0.4` m of free climb, but the reference's `peak_climb` is **0.617 m**
   (0.680 m deployable). Under the current reward the maneuver we say we want would collect a small
   `rise_scale` penalty. That is a genuine, actionable mismatch between the stated target and the
   reward — raising `pop_allow` to ~0.7 is a training decision, so it is flagged here rather than
   changed.

The `imu` channel is what makes the deliverable dual-use: `analysis/flight_log.py` already carries
`acc_x`/`acc_y`/`acc_z`, so a real flight and this reference land in the same slot and become
directly comparable (see `docs/VISUAL_CONTRACT.md`).

---

## Layout

| file | contents |
|---|---|
| `reference/model.py` | `RefModel` — the airframe derived against; a test asserts it matches `WhoopParams` |
| `reference/limits.py` | the `ActionLimits` scalars mirrored (a pure module cannot import torch); a test asserts equality |
| `reference/flatness.py` | the flatness map, its inverse, and quaternion helpers |
| `reference/segments.py` | `PathSegment` / `RateSegment` / `BallisticSegment` / `Trajectory` |
| `reference/maneuvers.py` | `FlipSpec`, `solve_flip` (the shoot), `build_sequence` |
| `reference/imu.py` | `specific_force_body` — what the accelerometer reads |
| `reference/emit.py` | `Samples` → replay + `reference.json` |
| `reference/verify.py` | the residual / limit / allocation / continuity checks |
| `tests/test_reference.py` | 28 pure-numpy tests (no simulator) |
| `tests/test_reference_flip.py` | the open-loop sim replay (the only torch test) |

Charts live in `viz/render.py`: `plot_reference_telemetry` (six shared-x panels) and
`plot_reference_envelope` (the "flip strip" — the maneuver plane with a body-z tick every few
frames, which is the single most legible picture of the maneuver).

**Charts must never compute on `rpy`.** `quaternion_to_euler` (`utils/math.py:190`) is ZYX with
pitch clamped to ±90°, so a full 360° roll renders there as a 180° wobble. The replay still *carries*
`rpy` because the schema requires it; everything downstream uses the unwrapped angle from the
quaternion — and unwraps the **half** angle before doubling, because doubling first makes the flip a
4π jump that `np.unwrap` reads as no jump at all.
