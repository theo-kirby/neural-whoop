"""The **maneuver protocol**, and the flip: a phase program plus a damped-Newton **shoot**.

This module holds two things. :class:`ManeuverSpec` is the small protocol every reference maneuver
satisfies, so :mod:`~neural_whoop.reference.emit` and :mod:`~neural_whoop.reference.verify` work
against "a maneuver" rather than against the flip; :mod:`~neural_whoop.reference.maneuvers_swing`
and :mod:`~neural_whoop.reference.maneuvers_orbit` are the other two implementations. Everything
below the protocol is the flip.

The flip: a phase program, and a damped-Newton **shoot** to close it.

Flatness authors the climb, the recovery and the landing. It cannot author the flip — through
inversion the required specific force points up while the thrust axis points down, so the map
would demand negative thrust and has no solution there. So through the flip we author the
*commands* and let physics return the path, and "come back to where you started" stops being an
interpolation problem and becomes a **boundary-value problem**: solve for the pop and catch
parameters that land the drone on ``φ = 2π``, at its entry altitude, at rest.

The phase program (``ψ ≡ 0`` throughout, rotation about the maneuver axis)::

    CLIMB     PathSegment       rest -> z_entry              <- the legible "straight up"
    HOVER     PathSegment       hold
    POP       RateSegment       level, thrust ramps to A_flip
    ROLL-IN   RateSegment       thrust held, ω -> Ω          <- the "nudge of off-centredness"
    COAST     BallisticSegment  thrust -> floor, zero commanded torque
    CATCH     RateSegment       brake ω -> 0, arrest, taper back to hover
    RECOVER   PathSegment       null the residual lateral offset, settle
    LAND      PathSegment       z_entry -> rest

Why ``Ω = 9 rad/s`` and not the 11-12 the envelope allows: it is the better *hero* number. It buys
a longer, more legible inverted coast, roughly 0.6 m of apex gain that actually reads on camera,
and about half the lateral excursion — while a 12 rad/s flip compresses the level pop beat to
under a millisecond, i.e. invisible.

**ψ ≡ 0 is silently load-bearing in two places** (it was three before 2026-08-01), which is why the
generator asserts it rather than trusting it: it is what keeps ω *exactly* constant through the
coast (no gyroscopic term), and it keeps the heading construction non-degenerate. A future
cinematic yaw sweep would break both, and neither fails loudly.

Historically it was load-bearing in a third way that mattered more than either: it made DiffAero's
``RateController`` frame bug (``R_i2b @ w``) an exact no-op, because ``R`` is the identity for a
rotation about the same axis the rate is on. That bug is **fixed** in the fork now, so the flip no
longer depends on ψ ≡ 0 for *stability* — but the assertion stays, because the other two reasons
are unchanged and because the planarity check is what made the bug findable in the first place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol, runtime_checkable

import numpy as np

from neural_whoop.reference import flatness as fl
from neural_whoop.reference.limits import (
    MAX_BODY_RATE_YAW_RPS,
    MAX_RATE_CMD_RPS,
    MAX_THRUST_NORMED,
    WHOOP_REST_Z_M,
)
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.segments import (
    BallisticSegment,
    PathSegment,
    RateSegment,
    RefState,
    Samples,
    Trajectory,
)


# =============================================================================================
# The maneuver protocol
# =============================================================================================
@dataclass
class ManeuverBuild:
    """What a spec hands back: the trajectory, plus whatever solving it took to get there.

    ``solution`` is ``None`` for a maneuver that needs no boundary-value solve — which is not an
    absence but a *result*. The swing closes on its own start point at machine precision because
    differential flatness authors the whole beat; the flip needed a shoot because flatness has no
    solution through inversion. Carrying that as ``None`` rather than an empty record is the honest
    encoding of "there was nothing to solve".
    """

    traj: Trajectory
    solution: Any = None
    derived: dict[str, float] = field(default_factory=dict)


class RateEnvelopeError(RuntimeError):
    """The authored maneuver asks for a command outside the act-v2 envelope.

    Raised at **build** time by the maneuvers that have no shoot to absorb a bad sizing, so a
    request the airframe cannot fly fails immediately with the measured numbers rather than
    producing an artifact that looks fine and saturates.
    """


@runtime_checkable
class ManeuverSpec(Protocol):
    """What :mod:`~neural_whoop.reference.emit` and :mod:`~neural_whoop.reference.verify` need.

    Small on purpose. :class:`FlipSpec` satisfied all of the geometric half of this before the
    protocol existed; what the generalization added is the reporting half (``phase_labels``,
    ``describe``, ``reference_meta``, ``caveats``), which used to be module-global constants and
    could therefore only ever describe one maneuver.

    Attributes:
        name: Short identifier, e.g. ``"flip"`` / ``"swing"`` / ``"orbit"``.
        phase_labels: Caption labels for the numeric ``scene.phase`` channel, index == code. The
            capture page reads these straight out of ``meta.scene_info.phase_labels``
            (``web/capture/capture.js``), so per-spec labels give per-maneuver captions for free.
        c2_break_phases: ``(from, to)`` phase pairs where a command step is *intended*. Empty for
            a fully powered maneuver — which is itself a claim worth making, and one the swing and
            orbit both make.
        metric_window: ``(lo, hi)`` phase codes bounding the window metrics are computed over —
            the maneuver proper, excluding the climb and landing stagecraft.
        settle_phase: The phase whose last frame is the "did it come back?" measurement.
        station: The world point the maneuver departs from and returns to.
        z_entry / z_rest: Hover altitude and resting altitude (m).
        is_planar: Whether the maneuver is a pure rotation about one body axis with ``ψ ≡ 0``.
        axis_idx: That axis (0 = roll, 1 = pitch) when planar; meaningless otherwise.
        min_thrust_normed: The free-flight throttle floor the stream was authored under.
    """

    name: str

    @property
    def phase_labels(self) -> list[str]: ...
    @property
    def c2_break_phases(self) -> tuple[tuple[int, int], ...]: ...
    @property
    def metric_window(self) -> tuple[int, int]: ...
    @property
    def settle_phase(self) -> int: ...
    @property
    def station(self) -> np.ndarray: ...
    @property
    def z_entry(self) -> float: ...
    @property
    def z_rest(self) -> float: ...
    @property
    def is_planar(self) -> bool: ...
    @property
    def axis_idx(self) -> int: ...
    @property
    def min_thrust_normed(self) -> float: ...

    def build(self, model: RefModel, *, dt: float = 1e-3, verbose: bool = False) -> ManeuverBuild:
        """Assemble the whole sequence, solving whatever has to be solved."""
        ...

    def describe(self, solution: Any) -> str:
        """One-line human description for ``meta.policy`` in the replay."""
        ...

    def reference_meta(self, solution: Any) -> dict:
        """The ``meta.reference`` block — the authored knobs, for a consumer to reconstruct."""
        ...

    def extra_metrics(self, samples: Samples, model: RefModel) -> dict[str, float]:
        """Metrics only this maneuver has (the shared ones live in ``emit``)."""
        ...

    def caveats(self, model: RefModel) -> list[str]:
        """Maneuver-specific honest caveats, appended to the package-wide ones."""
        ...


def assert_within_envelope(
    samples: Samples,
    *,
    rate_cmd_max: float = MAX_RATE_CMD_RPS,
    thrust_max: float = MAX_THRUST_NORMED,
    yaw_cmd_max: float = MAX_BODY_RATE_YAW_RPS,
    what: str = "maneuver",
) -> dict[str, float]:
    """Raise :class:`RateEnvelopeError` unless every authored command is inside the envelope.

    The flip can absorb a bad sizing — the shoot simply returns different parameters. The swing and
    the orbit cannot: their sizing *is* the maneuver, so an out-of-envelope request has to fail at
    build time with the measured numbers attached, or it ships as an artifact that looks perfect
    and saturates the moment anything tries to fly it.

    Returns:
        The measured peaks, so a caller can publish them rather than merely pass the check.
    """
    rp = float(np.max(np.abs(samples.rate_cmd[:, :2])))
    yaw = float(np.max(np.abs(samples.rate_cmd[:, 2])))
    thrust = float(np.max(samples.normed_thrust))
    if rp > rate_cmd_max or yaw > yaw_cmd_max or thrust > thrust_max:
        raise RateEnvelopeError(
            f"the authored {what} is outside the act-v2 envelope: roll/pitch rate command "
            f"{rp:.2f} of {rate_cmd_max:.2f} rad/s, yaw {yaw:.2f} of {yaw_cmd_max:.2f}, collective "
            f"{thrust:.2f} of {thrust_max:.2f}. The rate loop approaches its command "
            f"asymptotically, so a reference that asks for more than this is not merely tight — it "
            f"is untrackable, and the replay would not show it. Size the maneuver down."
        )
    return {"max_rate_cmd_rp_rps": rp, "max_rate_cmd_yaw_rps": yaw, "max_normed_thrust": thrust}


# =============================================================================================
# The flip
# =============================================================================================
#: Caption labels for the numeric ``scene.phase`` channel, index == code. Same mechanism
#: ``scripts/hero_takeoff_flip_land.py`` uses, so ``web/capture/capture.js`` picks these up as
#: on-screen captions with no renderer change. **The flip's** — every spec now carries its own,
#: which is what lets one renderer caption three different maneuvers.
PHASE_LABELS = ["CLIMB", "HOVER", "POP", "ROLL-IN", "COAST", "CATCH", "RECOVER", "LAND"]
PHASE = {name: i for i, name in enumerate(PHASE_LABELS)}
#: The two seams where thrust steps — the intentional C² breaks. Verification masks exactly these
#: by phase transition rather than by eyeball.
C2_BREAK_PHASES = ((PHASE["ROLL-IN"], PHASE["COAST"]), (PHASE["COAST"], PHASE["CATCH"]))

_AXIS_IDX = {"roll": 0, "pitch": 1}
#: The heading construction that stays non-degenerate for each maneuver plane (see
#: :func:`neural_whoop.reference.flatness.attitude_from_f`).
_AXIS_HEADING = {0: "x_c", 1: "y_c"}
#: The world axis the maneuver translates along: a roll (about body x) pushes ±y, a pitch ±x.
_AXIS_LATERAL = {0: 1, 1: 0}


def _smoothstep(x: float) -> float:
    """C¹ 0->1 ramp ``3x² − 2x³``, clamped outside ``[0, 1]``."""
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)


def _smoothstep_d(x: float) -> float:
    if x < 0.0 or x > 1.0:
        return 0.0
    return 6.0 * x * (1.0 - x)


@dataclass(frozen=True)
class FlipSpec:
    """What the author chooses. Everything else in the maneuver is solved or derived.

    Satisfies :class:`ManeuverSpec`.
    """

    name: str = field(default="flip", init=False, repr=False)
    axis: str = "roll"
    #: Peak body rate through the coast (rad/s). The hero number, not the envelope number.
    omega_peak: float = 9.0
    n_rotations: float = 1.0
    #: Hover / flip-entry altitude (m).
    z_entry: float = 1.2
    #: Resting altitude — the airframe's half-height. The sequence starts at LIFTOFF and ends at
    #: TOUCHDOWN; there is deliberately no "props spooling on the ground" beat, because at rest a
    #: PathSegment yields ``normed_thrust = 1.0``, which lifts off (the model has no contact).
    #: Leave the spool-up to the video's title card.
    z_rest: float = WHOOP_REST_Z_M
    #: Collective held through the pop and roll-in (DiffAero normed units).
    thrust_flip: float = 3.8
    #: Collective during the coast: 0.0 (motors off — the aesthetic ideal) or the deploy 0.25.
    coast_thrust: float = 0.0
    #: Largest body-rate COMMAND the reference will author.
    rate_cmd_max: float = MAX_RATE_CMD_RPS
    # Fixed durations of the flatness-authored beats (s).
    t_climb: float = 1.4
    t_hover: float = 0.4
    t_recover: float = 1.2
    t_land: float = 2.2
    #: Duration of the catch's thrust taper back to hover. Without it the catch would hand
    #: RECOVER a state with ~+27 m/s² of acceleration, and the septic that has to null that
    #: overshoots hard enough to demand a below-singular thrust on the way back down.
    t_taper: float = 0.06

    @property
    def axis_idx(self) -> int:
        if self.axis not in _AXIS_IDX:
            raise ValueError(f"axis must be one of {sorted(_AXIS_IDX)}, got {self.axis!r}")
        return _AXIS_IDX[self.axis]

    @property
    def heading(self) -> str:
        return _AXIS_HEADING[self.axis_idx]

    @property
    def lateral_idx(self) -> int:
        return _AXIS_LATERAL[self.axis_idx]

    @property
    def target_phi(self) -> float:
        return 2.0 * math.pi * self.n_rotations

    # --- the ManeuverSpec protocol -------------------------------------------------------
    @property
    def phase_labels(self) -> list[str]:
        return list(PHASE_LABELS)

    @property
    def c2_break_phases(self) -> tuple[tuple[int, int], ...]:
        return C2_BREAK_PHASES

    @property
    def metric_window(self) -> tuple[int, int]:
        """POP..RECOVER — ``acro_flip`` scores an episode that begins at a level hover at ``z0``
        and ends after the recover, so the climb and the landing are stagecraft, not the target."""
        return (PHASE["POP"], PHASE["RECOVER"])

    @property
    def settle_phase(self) -> int:
        return PHASE["RECOVER"]

    @property
    def rotation_window(self) -> tuple[int, int]:
        """POP..CATCH — the window φ is claimed monotone over. **Not** the whole flight: through
        RECOVER the airframe leans to fly the residual offset back, so φ wobbles about 2π."""
        return (PHASE["POP"], PHASE["CATCH"])

    @property
    def station(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.z_entry])

    @property
    def is_planar(self) -> bool:
        return True

    @property
    def min_thrust_normed(self) -> float:
        return float(self.coast_thrust)

    @property
    def variant(self) -> str:
        return ("motors-off" if self.coast_thrust <= 0.0
                else f"deployable (coast {self.coast_thrust:g})")

    def build(self, model: RefModel, *, dt: float = 1e-3, verbose: bool = False,
              try_stage2: bool = True) -> ManeuverBuild:
        """Solve the shoot, then assemble CLIMB → HOVER → flip → RECOVER → LAND around it."""
        entry = hover_entry_state(self)
        solution = solve_flip(self, model, entry, dt=dt, try_stage2=try_stage2, verbose=verbose)
        return ManeuverBuild(traj=build_sequence(self, model, solution), solution=solution,
                             derived=dict(solution.derived))

    def describe(self, solution: "FlipSolution | None") -> str:
        stage = (f", flip closed by a damped-Newton shoot (stage {solution.stage})"
                 if solution else "")
        return (
            f"HAND-AUTHORED REFERENCE — not a policy rollout. {self.axis}-flip, "
            f"Ω={self.omega_peak:g} rad/s, {self.variant}; attitude/thrust/rates derived by "
            f"differential flatness{stage}."
        )

    def reference_meta(self, solution: "FlipSolution | None") -> dict:
        return {
            "maneuver": "flip", "axis": self.axis, "omega_peak_rps": self.omega_peak,
            "n_rotations": self.n_rotations, "coast_thrust": self.coast_thrust,
            "variant": self.variant, "z_entry_m": self.z_entry,
            "stage": solution.stage if solution else None,
            "plane": "yz" if self.axis_idx == 0 else "xz",
            "lateral_axis": self.lateral_idx,
            "station": [float(v) for v in self.station],
            "rotation": {
                "kind": "axis", "axis": self.axis_idx,
                "target_turns": float(self.n_rotations),
                "label": f"{self.axis} rotation (turns)",
                "note": ("unwrapped from the quaternion HALF angle then doubled — doubling first "
                         "makes a full flip a 4-pi jump that np.unwrap reads as no jump at all"),
            },
        }

    def extra_metrics(self, samples: Samples, model: RefModel) -> dict[str, float]:
        """The flip's own shape: how far round, how long the flip beat was, and the coast IMU."""
        phi = fl.rotation_angle_about(samples.quat, self.axis_idx)
        flip = np.flatnonzero(
            (samples.phase >= PHASE["POP"]) & (samples.phase <= PHASE["CATCH"])
        )
        imu = samples.imu(model)
        coast = samples.phase == PHASE["COAST"]
        out = {
            "flip_duration_s": (float(samples.t[flip[-1]] - samples.t[flip[0]])
                                if flip.size else 0.0),
            "rotation_turns": float(phi[-1] / (2.0 * np.pi)),
        }
        if np.any(coast):
            mag = np.linalg.norm(imu[coast], axis=-1) / model.g
            out["imu_coast_min_g"] = float(np.min(mag))
            out["imu_coast_max_g"] = float(np.max(mag))
        return out

    def caveats(self, model: RefModel) -> list[str]:
        return [
            "Body rate is exactly constant through the coast because DiffAero applies drag only to "
            "linear velocity and both gyroscopic terms vanish on a symmetric-inertia axis with "
            "w_z = 0. A real whoop would shed 5-15% of its roll rate to blade flapping over a "
            "0.6 s coast. That is NOT modeled here.",
            "The coast IMU is a V, not a flat free-fall null: drag scales with speed, which is "
            "large at both ends of a ballistic arc and zero at the apex. See metrics."
            "imu_coast_min_g / imu_coast_max_g for the measured spread. The body-z component goes "
            "strongly negative at coast entry because the drone is climbing fast along its own "
            "+z and drag pushes back along -z — that is what the accelerometer reads, not a sign "
            "error.",
            "psi == 0 is load-bearing in two places (the coast rate stays exactly constant, the "
            "heading construction stays non-degenerate), and a yaw sweep breaks both without "
            "failing loudly. Before 2026-08-01 it was load-bearing in a third and larger way: it "
            "made the RateController frame bug an exact no-op, because the flip's omega lies on "
            "R's fixed axis, the one eigenvalue that stays -K regardless of attitude. That bug is "
            "now fixed in the fork, so stability no longer rests on it. See "
            "checks.rate_loop_stability.",
            "Control allocation: the catch itself is comfortably feasible here (see "
            "checks.allocation.min_margin_torqued) because the rate brake is authored as a "
            "smoothstep rather than a step command, so the torque it asks for is modest. The "
            "binding problem is elsewhere and is structural: through the motors-off coast the "
            "margin is exactly 0 — zero thrust demanding zero torque — which means the airframe "
            "has NO rate authority for that whole stretch and could not correct a disturbance if "
            "it had one. That is the AIRMODE flip-stall failure of docs/SIM2REAL.md in miniature. "
            "If this reference is used as an RL target or a scoring reference, use the "
            "--deployable variant, whose 0.25 floor keeps authority alive throughout.",
        ]


