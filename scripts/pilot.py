#!/usr/bin/env python3
"""Offboard pilot: fly a trained hover_blind policy over the WiFi MSP bridge — pure stdlib.

The deployment end of sim2real branch B (docs/SIM2REAL.md Stage 0.5): observations come from
MSP_ATTITUDE + MSP_RAW_IMU over the xiao_bridge, the TinyPolicy actor runs right here in pure
Python (weights from ``policy_weights.json`` — see the extraction note below), and act-v2
commands stream back as MSP_SET_RAW_RC in **AETR wire order** at ``--hz``.

Deliberately dependency-free (like bench.py's UDP path): runs on a macOS laptop with no venv.
A [64,64] MLP forward is ~5k MACs — microseconds in CPython, nothing to optimize.

Subcommands:
  selftest   Pure-math parity check of the Python forward pass against the deploy-exact
             reference outputs saved next to the weights (run after any weights change).
  check      PROPS OFF, powered drone: stream live obs + the policy's commanded channels.
             Hand-tilt the drone and verify every correction points the right way BEFORE
             the first flight (the printed hints say what to expect).
  fly        The real thing. Streams the policy at --hz for --seconds, then ramps thrust
             down and releases the link (Betaflight's MSP freshness window hands control
             back to the radio). Arming and the override switch STAY ON THE POCKET.

Safety model: this script never touches aux channels, never arms, and stops streaming on ANY
fault (stale observations, socket error, Ctrl+C, timer end) — stopping is the safe action,
because Betaflight reverts to the live Pocket RC within its 300 ms MSP freshness window.

Frame/sign conventions (bench-verified 2026-07-05, see docs/SIM2REAL.md):
  sim body frame is x fwd / y LEFT / z UP; Betaflight is roll-right/pitch-up/yaw-right +.
  -> roll matches, pitch and yaw FLIP, both for observations and commanded rates.
  MSP_SET_RAW_RC wire order is AETR: [roll, pitch, THROTTLE, yaw, aux1..4].

Weights: produced from a checkpoint by ``scripts/export_json.py`` (torch needed once, anywhere):
actor Linear layers + log_std + stacking meta to JSON. Deploy convention since 5c735cd is the
clipped-Gaussian effective mean E[clip(N(mu, sigma))] — implemented here with math.erf.
Stacked/vz-aware policies (hover_blind_v2, meta.obs_stack/base_obs_dim): the base frame grows
the pilot's own leaky climb-rate estimate as channel 6, and the network sees the last obs_stack
frames concatenated oldest->newest (history seeded by repeating the first frame — the env's
reset semantics). When the policy consumes vz it OWNS vertical damping: the external climb
damper is disabled; the RPM governor stays (it anchors ABSOLUTE thrust, which a high-passed
climb rate cannot see). A blind (5-dim) policy instead gets a proportional climb damper riding
the DRIFTLESS RPM-anchored climb rate (rpm_climb_rate) — never the accel integral, which once
railed at -2 m/s on a level hover and flew the drone into the ceiling (docs/SIM2REAL.md).

Thrust mapping: act[0] -> normed thrust t in [0, 4] hover-units (contract.py), then
us = 1000 + (hover_us - 1000) * sqrt(t)  (prop thrust ~ quadratic in throttle; sqrt inverts),
clamped to [--min-us, --max-us]. --hover-us anchors on the bench-measured hover throttle;
--trim-thrust nudges act[0] if the bench check shows residual bias (SIM2REAL: mandatory step).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import signal
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neural_whoop.bench.msp import (  # noqa: E402
    MSP_ALTITUDE,
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_MODE_RANGES,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    MSP_STATUS,
    MspError,
    MspTimeout,
    MspUdpClient,
    decode_altitude,
    decode_analog,
    decode_attitude,
    decode_mode_ranges,
    decode_motor_telemetry,
    decode_raw_imu,
    decode_status_sensors,
    decode_u16s,
    pack_rc_channels,
)

DEFAULT_WEIGHTS = "runs/hover_blind_air65_long/policy_weights.json"

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

# Acc-z climb damper. Open-loop thrust-from-voltage failed honestly: a fresh pack and a tired
# pack both read ~3.65-3.7 V UNDER LOAD yet the same 1410 us climbs to the ceiling on one and
# sinks to the floor on the other (flights 1783278136 vs 1783276185). So close the loop with
# the accelerometer instead: acc-z at rest during the countdown IS 1 g (self-calibrating, no
# scale lore), vertical specific force integrates to a leak-filtered climb-rate estimate, and
# a proportional thrust trim damps it. The leak (tau below) bounds acc-bias drift; this is a
# DAMPER, not an altitude hold — it turns the blind policy's altitude random walk into a
# strongly damped one, and also arrests the leftover takeoff-boost climb after handoff.
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
# accel-integrated vz above drifted on its acc-z DC bias and RAILED at -VZ_CLAMP while the drone
# sat level (d50var_s8_f1: railed by t=8.24 s -> the damper piled +203 us of phantom thrust ->
# ceiling). rpm_hover (breakaway = weight) is a driftless anchor: (rpm/rpm_hover)^2 - 1 is the
# MEASURED net thrust-over-weight fraction, *g its net vertical specific force, *VZ_AERO_TAU the
# quasi-steady climb rate it sustains against aero drag — instantaneous, no integrator, so it
# cannot rail. Shares rpm_hover + (rpm/rpm_hover)^2 with the RPM governor below (that loop's
# integral absorbs the pack's DC thrust bias the retired i_trim used to chase): one anchor, a
# fast proportional damper and a slow command-tracking governor riding it.
VZ_AERO_TAU = 0.25   # s; thrust-excess -> climb-rate scale (the --vz-gain tune absorbs its level)

# Ground-takeoff (--takeoff): SEEK, don't assume. A fixed boost anchored to --hover-us shot
# every fresh-pack flight straight into the ceiling (flights 1783323895/910/928: "1.18x" of
# 1410 was really ~1.5x of that pack's true ~1360 hover; vz railed +3 m/s during the boost
# itself). Instead: spool to SEEK_START fast, then ramp throttle SLOWLY while watching the
# acc-z climb estimator; the instant the drone actually lifts (vz > LIFT_VZ), the throttle at
# breakaway IS that pack's true hover point — learn it (minus the detection lag), re-anchor
# the whole flight's thrust map on it, apply a tiny RISE_THRUST for RISE_S to gain height,
# then hand to the policy. Takeoff doubles as per-pack hover calibration.
SEEK_START_US = 1200   # jump here quickly (well below any pack's hover)
SEEK_SPOOL_S = 0.2
SEEK_RATE_US_S = 250.0  # slow ramp: ~35 us of overshoot at the estimator's ~0.15 s lag
SEEK_TIMEOUT_S = 2.5
LIFT_VZ = 0.20         # m/s of estimated climb = the wheels left the ground
LIFT_LAG_US = 60       # detection-lag overshoot to subtract (sim: learned anchor then lands
#                        within +0..+10 us of true hover for packs from 1340 to 1480 us)
RISE_THRUST = 1.06     # gentle climb-out after liftoff (in learned-hover units)
RISE_S = 0.5

# MSP_RAW_IMU gyro scale. Betaflight's gyroRateDps() (sensors/gyro_init.c) returns
# gyroADCf / rawSensorDev->scale — i.e. the FILTERED rate converted back to raw LSB units,
# 16.384 LSB per deg/s on a +-2000 dps gyro. Confirmed empirically from flight_1783271742:
# the crash-tumble railed at |31527| raw = 1924 dps ~= the sensor's 2000 dps full scale.
# (First two flights fed the policy rates 16.4x real -> constant overreaction -> climb.)
GYRO_RAW_TO_DPS = 2000.0 / 32768.0

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


# --- policy ---------------------------------------------------------------------------------


class Policy:
    """TinyPolicy actor (tanh MLP) + clipped-Gaussian effective-mean output, pure Python."""

    def __init__(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        self.meta = data["meta"]
        self.layers = [(l["W"], l["b"]) for l in data["layers"]]
        self.sigma = [math.exp(v) for v in self.meta["log_std"]]
        self.obs_dim = self.meta["obs_dim"]
        self.act_dim = self.meta["act_dim"]
        # Stacked-obs / vz-aware policies (export_json.py meta). Pre-stacking JSON files carry
        # neither key -> base == obs_dim, stack 1: unchanged behavior for the old 5-dim files.
        self.base_obs_dim = int(self.meta.get("base_obs_dim", self.obs_dim))
        self.obs_stack = int(self.meta.get("obs_stack", 1))
        if self.base_obs_dim * self.obs_stack != self.obs_dim:
            raise ValueError(f"inconsistent meta: base_obs_dim {self.base_obs_dim} x obs_stack "
                             f"{self.obs_stack} != obs_dim {self.obs_dim}")
        self.uses_vz = self.base_obs_dim >= 6

    @staticmethod
    def _clipped_gaussian_mean(mu: float, sd: float, lo: float = -1.0, hi: float = 1.0) -> float:
        # E[clip(N(mu, sd))] — mirrors training/ppo.py::clipped_gaussian_mean exactly.
        a = (lo - mu) / sd
        b = (hi - mu) / sd
        cdf_a = 0.5 * (1.0 + math.erf(a / _SQRT2))
        cdf_b = 0.5 * (1.0 + math.erf(b / _SQRT2))
        pdf_a = math.exp(-0.5 * a * a) / _SQRT2PI
        pdf_b = math.exp(-0.5 * b * b) / _SQRT2PI
        return lo * cdf_a + hi * (1.0 - cdf_b) + mu * (cdf_b - cdf_a) - sd * (pdf_b - pdf_a)

    def __call__(self, obs: list[float]) -> list[float]:
        x = obs
        last = len(self.layers) - 1
        for i, (W, b) in enumerate(self.layers):
            y = [sum(wr[j] * x[j] for j in range(len(x))) + b[k] for k, wr in enumerate(W)]
            x = [math.tanh(v) for v in y] if i < last else y
        return [self._clipped_gaussian_mean(x[k], self.sigma[k]) for k in range(self.act_dim)]


def stack_frames(hist: deque, frame: list[float], stack: int) -> list[float]:
    """Push the newest base frame and return the stacked obs, oldest->newest.

    An empty history is seeded by repeating the first frame across the whole stack — exactly
    the env's reset semantics (envs/base.py), which the exporter's ref outputs also use. The
    deque must be created with ``maxlen=stack``; stack 1 degenerates to the plain frame.
    """
    if not hist:
        hist.extend([frame] * stack)
    else:
        hist.append(frame)
    return [v for fr in hist for v in fr]


def check_policy_family(pol: Policy) -> None:
    """This pilot builds [roll, pitch, p, q, r] (+ vz_est) frames — refuse anything else."""
    if pol.base_obs_dim not in (5, 6):
        sys.exit(f"unsupported policy: base_obs_dim {pol.base_obs_dim} (this pilot feeds the "
                 "5-dim hover_blind or 6-dim hover_blind_v2 obs layout only)")
    if pol.obs_stack > 1 or pol.uses_vz:
        print(f"policy: base obs {pol.base_obs_dim}{' (incl. vz_est)' if pol.uses_vz else ''}"
              f" x {pol.obs_stack} stacked frames"
              + ("; external climb-damper P/I DISABLED — the policy owns vertical damping "
                 "(RPM governor stays: absolute thrust anchor)" if pol.uses_vz else ""))


# --- conversions ----------------------------------------------------------------------------


def obs_from_msp(att: dict, imu: dict) -> list[float]:
    """[roll, pitch, p, q, r] in sim convention from MSP attitude (deg) + gyro (raw LSB).

    Signs are EMPIRICAL for this Air65 II stack (2026-07-05: hand-pose check + manual-flight
    command/attitude correlation, 87:1 roll / 57:3 pitch): this board reports nose-down as
    POSITIVE on both attitude pitch and gyro y — same as the sim convention — so pitch takes
    no flip (the textbook BF nose-up+ convention does NOT hold here). Yaw likewise takes NO
    flip (clockwise-spin check 2026-07-07: CW-from-above read gz NEGATIVE, refuting the
    doc-derived gz+ = yaw-right assumption — same inverted-vs-textbook pattern as pitch).
    Only the OBSERVED r is verified; the commanded-yaw sign through the FC is still
    unverified, so fly keeps its --yaw center default.
    """
    roll = math.radians(att["roll_deg"])           # + = roll right (matches sim)
    pitch = math.radians(att["pitch_deg"])         # + = nose down on this board (matches sim)
    gx, gy, gz = (v * GYRO_RAW_TO_DPS for v in imu["gyro_raw"])  # raw LSB -> deg/s
    p = math.radians(gx)                           # + = roll-right rate (check-verified)
    q = math.radians(gy)                           # + = nose-down rate (event-verified)
    r = math.radians(gz)                           # + = CCW-from-above rate (spin-check-verified)
    return [roll, pitch, p, q, r]


def action_to_us(act: list[float], hover_us: int, min_us: int, max_us: int,
                 trim_thrust: float = 0.0) -> list[int]:
    """act-v2 -> AETR channel microseconds [roll, pitch, throttle, yaw]."""
    a0 = max(-1.0, min(1.0, act[0] + trim_thrust))
    t = (a0 + 1.0) * 0.5 * MAX_THRUST_NORMED               # hover-units, 1.0 == hover
    thr = 1000.0 + (hover_us - 1000.0) * math.sqrt(max(0.0, t))
    thr_us = int(max(min_us, min(max_us, thr)))

    wx = act[1] * SIM_MAX_RATE_RP                          # sim rad/s
    wy = act[2] * SIM_MAX_RATE_RP
    wz = act[3] * SIM_MAX_RATE_YAW
    # Command signs: EMPIRICAL from the manual-flight rcData/attitude correlation (see
    # obs_from_msp) — on this setup channel-high = roll right AND nose DOWN (pitch takes no
    # flip, mirroring the telemetry convention). Yaw is doc-derived and unverified; fly
    # streams 1500 there unless --yaw policy.
    roll_us = 1500.0 + 500.0 * max(-1.0, min(1.0, wx / BF_MAX_RATE_RP))    # + = roll right
    pitch_us = 1500.0 + 500.0 * max(-1.0, min(1.0, wy / BF_MAX_RATE_RP))   # + = nose down
    yaw_us = 1500.0 + 500.0 * max(-1.0, min(1.0, -wz / BF_MAX_RATE_YAW))   # sim nose-left+ -> BF nose-right+
    return [int(roll_us), int(pitch_us), thr_us, int(yaw_us)]


def rpm_climb_rate(rpm_now: float | None, rpm_hover: float | None,
                   aero_tau: float = VZ_AERO_TAU) -> float:
    """RPM-anchored vertical climb-rate estimate (m/s) — driftless, replaces the accel integral.

    ``rpm_hover`` is the RMS motor RPM learned at breakaway, i.e. by definition the RPM that
    carries the weight, so ``(rpm_now/rpm_hover)**2 - 1`` is the *measured* net thrust-over-weight
    fraction (thrust ~ rpm^2): >0 while producing climb thrust, <0 while sinking. Times ``g`` that
    is the net vertical specific force; times ``aero_tau`` the quasi-steady climb rate it sustains
    against aero drag. Instantaneous and bounded by the whoop's throttle range around hover — with
    NO integrator it cannot drift to the -VZ_CLAMP rail that flew ``d50var_s8_f1`` into the ceiling.

    Returns ``0.0`` until both the anchor and live RPM telemetry exist (pre-breakaway, or bidir-
    DShot off) — the seek/rise phase owns the throttle then, so a zero damper trim is inert.
    """
    if not rpm_hover or not rpm_now:
        return 0.0
    return ((rpm_now / rpm_hover) ** 2 - 1.0) * 9.81 * aero_tau


def rpm_damper_trim(rpm_now: float | None, rpm_hover: float | None, vz_gain: float,
                    cap: float = VZ_TRIM_CAP) -> float:
    """Proportional altitude-damper trim on act[0] (blind policy) — opposes RPM-measured climb.

    ``-vz_gain`` times :func:`rpm_climb_rate`, clamped to ``+-cap``: negative (pull thrust back)
    while climbing, positive while sinking, exactly zero at hover RPM and before the anchor is
    live. A single cap suffices now that the damper is pure proportional (the retired accel path
    needed a second cap on its P+I sum). Because the input is an instantaneous RPM measurement
    with NO integrator, the trim is bounded by construction — it can never wind to a rail and
    command the phantom climb that put ``d50var_s8_f1`` into the ceiling. Depends ONLY on the RPM
    ratio, never on the accel vz.
    """
    return max(-cap, min(cap, -vz_gain * rpm_climb_rate(rpm_now, rpm_hover)))


# --- MSP plumbing (non-blocking polling on top of MspUdpClient) -----------------------------


class Telemetry:
    """Fire-and-forget MSP pollers + latest-known state. Never blocks the control loop."""

    def __init__(self, fc: MspUdpClient) -> None:
        self.fc = fc
        # Non-blocking reads: poll() must drain EVERY waiting datagram each tick (we send 2-3
        # queries per tick; one blocking read per tick would back-log replies -> stale obs).
        self.fc._sock.settimeout(0.0)
        self.att: dict | None = None
        self.imu: dict | None = None
        self.vbat: float | None = None
        self.rc: tuple[int, ...] | None = None
        self.mt: list[dict] | None = None
        self.t_att = 0.0
        self.t_imu = 0.0
        self.t_rc = 0.0
        self.t_mt = 0.0

    def poll(self, now: float, want_analog: bool = False, want_rc: bool = False,
             want_rpm: bool = False) -> None:
        self.fc.send(MSP_ATTITUDE)
        self.fc.send(MSP_RAW_IMU)
        if want_rpm:
            self.fc.send(MSP_MOTOR_TELEMETRY)
        if want_analog:
            self.fc.send(MSP_ANALOG)
        if want_rc:
            self.fc.send(MSP_RC)
        frames = []
        for _ in range(32):  # drain the socket dry (non-blocking)
            got = self.fc._drain()
            if not got:
                break
            frames.extend(got)
        for frame in frames:
            if frame.is_error:
                continue
            if frame.cmd == MSP_ATTITUDE and len(frame.payload) >= 6:
                self.att, self.t_att = decode_attitude(frame.payload), now
            elif frame.cmd == MSP_RAW_IMU and len(frame.payload) >= 18:
                self.imu, self.t_imu = decode_raw_imu(frame.payload), now
            elif frame.cmd == MSP_ANALOG and len(frame.payload) >= 7:
                self.vbat = decode_analog(frame.payload)["vbat_v"]
            elif frame.cmd == MSP_RC and len(frame.payload) >= 16:
                self.rc, self.t_rc = decode_u16s(frame.payload), now
            elif frame.cmd == MSP_MOTOR_TELEMETRY and len(frame.payload) >= 14:
                self.mt, self.t_mt = decode_motor_telemetry(frame.payload), now

    def rpm_rms(self, now: float) -> float | None:
        """RMS motor RPM (thrust ~ sum(rpm^2)); None if stale, missing, or bidir-DShot off."""
        if self.mt is None or now - self.t_mt > 0.2:
            return None
        vals = [m["rpm"] for m in self.mt]
        if len(vals) < 4 or any(v < 500 for v in vals):
            return None
        return math.sqrt(sum(v * v for v in vals) / len(vals))

    def obs_age(self, now: float) -> float:
        if self.att is None or self.imu is None:
            return float("inf")
        return now - min(self.t_att, self.t_imu)

    def obs(self) -> list[float]:
        return obs_from_msp(self.att, self.imu)


def stream_rc(fc: MspUdpClient, us4: list[int]) -> None:
    # AETR + aux low. Aux is not overridden (mask) — values here are ignored by the FC.
    fc.send(MSP_SET_RAW_RC, pack_rc_channels(us4 + [1000, 1000, 1000, 1000]))


# --- subcommands ----------------------------------------------------------------------------


def cmd_selftest(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    check_policy_family(pol)
    ref_path = Path(args.weights).parent / "policy_ref_outputs.json"
    with open(ref_path) as f:
        ref = json.load(f)
    worst = 0.0
    for name, frame in ref["inputs"].items():
        # Ref inputs are single BASE frames (old 5-dim files: stack 1 -> identity); tiling the
        # frame across the stack is the reset semantics both env and exporter use.
        got = pol(list(frame) * pol.obs_stack)
        want = ref["outputs"][name]
        err = max(abs(g - w) for g, w in zip(got, want))
        worst = max(worst, err)
        print(f"  {name:26s} max|err| {err:.2e}  act {[round(v, 4) for v in got]}")
    ok = worst < 1e-4
    print(f"parity vs {ref_path}: worst {worst:.2e} -> {'OK' if ok else 'FAIL'}")
    if ok:
        def probe(idx: int | None = None, val: float = 0.0) -> list[float]:
            base = [0.0] * pol.base_obs_dim
            if idx is not None:
                base[idx] = val
            return base * pol.obs_stack

        us = action_to_us(pol(probe()), args.hover_us, args.min_us, args.max_us)
        print(f"level-still command @ hover_us={args.hover_us}: AETR {us} "
              f"(throttle should be ~{args.hover_us})")
        # Closed-loop direction sanity through the FULL conversion chain (empirical signs):
        nose_down = action_to_us(pol(probe(1, 0.2)), args.hover_us, args.min_us, args.max_us)
        tilt_right = action_to_us(pol(probe(0, 0.2)), args.hover_us, args.min_us, args.max_us)
        dir_ok = nose_down[1] < 1500 and tilt_right[0] < 1500
        print(f"nose-down obs -> pitch_us {nose_down[1]} (<1500 = nose-up correction); "
              f"tilt-right obs -> roll_us {tilt_right[0]} (<1500 = roll-left correction) "
              f"-> {'OK' if dir_ok else 'FAIL'}")
        ok = ok and dir_ok
        if pol.uses_vz:  # informational: a healthy v2 policy raises thrust against a sink
            sink = action_to_us(pol(probe(5, -0.5)), args.hover_us, args.min_us, args.max_us)
            print(f"sinking obs (vz_est -0.5 m/s) -> throttle {sink[2]} us vs level {us[2]} us "
                  "(expect higher)")
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    check_policy_family(pol)
    print("PROPS OFF check: hand-move the drone and verify (signs per the 2026-07-05 calibration):")
    print("  tilt RIGHT              -> roll(sim) positive,  roll_us  < 1500 (roll-left correction)")
    print("  tilt NOSE DOWN          -> pitch(sim) POSITIVE, pitch_us < 1500 (nose-up correction)")
    print("  spin CLOCKWISE (top)    -> 3rd gyro number NEGATIVE  (verifies the yaw sign; report it!)")
    print("  level & still           -> throttle ~ hover_us, roll/pitch/yaw ~ 1500")
    if pol.uses_vz:
        print("  lift/lower STEADILY     -> vz_est +/- (leaky, decays back); throttle counters it")
    print("Ctrl+C to stop. Nothing is streamed to the FC in this mode.\n")
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        tel = Telemetry(fc)
        hist: deque = deque(maxlen=pol.obs_stack)
        # Same vz estimator the fly loop runs (full projection, leak, clamp, tilt-freeze) so a
        # v2 policy's 6th channel — and its thrust response — can be sanity-checked by hand.
        az_cal: list[int] = []
        az_ref = None
        vz = 0.0
        t_last = None
        try:
            while True:
                now = time.monotonic()
                tel.poll(now, want_analog=True)
                if tel.obs_age(now) < 0.5:
                    o = tel.obs()
                    acc = tel.imu["acc_raw"]
                    if az_ref is None:
                        az_cal.append(acc[2])
                        if len(az_cal) >= 20:
                            tail = az_cal[len(az_cal) // 4:]
                            ref = sum(tail) / len(tail)
                            if abs(ref) > 100:
                                az_ref = ref
                                print(f"  acc 1g = {az_ref:.0f} raw (hold-still cal) — vz estimate live\n")
                    else:
                        dt = min(0.5, now - t_last) if t_last is not None else 0.0
                        f_up = (-acc[0] * math.sin(o[1])
                                + acc[1] * math.cos(o[1]) * math.sin(o[0])
                                + acc[2] * math.cos(o[1]) * math.cos(o[0]))
                        if abs(o[0]) < VZ_TILT_LIMIT and abs(o[1]) < VZ_TILT_LIMIT:
                            vz = (vz + (f_up / az_ref - 1.0) * 9.81 * dt) * math.exp(-dt / VZ_LEAK_TAU)
                            vz = max(-VZ_CLAMP, min(VZ_CLAMP, vz))
                        else:
                            vz *= math.exp(-dt / VZ_LEAK_TAU)
                    t_last = now
                    frame = o + [vz] if pol.uses_vz else o
                    us = action_to_us(pol(stack_frames(hist, frame, pol.obs_stack)),
                                      args.hover_us, args.min_us, args.max_us, args.trim_thrust)
                    print(f"\r roll {math.degrees(o[0]):+6.1f}  pitch(sim) {math.degrees(o[1]):+6.1f} deg"
                          f" | gyro {math.degrees(o[2]):+7.1f} {math.degrees(o[3]):+7.1f}"
                          f" {math.degrees(o[4]):+7.1f} deg/s"
                          + (f" | vz_est {vz:+5.2f} m/s" if pol.uses_vz else "")
                          + f" | cmd RPTY(us) {us}"
                          f" | vbat {tel.vbat or 0:.2f}V   ", end="")
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Discover better vertical-state sensors than acc integration: a barometer (Betaflight
    fuses altitude+vario for us) and bidirectional-DShot RPM telemetry (hover RPM is a true
    thrust anchor, immune to pack freshness/sag). Battery in; props off is fine."""
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        sensors = decode_status_sensors(fc.request(MSP_STATUS))
        print("sensors:", " ".join(f"{k}={'YES' if v else 'no'}" for k, v in sensors.items()))
        try:
            alt = decode_altitude(fc.request(MSP_ALTITUDE))
            print(f"MSP_ALTITUDE: alt {alt['alt_m']:+.2f} m  vario {alt['vario_ms']:+.2f} m/s"
                  + ("" if sensors["baro"] else "  (no baro: expect zeros)"))
        except (MspError, MspTimeout) as e:
            print(f"MSP_ALTITUDE: unavailable ({e})")
        try:
            mt = decode_motor_telemetry(fc.request(MSP_MOTOR_TELEMETRY))
            print("MSP_MOTOR_TELEMETRY:",
                  " ".join(f"m{i}={m['rpm']}rpm({m['invalid_pct']:.0f}%inv)" for i, m in enumerate(mt))
                  or "empty")
            print("  (rpm needs bidirectional DShot; re-run while armed at idle to see nonzero)")
        except (MspError, MspTimeout) as e:
            print(f"MSP_MOTOR_TELEMETRY: unavailable ({e})")
    return 0


