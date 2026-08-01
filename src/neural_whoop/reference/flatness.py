"""The differential-flatness map: author a path, and the attitude/rates/thrust fall out.

A quadrotor is differentially flat in ``(x, y, z, ψ)``. Given a position trajectory and a heading,
the required **attitude, body rates and collective thrust are determined exactly** — no search, no
learning, algebra. That is what makes "hard-code the path" a legitimate way to author the powered,
level-ish parts of a flight, and it is why working out the thrust is *not* a job for RL.

The signs here are fixed by the vendored dynamics (``third_party/diffaero/dynamics/quadrotor.py``
lines 111-142), not by a textbook: ``G_vec = [0, 0, −g]``, drag is a **force**
``f_drag = R D Rᵀ v`` subtracted from ``m·a``, and quaternions are real-last (xyzw). With
isotropic ``D`` the drag term collapses to ``D·v`` and the map is closed form::

    a    = normed_thrust·g·z_B − g·ê_z − (D/m)·v          [the simulator's own ODE]
    f    = a + g·ê_z + (D/m)·v  =  normed_thrust·g·z_B    [the specific force]
    normed_thrust = ‖f‖ / g                               [mass cancels — controller.py:102]
    z_B  = f/‖f‖
    ḟ    = jerk + (D/m)·a
    ω_x  = −(y_B·ḟ)/‖f‖ ,  ω_y = +(x_B·ḟ)/‖f‖             [exact, not finite-differenced]

Because the map consumes **jerk**, a path segment must be at least C³ at its seams or the emitted
body rate jumps at every join — which is why :mod:`~neural_whoop.reference.segments` uses septic
(8-coefficient) polynomials matching ``{p, ṗ, p̈, p⃛}`` at both ends rather than the usual quintic.

Two structural facts this module encodes, both of which shape the maneuver design:

**Flatness cannot author a flip.** The map inverts ``p(t) → (attitude, thrust)`` only while thrust
is positive. Through inversion the required specific force still points *up* while the body's
thrust axis points *down*, so the map would demand negative thrust; it has no solution there.
Position is therefore an **output** of the flip, not an input — through the flip we author the
*commands* and let physics return the path (see
:class:`~neural_whoop.reference.segments.RateSegment`).

**The heading construction is singular at 90° of tilt.** Both standard constructions pick the body
y (or x) axis from a horizontal heading reference, and that reference becomes parallel to ``z_B``
at 90°. :func:`attitude_from_f` therefore takes a ``heading`` argument selecting *which* reference
to use, so a roll-axis maneuver (which tilts about body x, never toward ``x_C``) uses ``"x_c"`` and
a pitch-axis maneuver uses ``"y_c"``. Each is non-degenerate for its own maneuver plane, and both
raise rather than returning garbage.
"""

from __future__ import annotations

import numpy as np

from neural_whoop.reference.model import RefModel

#: Below this normed thrust the attitude is not recoverable from the path: ``z_B = f/‖f‖`` has no
#: meaningful direction and ``ω = ±(x_B|y_B)·ḟ/‖f‖`` blows up. It fires on free fall **and** — the
#: non-obvious one — on steady descent at terminal velocity, where ``a = 0`` but the drag term
#: exactly cancels gravity in ``f``. Those are the same statement.
MIN_NORMED_THRUST = 0.30

#: ``‖z_B × heading_ref‖`` below this means the heading reference has gone parallel to the thrust
#: axis (~90° of tilt toward it) and the attitude is ill-defined.
MIN_HEADING_CROSS = 1e-3

_E_Z = np.array([0.0, 0.0, 1.0])

#: Valid ``heading`` constructions. ``"x_c"`` builds ``y_B`` from ``z_B × x_C`` (the Mellinger
#: convention) and is non-degenerate for a **roll**-axis maneuver; ``"y_c"`` builds ``x_B`` from
#: ``y_C × z_B`` and is non-degenerate for a **pitch**-axis maneuver.
HEADINGS = ("x_c", "y_c")


class SingularFlatnessError(RuntimeError):
    """The flatness map has no solution for this state (thrust too low / heading degenerate).

    Raised rather than returning NaN: a NaN in a reference trajectory propagates silently into an
    artifact that *looks* fine, and the whole point of this package is that the numbers are true.
    """