@dataclass
class FlipParams:
    """The shoot's unknowns (all durations in s, thrusts in DiffAero normed units)."""

    t_pop: float = 0.06
    t_coast: float = 0.60
    a_catch: float = 3.50
    a_rollin: float = 3.80
    t_hold: float = 0.09

    def as_vector(self, names: tuple[str, ...]) -> np.ndarray:
        return np.array([getattr(self, n) for n in names], dtype=np.float64)

    def with_vector(self, names: tuple[str, ...], x: np.ndarray) -> "FlipParams":
        return replace(self, **{n: float(v) for n, v in zip(names, x)})


#: Hard bounds on every unknown. A shoot can converge to a nonsense root (negative coast, a
#: two-turn solution); bounded unknowns plus the monotone-φ assertion plus published residuals are
#: what stop a wrong reference from shipping while looking perfect.
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "t_pop": (0.002, 0.60),
    "t_coast": (0.02, 2.50),
    "a_catch": (1.05, MAX_THRUST_NORMED - 0.05),
    "a_rollin": (1.50, MAX_THRUST_NORMED - 0.05),
    "t_hold": (0.002, 0.60),
}

STAGE1_UNKNOWNS = ("t_pop", "t_coast", "a_catch")
#: Alternate stage-1 parameterization, used when ``t_pop`` pins at its lower bound. That happens
#: at high Ω and is not a solver failure but a physical statement: reaching a rate close to the
#: command ceiling takes a long roll-in (the loop approaches its command asymptotically), and a
#: long roll-in at full collective *already* over-delivers the climb. The pop then cannot be made
#: short enough, so the answer is to make it **weaker** — solve for the flip collective instead,
#: with the pop pinned to a token beat.
STAGE1_ALT_UNKNOWNS = ("a_rollin", "t_coast", "a_catch")
#: The token pop duration used by the alternate parameterization (s).
ALT_T_POP = 0.02
STAGE1_RESIDUALS = ("phi_end - 2pi", "z_end - z_entry", "vz_end")
STAGE2_UNKNOWNS = ("t_pop", "t_coast", "a_catch", "a_rollin", "t_hold")
STAGE2_RESIDUALS = (*STAGE1_RESIDUALS, "lateral_end", "v_lateral_end")


