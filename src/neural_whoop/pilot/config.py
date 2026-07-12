"""Offboard-pilot tuning constants — the single source of truth for the flight engine.

Every module constant that ``scripts/pilot.py`` used to define lives here verbatim (the values,
and the validated design lore in their comments, are load-bearing — see docs/SIM2REAL.md). The
pure-stdlib engine modules (:mod:`neural_whoop.pilot.policy` / ``telemetry`` / ``controller``) and
the CLI shim (``scripts/pilot.py``) all import from here, so a tune changes in exactly one place.

Deliberately dependency-free (only ``math``): the whole real-flight path imports zero torch/numpy.
"""

from __future__ import annotations

import math

#: Deploy-exact hover policy shipped as the always-on dashboard default (docs/SIM2REAL.md).
DEFAULT_WEIGHTS = "runs/hover_blind_air65_d50var_s8/policy_weights.json"

# Sim action limits (contract.py ActionLimits) and the Betaflight ACTUAL-rates the drone must
# be configured with (rates_type=ACTUAL, expo 0, roll/pitch 690 deg/s, yaw 345 deg/s).
MAX_THRUST_NORMED = 4.0
SIM_MAX_RATE_RP = 12.0    # rad/s
SIM_MAX_RATE_YAW = 6.0
BF_MAX_RATE_RP = math.radians(690.0)
BF_MAX_RATE_YAW = math.radians(345.0)

# Betaflight permanent box ids (msp_box.c) — stable across versions, keyed by MSP_MODE_RANGES.
BOX_ARM = 0
BOX_MSP_OVERRIDE = 50

# RPM thrust governor. Bidir-DShot RPM telemetry (probe-confirmed on this board) is a TRUE
# thrust anchor: thrust ~ rpm^2 independent of pack freshness/sag/voltage-sensor lies. At
# breakaway the RMS motor RPM is by definition the RPM that carries the weight; in flight a
# slow integrator steers the throttle so measured (rpm/rpm_hover)^2 tracks the thrust the
# policy is asking for. Kills the fresh-vs-tired-pack problem at the source.
RPM_KI_US = 300.0    # us of throttle correction per (thrust-unit error * s); tau ~ 0.7 s
RPM_CORR_CAP = 80.0  # us; the anchor is already within a few %, this is fine adjustment

VZ_LEAK_TAU = 4.0    # s; climb-rate estimate forgets (bounds acc-bias drift; vz-policy path only)
VZ_TRIM_CAP = 0.12   # act[0] units: the RPM damper's proportional authority clamp. Flight
#                      1783324924: a tilt-poisoned estimate pinned the old 0.35 total for 14 s and
#                      FLEW the drone; the RPM anchor is good to ~5%, so the damper only needs
#                      gentle authority. (The retired accel integrator's i_trim / VZ_ITRIM_* /
#                      VZ_TRIM_TOTAL constants went with the vz-rail fix — the RPM governor's
#                      integral now absorbs the pack's DC thrust bias the i_trim used to chase.)
VZ_CLAMP = 2.0       # m/s; a whoop indoors doesn't do more — beyond this the estimate is lying
VZ_TILT_LIMIT = math.radians(25.0)  # cos-tilt math reads sustained wobble as phantom descent
#                     (1783324924: roll +-30-60 deg -> vz "-3 m/s" for 14 s). Freeze early.
# RPM-anchored climb-rate (the blind-policy altitude damper's input since the vz-rail fix). The
# accel-integrated vz drifted on its acc-z DC bias and RAILED at -VZ_CLAMP while the drone sat
# level (d50var_s8_f1: railed by t=8.24 s -> the damper piled +203 us of phantom thrust ->
# ceiling). rpm_hover (breakaway = weight) is a driftless anchor: (rpm/rpm_hover)^2 - 1 is the
# MEASURED net thrust-over-weight fraction, *g its net vertical specific force, *VZ_AERO_TAU the
# quasi-steady climb rate it sustains against aero drag — instantaneous, no integrator, so it
# cannot rail.
VZ_AERO_TAU = 0.25   # s; thrust-excess -> climb-rate scale (the --vz-gain tune absorbs its level)

# Ground-takeoff (--takeoff): SEEK, don't assume. A fixed boost anchored to --hover-us shot
# every fresh-pack flight straight into the ceiling. Instead: spool to SEEK_START fast, then ramp
# throttle SLOWLY while watching the acc-z climb estimator; the instant the drone actually lifts
# (vz > LIFT_VZ), the throttle at breakaway IS that pack's true hover point — learn it (minus the
# detection lag), re-anchor the whole flight's thrust map on it, apply a tiny RISE_THRUST for
# RISE_S to gain height, then hand to the policy. Takeoff doubles as per-pack hover calibration.
SEEK_START_US = 1200   # jump here quickly (well below any pack's hover)
SEEK_SPOOL_S = 0.2
SEEK_RATE_US_S = 250.0  # slow ramp: ~35 us of overshoot at the estimator's ~0.15 s lag
SEEK_TIMEOUT_S = 2.5
LIFT_VZ = 0.20         # m/s of estimated climb = the wheels left the ground
LIFT_LAG_US = 60       # detection-lag overshoot to subtract (sim: learned anchor then lands
#                        within +0..+10 us of true hover for packs from 1340 to 1480 us)
RISE_THRUST = 1.06     # gentle climb-out after liftoff (in learned-hover units)
RISE_S = 0.5

# End-of-flight thrust ramp-down window (s): the policy's act[0] is eased toward the floor over
# this window before the link is released so the drone settles rather than dropping.
RAMP_DOWN_S = 1.5

# Acro FLIP maneuver (docs/SIM2REAL.md): the learned single-axis flip inserted as a bounded window
# at HOVER. The system-level split — the pilot owns takeoff/land, the acro policy owns the flip.
# The task side fixes Φ = 2π·n_rotations and the 15° recovered-tilt success gate; these mirror it.
ACRO_AXIS = "roll"            # "roll" (drives gyro p) or "pitch" (drives gyro q) — matches acro_flip
ACRO_N_ROTATIONS = 1.0        # Φ = 2π·n_rotations (1 = a single barrel roll / loop)
ACRO_FLIP_MAX_S = 1.0         # HARD bounded window: exit FLIP no later than this (safety — a failed
#                              flip must hand the crash detector back before a real tumble persists)
ACRO_SETTLE_TILT_DEG = 15.0   # a completed flip counts as recovered (-> HOVER) when tilt < this
#                              (= acro_flip's success_tilt_deg)

# MSP_RAW_IMU gyro scale. Betaflight's gyroRateDps() (sensors/gyro_init.c) returns
# gyroADCf / rawSensorDev->scale — i.e. the FILTERED rate converted back to raw LSB units,
# 16.384 LSB per deg/s on a +-2000 dps gyro. Confirmed empirically from flight_1783271742:
# the crash-tumble railed at |31527| raw = 1924 dps ~= the sensor's 2000 dps full scale.
GYRO_RAW_TO_DPS = 2000.0 / 32768.0

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)
