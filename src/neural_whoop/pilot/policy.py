"""The pure-Python TinyPolicy actor + the act-v2 <-> MSP conversions and the RPM altitude damper.

Moved verbatim from ``scripts/pilot.py`` (only the constant imports now come from
:mod:`neural_whoop.pilot.config`); the numerics are byte-for-byte identical so the deploy-exact
``selftest`` parity and the ``sim_vs_real`` offline diff are unaffected. Dependency-free stdlib
(``math`` + ``json``): a [64,64] MLP forward is ~5k MACs, microseconds in CPython.

Weights are produced from a checkpoint by ``scripts/export_json.py``. Deploy convention is the
clipped-Gaussian effective mean E[clip(N(mu, sigma))] (math.erf). Stacked/vz-aware policies
(meta.obs_stack/base_obs_dim) grow the pilot's own leaky climb-rate estimate as channel 6 and see
the last ``obs_stack`` frames concatenated oldest->newest.
"""

from __future__ import annotations

import json
import math
import sys
from collections import deque

from .config import (
    BF_MAX_RATE_RP,
    BF_MAX_RATE_YAW,
    GYRO_RAW_TO_DPS,
    MAX_THRUST_NORMED,
    SIM_MAX_RATE_RP,
    SIM_MAX_RATE_YAW,
    VZ_AERO_TAU,
    VZ_TRIM_CAP,
    _SQRT2,
    _SQRT2PI,
)


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
