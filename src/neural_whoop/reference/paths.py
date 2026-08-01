"""Analytic maneuver paths: author ``p(t)`` in closed form, hand the derivatives to flatness.

:mod:`~neural_whoop.reference.segments`' :class:`~neural_whoop.reference.segments.PathSegment`
authors a path as a **septic between endpoint conditions** — the right tool when what you know is
"start here, end there, smoothly". It is the wrong tool for a *shape*: a pendulum arc or a circle
is not an interpolation problem, and forcing one through a polynomial would only approximate the
geometry you already have exactly.

So this module authors the shape directly and differentiates it by hand. Every path here returns
``(p, v, a, j)`` analytically — no finite differences anywhere in the position chain — because the
flatness map consumes **jerk**, and a differenced jerk would put its noise straight into the
emitted body rate.

Two paths, and they are complementary:

- :class:`PendulumPath` — a swinging arc in a vertical plane. Planar, ``ψ ≡ 0``, and it closes on
  its own start point **exactly** (see :class:`Envelope`), so unlike the flip it needs no shoot at
  all. That is the whole point of it: flatness authors the entire maneuver.
- :class:`OrbitPath` — a circle about a vertical anchor axis, with the nose free to point at (or
  away from) the axis. Genuinely 3D, and the first maneuver in the package that breaks ``ψ ≡ 0``.

Both are driven by the same :class:`Envelope`, which is what makes the seams into and out of the
maneuver C³ — the condition the flatness map actually needs.

Pure numpy + stdlib, like the rest of the package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# =============================================================================================
# The envelope
# =============================================================================================
def septic_smoothstep(x: np.ndarray) -> np.ndarray:
    """``35x⁴ − 84x⁵ + 70x⁶ − 20x⁷`` — the 0→1 ramp that is flat through its **third** derivative.

    The usual ``3x² − 2x³`` is C¹ and the usual ``6x⁵ − 15x⁴ + 10x³`` is C²; neither is enough
    here. The flatness map turns jerk into body rate, so an envelope whose *third* derivative steps
    at the seam emits a body rate that steps — visibly, in the replay, at exactly the frame the
    maneuver begins. Being flat through the third derivative at both ends is what makes the join
    into HOVER and out to the settle silent.
    """
    x = np.asarray(x, dtype=np.float64)
    x2 = x * x
    x3 = x2 * x
    return x3 * x * (35.0 - 84.0 * x + 70.0 * x2 - 20.0 * x3)


def septic_smoothstep_d(x: np.ndarray) -> np.ndarray:
    """``140x³(1−x)³`` — the ramp's first derivative, in its factored form."""
    x = np.asarray(x, dtype=np.float64)
    return 140.0 * (x * (1.0 - x)) ** 3