@dataclass
class FlipSolution:
    """The shoot's record — written verbatim into ``reference.json``.

    A silently non-converged solve is the easiest way to ship a wrong reference that looks
    perfect, so ``stage``, ``residuals`` and ``bounds_hit`` are all first-class output.
    """

    params: FlipParams
    stage: int                       # 1 = altitude/rotation closed; 2 = the point closed too
    converged: bool
    residuals: dict[str, float]
    residual_norm: float
    iterations: int
    bounds_hit: list[str] = field(default_factory=list)
    stage2_note: str = ""
    derived: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "stage_meaning": {
                1: "rotation + altitude + vertical rest closed; lateral offset flown out by "
                   "RECOVER",
                2: "also returns to the POINT (lateral position and velocity closed)",
            }[self.stage],
            "converged": bool(self.converged),
            "unknowns": {k: float(v) for k, v in vars(self.params).items()},
            "residuals": {k: float(v) for k, v in self.residuals.items()},
            "residual_norm": float(self.residual_norm),
            "iterations": int(self.iterations),
            "bounds_hit": list(self.bounds_hit),
            "stage2_note": self.stage2_note,
            "derived": {k: float(v) for k, v in self.derived.items()},
        }


# =============================================================================================
# Derived timings — the parts that are algebra, not search
# =============================================================================================
def rollin_duration(spec: FlipSpec, model: RefModel) -> float:
    """Time for the exponential rate-loop response to reach ``Ω`` under a constant command.

    The roll-in authors ``ω(t) = u(1 − e^{−Kt})`` — literally the first-order lag response to a
    step command ``u`` — so the emitted command ``u = ω + ω̇/K`` is *exactly the constant* ``u``,
    provably inside the envelope with no numerical argument. It is also the fastest in-limits way
    to get to Ω, which is what makes the pop a distinct beat rather than a smear.
    """
    u = spec.rate_cmd_max
    if spec.omega_peak >= u:
        raise ValueError(
            f"omega_peak {spec.omega_peak} must be below the command ceiling {u:.3f} rad/s — the "
            f"rate loop approaches its command asymptotically and can never reach it."
        )
    return -math.log(1.0 - spec.omega_peak / u) / model.K_angvel_rp