def _norm(v: np.ndarray) -> np.ndarray:
    return np.linalg.norm(v, axis=-1)


def _dot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.sum(a * b, axis=-1)


def _heading_refs(psi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(x_C, y_C)`` — the yaw-frame horizontal axes for heading ``ψ``, shape ``(..., 3)``."""
    c, s = np.cos(psi), np.sin(psi)
    zero = np.zeros_like(c)
    return np.stack([c, s, zero], axis=-1), np.stack([-s, c, zero], axis=-1)


def specific_force(acc: np.ndarray, vel: np.ndarray, model: RefModel) -> np.ndarray:
    """The specific force the airframe must produce: ``f = a + g·ê_z + (D/m)·v``, ``(..., 3)``.

    This is the simulator's own acceleration equation rearranged, so a sign error here would show
    up immediately in the round-trip test — which is exactly what that test is for.
    """
    acc = np.asarray(acc, dtype=np.float64)
    vel = np.asarray(vel, dtype=np.float64)
    return acc + model.g * _E_Z + model.drag_per_mass * vel


def normed_thrust_from_f(f: np.ndarray, model: RefModel, *, check: bool = True) -> np.ndarray:
    """``‖f‖/g`` — the DiffAero collective thrust (1.0 == hover). Mass cancels.

    Raises:
        SingularFlatnessError: if any sample is below :data:`MIN_NORMED_THRUST` and ``check``.
    """
    nt = _norm(np.asarray(f, dtype=np.float64)) / model.g
    if check and np.any(nt < MIN_NORMED_THRUST):
        worst = float(np.min(nt))
        raise SingularFlatnessError(
            f"flatness is singular: normed thrust {worst:.4f} < {MIN_NORMED_THRUST} — the path "
            f"asks for near-zero specific force, so attitude and body rate are undefined. This "
            f"fires on free fall AND on steady descent at terminal velocity "
            f"({model.terminal_velocity_mps:.2f} m/s), which are the same statement. Author this "
            f"stretch as a RateSegment (commands in, path out) instead."
        )
    return nt


def attitude_from_f(
    f: np.ndarray, psi: np.ndarray | float, *, heading: str = "x_c"
) -> np.ndarray:
    """Body->world rotation ``R`` (columns ``[x_B | y_B | z_B]``) from specific force + heading.

    Args:
        f: Specific force, shape ``(..., 3)``. Must be non-degenerate (see
            :func:`normed_thrust_from_f`).
        psi: Heading (rad), broadcastable to ``f``'s leading shape.
        heading: ``"x_c"`` (``y_B ∝ z_B × x_C``) or ``"y_c"`` (``x_B ∝ y_C × z_B``). Pick the one
            whose reference axis stays out of the maneuver plane — see the module docstring.

    Returns:
        ``(..., 3, 3)`` rotation matrices.

    Raises:
        SingularFlatnessError: heading reference parallel to the thrust axis, or ``‖f‖ == 0``.
    """
    if heading not in HEADINGS:
        raise ValueError(f"heading must be one of {HEADINGS}, got {heading!r}")
    f = np.asarray(f, dtype=np.float64)
    nf = _norm(f)
    if np.any(nf <= 0.0):
        raise SingularFlatnessError("attitude_from_f: ‖f‖ == 0 (no thrust direction).")
    z_B = f / nf[..., None]
    psi = np.broadcast_to(np.asarray(psi, dtype=np.float64), nf.shape)
    x_C, y_C = _heading_refs(psi)

    if heading == "x_c":
        u = np.cross(z_B, x_C)
        nu = _norm(u)
        _check_heading(nu, heading)
        y_B = u / nu[..., None]
        x_B = np.cross(y_B, z_B)
    else:
        u = np.cross(y_C, z_B)
        nu = _norm(u)
        _check_heading(nu, heading)
        x_B = u / nu[..., None]
        y_B = np.cross(z_B, x_B)
    return np.stack([x_B, y_B, z_B], axis=-1)


def _check_heading(nu: np.ndarray, heading: str) -> None:
    if np.any(nu < MIN_HEADING_CROSS):
        raise SingularFlatnessError(
            f"heading construction {heading!r} is degenerate: the horizontal reference axis has "
            f"gone parallel to the thrust axis (‖cross‖ = {float(np.min(nu)):.2e}, i.e. ~90° of "
            f"tilt toward it). Use the other construction for this maneuver plane."
        )


def rates_from_jerk(
    f: np.ndarray,
    fdot: np.ndarray,
    R: np.ndarray,
    psi: np.ndarray | float,
    psidot: np.ndarray | float,
    *,
    heading: str = "x_c",
) -> np.ndarray:
    """Body angular velocity ``ω = [p, q, r]`` (rad/s) — exact, from ``ḟ``, not differenced.

    ``ż_B = ω_y·x_B − ω_x·y_B`` and ``ż_B`` is the component of ``ḟ/‖f‖`` perpendicular to ``z_B``,
    which gives the roll/pitch rates directly. ``ω_z`` comes from differentiating the heading
    construction itself, so it carries both the ``ψ̇`` term and the (usually forgotten) term from
    the thrust axis tipping relative to a *fixed* heading reference.

    Args:
        f: Specific force ``(..., 3)``.
        fdot: Its time derivative ``jerk + (D/m)·a``, ``(..., 3)``.
        R: The attitude from :func:`attitude_from_f`, ``(..., 3, 3)``.
        psi: Heading (rad).
        psidot: Heading rate (rad/s).
        heading: Same construction that produced ``R``.

    Returns:
        ``(..., 3)`` body rates.
    """
    f = np.asarray(f, dtype=np.float64)
    fdot = np.asarray(fdot, dtype=np.float64)
    nf = _norm(f)
    x_B, y_B, z_B = R[..., 0], R[..., 1], R[..., 2]

    wx = -_dot(y_B, fdot) / nf
    wy = _dot(x_B, fdot) / nf
    # The thrust-axis rate, i.e. the part of ḟ/‖f‖ perpendicular to z_B.
    zdot_B = (fdot - _dot(z_B, fdot)[..., None] * z_B) / nf[..., None]

    psi = np.broadcast_to(np.asarray(psi, dtype=np.float64), nf.shape)
    psidot = np.broadcast_to(np.asarray(psidot, dtype=np.float64), nf.shape)
    x_C, y_C = _heading_refs(psi)

    if heading == "x_c":
        # y_B ∝ z_B × x_C  ->  ω_z = −x_B·ẏ_B
        u = np.cross(z_B, x_C)
        wz = -(_dot(x_B, np.cross(zdot_B, x_C)) + psidot * _dot(x_B, np.cross(z_B, y_C))) / _norm(u)
    else:
        # x_B ∝ y_C × z_B  ->  ω_z = +y_B·ẋ_B
        v = np.cross(y_C, z_B)
        wz = (_dot(y_B, np.cross(y_C, zdot_B)) - psidot * _dot(y_B, np.cross(x_C, z_B))) / _norm(v)
    return np.stack([wx, wy, wz], axis=-1)


def flat_to_state(
    vel: np.ndarray,
    acc: np.ndarray,
    jerk: np.ndarray,
    psi: np.ndarray | float,
    psidot: np.ndarray | float,
    model: RefModel,
    *,
    heading: str = "x_c",
    check: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The forward flatness map: ``(v, a, j, ψ, ψ̇) -> (R, ω, normed_thrust)``.

    Position itself never enters — the map depends only on the derivatives.

    Returns:
        ``(R, omega, normed_thrust)`` with shapes ``(..., 3, 3)``, ``(..., 3)``, ``(...,)``.
    """
    f = specific_force(acc, vel, model)
    nt = normed_thrust_from_f(f, model, check=check)
    R = attitude_from_f(f, psi, heading=heading)
    fdot = np.asarray(jerk, dtype=np.float64) + model.drag_per_mass * np.asarray(
        acc, dtype=np.float64
    )
    omega = rates_from_jerk(f, fdot, R, psi, psidot, heading=heading)
    return R, omega, nt


def state_to_flat(
    R: np.ndarray,
    normed_thrust: np.ndarray,
    normed_thrust_dot: np.ndarray,
    omega: np.ndarray,
    vel: np.ndarray,
    model: RefModel,
    *,
    heading: str = "x_c",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The inverse map: ``(R, T, Ṫ, ω, v) -> (a, j, ψ, ψ̇)``.

    Exists to be **tested against** :func:`flat_to_state`: a 10k-sample random round trip that
    recovers to 1e-12 is what catches a sign error in ``G_vec`` or in the drag term, which are the
    two places this whole package would be quietly wrong.

    Returns:
        ``(acc, jerk, psi, psidot)``.
    """
    R = np.asarray(R, dtype=np.float64)
    nt = np.asarray(normed_thrust, dtype=np.float64)
    ntd = np.asarray(normed_thrust_dot, dtype=np.float64)
    omega = np.asarray(omega, dtype=np.float64)
    vel = np.asarray(vel, dtype=np.float64)
    x_B, y_B, z_B = R[..., 0], R[..., 1], R[..., 2]

    acc = nt[..., None] * model.g * z_B - model.g * _E_Z - model.drag_per_mass * vel
    # ż_B = R(ω × ê_3) = ω_y·x_B − ω_x·y_B
    zdot_B = omega[..., 1, None] * x_B - omega[..., 0, None] * y_B
    fdot = model.g * (ntd[..., None] * z_B + nt[..., None] * zdot_B)
    jerk = fdot - model.drag_per_mass * acc

    # Heading. x_C is the horizontal axis perpendicular to y_B (x_c construction); y_C the
    # horizontal axis perpendicular to x_B (y_c construction). The DIRECTION of that axis is
    # ambiguous and the naive choice is wrong through inversion — at z_B = −ê_z, ``y_B × ê_z``
    # comes out as −x_C and the recovered heading is off by exactly π. Pin the sign with the fact
    # that x_B is the normalized horizontal-reference component perpendicular to z_B, so
    # ``x_C·x_B = ‖z_B × x_C‖ > 0`` always (symmetrically ``y_C·y_B > 0``).
    if heading == "x_c":
        ref = np.cross(y_B, _E_Z)
        ref = ref * np.sign(_dot(ref, x_B))[..., None]
        psi = np.arctan2(ref[..., 1], ref[..., 0])
    else:
        ref = np.cross(_E_Z, x_B)
        ref = ref * np.sign(_dot(ref, y_B))[..., None]
        psi = np.arctan2(-ref[..., 0], ref[..., 1])

    x_C, y_C = _heading_refs(psi)
    if heading == "x_c":
        nu = _norm(np.cross(z_B, x_C))
        num = omega[..., 2] * nu + _dot(x_B, np.cross(zdot_B, x_C))
        den = -_dot(x_B, np.cross(z_B, y_C))
    else:
        nu = _norm(np.cross(y_C, z_B))
        num = _dot(y_B, np.cross(y_C, zdot_B)) - omega[..., 2] * nu
        den = _dot(y_B, np.cross(x_C, z_B))
    with np.errstate(divide="ignore", invalid="ignore"):
        psidot = num / den
    return acc, jerk, psi, psidot


def heading_conditioning(R: np.ndarray, psi: np.ndarray | float, *, heading: str = "x_c"):
    """``|∂ω_z/∂ψ̇|`` — how observable the heading RATE is in this attitude, ``(...,)``.

    This is not a numerical nicety, it is a real property of the map. Under the ``"x_c"``
    construction the attitude becomes **independent of ψ to first order** once the thrust axis
    tips 90° *perpendicular* to ``x_C``: at ``z_B = (0, 1, 0)`` the whole construction returns the
    same ``R`` for every ψ, so ``ψ̇`` cannot be recovered from ``(R, ω)`` there at any precision.

    The forward map is unaffected — it only ever *multiplies* by this quantity. Only
    :func:`state_to_flat` divides by it, so a round-trip test must filter on it rather than assume
    ``ψ̇`` always comes back. Returns ``|y_B·y_C|`` (``x_c``) or ``|x_B·x_C|`` (``y_c``); 1.0 is
    perfectly conditioned (level flight), 0.0 is unrecoverable.
    """
    R = np.asarray(R, dtype=np.float64)
    x_B, y_B = R[..., 0], R[..., 1]
    psi = np.broadcast_to(np.asarray(psi, dtype=np.float64), R.shape[:-2])
    x_C, y_C = _heading_refs(psi)
    return np.abs(_dot(y_B, y_C)) if heading == "x_c" else np.abs(_dot(x_B, x_C))


# =============================================================================================
# Quaternion helpers (xyzw, matching DiffAero). Pure numpy — no torch, no scipy.
# =============================================================================================
def rotmat_to_quat_xyzw(R: np.ndarray) -> np.ndarray:
    """Body->world rotation matrix -> quaternion ``[qx, qy, qz, qw]`` (real-last), ``(..., 4)``.

    Shepperd's method (pick the largest-magnitude component to divide by), so it is stable through
    the 180° of inversion where the naive ``qw``-based formula loses all its precision — which is
    the single place in a flip where it matters most.
    """
    R = np.asarray(R, dtype=np.float64)
    m00, m01, m02 = R[..., 0, 0], R[..., 0, 1], R[..., 0, 2]
    m10, m11, m12 = R[..., 1, 0], R[..., 1, 1], R[..., 1, 2]
    m20, m21, m22 = R[..., 2, 0], R[..., 2, 1], R[..., 2, 2]
    trace = m00 + m11 + m22

    # Four candidate parameterizations; take the one whose divisor is largest.
    cands = np.stack([trace, m00, m11, m22], axis=-1)
    pick = np.argmax(cands, axis=-1)

    def _branch(w2, x2, y2, z2):
        return np.stack([x2, y2, z2, w2], axis=-1)

    s0 = np.sqrt(np.maximum(1.0 + trace, 1e-30)) * 2.0
    q0 = _branch(0.25 * s0, (m21 - m12) / s0, (m02 - m20) / s0, (m10 - m01) / s0)
    s1 = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 1e-30)) * 2.0
    q1 = _branch((m21 - m12) / s1, 0.25 * s1, (m01 + m10) / s1, (m02 + m20) / s1)
    s2 = np.sqrt(np.maximum(1.0 - m00 + m11 - m22, 1e-30)) * 2.0
    q2 = _branch((m02 - m20) / s2, (m01 + m10) / s2, 0.25 * s2, (m12 + m21) / s2)
    s3 = np.sqrt(np.maximum(1.0 - m00 - m11 + m22, 1e-30)) * 2.0
    q3 = _branch((m10 - m01) / s3, (m02 + m20) / s3, (m12 + m21) / s3, 0.25 * s3)

    q = np.stack([q0, q1, q2, q3], axis=-2)
    idx = pick[..., None, None]
    q = np.take_along_axis(q, np.broadcast_to(idx, q.shape[:-2] + (1, 4)), axis=-2)[..., 0, :]
    return q / _norm(q)[..., None]


def quat_xyzw_to_rotmat(q: np.ndarray) -> np.ndarray:
    """Quaternion ``[qx, qy, qz, qw]`` -> body->world rotation matrix ``(..., 3, 3)``."""
    q = np.asarray(q, dtype=np.float64)
    q = q / _norm(q)[..., None]
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.empty(q.shape[:-1] + (3, 3), dtype=np.float64)
    R[..., 0, 0] = 1 - 2 * (y * y + z * z)
    R[..., 0, 1] = 2 * (x * y - z * w)
    R[..., 0, 2] = 2 * (x * z + y * w)
    R[..., 1, 0] = 2 * (x * y + z * w)
    R[..., 1, 1] = 1 - 2 * (x * x + z * z)
    R[..., 1, 2] = 2 * (y * z - x * w)
    R[..., 2, 0] = 2 * (x * z - y * w)
    R[..., 2, 1] = 2 * (y * z + x * w)
    R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def quat_mul_xyzw(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a ⊗ b`` for real-last quaternions, ``(..., 4)``."""
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], axis=-1)


