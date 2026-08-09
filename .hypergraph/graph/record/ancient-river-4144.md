---
node_id: c2da8bde-8daa-5831-9729-f035ef951b41
slug: ancient-river-4144
title: 'Two more reference maneuvers, and the package stops being about the flip: the swing closes at MACHINE PRECISION with no shoot (0.00e+00), the orbit is the first 3D one (24.06° axis-pointing error = its closed form)'
created_at: '2026-08-01T01:42:12.981176+00:00'
parents:
- sparkling-shadow-0034
- hidden-field-0837
summary: 'Generalized `reference/` from FlipSpec to a `ManeuverSpec` protocol and added two maneuvers, which turned out to need three DIFFERENT authoring mechanisms — that, not the clips, is the result. flip: flatness has no solution through inversion, so COMMANDS are authored and a damped-Newton shoot closes it (residuals ~1e-8). swing: the exact complement — theta(t) = Theta*W(t)*sin(wt) with a septic window and wT = 2*pi*n closes on its own start point at MACHINE PRECISION, measured |p-p0| = |v| = |a| = |j| = 0.00e+00, so there is NO shoot and `build().solution is None`. orbit: the first genuinely 3D maneuver and the one that breaks psi == 0. Swing (L=0.9 Theta=50deg 0.8x resonance, 2 swings, z=0.9): 4.76 s, +-0.689 m, apex 1.221 m, peak tilt 69.3deg, thrust 0.67..1.63/4.0, rate cmd 7.94/11.64 (32% headroom), allocation min margin +0.646, planarity EXACTLY 0.0, ZERO C2 breaks anywhere, open-loop sim replay 0.29 cm / 0.25deg — 7.5x better than the flip''s 2.15 cm, and asserted to BE better, because it has no command step to leave a ZOH error behind. Orbit (R=0.5 Omega=7, 3 revs nose-in, z=0.9): 3.85 s, 3.50 m/s, bank 69.9deg, thrust 1.00..2.91/4.0, exactly 3.000000 revolutions, and an axis-pointing error of 24.06deg that EQUALS its closed form atan((D/m)/Omega) to 4 digits and is unchanged across three radii — a sim-drag artifact, measured collapsing 24.1 -> 8.0 -> 0.0deg across the drag column. Two sizing findings the maneuvers forced out: driving the pendulum at RESONANCE is out of envelope (89deg tilt, 15.45 rad/s against an 11.64 ceiling) and the generator now RAISES rather than shipping it, and peak tilt runs ~1.4x the authored amplitude so --amplitude-deg is not the bank angle. Also locked the render path: --preset hero is now pinned field-by-field by a test and invoked from one place, and its framing check lands in run.json. GREEN as tooling. Honest: the orbit is NOT flyable in DiffAero as vendored (separate measurement node), and --preset hero has a measured limit it did not have before — the orbit''s apparent size swings 117%.'
origin:
  backend: flywheel
  node_id: c2da8bde-8daa-5831-9729-f035ef951b41
  slug: ancient-river-4144
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9a126f9f-73be-56b4-8362-7dfd037b9534
  slug: gentle-brook-8582
  revision: 0
  pushed_at: '2026-08-09T21:28:18+00:00'
  content_sha256: f7d218627bc1770dfae090d8216b4a52ebce73026d3371c52109c9ea1843c033
---
## Hypothesis

The reference flip (parent `sparkling-shadow-0034`) landed and the format was right: `--preset hero` on a generated `replay.json.gz` gives a concept video of what the drone *should* do rather than a rollout we grade afterwards. Two claims to test by trying to reuse it:

1. **The package is about "a maneuver", not "the flip".** It was not: `emit.py`, `verify.py` and the phase labels all took a `FlipSpec` and assumed a planar single-axis rotation.
2. **`--preset hero` is a deliverable, not a flag I happened to type.** That promise lived entirely in my memory of which flags to use.

And one open question with no prediction attached: what does it take to author a maneuver that is *not* a flip?

## Setup

**Locked the render path first**, since it is the standing deliverable. `tests/test_capture_preset.py` pins `PRESETS["hero"]` field by field, each assertion carrying the measured reason its value has that value, and additionally asserts that every preset-able flag declares **no argparse default** — a flag with its own default would silently outrank the preset, which is the one failure mode nothing else would notice. `reference/video.py` writes the one invocation down once (`--preset hero --width 1080 --height 1080`) and parses the capturer's framing check out of stdout into `run.json`. `scripts/reference_maneuver.py --video` shells out to it and **takes no camera flags on purpose**.

**Generalized the package.** A small `ManeuverSpec` protocol (`phase_labels`, `station`, `metric_window`, `is_planar`, `build(model)`, plus the reporting half that used to be module-global constants); `emit`/`verify` now work against it, and `solution` is optional. New `paths.py` (`Envelope`, `PendulumPath`, `OrbitPath` — analytic derivatives, no finite differencing anywhere in the position chain, because the flatness map eats jerk) and `AnalyticPathSegment`, the `PathSegment` sibling that takes a closed-form shape instead of septic endpoint conditions. An arc and a circle are not interpolation problems; fitting one through a polynomial would only approximate geometry we already have exactly.