def brake_duration(spec: FlipSpec, model: RefModel, *, margin: float = 1.10) -> float:
    """Shortest smoothstep decay ``Ω -> 0`` whose implied command stays inside the envelope.

    The catch authors ``ω(t) = Ω(1 − h(t/T))``; the command is ``u = ω + ω̇/K`` and its most
    negative excursion scales as ``−1.5Ω/(K·T)``. Solved numerically rather than by hand because
    the extremum is not at the midpoint once the ``ω`` term is included. ``margin`` buys headroom
    so a later regression that *does* saturate fails the limits check instead of tying it.
    """
    K = model.K_angvel_rp
    x = np.linspace(0.0, 1.0, 2001)
    h = x * x * (3.0 - 2.0 * x)
    hd = 6.0 * x * (1.0 - x)

    def worst(T: float) -> float:
        u = spec.omega_peak * (1.0 - h) - spec.omega_peak * hd / (K * T)
        return float(np.max(np.abs(u)))

    lo, hi = 1e-4, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if worst(mid) > spec.rate_cmd_max:
            lo = mid
        else:
            hi = mid
    return hi * margin


# =============================================================================================
# The flip segments
# =============================================================================================
def flip_segments(
    spec: FlipSpec, p: FlipParams, model: RefModel
) -> list[RateSegment]:
    """POP / ROLL-IN / COAST / CATCH for one parameter set."""
    ax = spec.axis_idx
    K = model.K_angvel_rp
    u_roll = spec.rate_cmd_max
    t_rollin = rollin_duration(spec, model)
    t_brake = brake_duration(spec, model)
    Om = spec.omega_peak

    a_roll = p.a_rollin
    t_pop = max(p.t_pop, 1e-6)

    def pop_thrust(t: float) -> float:
        return 1.0 + (a_roll - 1.0) * _smoothstep(t / t_pop)

    def rollin_omega(t: float) -> float:
        return u_roll * (1.0 - math.exp(-K * t))

    def rollin_omega_dot(t: float) -> float:
        return u_roll * K * math.exp(-K * t)

    t_brake_hold = t_brake + max(p.t_hold, 1e-6)

    def catch_thrust(t: float) -> float:
        if t <= t_brake_hold:
            return p.a_catch
        return p.a_catch + (1.0 - p.a_catch) * _smoothstep((t - t_brake_hold) / spec.t_taper)

    def catch_omega(t: float) -> float:
        return Om * (1.0 - _smoothstep(t / t_brake))

    def catch_omega_dot(t: float) -> float:
        return -Om * _smoothstep_d(t / t_brake) / t_brake

    zero: Callable[[float], float] = lambda t: 0.0  # noqa: E731

    return [
        RateSegment("POP", PHASE["POP"], t_pop, pop_thrust, zero, zero, axis=ax),
        RateSegment("ROLL-IN", PHASE["ROLL-IN"], t_rollin, lambda t: a_roll,
                    rollin_omega, rollin_omega_dot, axis=ax),
        BallisticSegment("COAST", PHASE["COAST"], max(p.t_coast, 1e-6),
                         coast_thrust=spec.coast_thrust, axis=ax),
        RateSegment("CATCH", PHASE["CATCH"], t_brake_hold + spec.t_taper,
                    catch_thrust, catch_omega, catch_omega_dot, axis=ax),
    ]