def quat_derivative(q: np.ndarray, omega_body: np.ndarray) -> np.ndarray:
    """``q̇ = ½ q ⊗ [ω, 0]`` — DiffAero's convention (``quadrotor.py:137``), ``(..., 4)``."""
    w = np.concatenate([np.asarray(omega_body, dtype=np.float64),
                        np.zeros(np.shape(omega_body)[:-1] + (1,))], axis=-1)
    return 0.5 * quat_mul_xyzw(np.asarray(q, dtype=np.float64), w)


def enforce_quat_continuity(q: np.ndarray) -> np.ndarray:
    """Flip signs so consecutive quaternions stay on the same hemisphere (``q_k·q_{k−1} > 0``).

    Do **not** reach for DiffAero's ``quat_standardize`` (``utils/math.py:143``) here: it forces
    ``qw ≥ 0``, so on a trajectory that passes through 180° of roll it is *guaranteed* to inject a
    sign flip exactly at inversion — precisely the frame a flip reference cares about. A renderer
    that slerps across that flip spins the drone the wrong way for one frame.

    Args:
        q: ``(N, 4)`` quaternion sequence in time order.

    Returns:
        The same rotations, sign-continuous.
    """
    q = np.array(q, dtype=np.float64, copy=True)
    if q.shape[0] < 2:
        return q
    dots = np.einsum("ij,ij->i", q[1:], q[:-1])
    # A sign flip at k must propagate to every later sample, hence the running parity.
    flips = np.cumprod(np.where(dots < 0.0, -1.0, 1.0))
    q[1:] *= flips[:, None]
    return q