Three maneuvers generated at `z = 0.9 m`, each with the full artifact set and its MP4 through the one standard invocation.

## Results

### The result is that three maneuvers need three different authoring mechanisms

| | mechanism | closes to | needs a shoot? |
|---|---|---|---|
| `flip` | flatness has **no solution** through inversion (it would demand negative thrust) → author the **commands**, close with damped Newton | ~1e-8 | **yes** |
| `swing` | flatness authors the **whole beat** | **0.00e+00** | **no** |
| `orbit` | flatness, with a winding `psi` | 0.00e+00 | no |

**The swing is the exact complement of the flip's structural finding.** Author `theta(t) = Theta*W(t)*sin(wt)` with a septic window and `wT = 2*pi*n`, and the beat starts *and ends* at the hover point at **machine precision** — measured `|p - p0| = |v| = |a| = |j| = 0.00e+00`, so the test asserts `== 0.0` rather than a tolerance. `sin` vanishes at both ends because `wT` is a whole number of periods, and the envelope vanishing through its **second** derivative there kills every `W'` cross term. `build().solution is None`, which is a *result* rather than an omission.

The envelope being flat through its **third** derivative is separately load-bearing: the flatness map turns jerk into body rate, so a quintic window at a septic seam would step the emitted body rate visibly, on the frame the maneuver starts.

### `swing` — L=0.9 m, Theta=50deg, 0.8x resonance, 2 swings, z=0.9

| | |
|---|---|
| duration / swing period | 4.76 s / 2.38 s |
| half-width / rise / apex | +-0.689 m / 0.321 m / z = 1.221 m |
| **peak tilt** | **69.3deg** — 1.39x the swing amplitude, *not* equal to it |
| normed thrust (in the swing) | 0.666 .. 1.632 of 4.0 |
| rate command | 7.94 of 11.64 (**32% headroom**) |
| allocation `min_margin_torqued` | **+0.646** |
| planarity | `max\|omega_z\|` and off-axis quat **exactly 0.0** |
| C2 breaks | **none anywhere** |
| **open-loop sim replay** | **0.29 cm / 0.25deg** over 8.96 s |

**0.29 cm beats the flip's 2.15 cm by 7.5x, and the test asserts the ordering, not just the number** — which is what keeps the measurement tied to its explanation. The flip's residual is dominated by its two intentional C2 breaks (the thrust cut is one control step wide, so even an impulse-matched hold leaves a step the 50 Hz stream cannot represent). The swing has no command step at all, so that error source is simply absent. If a seam ever crept in, this fails even if 2 cm still passed.

### `orbit` — R=0.5 m, Omega=7 rad/s, 3 revs, nose-in, z=0.9

| | |
|---|---|
| duration / revolution | 3.85 s / 0.898 s |
| radius / speed | 0.5 m / 3.50 m/s |
| peak bank | 69.9deg |
| normed thrust | 1.00 .. 2.913 of 4.0 |
| rate cmd, roll-pitch / yaw | 7.044 of 11.64 / 3.637 of 6.0 |
| revolutions | **exactly 3.000000** |
| **axis-pointing error** | **24.06deg median** |
| heading conditioning | 0.372 min |
| non-planar | `max\|omega_z\| = 3.34`, attitude reaches 179.9deg |

The revolution count is *exactly* 3 because the septic ramp integrates to exactly 1/2, so the duration `2*pi*n / (Omega(1-ramp_frac))` is closed form rather than quadrature-accurate.

**"The top face points at the axis" has a closed-form error and it is not zero.** Drag is tangential, so the thrust axis leans into travel by exactly `atan((D/m)/Omega)` — **independent of radius**, since `R*Omega^2` over `(D/m)*R*Omega` cancels `R`. Predicted 24.06deg, measured 24.06deg, and unchanged across R = 0.25 / 0.375 / 0.5. The drag column re-flies the identical path and measures it collapse:

| drag model | terminal v | peak bank | **axis-pointing error** |
|---|---|---|---|
| `sim` (what this IS) | 3.14 m/s | 69.9deg | **24.1deg** |
| `real_est` (still **linear**) | 10.0 m/s | 68.4deg | **8.0deg** |
| `none` | inf | 68.2deg | **0.0deg** |

A genuinely *quadratic* drag at the same 10 m/s terminal velocity has an effective `D/m` of only 0.34 1/s at this 3.5 m/s orbit speed, i.e. **~2.8deg**. Different law, so it is quoted separately rather than substituted for the 8.0deg the shipped column reports.

### Two sizing findings, both now enforced rather than remembered

**Driving the pendulum at resonance is out of envelope.** "Thrust points along the rope, so bank equals theta" is a **no-drag** statement; this sim's `D/m = 3.125 1/s` leans the thrust axis into travel on top of the centripetal lean. At `freq_scale = 1.0` the same sizing demands ~89deg of tilt and a **15.45 rad/s** rate command against an 11.64 ceiling — untrackable rather than merely tight, and the replay would not show it. `SwingSpec.build()` now **raises** on any out-of-envelope sizing, because with no shoot to absorb it a bad sizing would otherwise ship as an artifact that looks perfect and saturates. A test asserts `freq_scale = 1.0` raises, so the 0.8 cannot be "simplified" back out.

**`ramp_frac` is what spends the rate budget**, and it is not cosmetic: 0.20 is already out of envelope, **0.25** gives 69.3deg / 7.94, 0.30 gives 58.4deg / 5.88, 0.50 gives 55.5deg / 3.48.

### The video contract, and the limit it found

Every clip through the one invocation. Framing, captured into `run.json`:

| clip | worst \|NDC\| | apparent size | spread |
|---|---|---|---|
| `flip_roll_z09` | 0.47 | 17.8-20.2% | **13%** |
| `swing_roll` | 0.44 | 17.5-21.8% | 25% |
| `orbit_z` | 0.65 | 13.9-30.2% | **117%** |

## Verdict / Honesty

**GREEN** as tooling. `pytest`: 50 pure-numpy + 9 sim reference tests + 8 preset tests pass; one pre-existing failure (`tensorboard` not installed on this Mac, identical on a stashed tree). The 1.2 m flip artifacts are untouched and still render, because the charts fall back to the pre-generalization reading of `meta.reference`.

**The orbit cannot be flown in DiffAero as vendored.** It is a valid reference and a valid video; it is not something a policy can be trained to or evaluated against here. That is a finding about the *substrate* rather than about these videos, so it has its own child node rather than being buried in this one.

**`--preset hero` has a measured limit, and it is not the one its fallback ladder documents.** The orbit never leaves frame (0.65 of 1.0), so no rung was taken and the shipped clip is plain `hero`. What it fails is the *other* guarantee — apparent size swings 117%. Measured ladder:

| variant | worst \|NDC\| | spread |
|---|---|---|
| `hero` (shipped) | 0.65 | 117% |
| `--drone-frac 0.15` | 0.47 | 67% |
| `--drone-frac 0.10` | 0.36 | 41% |
| `--max-drift 0.45` | 0.83 | **117% — no effect at all** |
| **`--track-smooth 6`** | 0.32 | **10%** |
| `--shot fit` | 0.52 | 3-5% of frame (unusable) |

**The lever is `track_smooth`, which the ladder does not mention.** Mechanism: `hero`'s `track_smooth = 20` is a +-0.4 s window and the orbit's revolution is 0.898 s, so the smoothed subject track averages nearly a whole revolution, collapses onto the circle's centre, and the follow rig **silently degenerates into a tripod**. So the honest statement of its reach is: *`hero` assumes the subject's motion is slow compared to its smoothing window; a periodic maneuver whose period is comparable to `2 x track_smooth` frames defeats it.* The preset is deliberately **not** retuned — that is a decision about every other clip in the repo and should be made with these numbers rather than by me while rendering an orbit.

**Other honest notes:**

- **`max_lateral_drift` means different things per maneuver.** Measured from each spec's own station, so it is genuine drift for the flip (0.180 m), the swing's own half-width by construction (0.689 m) and the orbit's diameter (1.0 m). The maneuver-specific names are the ones to read for shape; the four shared `acro_flip` names exist so "did it come back?" is comparable (`settle_pos_error` is 0.000 for all three).
- **Neither new maneuver needs a `--deployable` variant** and neither should get one implicitly: both are fully powered, `zero_authority_frac` is exactly 0, `min_margin_torqued` is +0.646 on the swing. The flip needs one only because of its motors-off coast.
- **The swing is roll-axis only.** A pitch swing would be the same maneuver rotated 90deg needing the other heading construction; it is not offered rather than offered and quietly degenerate.
- **The orbit sits at the worst heading conditioning in the package (0.372).** The *forward* map only multiplies by that quantity so it is unaffected; only `state_to_flat` divides by it, so any round-trip test on this maneuver must filter on it rather than assume psi-dot comes back.
- **The flip's shape does not depend on the altitude it is flown at.** Re-solved at `z_entry = 0.9`, every metric is unchanged except the apex (1.82 -> 1.517 m). That was the one tweak asked for and it is a null result.
- **"No C2 breaks" is measured against each maneuver's own p99 per-sample change**, not an absolute epsilon — a real break *is* a sample, so comparing against the max would compare the thing to itself. Swing 0.002x, flip 189x: the same measure separates them by five orders.

## Lineage

- `sparkling-shadow-0034` **the reference flip** — the format, the flatness machinery, and the structural finding the swing turns out to be the complement of. Its 1.2 m artifacts are untouched; `scripts/reference_flip.py` survives as a thin alias so every command already documented still works.
- `hidden-field-0837` **`--preset hero`** — the video rides on it unchanged, and this node is where it is first *pinned by a test* and first *measured to have a limit*.

Commits `6b3f31e` (lock the render path), `3ad9b7f` (generalize + the two maneuvers), `0d9d092` (charts + CLI), `793b3a9` (tests), `a3d3ce8` (docs) on branch `reference-maneuver`. Docs: `docs/REFERENCE_MANEUVER.md`.