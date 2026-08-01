"""The segment model: four types, two mechanisms, composed by strict sequential state-passing.

Every segment implements ``sample(state_in, model, ts) -> rows``; the last row *is* the next
segment's ``state_in``. There is no seam solve and no boundary-value problem across segments —
position and velocity are continuous **by construction**.

============ ============================= ===================================== ==================
type         authored                      derived                               used for
============ ============================= ===================================== ==================
PathSegment  ``p(t)`` septic + ``ψ(t)``     attitude, thrust, ω via flatness      climb/recover/land
Analytic     ``p(t)`` closed form + ``ψ(t)``same                                  swing / orbit
RateSegment  ``u_thrust(t)``, ``ω(t)``      q, v, p by forward integration        pop/roll-in/catch
Ballistic    thrust ≡ const, ω ≡ const      same; asserts commanded torque ≡ 0    the coast
============ ============================= ===================================== ==================

``PathSegment`` and ``AnalyticPathSegment`` share one mechanism (the flatness map) and differ only
in where the path comes from: a septic fitted between endpoint conditions, versus a shape the
author already knows in closed form. Reach for the septic when what you know is "start here, end
there, smoothly", and for the analytic one when you know the *geometry* — an arc or a circle is
not an interpolation problem, and fitting one through a polynomial would only approximate a thing
you already had exactly.

**Why the rate segments author ``ω(t)`` and not a hand-drawn rate command.** DiffAero's
``RateController`` is exactly first order for a single-axis rotation from ψ = 0:
``ω̇ = K(u − ω)`` with ``K = 16 s⁻¹`` (``third_party/diffaero/dynamics/controller.py:82-104``). The
binding constraint on a flip is therefore **not** the 12 rad/s rate ceiling but that loop's
bandwidth: at ω = 11 the largest achievable ω̇ is ``16·(12 − 11) = 16 rad/s²``. A hand-drawn
smoothstep *rate command* is simply un-trackable, and the reference would not show it — it would
look perfect and lag reality by ~60 ms. So we author the **response** ``ω(t)`` and emit
``u = ω + ω̇/K``, which is exact and in-limits by construction rather than by hope.

**Why septics.** The flatness map consumes jerk, so a path segment must match ``{p, ṗ, p̈, p⃛}`` at
both ends or the emitted body rate steps at every seam. A quintic matches only through
acceleration. Eight coefficients per axis, solved in normalized time ``τ = t/T`` so the 4x4 is a
constant, perfectly-conditioned matrix regardless of segment duration.

**The two intentional C² breaks.** Acceleration is *not* continuous at the motor cut and should
not be — a step in the motor command **is** the maneuver. Exactly two seams have it (thrust →
coast, coast → catch); every other seam is C² or better. ``scene.phase`` records where they are so
verification masks those frames by phase transition rather than by eyeball.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from neural_whoop.reference import flatness as fl
from neural_whoop.reference.model import RefModel

_E_Z = np.array([0.0, 0.0, 1.0])
_E_3 = np.array([0.0, 0.0, 1.0])

#: Step used to central-difference ``ω`` on a PathSegment. The septic is analytic, so we evaluate
#: it at ``t ± h`` (including just outside the segment) rather than differencing the sample grid —
#: that keeps the endpoints as accurate as the interior. At 1e-4 s the truncation error is ~1e-8
#: and the round-off floor ~2e-12, comfortably below anything that matters here.
_OMEGA_DIFF_H = 1e-4
#: Same idea for ``d(normed_thrust)/dt`` inside a RateSegment.
_THRUST_DIFF_H = 1e-5


@dataclass
class RefState:
    """The full reference state at an instant — what one segment hands the next."""

    t: float
    pos: np.ndarray
    vel: np.ndarray
    acc: np.ndarray
    jerk: np.ndarray
    quat: np.ndarray
    omega: np.ndarray
    normed_thrust: float

    @staticmethod
    def at_rest(pos, *, t: float = 0.0, normed_thrust: float = 1.0) -> "RefState":
        """Level, motionless, hover thrust — the state a sequence starts and ends in."""
        return RefState(
            t=float(t),
            pos=np.asarray(pos, dtype=np.float64).copy(),
            vel=np.zeros(3),
            acc=np.zeros(3),
            jerk=np.zeros(3),
            quat=np.array([0.0, 0.0, 0.0, 1.0]),
            omega=np.zeros(3),
            normed_thrust=float(normed_thrust),
        )


@dataclass
class Samples:
    """A sampled trajectory: parallel arrays, one row per time sample.

    ``rate_cmd`` is the **act-v2 body-rate command** ``u = ω + ω̇/K`` the emitted action carries —
    i.e. what you would have to send DiffAero's rate loop to get this ``ω(t)``, not ``ω`` itself.
    """

    t: np.ndarray
    phase: np.ndarray            # (N,) int phase code, indexes meta.scene_info.phase_labels
    seg: np.ndarray              # (N,) int segment index
    pos: np.ndarray              # (N, 3) world m
    vel: np.ndarray              # (N, 3) world m/s
    acc: np.ndarray              # (N, 3) world m/s^2
    jerk: np.ndarray             # (N, 3) world m/s^3
    quat: np.ndarray             # (N, 4) xyzw, sign-continuous
    omega: np.ndarray            # (N, 3) body rad/s
    omega_dot: np.ndarray        # (N, 3) body rad/s^2
    normed_thrust: np.ndarray    # (N,) DiffAero units, 1.0 == hover
    rate_cmd: np.ndarray         # (N, 3) body rate COMMAND, rad/s

    def __len__(self) -> int:
        return len(self.t)

    @property
    def R(self) -> np.ndarray:
        """Body->world rotation matrices ``(N, 3, 3)``."""
        return fl.quat_xyzw_to_rotmat(self.quat)

    def imu(self, model: RefModel) -> np.ndarray:
        """Body-frame specific force ``(N, 3)`` — what the onboard accelerometer would read."""
        from neural_whoop.reference.imu import specific_force_body

        return specific_force_body(self.R, self.acc, model)

    def state_at(self, i: int) -> RefState:
        """Row ``i`` as a :class:`RefState`."""
        return RefState(
            t=float(self.t[i]), pos=self.pos[i].copy(), vel=self.vel[i].copy(),
            acc=self.acc[i].copy(), jerk=self.jerk[i].copy(), quat=self.quat[i].copy(),
            omega=self.omega[i].copy(), normed_thrust=float(self.normed_thrust[i]),
        )

    def segment_bounds(self) -> list[tuple[int, int]]:
        """``[(start, stop), ...]`` index ranges per segment (stop exclusive)."""
        out: list[tuple[int, int]] = []
        if len(self) == 0:
            return out
        edges = np.flatnonzero(np.diff(self.seg)) + 1
        starts = np.concatenate([[0], edges])
        stops = np.concatenate([edges, [len(self)]])
        return [(int(a), int(b)) for a, b in zip(starts, stops)]


def _concat(rows: list[dict[str, np.ndarray]]) -> Samples:
    keys = Samples.__dataclass_fields__
    merged = {k: np.concatenate([r[k] for r in rows], axis=0) for k in keys}
    merged["quat"] = fl.enforce_quat_continuity(merged["quat"])
    return Samples(**merged)


# =============================================================================================
# Septic path segments (flatness-authored)
# =============================================================================================
def septic_coeffs(
    p0: np.ndarray, v0: np.ndarray, a0: np.ndarray, j0: np.ndarray,
    p1: np.ndarray, v1: np.ndarray, a1: np.ndarray, j1: np.ndarray,
    T: float,
) -> np.ndarray:
    """Per-axis septic coefficients in **normalized** time ``τ = t/T``, shape ``(8, 3)``.

    Matching ``{p, ṗ, p̈, p⃛}`` at both ends is what keeps the emitted body rate continuous across
    a seam; solving in ``τ`` keeps the 4x4 a constant matrix (condition number ~1e3) instead of a
    ``T^7``-scaled one that goes singular for short segments.
    """
    if T <= 0.0:
        raise ValueError(f"septic segment duration must be > 0, got {T}")
    c = np.zeros((8, 3), dtype=np.float64)
    c[0] = p0
    c[1] = T * np.asarray(v0, dtype=np.float64)
    c[2] = T * T * np.asarray(a0, dtype=np.float64) / 2.0
    c[3] = T ** 3 * np.asarray(j0, dtype=np.float64) / 6.0
    # Value / 1st / 2nd / 3rd derivative at tau = 1 contributed by c0..c3.
    base = np.stack([
        c[0] + c[1] + c[2] + c[3],
        c[1] + 2 * c[2] + 3 * c[3],
        2 * c[2] + 6 * c[3],
        6 * c[3],
    ])
    target = np.stack([
        np.asarray(p1, dtype=np.float64),
        T * np.asarray(v1, dtype=np.float64),
        T * T * np.asarray(a1, dtype=np.float64),
        T ** 3 * np.asarray(j1, dtype=np.float64),
    ])
    M = np.array([
        [1.0, 1.0, 1.0, 1.0],
        [4.0, 5.0, 6.0, 7.0],
        [12.0, 20.0, 30.0, 42.0],
        [24.0, 60.0, 120.0, 210.0],
    ])
    c[4:] = np.linalg.solve(M, target - base)
    return c


def septic_eval(c: np.ndarray, T: float, t: np.ndarray) -> tuple[np.ndarray, ...]:
    """Evaluate a normalized-time septic and its first three derivatives at absolute times ``t``.

    Returns:
        ``(p, v, a, j)``, each ``(N, 3)``.
    """
    tau = np.asarray(t, dtype=np.float64) / T
    k = np.arange(8, dtype=np.float64)
    powers = tau[:, None] ** k[None, :]                      # (N, 8): tau^0 .. tau^7
    p = powers @ c
    # d^n/dtau^n: columns tau^(k-n) are powers[:, :8-n]; coefficients are the falling factorials.
    v = (powers[:, :7] * k[1:][None, :]) @ c[1:] / T
    a = (powers[:, :6] * (k[2:] * (k[2:] - 1.0))[None, :]) @ c[2:] / (T * T)
    j = (powers[:, :5] * (k[3:] * (k[3:] - 1.0) * (k[3:] - 2.0))[None, :]) @ c[3:] / (T ** 3)
    return p, v, a, j


@dataclass
class PathSegment:
    """Author ``p(t)``; derive attitude, thrust and body rate from flatness.

    The endpoint boundary conditions are given; the start ones come from the incoming state, so a
    ``PathSegment`` never needs to know what preceded it.
    """

    name: str
    phase: int
    duration: float
    end_pos: np.ndarray
    end_vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    end_acc: np.ndarray = field(default_factory=lambda: np.zeros(3))
    end_jerk: np.ndarray = field(default_factory=lambda: np.zeros(3))
    psi: float = 0.0
    heading: str = "x_c"

    def sample(self, state_in: RefState, model: RefModel, ts: np.ndarray) -> dict[str, np.ndarray]:
        T = float(self.duration)
        c = septic_coeffs(
            state_in.pos, state_in.vel, state_in.acc, state_in.jerk,
            np.asarray(self.end_pos, dtype=np.float64),
            np.asarray(self.end_vel, dtype=np.float64),
            np.asarray(self.end_acc, dtype=np.float64),
            np.asarray(self.end_jerk, dtype=np.float64),
            T,
        )
        pos, vel, acc, jerk = septic_eval(c, T, ts)
        R, omega, nt = fl.flat_to_state(vel, acc, jerk, self.psi, 0.0, model, heading=self.heading)
        # ω̇ by central difference *of the analytic septic* (see _OMEGA_DIFF_H) — the map has no
        # closed form for it without carrying snap through, and this is accurate to ~1e-8.
        h = _OMEGA_DIFF_H
        om_p = self._omega_at(c, T, ts + h, model)
        om_m = self._omega_at(c, T, ts - h, model)
        omega_dot = (om_p - om_m) / (2.0 * h)
        quat = fl.rotmat_to_quat_xyzw(R)
        n = len(ts)
        return {
            "t": state_in.t + np.asarray(ts, dtype=np.float64),
            "phase": np.full(n, self.phase, dtype=np.int64),
            "seg": np.zeros(n, dtype=np.int64),
            "pos": pos, "vel": vel, "acc": acc, "jerk": jerk,
            "quat": quat, "omega": omega, "omega_dot": omega_dot,
            "normed_thrust": nt,
            "rate_cmd": omega + omega_dot / np.array(model.K_angvel),
        }

    def _omega_at(self, c, T, ts, model) -> np.ndarray:
        _, vel, acc, jerk = septic_eval(c, T, ts)
        _, omega, _ = fl.flat_to_state(
            vel, acc, jerk, self.psi, 0.0, model, heading=self.heading, check=False
        )
        return omega


#: ``t -> (p, v, a, j)``, each ``(N, 3)``, in the maneuver's own time base.
PathFn = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
#: ``t -> (ψ, ψ̇)``, each ``(N,)``.
PsiFn = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass
class AnalyticPathSegment:
    """Author ``p(t)`` and ``ψ(t)`` in **closed form**; derive the rest through flatness.

    The sibling of :class:`PathSegment`, sharing its mechanism exactly — ``fl.flat_to_state`` plus
    the same central difference for ``ω̇`` — and differing only in the source of the path. There is
    no septic and no endpoint conditions here: :mod:`~neural_whoop.reference.paths` already knows
    the shape and its first three derivatives analytically.

    ``t_offset`` lets several segments carve **one** continuous authored path into separately
    labelled beats (the orbit's WIND-UP / ORBIT / WIND-DOWN), which is what puts a caption on each
    without introducing a seam: every sub-segment evaluates the same function, so continuity across
    the join is exact to the last bit rather than merely matched.

    The entry position is **asserted**, not assumed. A ``PathSegment`` takes its start conditions
    from the incoming state and therefore cannot be discontinuous; an analytic path ignores the
    incoming state entirely, so a mis-placed station would silently teleport the drone one frame
    before the maneuver. Checking it costs nothing and turns that into a loud failure.
    """

    name: str
    phase: int
    duration: float
    path: PathFn
    psi_fn: PsiFn | None = None
    heading: str = "x_c"
    t_offset: float = 0.0
    #: Tolerance on the entry-position continuity assertion (m).
    entry_tol: float = 1e-9

    def sample(self, state_in: RefState, model: RefModel, ts: np.ndarray) -> dict[str, np.ndarray]:
        ts = np.asarray(ts, dtype=np.float64)
        tau = self.t_offset + ts
        pos, vel, acc, jerk = self.path(tau)
        gap = float(np.max(np.abs(pos[0] - state_in.pos)))
        if gap > self.entry_tol:
            raise ValueError(
                f"{self.name}: the authored path starts {gap:.3e} m from the incoming state "
                f"({pos[0]} vs {state_in.pos}). An analytic segment ignores the state it is "
                f"handed, "
                f"so this would teleport the drone at the seam instead of flying there. Fix the "
                f"station the preceding segment ends on."
            )
        psi, psidot = self._psi(tau)
        R, omega, nt = fl.flat_to_state(vel, acc, jerk, psi, psidot, model, heading=self.heading)
        h = _OMEGA_DIFF_H
        omega_dot = (self._omega_at(tau + h, model) - self._omega_at(tau - h, model)) / (2.0 * h)
        n = len(ts)
        return {
            "t": state_in.t + ts,
            "phase": np.full(n, self.phase, dtype=np.int64),
            "seg": np.zeros(n, dtype=np.int64),
            "pos": pos, "vel": vel, "acc": acc, "jerk": jerk,
            "quat": fl.rotmat_to_quat_xyzw(R), "omega": omega, "omega_dot": omega_dot,
            "normed_thrust": nt,
            "rate_cmd": omega + omega_dot / np.array(model.K_angvel),
        }

    def _psi(self, tau: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.psi_fn is None:
            return np.zeros_like(tau), np.zeros_like(tau)
        return self.psi_fn(tau)

    def _omega_at(self, tau: np.ndarray, model: RefModel) -> np.ndarray:
        _, vel, acc, jerk = self.path(tau)
        psi, psidot = self._psi(tau)
        _, omega, _ = fl.flat_to_state(
            vel, acc, jerk, psi, psidot, model, heading=self.heading, check=False
        )
        return omega


# =============================================================================================
# Rate segments (command-authored, path integrated)
# =============================================================================================
#: ``f(t_local) -> value``. Bound to the segment's entry state by :meth:`RateSegment.bind`.
ScalarFn = Callable[[float], float]


@dataclass
class RateSegment:
    """Author ``u_thrust(t)`` and ``ω(t)``; integrate ``q``, ``v``, ``p`` forward.

    This is the mechanism the flip needs, because flatness has no solution through inversion: the
    required specific force points up while the thrust axis points down. Position is an **output**
    here, not an input — once the motors cut, where the drone goes is gravity's business.

    ``omega_fn``/``omega_dot_fn`` give the body rate about ``axis`` only; the other two body-rate
    components are authored as exactly zero, which is what keeps ψ ≡ 0. (Before the 2026-08-01
    controller fix that also made DiffAero's ``RateController`` frame bug — ``R_i2b @ w`` — a
    genuine no-op, which is why every planar maneuver tracked while the substrate was wrong.)
    """

    name: str
    phase: int
    duration: float
    thrust_fn: ScalarFn
    omega_fn: ScalarFn
    omega_dot_fn: ScalarFn
    axis: int = 0

    def bind(self, state_in: RefState) -> tuple[ScalarFn, ScalarFn, ScalarFn]:
        """Resolve the authored fns against the entry state (see :class:`BallisticSegment`)."""
        return self.thrust_fn, self.omega_fn, self.omega_dot_fn

    def sample(self, state_in: RefState, model: RefModel, ts: np.ndarray) -> dict[str, np.ndarray]:
        thrust_fn, omega_fn, omega_dot_fn = self.bind(state_in)
        ts = np.asarray(ts, dtype=np.float64)
        n = len(ts)
        dpm = model.drag_per_mass
        g = model.g
        ax = self.axis

        def omega_vec(t: float) -> np.ndarray:
            w = np.zeros(3)
            w[ax] = omega_fn(t)
            return w

        def deriv(t: float, y: np.ndarray) -> np.ndarray:
            v = y[3:6]
            q = y[6:10]
            q = q / np.linalg.norm(q)
            z_B = fl.quat_xyzw_to_rotmat(q)[:, 2]
            a = thrust_fn(t) * g * z_B - g * _E_Z - dpm * v
            qd = fl.quat_derivative(q, omega_vec(t))
            return np.concatenate([v, a, qd])

        y = np.concatenate([state_in.pos, state_in.vel, state_in.quat])
        ys = np.empty((n, 10), dtype=np.float64)
        ys[0] = y
        for i in range(1, n):
            t0, dt = float(ts[i - 1]), float(ts[i] - ts[i - 1])
            k1 = deriv(t0, y)
            k2 = deriv(t0 + dt / 2, y + dt / 2 * k1)
            k3 = deriv(t0 + dt / 2, y + dt / 2 * k2)
            k4 = deriv(t0 + dt, y + dt * k3)
            y = y + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
            y[6:10] /= np.linalg.norm(y[6:10])
            ys[i] = y

        pos, vel, quat = ys[:, 0:3], ys[:, 3:6], ys[:, 6:10]
        R = fl.quat_xyzw_to_rotmat(quat)
        z_B = R[:, :, 2]
        nt = np.array([thrust_fn(float(t)) for t in ts])
        acc = nt[:, None] * g * z_B - g * _E_Z - dpm * vel

        omega = np.zeros((n, 3))
        omega_dot = np.zeros((n, 3))
        omega[:, ax] = [omega_fn(float(t)) for t in ts]
        omega_dot[:, ax] = [omega_dot_fn(float(t)) for t in ts]

        # jerk = d/dt [ T·g·z_B − g·ê_z − (D/m)·v ] , with ż_B = R(ω × ê_3).
        h = _THRUST_DIFF_H
        ntd = np.array([(thrust_fn(float(t) + h) - thrust_fn(float(t) - h)) / (2 * h) for t in ts])
        zdot_B = np.einsum("nij,nj->ni", R, np.cross(omega, _E_3))
        jerk = ntd[:, None] * g * z_B + nt[:, None] * g * zdot_B - dpm * acc

        return {
            "t": state_in.t + ts,
            "phase": np.full(n, self.phase, dtype=np.int64),
            "seg": np.zeros(n, dtype=np.int64),
            "pos": pos, "vel": vel, "acc": acc, "jerk": jerk,
            "quat": quat, "omega": omega, "omega_dot": omega_dot,
            "normed_thrust": nt,
            "rate_cmd": omega + omega_dot / np.array(model.K_angvel),
        }


class BallisticSegment(RateSegment):
    """The coast: thrust pinned to a floor (0 or the deploy 0.25) and **zero commanded torque**.

    The body rate is exactly constant here, to machine precision, and that is a property of the
    simulator rather than an approximation: DiffAero applies drag only to *linear* velocity (there
    is no ``−Cω`` term), and with ``ω_z ≡ 0`` on a symmetric-inertia axis both gyroscopic terms
    vanish identically. A real whoop would shed 5-15% of its roll rate to blade flapping over a
    0.6 s coast; **the reference does not model that**, and the artifact says so.

    Because ``ω̇ ≡ 0``, the emitted command is ``u = ω`` — literally "hold what you have", i.e. the
    rate loop asks the motors for no differential thrust at all.
    """

    def __init__(self, name: str, phase: int, duration: float, *,
                 coast_thrust: float = 0.0, axis: int = 0):
        # NOT a @dataclass: the decorator would synthesize an __init__ over the parent's fields
        # and clobber this one. The authored functions are placeholders — bind() replaces them
        # with ones closed over the entry rate, which is only known at sample time.
        zero: ScalarFn = lambda t: 0.0  # noqa: E731
        super().__init__(name=name, phase=phase, duration=duration,
                         thrust_fn=lambda t: coast_thrust, omega_fn=zero,
                         omega_dot_fn=zero, axis=axis)
        self.coast_thrust = float(coast_thrust)

    def bind(self, state_in: RefState) -> tuple[ScalarFn, ScalarFn, ScalarFn]:
        w0 = float(state_in.omega[self.axis])
        off_axis = np.delete(np.asarray(state_in.omega, dtype=np.float64), self.axis)
        if np.any(np.abs(off_axis) > 1e-9):
            raise ValueError(
                f"{self.name}: a ballistic coast must enter with rate on the maneuver axis only, "
                f"got ω = {state_in.omega} (off-axis {off_axis}). Off-axis rate would make the "
                f"gyroscopic term non-zero and the 'ω is exactly constant' claim false."
            )
        return (lambda t: self.coast_thrust, lambda t: w0, lambda t: 0.0)


# =============================================================================================
# Composition
# =============================================================================================
@dataclass
class Trajectory:
    """An ordered list of segments plus the state the first one starts from.

    Sampling is strict sequential state-passing: segment ``k+1``'s boundary conditions ARE segment
    ``k``'s last row. Nothing is solved across a seam.
    """

    segments: list[PathSegment | AnalyticPathSegment | RateSegment]
    start: RefState

    @property
    def duration(self) -> float:
        return float(sum(s.duration for s in self.segments))

    def sample(self, model: RefModel, dt: float) -> Samples:
        """Sample the whole sequence at ~``dt`` (each segment gets an exact integer subdivision).

        A segment's duration is generally not a multiple of ``dt``, so each segment uses
        ``dt_seg = T/round(T/dt)`` — within 0.1% of ``dt`` and *exactly* spanning the segment. The
        resulting global time base is monotone but very slightly non-uniform at seams, which is
        why :mod:`~neural_whoop.reference.verify` differentiates with the non-uniform 3-point
        formula rather than assuming a fixed step.
        """
        if not self.segments:
            raise ValueError("Trajectory has no segments")
        state = replace(self.start)
        rows: list[dict[str, np.ndarray]] = []
        for k, seg in enumerate(self.segments):
            T = float(seg.duration)
            n = max(1, int(round(T / dt)))
            ts = np.linspace(0.0, T, n + 1)
            row = seg.sample(state, model, ts)
            row["seg"] = np.full(len(ts), k, dtype=np.int64)
            last = _row_state(row, -1)
            if k < len(self.segments) - 1:
                row = {key: val[:-1] for key, val in row.items()}
            rows.append(row)
            state = last
        return _concat(rows)


def _row_state(row: dict[str, np.ndarray], i: int) -> RefState:
    return RefState(
        t=float(row["t"][i]), pos=row["pos"][i].copy(), vel=row["vel"][i].copy(),
        acc=row["acc"][i].copy(), jerk=row["jerk"][i].copy(), quat=row["quat"][i].copy(),
        omega=row["omega"][i].copy(), normed_thrust=float(row["normed_thrust"][i]),
    )
