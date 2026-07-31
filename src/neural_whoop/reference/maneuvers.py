"""The flip itself: a phase program, and a damped-Newton **shoot** to close it.

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

**ψ ≡ 0 is silently load-bearing in three places at once**, which is why the generator asserts it
rather than trusting it: it makes DiffAero's ``RateController`` frame bug (``controller.py:93``,
``R_i2b @ w``) an exact no-op (identity for a rotation about the same axis the rate is on); it is
what keeps ω *exactly* constant through the coast (no gyroscopic term); and it keeps the heading
construction non-degenerate. A future cinematic yaw sweep would break all three, and only the
first would fail loudly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from neural_whoop.reference import flatness as fl
from neural_whoop.reference.limits import (
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

#: Caption labels for the numeric ``scene.phase`` channel, index == code. Same mechanism
#: ``scripts/hero_takeoff_flip_land.py`` uses, so ``web/capture/capture.js`` picks these up as
#: on-screen captions with no renderer change.
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
    """What the author chooses. Everything else in the maneuver is solved or derived."""

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


def assert_planar(samples: Samples, spec: FlipSpec, *, tol: float = 1e-9) -> dict[str, float]:
    """Assert the maneuver is a pure rotation about its own axis — no yaw, no off-axis rate.

    Measured on the **quaternion**, not on euler yaw. A pitch flip passes through 180° of pitch,
    where the ZYX yaw ``atan2(R₁₀, R₀₀)`` reads exactly π even though the airframe never yawed —
    the same gimbal artifact that makes ``rpy`` useless for charting a flip. A pure rotation about
    body axis ``k`` from identity has ``q_j = 0`` for the other two vector components, which is
    exact and axis-agnostic.

    This matters because ψ ≡ 0 is silently load-bearing in three places at once (module
    docstring), and only one of the three would fail loudly on its own. Returns the measured
    maxima so they are published rather than merely checked.
    """
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
            f"heading drifted and DiffAero's RateController frame bug (controller.py:93) stops "
            f"being a no-op."
        )
    return {"max_abs_off_axis_quat": max_off_q, "max_abs_omega_z_rps": max_wz,
            "max_abs_off_axis_rate_rps": max_off_rate}