def septic_smoothstep_dd(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x2 = x * x
    return 420.0 * x2 - 1680.0 * x2 * x + 2100.0 * x2 * x2 - 840.0 * x2 * x2 * x


def septic_smoothstep_ddd(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x2 = x * x
    return 840.0 * x - 5040.0 * x2 + 8400.0 * x2 * x - 4200.0 * x2 * x2


def septic_smoothstep_int(x: np.ndarray) -> np.ndarray:
    """``∫₀ˣ S`` = ``7x⁵ − 14x⁶ + 10x⁷ − 2.5x⁸``; equals **exactly 0.5** at ``x = 1``.

    That the ramp integrates to half its width is what lets :class:`OrbitPath` solve its duration
    in closed form instead of by quadrature: a maneuver that must deliver exactly ``2πn`` of yaw
    would otherwise close only to the accuracy of a numerical integral.
    """
    x = np.asarray(x, dtype=np.float64)
    x2 = x * x
    x4 = x2 * x2
    return 7.0 * x4 * x - 14.0 * x4 * x2 + 10.0 * x4 * x2 * x - 2.5 * x4 * x4


@dataclass(frozen=True)
class Envelope:
    """A 0→1→0 **window**: septic ramp up, flat hold, septic ramp down.

    ``ramp_frac`` is the fraction of the total duration each ramp occupies, so ``0.3`` means
    "30% up, 40% held, 30% down" and ``0.5`` means a raised septic with no hold at all.

    A window rather than a ramp because both maneuvers here have to **end where they started**: the
    swing's amplitude has to come back to zero or the drone finishes the beat mid-arc, and the
    orbit's rate has to come back to zero or it finishes still travelling. Vanishing through the
    third derivative at *both* ends is what makes both closures exact rather than merely small.

    Attributes:
        duration: Total window length (s).
        ramp_frac: Fraction of ``duration`` spent in each ramp, in ``(0, 0.5]``. ``0`` is accepted
            and means a bare rectangle (no ramp) — useful only for tests.
    """

    duration: float
    ramp_frac: float = 0.3

    def __post_init__(self) -> None:
        if self.duration <= 0.0:
            raise ValueError(f"envelope duration must be > 0, got {self.duration}")
        if not (0.0 <= self.ramp_frac <= 0.5):
            raise ValueError(
                f"ramp_frac must be in [0, 0.5] (each ramp is that fraction of the duration, and "
                f"two of them must fit), got {self.ramp_frac}"
            )

    @property
    def ramp_s(self) -> float:
        """Length of one ramp (s)."""
        return self.ramp_frac * self.duration

    @property
    def mean(self) -> float:
        """``(1/T)∫₀ᵀ W`` = ``1 − ramp_frac`` — exact, because the septic integrates to ½."""
        return 1.0 - self.ramp_frac

    @property
    def area(self) -> float:
        """``∫₀ᵀ W dt`` = ``T(1 − ramp_frac)``, exactly."""
        return self.duration * self.mean

    def derivatives(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """``(W, Ẇ, Ẅ, W⃛)`` at times ``t`` (s), clamped to 0 outside ``[0, T]``.

        Clamping is C³-safe rather than a hack: the septic and its first three derivatives are all
        exactly zero at both ends, so the clamped extension agrees with the polynomial to fourth
        order. That matters because the ``ω̇`` central difference in
        :class:`~neural_whoop.reference.segments.AnalyticPathSegment` evaluates just *outside* the
        segment at its endpoints.
        """
        t = np.asarray(t, dtype=np.float64)
        T, tau = self.duration, self.ramp_s
        w = np.zeros_like(t)
        wd = np.zeros_like(t)
        wdd = np.zeros_like(t)
        wddd = np.zeros_like(t)

        inside = (t > 0.0) & (t < T)
        if tau <= 0.0:
            w[inside] = 1.0
            return w, wd, wdd, wddd

        up = inside & (t < tau)
        x = t[up] / tau
        w[up] = septic_smoothstep(x)
        wd[up] = septic_smoothstep_d(x) / tau
        wdd[up] = septic_smoothstep_dd(x) / (tau * tau)
        wddd[up] = septic_smoothstep_ddd(x) / (tau ** 3)

        hold = inside & (t >= tau) & (t <= T - tau)
        w[hold] = 1.0

        down = inside & (t > T - tau)
        x = (T - t[down]) / tau
        w[down] = septic_smoothstep(x)
        wd[down] = -septic_smoothstep_d(x) / tau
        wdd[down] = septic_smoothstep_dd(x) / (tau * tau)
        wddd[down] = -septic_smoothstep_ddd(x) / (tau ** 3)
        return w, wd, wdd, wddd

    def value(self, t: np.ndarray) -> np.ndarray:
        return self.derivatives(t)[0]

    def integral(self, t: np.ndarray) -> np.ndarray:
        """``∫₀ᵗ W ds`` — closed form, so the orbit's total yaw closes exactly."""
        t = np.asarray(t, dtype=np.float64)
        T, tau = self.duration, self.ramp_s
        out = np.zeros_like(t)
        if tau <= 0.0:
            return np.clip(t, 0.0, T)
        up = (t > 0.0) & (t < tau)
        out[up] = tau * septic_smoothstep_int(t[up] / tau)
        hold = (t >= tau) & (t <= T - tau)
        out[hold] = 0.5 * tau + (t[hold] - tau)
        down = (t > T - tau) & (t < T)
        out[down] = T - tau - tau * septic_smoothstep_int((T - t[down]) / tau)
        out[t >= T] = T - tau
        return out


# =============================================================================================
# The pendulum (the U-swing)
# =============================================================================================
@dataclass(frozen=True)
class PendulumPath:
    """A swinging arc: ``θ(t) = Θ·W(t)·sin(ωt)`` on a rigid rope of length ``L``.

    The drone hangs below a pivot and swings in the world **y–z** plane (``x ≡ 0``), so the
    maneuver is a pure roll and inherits the flip's exact planarity and its well-conditioned
    ``"x_c"`` heading construction.

    **This maneuver needs no shoot, and that is the finding.** The flip needed a damped-Newton
    boundary-value solve because flatness has no solution through inversion. Here the opposite is
    true: choose ``ωT = 2π·n`` and the beat returns to the hover point at *machine precision* —
    measured ``|p − p₀| = |v| = |a| = |j| = 0.00e+00`` — because ``sin`` vanishes at both ends and
    the envelope vanishes through its second derivative there, killing every ``Ẇ`` cross term.
    Differential flatness authors the entire maneuver.

    **Do not drive it at resonance.** "Thrust points along the rope, so bank equals θ" is a
    *no-drag* statement. This simulator's drag (``D/m = 3.125 s⁻¹``, ~8× a real whoop) leans the
    thrust axis hard into travel: at ``L = 0.9 m``, ``Θ = 50°``, ``ω = √(g/L)`` gives an 89° peak
    tilt and a **15.45 rad/s** rate command against an 11.64 ceiling. At ``0.8×`` resonance the
    same swing is 69° / 7.94 rad/s. Peak tilt runs about **1.4× the swing amplitude**, so
    ``amplitude_deg`` is emphatically not the bank angle.

    Attributes:
        length: Rope length ``L`` (m) — the pivot sits this far above the bottom of the arc.
        amplitude: Peak swing angle ``Θ`` (rad) off vertical.
        omega: Angular frequency of the swing (rad/s).
        n_swings: Number of full ``sin`` periods; ``ωT = 2π·n_swings`` fixes the duration.
        z_bottom: World z of the bottom of the arc (m) — where the drone hovers before and after.
        ramp_frac: The envelope's ramp fraction.
    """

    length: float
    amplitude: float
    omega: float
    n_swings: float
    z_bottom: float
    ramp_frac: float = 0.3

    def __post_init__(self) -> None:
        for name, v in (("length", self.length), ("omega", self.omega),
                        ("n_swings", self.n_swings)):
            if v <= 0.0:
                raise ValueError(f"{name} must be > 0, got {v}")
        if not (0.0 < self.amplitude < 0.5 * math.pi):
            raise ValueError(
                f"amplitude must be in (0, 90°); past 90° the 'rope' would be above the pivot and "
                f"the arc stops being a swing. Got {math.degrees(self.amplitude):.1f}°."
            )

    @property
    def duration(self) -> float:
        """``2π·n_swings / ω`` — exactly a whole number of periods, which is what closes it."""
        return 2.0 * math.pi * self.n_swings / self.omega

    @property
    def period(self) -> float:
        return 2.0 * math.pi / self.omega

    @property
    def resonant_omega(self) -> float:
        """``√(g/L)`` for ``g = 9.81`` — the small-angle pendulum frequency, for reference only."""
        return math.sqrt(9.81 / self.length)

    @property
    def pivot(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.z_bottom + self.length])

    @property
    def start_pos(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.z_bottom])

    @property
    def half_width(self) -> float:
        """``L·sin Θ`` — how far the arc reaches to each side (m)."""
        return self.length * math.sin(self.amplitude)

    @property
    def rise(self) -> float:
        """``L(1 − cos Θ)`` — how far the arc climbs at its ends (m)."""
        return self.length * (1.0 - math.cos(self.amplitude))

    @property
    def envelope(self) -> Envelope:
        return Envelope(self.duration, self.ramp_frac)

    def theta(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """``(θ, θ̇, θ̈, θ⃛)`` — the product rule on ``Θ·W(t)·sin(ωt)``, analytically."""
        t = np.asarray(t, dtype=np.float64)
        w, wd, wdd, wddd = self.envelope.derivatives(t)
        om = self.omega
        s, c = np.sin(om * t), np.cos(om * t)
        A = self.amplitude
        th = A * (w * s)
        thd = A * (wd * s + w * om * c)
        thdd = A * (wdd * s + 2.0 * wd * om * c - w * om * om * s)
        thddd = A * (wddd * s + 3.0 * wdd * om * c - 3.0 * wd * om * om * s
                     - w * om ** 3 * c)
        return th, thd, thdd, thddd

    def __call__(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """``(p, v, a, j)`` at times ``t`` (s), each ``(N, 3)``.

        With ``e_t = (0, cos θ, sin θ)`` (along travel) and ``e_n = (0, −sin θ, cos θ)`` (toward
        the pivot), the chain rule closes it::

            v = L·θ̇·e_t
            a = L(θ̈·e_t + θ̇²·e_n)
            j = L((θ⃛ − θ̇³)·e_t + 3θ̇θ̈·e_n)
        """
        th, thd, thdd, thddd = self.theta(t)
        L = self.length
        s, c = np.sin(th), np.cos(th)
        zeros = np.zeros_like(th)
        e_t = np.stack([zeros, c, s], axis=-1)
        e_n = np.stack([zeros, -s, c], axis=-1)
        piv = self.pivot
        pos = piv + np.stack([zeros, L * s, -L * c], axis=-1)
        vel = (L * thd)[:, None] * e_t
        acc = (L * thdd)[:, None] * e_t + (L * thd ** 2)[:, None] * e_n
        jerk = (L * (thddd - thd ** 3))[:, None] * e_t + (3.0 * L * thd * thdd)[:, None] * e_n
        return pos, vel, acc, jerk


# =============================================================================================
# The orbit (a banked revolution about a vertical anchor axis)
# =============================================================================================
@dataclass(frozen=True)
class OrbitPath:
    """A circle of radius ``R`` about a vertical anchor axis, at constant altitude.

    ``φ̇(t) = Ω·W(t)`` with the envelope's ramps as the wind-up and wind-down, so the total angle
    is ``Ω·∫W = Ω·T(1 − ramp_frac)``; setting that equal to ``2π·n_revs`` fixes the duration in
    **closed form** (:attr:`septic_smoothstep_int` integrating to exactly ½ is what makes that
    possible), and the revolution count is therefore exact rather than quadrature-accurate.

    ``φ(0) = −π`` so the drone starts at ``(−R, 0, z)`` with ``ψ(0) = 0``: take-off and hover
    happen at identity heading with the anchor ``R`` metres straight off the nose, and the yaw
    winds from there.

    **The "top face points at the axis" intuition has a closed-form error, and it is not zero.**
    Drag is tangential, so the thrust axis leans backward along the track by exactly
    ``atan((D/m)/Ω)`` — **independent of radius**. For this simulator that is 24.1° at ``Ω = 7``;
    with a realistic quadratic drag (``v_term ≈ 10 m/s``) it would be ~3°. It is a sim-drag
    artifact, and it ships as a number in the drag-sensitivity column rather than as a footnote.

    Attributes:
        radius: Orbit radius ``R`` (m).
        omega: Steady-state orbital rate ``Ω`` (rad/s); speed is ``R·Ω``.
        n_revs: Number of full revolutions.
        z: Orbit altitude (m).
        anchor_xy: World ``(x, y)`` the vertical anchor axis passes through.
        nose: ``"in"`` (``ψ = φ + π``, nose at the axis) or ``"out"`` (``ψ = φ``).
        ramp_frac: Fraction of the run spent winding up / down at each end.
    """

    radius: float
    omega: float
    n_revs: float
    z: float
    anchor_xy: tuple[float, float] = (0.0, 0.0)
    nose: str = "in"
    ramp_frac: float = 0.3

    def __post_init__(self) -> None:
        for name, v in (("radius", self.radius), ("omega", self.omega), ("n_revs", self.n_revs)):
            if v <= 0.0:
                raise ValueError(f"{name} must be > 0, got {v}")
        if self.nose not in ("in", "out"):
            raise ValueError(f"nose must be 'in' or 'out', got {self.nose!r}")
        if self.ramp_frac >= 1.0:
            raise ValueError("ramp_frac must be < 1")

    @property
    def duration(self) -> float:
        """``2π·n_revs / (Ω(1 − ramp_frac))`` — exact, from the envelope's exact area."""
        return 2.0 * math.pi * self.n_revs / (self.omega * (1.0 - self.ramp_frac))

    @property
    def rev_period(self) -> float:
        """``2π/Ω`` — the steady-state revolution period (s), i.e. away from the ramps."""
        return 2.0 * math.pi / self.omega

    @property
    def speed(self) -> float:
        """``R·Ω`` (m/s) at full rate."""
        return self.radius * self.omega

    @property
    def anchor(self) -> np.ndarray:
        """The anchor point at orbit altitude — the thing the nose points at."""
        return np.array([self.anchor_xy[0], self.anchor_xy[1], self.z])

    @property
    def phi0(self) -> float:
        return -math.pi

    @property
    def psi_offset(self) -> float:
        return math.pi if self.nose == "in" else 0.0

    @property
    def start_pos(self) -> np.ndarray:
        return self.at_angle(self.phi0)

    @property
    def envelope(self) -> Envelope:
        return Envelope(self.duration, self.ramp_frac)

    def at_angle(self, phi: float) -> np.ndarray:
        return np.array([
            self.anchor_xy[0] + self.radius * math.cos(phi),
            self.anchor_xy[1] + self.radius * math.sin(phi),
            self.z,
        ])

    def phi(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """``(φ, φ̇, φ̈, φ⃛)`` at times ``t``."""
        t = np.asarray(t, dtype=np.float64)
        w, wd, wdd, _ = self.envelope.derivatives(t)
        om = self.omega
        return (self.phi0 + om * self.envelope.integral(t), om * w, om * wd, om * wdd)

    def psi(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(ψ, ψ̇)`` — the heading that keeps the nose on (or off) the anchor axis."""
        phi, phid, _, _ = self.phi(t)
        return phi + self.psi_offset, phid

    def __call__(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """``(p, v, a, j)`` at times ``t`` (s), each ``(N, 3)``.

        With ``e_r = (cos φ, sin φ, 0)`` and ``e_t = (−sin φ, cos φ, 0)``::

            v = R·φ̇·e_t
            a = R(φ̈·e_t − φ̇²·e_r)
            j = R((φ⃛ − φ̇³)·e_t − 3φ̇φ̈·e_r)
        """
        ph, phd, phdd, phddd = self.phi(t)
        R = self.radius
        c, s = np.cos(ph), np.sin(ph)
        zeros = np.zeros_like(ph)
        e_r = np.stack([c, s, zeros], axis=-1)
        e_t = np.stack([-s, c, zeros], axis=-1)
        base = np.array([self.anchor_xy[0], self.anchor_xy[1], self.z])
        pos = base + R * e_r
        vel = (R * phd)[:, None] * e_t
        acc = (R * phdd)[:, None] * e_t - (R * phd ** 2)[:, None] * e_r
        jerk = (R * (phddd - phd ** 3))[:, None] * e_t - (3.0 * R * phd * phdd)[:, None] * e_r
        return pos, vel, acc, jerk

    def axis_pointing_error_rad(self, drag_per_mass: float) -> float:
        """``atan((D/m)/Ω)`` — the closed-form backward lean of the thrust axis along the track.

        Radius-independent: the centripetal demand is ``RΩ²`` and the drag is ``(D/m)·RΩ``, so
        ``R`` cancels. Reported so the honest caveat is a *prediction* that the measurement can be
        checked against, not a hand-wave after the fact.
        """
        return math.atan2(drag_per_mass, self.omega)
