"""Hand-authored **reference maneuvers** — "this is the one we want", as data.

Everything else in this repo renders a *policy rollout*: we watch what the drone did and grade
it. Nothing says what it **should** do. This package builds that target: a maneuver authored by
hand, deterministically, where every physical quantity — attitude, body rates, collective thrust,
and the accelerometer the onboard IMU would read — is **derived** from the authored path/commands
rather than guessed.

The load-bearing idea is **differential flatness**: a quadrotor's position trajectory *determines*
its attitude, body rates and thrust exactly, so for the powered, level-ish parts of a flight
working out the thrust is algebra, not a job for RL. The flip is the exception, and it is what
dictates the whole design — see :mod:`~neural_whoop.reference.flatness` and
:mod:`~neural_whoop.reference.maneuvers`, and ``docs/REFERENCE_MANEUVER.md``.

The package is **pure numpy + stdlib** — importable without torch, unit-testable without the
simulator — the same convention as :mod:`neural_whoop.contract` / :mod:`neural_whoop.course` /
:mod:`neural_whoop.reward`.

Modules
-------
- :mod:`model` — :class:`RefModel`, the airframe the reference is derived against (mirrors
  ``WhoopParams`` defaults; a test asserts they match).
- :mod:`limits` — the four ``ActionLimits`` scalars mirrored (a pure module cannot import
  ``contract.py``, which pulls torch); a test asserts equality.
- :mod:`flatness` — the flatness map ``p(t) -> (R, ω, normed_thrust)`` and its inverse.
- :mod:`segments` — ``PathSegment`` / ``RateSegment`` / ``BallisticSegment`` / ``Trajectory``.
- :mod:`maneuvers` — ``FlipSpec``, ``solve_flip`` (the damped-Newton shoot), ``build_sequence``.
- :mod:`imu` — body-frame specific force (what the onboard accelerometer reads).
- :mod:`emit` — ``Samples`` -> replay document + ``reference.json``.
- :mod:`verify` — residual / limit / allocation / continuity checks.
"""

from __future__ import annotations

from neural_whoop.reference.limits import (
    DEPLOY_MIN_THRUST_NORMED,
    HOVER_THRUST_NORMED,
    MAX_BODY_RATE_RP_RPS,
    MAX_BODY_RATE_YAW_RPS,
    MAX_THRUST_NORMED,
)
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.imu import specific_force_body
from neural_whoop.reference.segments import (
    BallisticSegment,
    PathSegment,
    RateSegment,
    RefState,
    Samples,
    Trajectory,
)

__all__ = [
    "BallisticSegment",
    "DEPLOY_MIN_THRUST_NORMED",
    "HOVER_THRUST_NORMED",
    "MAX_BODY_RATE_RP_RPS",
    "MAX_BODY_RATE_YAW_RPS",
    "MAX_THRUST_NORMED",
    "PathSegment",
    "RateSegment",
    "RefModel",
    "RefState",
    "Samples",
    "Trajectory",
    "specific_force_body",
]