def _flip_end(
    spec: FlipSpec, p: FlipParams, model: RefModel, entry: RefState, dt: float
) -> tuple[Samples, np.ndarray]:
    """Integrate the flip from the hover entry state; return its samples + the residual vector."""
    traj = Trajectory(segments=flip_segments(spec, p, model), start=entry)
    s = traj.sample(model, dt)
    ax, lat = spec.axis_idx, spec.lateral_idx
    phi = fl.rotation_angle_about(s.quat, ax)
    return s, np.array([
        phi[-1] - spec.target_phi,
        s.pos[-1, 2] - spec.z_entry,
        s.vel[-1, 2],
        s.pos[-1, lat] - entry.pos[lat],
        s.vel[-1, lat],
    ])


def _clip_to_bounds(p: FlipParams, names: tuple[str, ...]) -> tuple[FlipParams, list[str]]:
    hit: list[str] = []
    vals: dict[str, float] = {}
    for n in names:
        lo, hi = PARAM_BOUNDS[n]
        v = float(getattr(p, n))
        if v <= lo + 1e-9:
            hit.append(f"{n}@min({lo})")
        elif v >= hi - 1e-9:
            hit.append(f"{n}@max({hi})")
        vals[n] = min(max(v, lo), hi)
    return replace(p, **vals), hit


