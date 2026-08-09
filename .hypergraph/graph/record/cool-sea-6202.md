---
node_id: ac746aa9-9a3e-596b-b186-241ca19c76ab
slug: cool-sea-6202
title: 'RPM-anchor vz fix: driftless altitude damper (kills the -2.0 rail ceiling bug) — IMPLEMENTED, awaiting bench flight (Air65 II, 2026-07-07)'
created_at: '2026-07-07T11:54:21.531228+00:00'
parents:
- royal-bar-2003
summary: 'Implements the deferred follow-on from the parent royal-bar-2003 (d50var_s8 first flight). The blind-policy altitude damper in scripts/pilot.py no longer rides the accel-integrated vz_est that drifted on its acc-z DC bias and RAILED at -2.0 m/s while the drone sat level (piling +203 us of phantom thrust -> ceiling). It now rides a DRIFTLESS RPM-anchored climb rate: rpm_climb_rate = ((rpm/rpm_hover)^2 - 1)*g*VZ_AERO_TAU, driving a pure-PROPORTIONAL trim rpm_damper_trim clamped +-VZ_TRIM_CAP (0.12). No integrator => it cannot wind to a rail, and at hover RPM the trim is exactly 0 every frame (stateless) => a level hover can''t pile on phantom thrust. Reconciled with the existing RPM thrust governor: both share the one rpm_hover anchor and (rpm/rpm_hover)^2 measurement (fast proportional damper + slow command-tracking governor); the governor''s integral SUBSUMES the retired accel i_trim (i_trim / VZ_ITRIM_* / VZ_TRIM_TOTAL deleted). Export-clean pure stdlib; +14 unit tests (tests/test_pilot_vz_damper.py), full suite 208 passed; pilot selftest deploy parity 4.63e-08 unchanged. Cannot flight-validate on this box (no drone). Verdict: IMPLEMENTED, AWAITING BENCH FLIGHT. Confirm from the next flight_report pack: vertical.vz_rail_frames ~= 0 over the airborne window (was 48), vertical.thrust_divergence.detected = false with us_thr_rise <~ 40 us (was +203 us while a_thr IQR 0.015), and a completed calm-air hover instead of a ~10 s ceiling contact. Commit d7fd877.'
origin:
  backend: flywheel
  node_id: ac746aa9-9a3e-596b-b186-241ca19c76ab
  slug: cool-sea-6202
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
---
# RPM-anchor vz fix — the deploy-harness bug from royal-bar-2003, fixed in software

**Hypothesis.** The parent `royal-bar-2003` exonerated the `d50var_s8` policy and pinned the first-flight ceiling crash on ONE deploy-harness bug: the pilot's accel-integrated `vz_est` drifted on its acc-z DC bias and railed at its `-2.0 m/s` clamp while the drone sat level (~1 deg tilt), so the blind-policy altitude damper piled `+203 us` of phantom thrust (`a_thr` never moved) -> climb -> ceiling. Prediction under test: replacing that drift-prone integral with an `rpm_rms`-derived hover anchor makes the rail structurally impossible, because hover RPM (learned at breakaway = weight) is a constant, driftless thrust reference.

## Setup (the change vs the parent)
- **New (`scripts/pilot.py`, pure stdlib, export-clean):**
  - `rpm_climb_rate(rpm_now, rpm_hover)` = `((rpm_now/rpm_hover)**2 - 1) * 9.81 * VZ_AERO_TAU` — the measured net thrust-over-weight fraction (thrust ~ rpm^2) times g times an aero time constant (`VZ_AERO_TAU = 0.25 s`): the quasi-steady climb rate the thrust excess sustains against drag. Instantaneous, no integrator.
  - `rpm_damper_trim(rpm_now, rpm_hover, vz_gain)` = `-vz_gain * rpm_climb_rate`, clamped to `+-VZ_TRIM_CAP (0.12)` act[0]. Pure proportional.
