# Reference maneuvers — "this is the one we want", as data

Everything else in this repo renders a **policy rollout**: we watch what the drone did and grade
it. Nothing said what it *should* do. The `acro_flip` v2 retrain is aimed at a shape described in
prose — *straight up, a burst of thrust with a nudge of off-centredness at the end of it, coast
around the rotation, catch it level at roughly the same point in space*. Prose is not a target.

This is that target. The maneuver is **authored by hand**, deterministically, and every physical
quantity — attitude, body rates, collective thrust, and the accelerometer the onboard IMU would
read — is **derived** from it rather than guessed. Nothing here trains or changes a policy: it is a
generator (`src/neural_whoop/reference/`), a CLI (`scripts/reference_maneuver.py`), a chart pack,
and a set of tests.

**Three maneuvers, and they need three different authoring mechanisms.** That is the finding this
package is really about, not the individual clips:

| | mechanism | closes to | flyable in DiffAero? |
|---|---|---|---|
| **`flip`** | flatness *cannot* author it → author the **commands**, close with a damped-Newton **shoot** | ~1e-8 (solved) | yes |
| **`swing`** | flatness authors the **whole beat** — **no shoot at all** | **0.00e+00** (exact) | yes |
| **`orbit`** | flatness authors it, with a winding `ψ` | 0.00e+00 (exact) | yes — **since the 2026-08-01 rate-loop fix** |

```bash
uv run python scripts/reference_maneuver.py --maneuver swing --out runs/reference/swing_roll --video
uv run python scripts/reference_maneuver.py --maneuver orbit --out runs/reference/orbit_z  --video
uv run python scripts/reference_maneuver.py --maneuver flip --z-entry 0.9 \
    --out runs/reference/flip_roll_z09 --video

# The original 1.2 m flip. reference_flip.py is a thin alias, so this still works verbatim.
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --z-entry 1.2 \
    --out runs/reference/flip_roll
uv run python scripts/reference_flip.py --axis roll --omega 9.0 --deployable \
    --out runs/reference/flip_roll_deployable
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

## The reference video contract

`--preset hero` is the **deliverable**, not a flag someone happened to type. Every reference
maneuver's MP4 comes out of exactly this invocation and no other, so the three clips are
comparable *pictures* rather than three separate camera tunes that happen to look similar:

```
scripts/capture_video.py --replay <replay.json.gz> --out <out.mp4>
    --preset hero --width 1080 --height 1080