def _newton(
    spec: FlipSpec,
    model: RefModel,
    entry: RefState,
    p0: FlipParams,
    names: tuple[str, ...],
    res_idx: tuple[int, ...],
    dt: float,
    *,
    tol: float = 1e-6,
    max_iter: int = 40,
) -> tuple[FlipParams, np.ndarray, bool, int]:
    """Damped Newton with a forward-difference Jacobian and bounded unknowns."""
    p = replace(p0)

    def R(par: FlipParams) -> np.ndarray:
        _, r = _flip_end(spec, par, model, entry, dt)
        return r[list(res_idx)]

    r = R(p)
    it = 0
    for it in range(1, max_iter + 1):
        if np.linalg.norm(r) < tol:
            return p, r, True, it - 1
        x = p.as_vector(names)
        J = np.empty((len(res_idx), len(names)))
        for k, n in enumerate(names):
            lo, hi = PARAM_BOUNDS[n]
            h = max(1e-5, abs(x[k]) * 1e-4)
            if x[k] + h > hi:
                h = -h
            xp = x.copy()
            xp[k] += h
            J[:, k] = (R(p.with_vector(names, xp)) - r) / h
        try:
            dx = np.linalg.solve(J, -r)
        except np.linalg.LinAlgError:
            dx = -np.linalg.lstsq(J, r, rcond=None)[0]
        # Damped line search: accept the first step that reduces ‖r‖.
        step, ok = 1.0, False
        for _ in range(24):
            cand, _hit = _clip_to_bounds(p.with_vector(names, x + step * dx), names)
            r_new = R(cand)
            if np.linalg.norm(r_new) < np.linalg.norm(r):
                p, r, ok = cand, r_new, True
                break
            step *= 0.5
        if not ok:
            return p, r, False, it
    return p, r, bool(np.linalg.norm(r) < tol), it


