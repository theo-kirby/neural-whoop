"""The act-v2 :class:`~neural_whoop.contract.ActionLimits` scalars, **mirrored** for pure numpy.

``contract.py`` imports torch, so a pure module cannot read the limits off it. They are pinned
here instead and ``tests/test_reference.py`` asserts the two agree — the same discipline
``scripts/takeoff_flip_land.py`` uses for ``MIN_THRUST_NORMED``. If someone retunes the
contract, that test fails rather than the reference silently drifting off the envelope it claims
to respect.
"""

from __future__ import annotations

#: Max collective thrust in DiffAero normed units (1.0 == a weight-cancelling hover).
MAX_THRUST_NORMED = 4.0
#: Thrust that cancels gravity (DiffAero convention).
HOVER_THRUST_NORMED = 1.0
#: Max |roll/pitch rate| the act-v2 channel maps onto (rad/s).
MAX_BODY_RATE_RP_RPS = 12.0
#: Max |yaw rate| (rad/s).
MAX_BODY_RATE_YAW_RPS = 6.0
#: The deploy free-flight throttle floor (``FlightParams.min_thrust_frac``, ``acro_flip``'s
#: ``act:`` section). The ``--deployable`` reference variant coasts at this instead of at zero.
DEPLOY_MIN_THRUST_NORMED = 0.25

#: Height of the drone's ORIGIN above the floor at rest (m) — mirrored from
#: ``contract.WHOOP_REST_Z_M`` for the same reason as the limits above.
WHOOP_REST_Z_M = 0.0092

#: Fraction of :data:`MAX_BODY_RATE_RP_RPS` the authored **rate commands** are allowed to use.
#: The reference is a target, so it must not sit on its own envelope: a regression that silently
#: saturates has to fail a test, which it cannot do if the reference already saturates. 3% of
#: headroom is what ``verify.check_limits`` asserts against.
RATE_CMD_HEADROOM = 0.03
#: The largest body-rate **command** the reference will author (rad/s).
MAX_RATE_CMD_RPS = MAX_BODY_RATE_RP_RPS * (1.0 - RATE_CMD_HEADROOM)


def act_v2_from_diffaero(
    normed_thrust: float,
    rates_rps: tuple[float, float, float],
    *,
    min_thrust_normed: float = 0.0,
) -> list[float]:
    """Invert ``action_to_diffaero``: DiffAero CTBR -> normalized act-v2 ``[-1, 1]``.

    Mirrors ``scripts/takeoff_flip_land.py::_act_v2_from_ctbr`` so a reference replay carries
    the *same* ``action`` / ``action_diffaero`` pair a policy rollout would. The
    ``min_thrust_normed`` floor is informational here (the generator never authors a thrust below
    it in the ``--deployable`` variant); it is accepted so the caller can assert that.

    Args:
        normed_thrust: DiffAero collective thrust (1.0 == hover).
        rates_rps: Body rate commands ``(wx, wy, wz)`` in rad/s.
        min_thrust_normed: The free-flight throttle floor this stream was authored under.

    Returns:
        The 4-vector act-v2 action, each channel clipped to ``[-1, 1]``.
    """
    thrust = max(float(normed_thrust), float(min_thrust_normed))
    a0 = thrust / MAX_THRUST_NORMED * 2.0 - 1.0
    a1 = rates_rps[0] / MAX_BODY_RATE_RP_RPS
    a2 = rates_rps[1] / MAX_BODY_RATE_RP_RPS
    a3 = rates_rps[2] / MAX_BODY_RATE_YAW_RPS
    return [max(-1.0, min(1.0, float(v))) for v in (a0, a1, a2, a3)]