- **Damper rewire (blind policy only):** `thr_trim = rpm_damper_trim(...)`; the logged `vz_est` becomes the bounded RPM climb rate (so `flight_metrics.vertical.vz_rail_*` reads the signal the damper actually used). The accel `vz` integral stays ONLY for vz-consuming (`hover_blind_v2`) policies and the takeoff-SEEK breakaway detector (which runs before any RPM anchor exists).
- **Retired:** the accel integrator's `i_trim` and the `VZ_TRIM_KI` / `VZ_ITRIM_CAP` / `VZ_ITRIM_LEAK_TAU` / `VZ_TRIM_TOTAL` constants — deleted.
- **The reconciliation (the honest design question the user raised).** The RPM thrust governor (`pilot.py` ~L820) already consumes `rpm_rms` for thrust: it drives `(rpm/rpm_hover)^2 -> t_des` to make DELIVERED thrust track the policy's COMMAND (actuator linearization against pack sag). The damper and governor now **share one RPM signal**: the same `rpm_hover` anchor and the same `(rpm/rpm_hover)^2` measurement. They are a clean cascade, not a duplication — the damper is the FAST proportional path (returns commanded thrust toward hover on a measured excess), the governor the SLOW command-tracking integral. Their fixed point is consistent: at policy-hover (`a_thr=-0.5`) the algebra gives `thr_trim=0`, `rpm=rpm_hover` (they agree, don't fight). And the governor's integral now does the DC-thrust-bias absorption that the retired `i_trim` used to attempt on a bad signal — so removing `i_trim` loses nothing.

## Results (implementation evidence — no drone on this box)
- **Unit tests:** `tests/test_pilot_vz_damper.py` (14 tests, all pass). Asserted invariants: `rpm_climb_rate` = 0 at hover RPM, correct sign, monotone in RPM, formula-exact, 0 without an anchor, and small over the +-20% hover band; `rpm_damper_trim` opposes climb, is 0 at hover, clamps to `+-VZ_TRIM_CAP`, is **stateless** (1000 identical hover calls -> exactly 0 every time -> no accumulation to a rail), and depends on the RPM ratio ONLY (no `vz`/accel input exists in its signature — the phantom signal can no longer reach the command).
- **Characterization (no drone):** the attached `damper_response.png` / `.csv` sweep `rpm/rpm_hover` from 0.7x to 1.3x: the climb estimate passes cleanly through 0 at hover and never approaches the `-2.0` accel rail; the trim is bounded, opposes climb, and pins to `+-0.12` only at extreme RPM. Max |trim| over the sweep = 0.12 (the cap), trim at hover = exactly 0.
- **Deploy parity intact:** pilot `selftest` worst |err| **4.63e-08** vs the deploy-exact reference (unchanged) — the fix does not touch the policy forward pass or the CTBR mapping. Full suite **208 passed**.

## Verdict / honesty
**IMPLEMENTED, AWAITING BENCH FLIGHT** — not yet a GREEN/RED empirical result (no drone here; the bench flight is the user's). Honesty: (1) this is characterized in software, not flown — the flight is the real test. (2) `VZ_AERO_TAU = 0.25 s` sets the climb-rate scale and the effective gain (`vz_gain * g * tau`); the `--vz-gain` bench tune absorbs the level, but the starting authority is a guess pending flight. (3) The damper is now an acceleration-toward-hover restoring term, NOT a velocity-hold — honest about what RPM can sense (thrust ~ accel, not velocity); it prevents the runaway, it does not close a tight altitude loop (that is the flow deck / a vz-consuming policy). (4) Extreme-RPM frames (a tumble) will still read a large `vz_est` and could flag `vz_rail` outside the hover window — that is honest departure telemetry, decoupled from the hover-window check.

**Confirm from the next flight's `flight_report` pack** (`scripts/flight_report.py runs/pilot/<next>.csv`):
- `vertical.vz_rail_frames` ~= **0** over the airborne window (was **48**; first rail was at t=8.24 s).
- `vertical.thrust_divergence.detected` = **false**, `us_thr_rise` <~ **40 us** across the stable hover (was **+203 us** while `a_thr` IQR 0.015).
- The hover HOLDS altitude — a completed calm-air flight, not a ~10 s ceiling contact.

## Lineage
Parent: **royal-bar-2003** (the first flight that root-caused the bug and named this fix as the deferred follow-on). Grandparent via royal-bar-2003: **broken-wildflower-8398** (the `d50var_s8` policy / studio-baseline this harness flies). Commit **d7fd877** (parent 636ad9b).