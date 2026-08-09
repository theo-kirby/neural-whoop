---
node_id: 5f238283-5afb-55fd-8dfa-52b5ff963397
slug: rapid-hill-4130
title: A pilot-side ToF zero-offset calibration does not exist, and it is the named blocker for a real Desk-Hover flight
created_at: '2026-08-09T18:42:33+00:00'
parents:
- modest-raven-7153
summary: The measured +23.9 mm static ToF offset is 2.4% of a 1.0 m setpoint and 24% of Desk-Hover's 0.10 m, against 8 cm of floor margin. In sim every Desk-Hover floor exit appears only once the height-error bias is on. Both the design node and the docs name a pilot-side tof_cal as the blocking item and record it as deferred, not done.
flywheel:
  node_id: cb9976e2-0a33-543e-aea9-c23e18318e94
  slug: fragrant-fire-8194
  revision: 0
  pushed_at: '2026-08-09T21:28:39+00:00'
  content_sha256: 784c99fbef8c492912f5d93c6832cb8bc6873fc75f9acdc2f99d9ad1bb57161f
---
Status: open

## Current

The sensor itself is healthy: static noise floor **23.9 mm mean, sigma 2.4 mm** over
629 pre-liftoff samples across five flights, no drift, no ambient sensitivity, 92-99%
coverage of control ticks, and monotone airborne traces in about 10 mm steps — a
credible control input rather than a diagnostic [rec: tiny-glitter-0842].

The offset is the problem, and only at desk scale. 23.9 mm is 2.4% of a 1.0 m
setpoint and nobody noticed; it is **24% of a 0.10 m setpoint**, against only 8 cm of
floor margin (`bound_z_min 0.010`, about the `WHOOP_REST_Z_M` at which the airframe
is touching the desk). A drone that trusts the reading sits about 2.4 cm low — most
of its margin — before any control error at all [rec: black-salad-4817].

The simulation prices this exactly. Desk-Hover arm 1's 98 floor exits localise
cleanly: **0 on clean, 0 on m1live, 29 on m2sensor, 69 under full DR** — every one
appears only once the +-0.03 m `h_err` bias is on [rec: dawn-bonus-9868]. That is the
sim pricing the uncalibrated offset against the margin, and it is what fails gate 3.

The fix is named and unbuilt [rec: black-salad-4817]. The pilot already learns `az_cal` and `lvl_cal` during
the on-floor countdown (`pilot/controller.py`); a ToF zero-offset learned in the same
branch is the exact analogue, and both `black-salad-4817` and `docs/SIM2REAL.md` say
it is worth more than anything in the training config. Both also say **"Not yet
implemented."**

Calibration data now exists for it: the first real-ToF flights logged height at
71-93% airborne coverage plus props-on gyro noise (sd p/q/r 0.091/0.108/0.082 rad/s,
lag-1 rho 0.60/0.62/0.82), so the placeholder noise DR can be fit rather than assumed
[rec: broken-fire-4858].

## Negative knowledge

- [scope: the height-noise domain randomisation on every hover_tof config to date | confidence: high | evidence: tiny-glitter-0842, broken-fire-4858] The ranging noise (sd 0.02 m) and mount/surface bias (+-0.03 m) in every `hover_tof` config are datasheet placeholders, explicitly flagged as such, and were never calibrated from hardware. The data to fit them has existed since the first real-ToF flights and the fit has not been done.
- [scope: the gyro DR on the Desk-Hover configs | confidence: high | evidence: dawn-bonus-9868] The parent idea node asks to refit the gyro DR from flight-2 calibration (props-on sd 0.091/0.108/0.082 rad/s) before training. The shipped configs keep the ladder's 1.25 / 1.1 / 0.75, about 10-14x larger. Recorded as deliberately not done, and named as the obvious next probe.

## Provenance

- tiny-glitter-0842 — the hardware characterisation of the sensor and its static offset
- black-salad-4817 — why the offset becomes first-order at desk scale, and the tof_cal proposal recorded as deferred
- dawn-bonus-9868 — the floor exits localising entirely to the bias-on conditions
- broken-fire-4858 — the first real calibration data, logged and not yet used