def solve_flip(
    spec: FlipSpec,
    model: RefModel,
    entry: RefState,
    *,
    dt: float = 1e-3,
    try_stage2: bool = True,
    verbose: bool = False,
) -> FlipSolution:
    """Shoot for the flip: solve for the parameters that bring the drone back.

    **Stage 1 (3x3, required)** — unknowns ``(T_pop, T_coast, A_catch)`` against residuals
    ``(φ_end − 2π, z_end − z_entry, vz_end)``. Note this is a 3x3 rather than the 4x4 you would
    write if you authored the rate *command*: because the catch authors ``ω(t)`` as a profile that
    terminates at exactly zero, ``ω_end = 0`` is satisfied **by construction** and is not a free
    residual. That is strictly better than solving for it — it cannot be missed by a tolerance.

    **Stage 2 (5x5, attempted)** — adds ``(A_rollin, T_hold)`` against ``(lateral_end,
    v_lateral_end)`` so the drone returns to the *point*, not just the altitude.

    Stage 2 is expected to fail for a single-lean flip, and the reason is structural rather than
    numerical: the roll-in tilts the thrust axis one way and the catch the other, so the lateral
    *impulses* can cancel — but the drone drifts monotonically to one side for the whole coast in
    between, and no choice of powered-phase thrust brings that displacement back within the flip.
    Closing it would need a deliberate counter-lean *before* the pop (what a freestyle pilot
    actually does), which is a different maneuver from the one specified. When stage 2 fails we
    keep stage 1 and let ``RECOVER`` fly out the residual offset — and report which was achieved,
    plus ``max_lateral_drift`` as a headline number.

    Args:
        spec: What the author chose.
        model: The airframe to derive against.
        entry: The hover state the flip starts from.
        dt: Integration step for the shoot (matches the emitted fine stream, so the solved
            residuals ARE the emitted ones).
        try_stage2: Attempt the 5x5.
        verbose: Print per-stage progress.

    Returns:
        The :class:`FlipSolution` record.
    """
    t_rollin = rollin_duration(spec, model)
    t_brake = brake_duration(spec, model)
    # A crude but principled first guess for the coast: the rotation not already delivered by the
    # roll-in ramp and the brake ramp, divided by Ω.
    phi_rollin = spec.rate_cmd_max * (
        t_rollin - spec.omega_peak / spec.rate_cmd_max / model.K_angvel_rp
    )
    phi_brake = spec.omega_peak * t_brake / 2.0
    p0 = FlipParams(
        t_pop=0.06,
        t_coast=max(0.05, (spec.target_phi - phi_rollin - phi_brake) / spec.omega_peak),
        a_catch=3.5,
        a_rollin=spec.thrust_flip,
        t_hold=0.02,
    )

    unknowns = STAGE1_UNKNOWNS
    p, r, ok, iters = _newton(spec, model, entry, p0, unknowns, (0, 1, 2), dt)
    total_iters = iters
    # If the catch thrust pinned against its ceiling, the arrest simply needs longer, not harder.
    grow = 0
    while (not ok or p.a_catch >= PARAM_BOUNDS["a_catch"][1] - 1e-6) and grow < 6:
        grow += 1
        p0 = replace(p, t_hold=min(p.t_hold * 1.6, PARAM_BOUNDS["t_hold"][1]))
        p, r, ok, iters = _newton(spec, model, entry, p0, unknowns, (0, 1, 2), dt)
        total_iters += iters
    # Pop pinned short: reparameterize onto the flip collective (see STAGE1_ALT_UNKNOWNS).
    if not ok and p.t_pop <= PARAM_BOUNDS["t_pop"][0] + 1e-9:
        unknowns = STAGE1_ALT_UNKNOWNS
        p_alt = replace(p, t_pop=ALT_T_POP)
        p, r, ok, iters = _newton(spec, model, entry, p_alt, unknowns, (0, 1, 2), dt)
        total_iters += iters
        if verbose:
            print(f"  stage 1 reparameterized on {unknowns} (pop pinned at its lower bound)")
    if not ok:
        raise RuntimeError(
            f"stage-1 shoot did not converge: residuals {dict(zip(STAGE1_RESIDUALS, r))}, "
            f"unknowns {vars(p)}, bounds hit {_clip_to_bounds(p, unknowns)[1]}. A reference whose "
            f"boundary conditions are not met is not a reference — refusing to emit. Try a "
            f"different omega_peak / thrust_flip."
        )
    _, hit = _clip_to_bounds(p, unknowns)
    stage, note = 1, ""
    res_names, res_vals = STAGE1_RESIDUALS, r
    if verbose:
        print(f"  stage 1 converged in {total_iters} iters: ‖r‖={np.linalg.norm(r):.3e} {vars(p)}")

    if try_stage2:
        p2, r2, ok2, it2 = _newton(spec, model, entry, p, STAGE2_UNKNOWNS, (0, 1, 2, 3, 4), dt)
        total_iters += it2
        if ok2:
            p, stage, res_names, res_vals = p2, 2, STAGE2_RESIDUALS, r2
            _, hit = _clip_to_bounds(p, STAGE2_UNKNOWNS)
            note = "stage 2 converged: the flip returns to the point, not just the altitude."
        else:
            note = (
                f"stage 2 (return to the POINT) did not converge — best ‖r‖ "
                f"{np.linalg.norm(r2):.3f} with lateral residual {r2[3]:+.3f} m. This is "
                f"structural, not numerical: the drone drifts monotonically to one side for the "
                f"whole coast, and no powered-phase thrust split brings that displacement back "
                f"within the flip. Stage 1 kept; RECOVER flies out the offset. Closing it would "
                f"need a counter-lean before the pop, which is a different maneuver."
            )
        if verbose:
            print(f"  stage 2 {'converged' if ok2 else 'refused'}: ‖r‖={np.linalg.norm(r2):.3e}")

    _, resid_full = _flip_end(spec, p, model, entry, dt)
    return FlipSolution(
        params=p,
        stage=stage,
        converged=True,
        residuals=dict(zip(res_names, [float(v) for v in res_vals])),
        residual_norm=float(np.linalg.norm(res_vals)),
        iterations=total_iters,
        bounds_hit=hit,
        stage2_note=note,
        derived={
            "t_rollin_s": t_rollin,
            "t_brake_s": t_brake,
            "t_taper_s": spec.t_taper,
            "rate_cmd_rollin_rps": spec.rate_cmd_max,
            "flip_duration_s": (p.t_pop + t_rollin + p.t_coast + t_brake + p.t_hold
                                + spec.t_taper),
            "lateral_residual_m": float(resid_full[3]),
            "v_lateral_residual_mps": float(resid_full[4]),
        },
    )