def tilt_from_vertical(q: np.ndarray) -> np.ndarray:
    """Angle (rad) between body **+z** and world up, ``(N,)`` — "how far over is it leaning".

    Read straight off the quaternion (``R₂₂ = 1 − 2(q_x² + q_y²)``), like everything else here, so
    it stays correct through inversion where euler roll/pitch do not. This is the number a
    ``peak_bank_deg`` metric actually means, and on the swing it is ~1.4× the authored swing
    amplitude rather than equal to it.
    """
    q = np.asarray(q, dtype=np.float64)
    zz = 1.0 - 2.0 * (q[..., 0] ** 2 + q[..., 1] ** 2)
    return np.arccos(np.clip(zz, -1.0, 1.0))


def attitude_angle_from_identity(q: np.ndarray) -> np.ndarray:
    """Geodesic rotation angle (rad, ``[0, π]``) between the attitude and identity, ``(N,)``.

    This is the ``θ`` in DiffAero's rate-loop eigenvalues ``−K`` and ``−K·e^{±iθ}`` (see
    :func:`neural_whoop.reference.verify.check_rate_loop_stability`), so it is the quantity that
    decides whether the vendored controller is stable on a given maneuver — not a cosmetic
    "how rotated is it" readout.
    """
    q = np.asarray(q, dtype=np.float64)
    return 2.0 * np.arccos(np.clip(np.abs(q[..., 3]), 0.0, 1.0))