```

It is written down once, in `src/neural_whoop/reference/video.py`, and
`scripts/reference_maneuver.py --video` shells out to it. **`--video` takes no camera flags on
purpose.** `tests/test_capture_preset.py` pins the preset field by field — with the measured reason
each value has its value — and additionally asserts that every preset-able flag declares *no*
argparse default, because a flag with its own default would silently outrank the preset and nothing
else would notice.

**What the framing check must report.** Every render prints two measured numbers, and the generator
copies both into `run.json`:

- **worst `|NDC|`** — how close the airframe came to the frame edge (1.0 *is* the edge). Under 0.8
  is comfortable.
- **apparent-size spread** — how much its on-screen height varied. The follow rig's whole promise is
  that this is fixed *by construction*, so a large spread means the rig did not deliver the shot
  even though the subject never left frame. A rig that keeps the drone in frame by letting it shrink
  has not held the shot, and only the second number notices.

Measured on the three shipped clips:

| clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| `flip_roll_z09` | 0.47 | 17.8–20.2% | **13%** |
| `swing_roll` | 0.44 | 17.5–21.8% | 25% |
| `orbit_z` | 0.65 | 13.9–30.2% | **117%** |

### The orbit found a limit of the preset's reach, and it is not the documented one

The fallback ladder was written for "the subject leaves frame": lower `--drone-frac`, then raise
`--max-drift`, then `--shot fit`. **The orbit does not leave frame** (0.65, comfortably inside), so
no rung was taken and the shipped clip is plain `--preset hero`. What it fails is the *other*
guarantee — apparent size swings 117%.

Measured, rather than reasoned about:

| variant | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| `hero` (shipped) | 0.65 | 13.9–30.2% | 117% |
| `--drone-frac 0.15` | 0.47 | 10.4–17.4% | 67% |
| `--drone-frac 0.10` | 0.36 | 7.4–10.4% | 41% |
| `--max-drift 0.45` | 0.83 | 13.9–30.2% | **117% — no effect** |
| **`--track-smooth 6`** | 0.32 | **18.2–20.1%** | **10%** |
| `--shot fit` | 0.52 | 3.3–4.7% (tiny) | 42% |

**The lever is `track_smooth`, which the ladder does not mention.** The mechanism: the follow rig
holds a constant offset from a *smoothed* subject track, and `hero`'s `track_smooth = 20` is a
±0.4 s window. The orbit's revolution period is 0.898 s, so that window averages very nearly a whole
revolution — the smoothed track collapses onto the circle's centre and the rig degenerates into a
**tripod**, with the drone circling toward and away from a stationary camera. At `--track-smooth 6`
(±0.12 s, ~13% of a revolution) the track actually follows the circle and the spread drops to 10%,
better than the swing's.

So the honest statement of the preset's reach is: **`hero` assumes the subject's motion is slow
compared to its smoothing window. A periodic maneuver whose period is comparable to
`2 × track_smooth` frames defeats it** — not by losing the subject, but by silently turning the
follow rig into a tripod. The preset is **not** retuned here; that is a decision about every other
clip in the repo, and it is recorded with its numbers so it can be made deliberately.

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

### The complement: the swing needs no shoot at all

The flip's structural finding has an exact counterpart, and finding it is what turned "the flip
package" into "the reference package". Author the pendulum angle as

```
θ(t) = Θ · W(t) · sin(ωt) ,   ω = 0.8·√(g/L) ,   ωT = 2π·n_swings
W    = septic window: 35x⁴−84x⁵+70x⁶−20x⁷ up, hold, down (ramp_frac 0.25 each end)
```

and the beat starts *and ends* at the hover point at **machine precision** — measured
`|p−p₀| = |v| = |a| = |j| = 0.00e+00`. `sin` vanishes at both ends because `ωT` is a whole number of
periods, and the envelope vanishing through its **second** derivative there kills every `Ẇ` cross
term. Differential flatness authors the entire maneuver, thrust included. There is no
boundary-value problem, so `build().solution is None` — which is a *result*, not an omission.

`W` being flat through its **third** derivative is what makes the seams into HOVER and out to
SETTLE silent: the flatness map turns jerk into body rate, so a quintic envelope at a septic seam
would step the emitted body rate visibly, on the frame the maneuver starts.

---

## The phase programs

Each spec carries its own `phase_labels`, and the capture page reads them straight out of
`meta.scene_info.phase_labels` — so **per-maneuver captions come free**, with no renderer change.

**`flip`** — `ψ ≡ 0` throughout, rotation about the maneuver axis:

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

**`swing`** — `CLIMB · HOVER · SWING · SETTLE · LAND`. `SWING` is deliberately **one**
`AnalyticPathSegment`: splitting it per half-swing would put a seam in the middle of a maneuver
that has none, and having no seam anywhere is the point.

**`orbit`** — `CLIMB · HOVER · WIND-UP · ORBIT · WIND-DOWN · SETTLE · LAND`. The three orbit beats
are three `AnalyticPathSegment`s over **one** authored path at different time offsets, so the joins
between them are exact to the last bit — they are labels, not seams.

**No "props spooling on the ground" beat.** At rest a `PathSegment` yields `normed_thrust = 1.0`,
which lifts off — the model has no contact. Start at liftoff, end at touchdown, and leave the
spool-up to the video's title card. That is strictly better than
`scripts/hero_takeoff_flip_land.py`'s `ground_contact()` clamp, which exists only because a PD
asymptotes toward its setpoint and never arrives.

### `AnalyticPathSegment` — why not just use a septic?

`PathSegment` fits a septic between endpoint conditions: the right tool when what you know is
"start here, end there, smoothly". It is the wrong tool for a **shape**. A pendulum arc and a circle
are not interpolation problems, and forcing one through a polynomial would only approximate geometry
we already have exactly. `AnalyticPathSegment` takes `path(t) → (p, v, a, j)` with **analytic**
derivatives — there is no finite differencing anywhere in the position chain, because the flatness
map eats jerk and a differenced jerk would put its noise straight into the emitted body rate.

One asymmetry worth knowing: a `PathSegment` takes its start conditions from the state it is handed
and therefore *cannot* be discontinuous, while an analytic segment ignores that state entirely. So
it **asserts** its entry position rather than assuming it — otherwise a mis-placed station would
teleport the drone one frame before the maneuver, silently.

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

## Measured results — the swing and the orbit

Both against `RefModel()` (the `randomize_airframe=False` airframe). Both are **fully powered**:
there is no motors-off coast, `zero_authority_frac` is exactly 0, and neither needs (or should
implicitly get) a `--deployable` variant the way the flip does.

### `swing` — `L = 0.9 m, Θ = 50°, 0.8× resonance, 2 swings, z = 0.9` (`runs/reference/swing_roll`)

| | |
|---|---|
| duration / swing period | 4.76 s / 2.38 s |
| half-width / rise / apex | ±0.689 m / 0.321 m / z = 1.221 m |
| **peak tilt** | **69.3°** — 1.39× the swing amplitude, *not* equal to it |
| normed thrust (in the swing) | 0.666 … 1.632 of 4.0 |
| rate command | 7.94 of 11.64 (**32% headroom**) |
| yaw command | exactly 0.0 |
| allocation `min_margin_torqued` | **+0.646** — never near infeasible |
| planarity | `max|ω_z| = 0.0`, `max|off-axis quat| = 0.0` — **exact** |
| attitude from identity | 69.3° max — under 90°, so the rate loop is stable twice over |
| C² breaks | **none anywhere** |
| **open-loop sim replay @ 50 Hz** | **0.29 cm / 0.25°** over 8.96 s |

0.29 cm beats the flip's 2.15 cm by 7.5×, and the reason is the row above it: with no command step
anywhere there is no zero-order-hold error to leave behind. The test asserts the *ordering*, not
just the number, so the measurement stays tied to the explanation.

**`ramp_frac` is what spends the rate budget**, and it is not cosmetic — measured on this sizing:

| `ramp_frac` | peak tilt | rate command |
|---|---|---|
| 0.20 | — | **out of envelope (refused)** |
| **0.25** (shipped) | **69.3°** | **7.94** |
| 0.30 | 58.4° | 5.88 |
| 0.50 | 55.5° | 3.48 |

### `orbit` — `R = 0.5 m, Ω = 7 rad/s, 3 revs, nose-in, z = 0.9` (`runs/reference/orbit_z`)

| | |
|---|---|
| duration / revolution period | 3.85 s / 0.898 s |
| radius / speed | 0.5 m (a 1 m circle) / 3.50 m/s |
| peak bank | 69.9° |
| normed thrust | 1.00 … 2.913 of 4.0 (27% headroom) |
| rate command, roll-pitch / yaw | 7.044 of 11.64 / 3.637 of 6.0 |
| revolutions | exactly **3.000000** |
| **axis-pointing error** | **24.06° median** — closed form `atan((D/m)/Ω)`, radius-independent |
| heading conditioning | 0.372 min (forward map fine; a round-trip test must filter on it) |
| non-planar | `max|ω_z| = 3.34`, attitude reaches 179.9° from identity |
| C² breaks | none anywhere |
| **open-loop sim replay, as vendored** | **17.65 m / 180°** — the frame bug, not the reference |
| **same, with `R_i2b` removed** | **1.80 cm / 0.65°** |

The revolution count is *exactly* 3 because the septic ramp integrates to exactly ½, so the orbit's
duration `2πn / (Ω(1−ramp_frac))` is closed form rather than quadrature-accurate.

---

## Measured results (the shipped flip)

`--axis roll --omega 9.0 --z-entry 1.2`, against `RefModel()` (the `randomize_airframe=False`
airframe). Re-solved at `--z-entry 0.9` (`runs/reference/flip_roll_z09`) every number below is
unchanged except the apex, which moves 1.82 → **1.517 m** — the flip's shape does not depend on the
altitude it is flown at:

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

It is silently load-bearing in two places: it is what keeps `ω` exactly constant through the coast,
and it keeps the heading construction non-degenerate. A cinematic yaw sweep breaks both and
*neither* fails loudly. So it is asserted, in the generator *and* in the simulator, and both report
exactly `0.0`.

Until 2026-08-01 there was a **third**, and it mattered more than either: `ψ ≡ 0` made DiffAero's
`RateController` frame bug (`R_i2b @ w`) an exact no-op, which is the only reason the flip tracked
through 180° of inversion on a simulator that could not actually do it. That one *did* fail loudly
— eventually, once a maneuver was authored that broke the invariant. The bug is fixed now, so the
flip's stability no longer rests on planarity; the assertion stays for the two reasons above, and
because it is the check that made the bug findable at all.

The planarity assertion measures the **quaternion**, not euler yaw: a pitch flip passes through 180°
of pitch, where the ZYX yaw `atan2(R₁₀, R₀₀)` reads exactly π even though the airframe never yawed.

The orbit is the maneuver that finally *did* break `ψ ≡ 0`, and what it exposed is the next section.

---

## The rate-loop finding: DiffAero's vendored controller was unstable past 90° of attitude

**Status: found by the orbit, FIXED in the fork on 2026-08-01.** This is about the **substrate**,
not about any of these videos. It is the most consequential thing this package produced — a latent
correctness bug in the simulator every policy in this lab is trained against, which was invisible
to every maneuver the lab had flown up to that point.

`third_party/diffaero/dynamics/controller.py` used to compute the *measured* body rate as

```python
actual_angvel_b = torch.bmm(R_i2b, w.unsqueeze(-1)).squeeze(-1)      # R_i2b @ w
```

but `w` is **already body-frame** — `quadrotor.py` integrates `q̇ = ½q⊗[w,0]` and applies
`M = τ − w×Jw`, both body-frame. The controller's own `ω×Jω` term cancels the rigid body's exactly,
so the closed loop reduces to

```
ω̇ = K(u − R·ω)          instead of          ω̇ = K(u − ω)
```

`R` is a rotation, so its eigenvalues are `1` and `e^{±iθ}` with `θ` the attitude's rotation angle
from identity. The loop's eigenvalues are therefore `−K` and `−K·e^{±iθ}`, whose **real part is
`−K·cos θ`** — negative (stable) below 90° of attitude, **positive (divergent) above it**. That is
verified directly in `tests/test_reference.py` by building `−K·R` and reading off its eigenvalues,
rather than cited.

**The 90° threshold alone is not the answer, and the flip is the proof.** A roll flip spends ~6% of
its frames past 90° and tracks to 2.15 cm anyway. The eigenvector for eigenvalue `1` is `R`'s own
**rotation axis**, and there the loop eigenvalue stays `−K` no matter what `θ` is. A planar
maneuver's `ω` lies exactly on that axis, so it never excites the two `−K·e^{±iθ}` modes at all.

Measured on all three, over their own durations:

| | max attitude | ω-to-fixed-axis alignment | vendored loop |
|---|---|---|---|
| `flip` | 179.9° | **1.000000000** | **2.15 cm** — stable |
| `swing` | 69.3° | 1.000000000 | 0.29 cm — stable twice over |
| `orbit` | 179.9° | **0.000584** | **17.65 m** — divergent |

And the control experiment, which is what makes this a finding rather than a guess:

| orbit, open-loop, 3.85 s | result |
|---|---|
| DiffAero as vendored | **17.65 m / 180°** |
| identical loop, `R_i2b` removed | **1.80 cm / 0.65°** |
| as vendored @ 20 / 5 / 1 ms | 17.65 / 17.87 / **17.65 m** — flat |

Asserting only "the orbit diverges" would still pass if the *reference* were wrong; a garbage
trajectory diverges too. Only the pairing isolates the cause. And the flat `dt` sweep is what rules
out the obvious misreading — a discretization error shrinks with the step, a positive eigenvalue
does not — so the next person reads `controller.py:93` instead of tuning `dt`.

**It does not reach NaN**, and that is worth stating: `WhoopDynamics` saturates body rate and
velocity every step, so the blow-up is *bounded* and the output still looks like a finite
trajectory. 17.65 m of error on a 1 m circle is the number to quote.

### It is fixed (2026-08-01)

`controller.py` now reads `actual_angvel_b = w`, and the orbit tracks at **1.80 cm / 0.65°** in
DiffAero as vendored — the number the control arm predicted, reproduced to three significant
figures by the patched fork. Non-planar maneuvers are **first-class RL targets** from here.

The control experiment is kept in `tests/test_reference_sim.py` with *both* arms: the patched fork,
and `_legacy_rollout`, a local re-implementation of the old loop. "The orbit tracks now" on its own
would also pass if someone quietly resized the maneuver below 90° of attitude, so only the pairing
says the frame bug was the cause and that the fix is what resolved it. (`_legacy_rollout` reads
~14.6 m rather than 17.65 m because it is pure numpy without `WhoopDynamics`' state clamps; the
assertion is on `> 1.0 m`, since the exact magnitude of an unstable mode is not the finding.)

**What it means for results predating the fix.** Everything this lab trained — gate_race, hover,
the flip, the swing — is *planar*, ω on `R`'s fixed axis, so those policies learned against a loop
that was locally correct and their numbers stand. What cannot be carried over uninspected is any
**non-planar** measurement made before 2026-08-01. `verify.check_rate_loop_stability` now answers
"would the **legacy** loop have tracked this" and ships `substrate_rate_loop_fixed` alongside it,
so an artifact's own `verify.json` says which simulator it was flown on.

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

### Caveats specific to the swing and the orbit

**Peak tilt is ~1.4× the swing amplitude, so `--amplitude-deg` is not the bank angle.** "Thrust
points along the rope, so bank equals θ" is a **no-drag** statement; this sim's `D/m = 3.125 s⁻¹`
leans the thrust axis into travel on top of the centripetal lean. Measured 69.3° at Θ = 50°. The
generator prints both numbers and `metrics.peak_bank_deg` carries the real one.

**The swing is driven at 0.8× resonance deliberately.** At 1.0× the same sizing demands ~89° of tilt
and a **15.45 rad/s** rate command against an 11.64 ceiling — out of envelope, i.e. *untrackable*
rather than merely tight, and the replay would not show it. `SwingSpec.build()` raises on any sizing
that leaves the envelope, and a test asserts that `freq_scale = 1.0` raises, so the 0.8 cannot be
"simplified" back out.

**The orbit's 24° axis-pointing error is this simulator's drag, not the maneuver.** Drag is
tangential, so the thrust axis leans into travel by exactly `atan((D/m)/Ω)` — **independent of
radius**, since `RΩ²` over `(D/m)·RΩ` cancels `R`. Measured against three radii and unchanged. The
drag-sensitivity column re-flies the identical path and measures it collapse:

| drag model | `D` | terminal v | peak bank | **axis-pointing error** |
|---|---|---|---|---|
| `sim` (what the reference IS) | 0.100 | 3.14 m/s | 69.9° | **24.1°** |
| `real_est` (still **linear**) | 0.031 | 10.0 m/s | 68.4° | **8.0°** |
| `none` | 0 | ∞ | 68.2° | **0.0°** |

A genuinely *quadratic* drag with the same 10 m/s terminal velocity has an effective `D/m` of only
`g·v/v_term² = 0.34 s⁻¹` at this 3.5 m/s orbit speed, i.e. **~2.8°**. That is a different drag law,
so it is quoted separately rather than substituted for the 8.0° the shipped column reports.

**Neither the swing nor the orbit needs a `--deployable` variant.** Both are fully powered
throughout: `zero_authority_frac` is exactly 0 and `min_margin_torqued` is comfortable (+0.646 on the
swing). The flip needs one only because of its motors-off coast. Neither should get one implicitly.

**`max_lateral_drift` means different things per maneuver.** It is measured from each spec's own
*station*, so it is genuine drift for the flip (0.180 m), the swing's own half-width by construction
(0.689 m), and the orbit's diameter (1.0 m). The maneuver-specific names — `swing_half_width_m`,
`orbit_radius_m` — are the ones to read for shape; the four shared names exist so a flip and a swing
can be compared on "did it come back?" (`settle_pos_error` is 0.000 for all three).

---

## Using it as an RL target

The metrics deliberately carry **the same names `acro_flip` computes**
(`AcroFlipTask.metrics()`): `max_lateral_drift`, `peak_climb`, `altitude_loss`,
`settle_pos_error` — measured over each maneuver's own window (a level hover at `z_entry` through the
end of the settle/recover). So "this is the one we want" is a literal number the RL can be graded
against.

Three things worth knowing before wiring it up:

1. **Use `--deployable`** — for the flip. See the allocation caveat above. The swing and the orbit
   are fully powered and need no equivalent.
2. **The reference's pop exceeds `acro_flip`'s current free headroom.** `configs/acro_flip_v2.yaml`
   sets `pop_allow: 0.4` m of free climb, but the reference's `peak_climb` is **0.617 m**
   (0.680 m deployable). Under the current reward the maneuver we say we want would collect a small
   `rise_scale` penalty. That is a genuine, actionable mismatch between the stated target and the
   reward — raising `pop_allow` to ~0.7 is a training decision, so it is flagged here rather than
   changed.
3. **The orbit is usable as an RL target as of the 2026-08-01 rate-loop fix.** It was blocked
   before that — the simulator could not track a non-planar maneuver at all — so any orbit result
   dated earlier was measured on a divergent substrate. See the rate-loop section above.

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
| `reference/paths.py` | `Envelope` (the septic window), `PendulumPath`, `OrbitPath` — analytic shapes + derivatives |
| `reference/segments.py` | `PathSegment` / **`AnalyticPathSegment`** / `RateSegment` / `BallisticSegment` / `Trajectory` |
| `reference/maneuvers.py` | the **`ManeuverSpec` protocol**, plus `FlipSpec` + `solve_flip` (the shoot) |
| `reference/maneuvers_swing.py` | `SwingSpec` — the U-swing, no shoot |
| `reference/maneuvers_orbit.py` | `OrbitSpec` — the banked revolution, and the rate-loop caveat |
| `reference/imu.py` | `specific_force_body` — what the accelerometer reads |
| `reference/emit.py` | `Samples` → replay + `reference.json`, against the protocol |
| `reference/verify.py` | residual / limit / allocation / continuity / **rate-loop-stability** checks |
| `reference/video.py` | the **video contract** — the one hero invocation, and its framing check |
| `scripts/reference_maneuver.py` | the generator (`--maneuver flip\|swing\|orbit`) |
| `scripts/reference_flip.py` | a thin alias for `--maneuver flip` |
| `tests/test_reference.py` | 50 pure-numpy tests (no simulator) |
| `tests/test_reference_sim.py` | the open-loop sim replays + the orbit control experiment (the torch tests) |
| `tests/test_capture_preset.py` | pins `--preset hero` field by field |

Charts live in `viz/render.py`: `plot_reference_telemetry` (six shared-x panels) and
`plot_reference_envelope` (the "maneuver strip" — a body-z tick every few frames, in a **side
elevation** for the planar maneuvers or **top-down** for the orbit, where an elevation would render
a 1 m circle as a flat line). Both are driven entirely by `meta.reference`, which the spec writes,
so one renderer captions three maneuvers and the shipped 1.2 m flip artifacts still render unchanged.

**Charts must never compute on `rpy`.** `quaternion_to_euler` (`utils/math.py:190`) is ZYX with
pitch clamped to ±90°, so a full 360° roll renders there as a 180° wobble. The replay still *carries*
`rpy` because the schema requires it; everything downstream uses the unwrapped angle from the
quaternion — and unwraps the **half** angle before doubling, because doubling first makes the flip a
4π jump that `np.unwrap` reads as no jump at all.