# =============================================================================================
# The whole sequence
# =============================================================================================
def build_sequence(spec: FlipSpec, model: RefModel, solution: FlipSolution) -> Trajectory:
    """Assemble CLIMB -> HOVER -> flip -> RECOVER -> LAND around a solved flip."""
    h = spec.heading
    station = np.array([0.0, 0.0, spec.z_entry])
    rest = np.array([0.0, 0.0, spec.z_rest])
    start = RefState.at_rest(rest)
    segs: list[PathSegment | RateSegment] = [
        PathSegment("CLIMB", PHASE["CLIMB"], spec.t_climb, end_pos=station, heading=h),
        PathSegment("HOVER", PHASE["HOVER"], spec.t_hover, end_pos=station, heading=h),
        *flip_segments(spec, solution.params, model),
        PathSegment("RECOVER", PHASE["RECOVER"], spec.t_recover, end_pos=station, heading=h),
        PathSegment("LAND", PHASE["LAND"], spec.t_land, end_pos=rest, heading=h),
    ]
    return Trajectory(segments=segs, start=start)


def hover_entry_state(spec: FlipSpec) -> RefState:
    """The state the flip starts from: level, at rest, at ``z_entry``, hover thrust."""
    return RefState.at_rest(np.array([0.0, 0.0, spec.z_entry]))


def assert_planar(samples: Samples, spec: ManeuverSpec, *, tol: float = 1e-9) -> dict[str, float]:
    """Assert the maneuver is a pure rotation about its own axis — no yaw, no off-axis rate.

    Only meaningful for a spec that declares ``is_planar``; it raises on one that does not, rather
    than reporting a failure for a maneuver whose whole point is being 3D.

    Measured on the **quaternion**, not on euler yaw. A pitch flip passes through 180° of pitch,
    where the ZYX yaw ``atan2(R₁₀, R₀₀)`` reads exactly π even though the airframe never yawed —
    the same gimbal artifact that makes ``rpy`` useless for charting a flip. A pure rotation about
    body axis ``k`` from identity has ``q_j = 0`` for the other two vector components, which is
    exact and axis-agnostic.

    This matters because ψ ≡ 0 is silently load-bearing in three places at once (module
    docstring), and only one of the three would fail loudly on its own. Returns the measured
    maxima so they are published rather than merely checked.
    """
    if not spec.is_planar:
        raise ValueError(
            f"{spec.name} declares itself non-planar, so 'pure rotation about one axis' is not a "
            f"claim it makes. Gate this call on spec.is_planar."
        )
    ax = spec.axis_idx
    off_q = [i for i in (0, 1, 2) if i != ax]
    max_off_q = float(np.max(np.abs(samples.quat[:, off_q])))
    max_wz = float(np.max(np.abs(samples.omega[:, 2])))
    off_w = [i for i in (0, 1) if i != ax]
    max_off_rate = float(np.max(np.abs(samples.omega[:, off_w])))
    if max_wz > tol:
        raise AssertionError(f"ω_z = {max_wz:.3e} > {tol}: the maneuver is not planar.")
    if max_off_q > 1e-9:
        raise AssertionError(
            f"off-axis quaternion component {max_off_q:.3e}: the rotation left its plane, so the "
            f"heading drifted and this maneuver is no longer the planar thing it claims to be. "
            f"(Before the 2026-08-01 controller fix this also meant DiffAero's RateController "
            f"frame bug stopped being a no-op and the maneuver became unflyable.)"
        )
    return {"is_planar": True, "axis": float(ax), "max_abs_off_axis_quat": max_off_q,
            "max_abs_omega_z_rps": max_wz, "max_abs_off_axis_rate_rps": max_off_rate}