def heading_azimuth(q: np.ndarray) -> np.ndarray:
    """Unwrapped azimuth (rad) of body **+x** projected onto the horizontal plane, ``(N,)``.

    The gimbal-free way to count how far a maneuver's *heading* has wound. Euler yaw cannot do it:
    ``quaternion_to_euler`` is ZYX with pitch clamped to ±90°, and the orbit sits at 70° of bank
    for most of its run, so its ZYX yaw is largely an artifact of the clamp.

    Undefined when body +x is exactly vertical (the airframe pointing straight up or down); that
    does not occur on any maneuver in this package, and the norm check makes it a loud ``NaN``
    rather than a silent wrong number if it ever does.
    """
    R = quat_xyzw_to_rotmat(np.asarray(q, dtype=np.float64))
    x_B = R[..., 0]
    horiz = _norm(x_B[..., :2])
    with np.errstate(invalid="ignore", divide="ignore"):
        az = np.where(horiz > 1e-9, np.arctan2(x_B[..., 1], x_B[..., 0]), np.nan)
    return np.unwrap(az)


def rotation_angle_about(q: np.ndarray, axis: int) -> np.ndarray:
    """Unwrapped rotation angle (rad) about body ``axis`` for a planar maneuver, ``(N,)``.

    For a pure rotation about a fixed body axis from identity, ``q = [.., sin(φ/2) on axis, ..,
    cos(φ/2)]``, so ``φ = 2·atan2(q_axis, q_w)``. **Unwrap the half-angle, then double** — the
    other order is a trap: doubling first produces a jump of 4π at inversion, which
    ``np.unwrap`` (period 2π) reads as no jump at all and silently flattens a full flip.

    Charts must use this, never ``rpy``: ``quaternion_to_euler`` (``utils/math.py:190``) is ZYX
    with pitch clamped to ±90°, so a full 360° roll renders as a 180° wobble.
    """
    q = np.asarray(q, dtype=np.float64)
    return 2.0 * np.unwrap(np.arctan2(q[..., axis], q[..., 3]))
