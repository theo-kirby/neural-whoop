""":class:`RefModel` — the airframe the reference maneuver is *derived against*.

A hand-authored reference is only meaningful relative to a model: change the drag coefficient and
the coast duration, apex height and return speed all move. So the model is a first-class, frozen
object that gets embedded **verbatim** in ``reference.json``, and the artifact is named for it.

The values mirror :class:`neural_whoop.dynamics.whoop.WhoopParams` **defaults** (the
``randomize_airframe=False`` airframe, which is what the Studio/hero/eval paths fly);
``tests/test_reference.py`` asserts they still match. We cannot import ``WhoopParams`` here —
it pulls torch, and this package is pure numpy.

Honest caveat, restated everywhere this model is used: ``D = 0.10 N/(m/s)`` on 32 g gives a
**3.14 m/s terminal velocity**, where a real 65 mm whoop is 8-12 m/s. The sim's drag at the flip's
~2.7 m/s is roughly 8x a plausible real value, and *linear* where reality is quadratic. Coast
duration, apex height, return speed and the entire coast IMU trace are therefore artifacts of
**this simulator**, not measurements of a whoop. :func:`drag_sensitivity_models` exists so the
generator can ship that as a column rather than a footnote.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


class AnisotropicDragError(ValueError):
    """Raised when ``D_xy != D_z``.

    The flatness map's closed form needs the drag force ``R D Rᵀ v`` to reduce to ``D·v``. With
    anisotropic drag it does not: ``f`` becomes implicit in ``R`` (a fixed point needing ~12
    iterations) and ``ω`` lands on both sides of its own equation. The reference is generated
    with ``randomize_airframe=False``, where DiffAero's ``D_xy`` and ``D_z`` defaults are equal,
    so we ship the closed form and **refuse** the anisotropic case rather than silently returning
    a wrong attitude. Extending to anisotropic drag means adding that fixed-point iteration.
    """


@dataclass(frozen=True)
class RefModel:
    """The whoop airframe + rate loop the reference is derived against (SI units).

    Attributes:
        mass: Airframe mass (kg).
        arm_l: Motor arm length (m) — used only by the control-allocation check.
        c_tau: Propeller torque constant — used only by the control-allocation check.
        J_xy: Roll/pitch inertia (kg·m²).
        J_z: Yaw inertia (kg·m²).
        D_xy: Horizontal linear drag coefficient (N per m/s).
        D_z: Vertical linear drag coefficient (N per m/s). Must equal ``D_xy``.
        g: Gravity (m/s²), matching DiffAero's ``G_vec = [0, 0, -g]``.
        K_angvel_rp: Roll/pitch rate-loop bandwidth (1/s). DiffAero's ``RateController`` is
            **exactly** first order for a single-axis rotation from ψ = 0: ``ω̇ = K(u − ω)``.
        K_angvel_yaw: Yaw rate-loop bandwidth (1/s).
    """

    mass: float = 0.032
    arm_l: float = 0.032
    c_tau: float = 0.0066
    J_xy: float = 2.3e-5
    J_z: float = 4.0e-5
    D_xy: float = 0.10
    D_z: float = 0.10
    g: float = 9.81
    K_angvel_rp: float = 16.0
    K_angvel_yaw: float = 8.0

    def __post_init__(self) -> None:
        if self.mass <= 0.0:
            raise ValueError(f"mass must be > 0, got {self.mass}")
        if abs(self.D_xy - self.D_z) > 1e-12:
            raise AnisotropicDragError(
                f"the flatness map's closed form requires isotropic drag, got "
                f"D_xy={self.D_xy} D_z={self.D_z}. See RefModel's AnisotropicDragError docstring."
            )

    @property
    def drag_per_mass(self) -> float:
        """``D/m`` (1/s) — the linear-drag rate that appears directly in the flatness map."""
        return self.D_xy / self.mass

    @property
    def drag_time_constant_s(self) -> float:
        """``m/D`` (s) — 0.32 s for the defaults; the coast is only ~2 of these long.

        ``inf`` for the drag-free sensitivity model.
        """
        return float("inf") if self.D_xy == 0.0 else self.mass / self.D_xy

    @property
    def terminal_velocity_mps(self) -> float:
        """Steady-state free-fall speed ``m·g/D`` = 3.14 m/s for the defaults (``inf`` at D=0).

        This is the number the "8x too much drag" caveat is about, and it is also the state the
        flatness map is **singular** at: at terminal velocity the required specific force is zero.
        """
        return float("inf") if self.D_xy == 0.0 else self.mass * self.g / self.D_xy

    @property
    def K_angvel(self) -> tuple[float, float, float]:
        """Per-axis rate-loop bandwidth ``(Kx, Ky, Kz)`` (1/s)."""
        return (self.K_angvel_rp, self.K_angvel_rp, self.K_angvel_yaw)

    def to_dict(self) -> dict[str, float]:
        """JSON-native dict, embedded verbatim in ``reference.json``."""
        d = {k: float(v) for k, v in asdict(self).items()}
        d["drag_per_mass"] = self.drag_per_mass
        d["drag_time_constant_s"] = self.drag_time_constant_s
        d["terminal_velocity_mps"] = self.terminal_velocity_mps
        return d


def drag_sensitivity_models(base: RefModel | None = None) -> dict[str, RefModel]:
    """The drag-sensitivity column: the same command stream re-flown under other drag models.

    The sim's drag is the dominant modeling error and the reference bakes it in. Re-running the
    identical authored commands at zero drag and at a plausible *real* coefficient is what turns
    that from an implicit assumption into a measured spread — and it is the single most likely way
    this deliverable would do damage later if left implicit.

    - ``sim`` — the vendored default (``D = 0.10``, terminal 3.14 m/s). What the reference IS.
    - ``none`` — ``D = 0`` : the textbook ballistic coast the ``acro_flip`` docstring's arithmetic
      assumes. Bounds the "how much of this shape is drag?" question from below.
    - ``real_est`` — ``D`` scaled so terminal velocity is ~10 m/s, a plausible 65 mm whoop. Still
      *linear* where reality is quadratic, so this is a bracket, not a measurement.

    Returns:
        ``{label: RefModel}``. Every field but the drag coefficients is the base model's.
    """
    base = base or RefModel()
    real_d = base.mass * base.g / 10.0  # D that puts terminal velocity at 10 m/s
    return {
        "sim": base,
        "none": RefModel(**{**{k: getattr(base, k) for k in _FIELDS}, "D_xy": 0.0, "D_z": 0.0}),
        "real_est": RefModel(
            **{**{k: getattr(base, k) for k in _FIELDS}, "D_xy": real_d, "D_z": real_d}
        ),
    }


_FIELDS = tuple(RefModel.__dataclass_fields__)