def cmd_fly(args: argparse.Namespace) -> int:
    if not args.ack_props_on:
        sys.exit("refusing: fly streams live flight commands. Re-run with --ack-props-on once\n"
                 "the drone is tethered, the area is clear, and YOUR thumb is on the override\n"
                 "switch + arm/kill on the Pocket.")
    pol = Policy(args.weights)
    check_policy_family(pol)
    log_path = Path(args.log or f"runs/pilot/flight_{int(time.time())}.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Never silently clobber a prior flight: if --log names an existing file, wedge a timestamp
    # before the suffix (mirrors the auto-timestamp fallback above). The multi-battery flights
    # were lost this way once — each flight's data is irreplaceable, so a fixed --log stem
    # rolls over to a fresh unique path instead of overwriting.
    if log_path.exists():
        log_path = log_path.with_name(f"{log_path.stem}_{int(time.time())}{log_path.suffix}")
    print(f"logging flight to {log_path}")
    fout = open(log_path, "w", newline="")
    writer = csv.writer(fout)
    writer.writerow(["t", "obs_age_ms", "roll", "pitch", "p", "q", "r",
                     "a_thr", "a_wx", "a_wy", "a_wz", "us_roll", "us_pitch", "us_thr", "us_yaw",
                     "vbat", "hover_eff", "vz_est", "trim", "acc_x", "acc_y", "acc_z",
                     "rpm_rms", "us_corr"])

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))

    period = 1.0 / args.hz
    ramp_s = 1.5  # end-of-flight thrust ramp-down
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        # WHICH aux channel is the override switch? Ask the FC — MSP_MODE_RANGES lists every
        # Modes-tab assignment by permanent box id. (Watching for "any aux that rises" grabbed
        # the ARM flip first: arm and override are both just aux channels on the Pocket.)
        override_rng = arm_rng = ranges = None
        for attempt in range(16):  # ~8 s of patience: single UDP losses must not abort a flight
            try:
                ranges = decode_mode_ranges(fc.request(MSP_MODE_RANGES, retries=0))
                break
            except MspTimeout:
                print("waiting for the FC link" if attempt == 0 else ".",
                      end="", flush=True)
            except MspError as e:
                sys.exit(f"FC rejected MSP_MODE_RANGES: {e}")
        if attempt:
            print()
        if ranges is None and args.aux is None:
            sys.exit("no reply to MSP_MODE_RANGES in ~8 s — bridge/FC link down? Check the bridge "
                     "LED, then: python3 scripts/bench.py --udp <host> info")
        for r in ranges or []:
            if r["perm_id"] == BOX_MSP_OVERRIDE and override_rng is None:
                override_rng = r
            elif r["perm_id"] == BOX_ARM and arm_rng is None:
                arm_rng = r
        if args.aux is not None:
            override_rng = {"aux_idx": args.aux - 1, "lo_us": 1700, "hi_us": 2115}
        if override_rng is None:
            sys.exit("the FC reports no MSP OVERRIDE mode range — assign it to a switch in the\n"
                     "Modes tab (and `save`), or pass --aux N to name the aux channel manually.")
        ov_ch = 4 + override_rng["aux_idx"]  # rcData index
        print(f"override switch = AUX{override_rng['aux_idx'] + 1} "
              f"[{override_rng['lo_us']}-{override_rng['hi_us']} us]"
              + (f"; arm = AUX{arm_rng['aux_idx'] + 1} (ignored)" if arm_rng else ""))

        tel = Telemetry(fc)
        print("acquiring telemetry...")
        t0 = time.monotonic()
        while tel.obs_age(time.monotonic()) > 0.1:
            tel.poll(time.monotonic(), want_analog=True)
            time.sleep(0.02)
            if time.monotonic() - t0 > 10.0:
                sys.exit("no telemetry from the bridge — is the battery in and the LED blinking?")
        print(f"telemetry live (vbat {tel.vbat or 0:.2f} V). hover_us={args.hover_us} "
              f"trim={args.trim_thrust:+.4f} yaw={args.yaw}. Ctrl+C = instant release.")

        # Watch rcData[ov_ch] (straight from the radio — the mask never overrides aux) for an
        # OFF -> IN-RANGE transition of the override switch: that starts the flight clock.
        # The same channel leaving the range mid-flight = manual takeover.
        seen_off = False
        warned_already_on = False
        armed_seen = False
        t_start = None
        if args.takeoff and args.launch:
            sys.exit("pick one of --takeoff / --launch")
        staged = args.launch or args.takeoff
        hold_s = args.hold_seconds if staged else 0.0
        ramp_in_s = (SEEK_TIMEOUT_S + RISE_S) if args.takeoff else (0.5 if args.launch else 0.0)
        if args.takeoff:
            print(f"GROUND-TAKEOFF mode: set the drone LEVEL on the floor, stand clear, ARM on "
                  f"the Pocket, flip the OVERRIDE switch — {hold_s:.0f}s idle countdown, then a "
                  f"slow throttle ramp SEEKS the liftoff point (learning this pack's true hover) "
                  f"and hands to the policy. After the flight it ramps down and lands: DISARM then.")
        elif args.launch:
            print(f"HAND-LAUNCH mode: hold the drone (grip the duct, fingers clear), ARM on the "
                  f"Pocket, flip the OVERRIDE SWITCH — {hold_s:.0f}s idle countdown, then the "
                  f"throttle ramps up WHILE YOU KEEP HOLDING; release only at 'GO'. After the "
                  f"flight it ramps down and settles: DISARM then.")
        else:
            print(f"streaming... FLIP THE OVERRIDE SWITCH to start the {args.seconds}s flight window "
                  "(keep your throttle stick at hover for the handback!)")

        n_sent = n_stale = 0
        worst_age = 0.0
        tick = 0
        last_countdown = -1
        bad_att_since = None  # crash detector: sustained extreme attitude -> cut + release
        vfilt = None          # slow-EMA vbat for the sag-compensated hover anchor
        last_wait_print = 0.0
        az_cal: list[int] = []   # countdown acc-z samples (drone at rest -> 1 g reference)
        az_ref = None
        lvl_cal: list[tuple] = []  # countdown roll/pitch samples (resting on the floor -> LEVEL)
        lvl = (0.0, 0.0)         # attitude bias to subtract: the FC read roll +3.5 / pitch +2.5
        #                          at rest (mount bias); the policy holding that "level" is a
        #                          constant ~0.5 m/s^2 lateral push -> wall (flight 1783324924)
        vz = 0.0                 # leak-filtered climb-rate estimate (m/s, + = up)
        obs_hist: deque = deque(maxlen=pol.obs_stack)  # base-frame history (stacked policies)
        thr_trim = 0.0           # damper trim on act[0]: RPM-anchored (blind) / 0 (vz policy)
        t_last_fresh = None
        t_liftoff_tp = None      # seek-phase time at which the drone left the ground
        hover_learned = None     # this pack's true hover us, measured at breakaway
        v_liftoff = None         # filtered vbat at breakaway (in-flight sag reference)
        fup_buf: list[tuple] = []  # seek-phase (t, f_up): ground-at-throttle 1 g re-reference
        rpm_buf: list[tuple] = []  # seek-phase (t, rms rpm): breakaway rpm == hover rpm
        rpm_hover = None
        us_corr = 0.0            # RPM governor's integrated throttle correction (us)
        trim_roll_rad = math.radians(args.trim_roll_deg)
        trim_pitch_rad = math.radians(args.trim_pitch_deg)
        if args.trim_roll_deg or args.trim_pitch_deg:
            print(f"manual trim: roll {args.trim_roll_deg:+.1f} / pitch {args.trim_pitch_deg:+.1f} deg "
                  "(+ = right / nose-down push)")
        try:
            while not stop["flag"]:
                now = time.monotonic()
                tick += 1
                tel.poll(now, want_analog=(tick % int(args.hz) == 0), want_rc=(tick % 5 == 0),
                         want_rpm=True)
                if tel.vbat:
                    vfilt = tel.vbat if vfilt is None else 0.98 * vfilt + 0.02 * tel.vbat

                if t_start is None and staged and now - last_wait_print > 3.0:
                    last_wait_print = now
                    sw = tel.rc[ov_ch] if tel.rc is not None and len(tel.rc) > ov_ch else None
                    print(f"waiting (idle throttle): override aux{override_rng['aux_idx'] + 1} = "
                          f"{sw if sw is not None else 'no RC data yet'}")

                if tel.rc is not None and len(tel.rc) > ov_ch:
                    ov_on = override_rng["lo_us"] <= tel.rc[ov_ch] <= override_rng["hi_us"]
                    if (arm_rng and not armed_seen and len(tel.rc) > 4 + arm_rng["aux_idx"]
                            and arm_rng["lo_us"] <= tel.rc[4 + arm_rng["aux_idx"]] <= arm_rng["hi_us"]):
                        armed_seen = True
                        print(f"\narm switch ON (aux{arm_rng['aux_idx'] + 1}) — now flip the "
                              f"OVERRIDE switch (aux{override_rng['aux_idx'] + 1}) to start")
                    if t_start is None:
                        if not ov_on:
                            seen_off = True
                        elif seen_off:
                            t_start = now
                            print(f"\noverride ON (aux{override_rng['aux_idx'] + 1}) -> policy flying")
                        elif not warned_already_on:
                            warned_already_on = True
                            print("override switch is already ON — flip it OFF, then ON to start")
                    elif not ov_on:
                        print("\noverride switch OFF -> manual takeover, releasing")
                        break

                t_fl = (now - t_start) if t_start is not None else 0.0
                t_air = t_fl - hold_s - ramp_in_s  # airborne time (launch phases excluded)
                if t_start is not None and t_air >= args.seconds + ramp_s:
                    break
                age = tel.obs_age(now)
                worst_age = max(worst_age, min(age, 9.9))
                if age > args.max_obs_age:
                    n_stale += 1
                    if age > 0.5 and t_start is not None:
                        print(f"\nobs stale {age * 1e3:.0f} ms -> releasing to Pocket")
                        break  # stop streaming: Betaflight freshness window hands back RC
                    # brief staleness: skip this tick (FC holds last values up to 300 ms).
                    # While still WAITING for the switch, stales are harmless (idle stream,
                    # drone on the ground) — never exit, just keep polling.
                else:
                    o = tel.obs()
                    # Crash detector (flight_1783273010: it lay INVERTED for 2 s with motors
                    # grinding at 1467 us — the blind policy can't know it's on its back).
                    # Sustained-only, so mid-tumble sign flips through +-180 don't cut a
                    # recovery attempt; a settled upside-down/pinned drone trips it fast.
                    hopeless = abs(o[0]) > math.radians(110) or abs(o[1]) > math.radians(80)
                    if t_start is not None and hopeless:
                        if bad_att_since is None:
                            bad_att_since = now
                        elif now - bad_att_since > 0.3:
                            print(f"\ncrashed (|roll| {math.degrees(abs(o[0])):.0f} deg for 0.3 s)"
                                  " -> releasing, DISARM on the Pocket")
                            break
                    else:
                        bad_att_since = None
                    # Acc-z climb damper (see VZ_* constants). Calibrate the 1 g reference while
                    # the drone rests through the countdown; integrate from spool start so the
                    # takeoff boost's climb rate is known — and damped — at handoff.
                    acc_z = tel.imu["acc_raw"][2]
                    rpm_now = tel.rpm_rms(now)
                    dt_tick = min(0.1, now - t_last_fresh) if t_last_fresh is not None else 0.0
                    if (args.takeoff and t_start is not None and t_liftoff_tp is None
                            and t_fl >= hold_s and rpm_now):
                        rpm_buf.append((t_fl - hold_s, rpm_now))
                    if t_start is not None and staged and t_fl < hold_s:
                        if t_fl > 0.5:
                            az_cal.append(acc_z)
                            if args.takeoff:  # resting on the floor: this attitude IS level
                                lvl_cal.append((o[0], o[1]))
                    elif az_ref is None and len(az_cal) >= 20:
                        tail = az_cal[len(az_cal) // 4:]
                        ref = sum(tail) / len(tail)
                        if abs(ref) > 100:
                            az_ref = ref
                            print(f"  acc 1g = {az_ref:.0f} raw ({len(az_cal)} rest samples) "
                                  f"— climb damper armed (gain {args.vz_gain})")
                        if lvl_cal:
                            n = len(lvl_cal)
                            tail_l = lvl_cal[n // 4:]
                            lvl = (sum(v[0] for v in tail_l) / len(tail_l),
                                   sum(v[1] for v in tail_l) / len(tail_l))
                            print(f"  level reference: roll {math.degrees(lvl[0]):+.1f} / "
                                  f"pitch {math.degrees(lvl[1]):+.1f} deg (floor-rest bias, "
                                  "subtracted from the policy's view)")
                    if (az_ref is not None and (args.vz_gain > 0 or pol.uses_vz)
                            and t_start is not None and t_fl >= hold_s):
                        dt = dt_tick
                        # Full projection of specific force onto world-up (RAW attitude — acc
                        # and attitude share the mount, so raw-with-raw is self-consistent).
                        # z-only undercounted lift by (1-cos)*g during ordinary wobble: every
                        # hover window of 1783342678-842 showed vz mean -0.6..-1.25 "descent"
                        # while the drone visibly climbed. Axis signs fitted on those logs.
                        ax, ay = tel.imu["acc_raw"][0], tel.imu["acc_raw"][1]
                        f_up = (-ax * math.sin(o[1])
                                + ay * math.cos(o[1]) * math.sin(o[0])
                                + acc_z * math.cos(o[1]) * math.cos(o[0]))
                        if args.takeoff and t_liftoff_tp is None:
                            fup_buf.append((t_fl - hold_s, f_up))
                        if abs(o[0]) < VZ_TILT_LIMIT and abs(o[1]) < VZ_TILT_LIMIT:
                            a_vert = (f_up / az_ref - 1.0) * 9.81
                            vz = (vz + a_vert * dt) * math.exp(-dt / VZ_LEAK_TAU)
                            vz = max(-VZ_CLAMP, min(VZ_CLAMP, vz))
                        else:
                            vz *= math.exp(-dt / VZ_LEAK_TAU)  # tilted: no new evidence, decay
                        # vz above is the accel-integrated estimate — still what a vz-consuming
                        # policy sees (obs channel 6) and what the takeoff SEEK reads to detect
                        # breakaway before any RPM anchor exists. It is NO LONGER a control input
                        # for a blind policy: that damper rides the driftless RPM climb rate below.
                        if pol.uses_vz:
                            # The policy sees vz and owns vertical damping — external P/I stay
                            # zero (they fought the policy through a biased estimate). The RPM
                            # governor below stays: vz is high-passed and cannot see DC thrust.
                            thr_trim = 0.0
                        else:
                            # RPM-anchored proportional damper (replaces the accel vz P + i_trim):
                            # a driftless thrust-excess climb rate, so no -VZ_CLAMP rail can pile
                            # on phantom thrust (the d50var_s8_f1 ceiling bug). The retired i_trim's
                            # job — absorbing the pack's DC thrust bias — is now the RPM governor's
                            # integral (one rpm_hover anchor, one (rpm/rpm_hover)^2 measurement
                            # shared: fast proportional damper here, slow governor there).
                            thr_trim = rpm_damper_trim(rpm_now, rpm_hover, args.vz_gain)
                            if rpm_hover:
                                # log the RPM climb rate (driftless) once anchored, in place of
                                # the accel vz — so flight_metrics.vertical.vz_rail_* reads the
                                # signal the damper actually used (bounded, cannot rail).
                                vz = rpm_climb_rate(rpm_now, rpm_hover)
                    t_last_fresh = now
                    # Level reference + manual trim, policy's view only (estimator uses raw).
                    # Backwards drift -> positive --trim-pitch-deg (holds more nose-down).
                    o = [o[0] - lvl[0] - trim_roll_rad,
                         o[1] - lvl[1] - trim_pitch_rad, o[2], o[3], o[4]]

                    # Base frame (+ the vz channel for v2 policies), stacked oldest->newest.
                    frame = o + [vz] if pol.uses_vz else o
                    act = pol(stack_frames(obs_hist, frame, pol.obs_stack))
                    if t_air > args.seconds:  # ramp down: ease thrust action toward floor
                        k = (t_air - args.seconds) / ramp_s
                        act = [act[0] * (1 - k) + (-1.0) * k, act[1], act[2], act[3]]
                    # Hover anchor: the liftoff-learned value, sag-adjusted RELATIVE to the
                    # voltage at liftoff (same pack, same flight — unlike the retired absolute
                    # vbat comp, this ratio is defensible: duty ~ 1/V as the pack sags in-flight,
                    # e.g. 1783342817 sagged 3.41 -> 3.06 V within one flight).
                    base_hover = hover_learned if hover_learned is not None else args.hover_us
                    comp = 1.0
                    if args.vbat_ref > 0 and vfilt:  # legacy absolute mode (opt-in)
                        comp = max(0.9, min(1.2, args.vbat_ref / vfilt))
                    elif v_liftoff and vfilt:
                        comp = max(0.97, min(1.12, v_liftoff / vfilt))
                    hover_eff = int(1000 + (base_hover - 1000) * comp)
                    us = action_to_us(act, hover_eff, args.min_us, args.max_us,
                                      args.trim_thrust + thr_trim)
                    if args.yaw == "center":
                        us[3] = 1500  # zero-rate setpoint: the FC damps yaw itself (sign unverified)
                    if staged and t_start is None:
                        # Waiting for the switch: stream IDLE, never the policy's hover throttle.
                        # (Streaming ~1410 us while waiting meant an early/undetected override
                        # flip sent the drone STRAIGHT UP — observed, ceiling included.)
                        us = [1500, 1500, args.min_us, 1500]
                    elif t_start is not None and staged and t_fl < hold_s:
                        # Countdown: props at idle (in hand for --launch, on the floor for --takeoff).
                        us = [1500, 1500, args.min_us, 1500]
                        remaining = int(hold_s - t_fl) + 1
                        if remaining != last_countdown:
                            last_countdown = remaining
                            print(f"  {'liftoff' if args.takeoff else 'throttle'} in {remaining}...")
                    elif t_start is not None and staged and t_fl < hold_s + ramp_in_s:
                        if last_countdown != 0:
                            last_countdown = 0
                            print("  seeking liftoff (slow ramp)..." if args.takeoff
                                  else "  throttle ramping — KEEP HOLDING")
                        tp = t_fl - hold_s
                        if args.takeoff:
                            if t_liftoff_tp is None:      # seek: slow ramp until acc-z sees liftoff
                                if tp < SEEK_SPOOL_S:
                                    us[2] = int(args.min_us
                                                + (SEEK_START_US - args.min_us) * (tp / SEEK_SPOOL_S))
                                else:
                                    us[2] = int(min(args.max_us,
                                                    SEEK_START_US + SEEK_RATE_US_S * (tp - SEEK_SPOOL_S)))
                                if us[2] > 1250 and vz > LIFT_VZ:
                                    t_liftoff_tp = tp
                                    hover_learned = max(1250, min(1550, us[2] - LIFT_LAG_US))
                                    ramp_in_s = t_liftoff_tp + RISE_S  # flight clock: rise ends it
                                    v_liftoff = vfilt
                                    print(f"  LIFTOFF at {us[2]} us -> hover anchor learned: "
                                          f"{hover_learned} us")
                                    # Re-reference 1 g from the ground-at-throttle window just
                                    # before breakaway: props-on vibration shifts the acc DC by
                                    # +-3-5% vs the idle countdown (measured across 1783342xxx),
                                    # and that error IS the damper's drift.
                                    cal = [f for (tt, f) in fup_buf if tp - 0.7 <= tt <= tp - 0.2]
                                    if len(cal) >= 8:
                                        new_ref = sum(cal) / len(cal)
                                        print(f"  1g re-referenced at throttle: {az_ref:.0f} -> "
                                              f"{new_ref:.0f} ({(new_ref / az_ref - 1) * 100:+.1f}%)")
                                        az_ref = new_ref
                                        vz = 0.3  # we know it just lifted at ~this rate
                                    rcal = [v for (tt, v) in rpm_buf if tp - 0.3 <= tt <= tp - 0.02]
                                    if len(rcal) >= 4:
                                        rpm_hover = sum(rcal) / len(rcal)
                                        print(f"  hover RPM anchor: {rpm_hover:.0f} rms "
                                              "(breakaway = weight) — RPM governor armed")
                                elif tp > SEEK_TIMEOUT_S:
                                    print("\nno liftoff within the seek window — weak pack or prop "
                                          "drag? releasing, DISARM")
                                    break
                            else:                         # rise: gentle climb-out on the LEARNED anchor
                                us[2] = int(1000 + (hover_learned - 1000) * math.sqrt(RISE_THRUST))
                        else:                             # --launch: idle -> policy while still held
                            us[2] = int(args.min_us + (us[2] - args.min_us) * (tp / ramp_in_s))
                    elif t_start is not None and args.launch and last_countdown != -2:
                        last_countdown = -2  # throttle is fully up now — only NOW let go
                        print("  GO — release!")
                    # RPM thrust governor (free flight only): steer throttle so the MEASURED
                    # thrust (rpm/rpm_hover)^2 tracks what the policy is asking for.
                    if (rpm_hover and rpm_now and t_start is not None
                            and t_fl >= hold_s + ramp_in_s):
                        a0c = max(-1.0, min(1.0, act[0] + args.trim_thrust + thr_trim))
                        t_des = (a0c + 1.0) * 0.5 * MAX_THRUST_NORMED
                        rpm_err = (rpm_now / rpm_hover) ** 2 - t_des
                        us_corr = max(-RPM_CORR_CAP,
                                      min(RPM_CORR_CAP, us_corr - RPM_KI_US * rpm_err * dt_tick))
                        us[2] = int(max(args.min_us, min(args.max_us, us[2] + us_corr)))
                    stream_rc(fc, us)
                    n_sent += 1
                    writer.writerow([f"{t_fl:.3f}", f"{age * 1e3:.0f}",
                                     *[f"{v:.4f}" for v in o], *[f"{v:.4f}" for v in act],
                                     *us, tel.vbat or "", hover_eff,
                                     f"{vz:.3f}", f"{thr_trim:+.4f}", *tel.imu["acc_raw"],
                                     f"{rpm_now:.0f}" if rpm_now else "", f"{us_corr:+.0f}"])
                time.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            fout.close()
        print(f"\nreleased. {n_sent} frames streamed, {n_stale} stale ticks, "
              f"worst obs age {worst_age * 1e3:.0f} ms. Log: {log_path}"
              + (f"\nlearned hover anchor this pack: {hover_learned} us (breakaway-measured)"
                 if hover_learned else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--udp", required=True, metavar="HOST[:PORT]", help="bridge address")
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    ap.add_argument("--hover-us", type=int, default=1410, help="bench-measured hover throttle (us)")
    ap.add_argument("--vbat-ref", type=float, default=0.0,
                    help="DEPRECATED voltage re-anchoring of the throttle map (duty ~ 1/V). "
                         "Default 0 = OFF: loaded vbat proved a bad thrust proxy in both "
                         "directions (flights 1783278136/1783280676); the acc-z climb damper "
                         "owns thrust bias now. Set to the calibration voltage to re-enable.")
    ap.add_argument("--trim-thrust", type=float, default=0.0, help="additive act[0] trim (bench-calibrated)")
    ap.add_argument("--min-us", type=int, default=1000)
    ap.add_argument("--max-us", type=int, default=1600, help="hard throttle ceiling for early flights")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    sub.add_parser("check")
    sub.add_parser("probe")
    fly = sub.add_parser("fly")
    fly.add_argument("--seconds", type=float, default=15.0)
    fly.add_argument("--hz", type=float, default=50.0)
    fly.add_argument("--max-obs-age", type=float, default=0.25, help="stale-obs watchdog (s)")
    fly.add_argument("--yaw", choices=["center", "policy"], default="center",
                     help="yaw channel: center (1500, FC damps yaw; default until the yaw sign "
                          "is verified) or policy")
    fly.add_argument("--takeoff", action="store_true",
                     help="ground-takeoff flow (RECOMMENDED): drone level on the floor; after the "
                          "override switch, idle countdown, spool to --boost x hover for --boost-s, "
                          "then hand to the policy")
    fly.add_argument("--boost", type=float, default=1.18,
                     help="DEPRECATED, ignored: --takeoff now auto-seeks the liftoff throttle")
    fly.add_argument("--boost-s", type=float, default=0.6,
                     help="DEPRECATED, ignored: --takeoff now auto-seeks the liftoff throttle")
    fly.add_argument("--launch", action="store_true",
                     help="hand-launch flow: after the override switch, idle countdown, throttle "
                          "ramps WHILE HELD, release only at GO")
    fly.add_argument("--hold-seconds", type=float, default=3.0)
    fly.add_argument("--vz-gain", type=float, default=0.15,
                     help="climb damper gain (act[0] per m/s of RPM-anchored climb rate for a "
                          "blind policy; vz-consuming policies own damping and ignore it); "
                          "0 disables")
    fly.add_argument("--trim-roll-deg", type=float, default=0.0,
                     help="manual level trim: + pushes RIGHT (drifts left -> positive)")
    fly.add_argument("--trim-pitch-deg", type=float, default=0.0,
                     help="manual level trim: + pushes FORWARD/nose-down (drifts backwards -> "
                          "positive, start with 1.5)")
    fly.add_argument("--aux", type=int, default=None, metavar="N",
                     help="override-switch aux channel number (1-4); normally auto-detected "
                          "from the FC's MSP OVERRIDE mode range")
    fly.add_argument("--log", default=None)
    fly.add_argument("--ack-props-on", action="store_true")
    args = ap.parse_args()

    host, _, port = args.udp.partition(":")
    args.udp_host, args.udp_port = host, int(port or 14550)
    return {"selftest": cmd_selftest, "check": cmd_check, "probe": cmd_probe,
            "fly": cmd_fly}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
