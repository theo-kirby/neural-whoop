"""The **U-swing**: a pendulum arc on the roll axis, authored end to end by flatness alone.

Bottom-centre hover, then a swinging arc up the left, back down through the bottom, up the right,
back — twice — ending exactly where it started. Pure ``ψ ≡ 0`` roll, so it inherits the flip's
exact planarity and its well-conditioned ``"x_c"`` heading construction.

**The finding is that there is no shoot.** The flip needed a damped-Newton boundary-value solve
because differential flatness has no solution through inversion. Here the complement holds:
author ``θ(t) = Θ·W(t)·sin(ωt)`` with a septic envelope and ``ωT = 2π·n``, and the beat starts
*and ends* at the hover point at machine precision — measured ``|p − p₀| = |v| = |a| = |j| =
0.00e+00``. Flatness authors the whole thing, including the thrust, which is the claim
``docs/REFERENCE_MANEUVER.md`` makes about powered flight taken to its conclusion.

The phase program::

    CLIMB   PathSegment          rest -> z_entry
    HOVER   PathSegment          hold
    SWING   AnalyticPathSegment  the pendulum arc — ONE segment, no internal seams
    SETTLE  PathSegment          hold, level
    LAND    PathSegment          z_entry -> rest

``SWING`` is deliberately a single segment. Splitting it per half-swing would put a seam in the
middle of a maneuver that has none, and the point of this reference is that it is smooth
*everywhere* — there is no C² break anywhere in the sequence to mask, which is why its open-loop
sim replay (0.29 cm) beats the flip's (2.15 cm) by 7.5x.

**Two things the sizing has to respect, both measured rather than assumed:**

1. **Do not drive it at resonance.** "Thrust points along the rope, so bank = θ" is a *no-drag*
   statement. This simulator's drag leans the thrust axis hard into travel: at ``L = 0.9 m``,
   ``Θ = 50°``, ``ω = √(g/L)`` demands an 89° tilt and a **15.45 rad/s** rate command against an
   11.64 ceiling. ``freq_scale = 0.8`` brings it to 69° / 7.94 rad/s. The default is 0.8 for that
   reason and :func:`SwingSpec.build` raises if a sizing leaves the envelope, so nobody can
   "simplify" the factor back out and ship a saturating reference.
2. **Peak tilt runs ~1.4× the swing amplitude**, so ``amplitude_deg`` is not the bank angle. The
   generator prints both.

The swing is **fully powered** throughout, so unlike the flip there is no zero-authority coast and
no reason for a ``--deployable`` variant. It should not get one implicitly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from neural_whoop.reference.limits import MAX_RATE_CMD_RPS, WHOOP_REST_Z_M
from neural_whoop.reference.maneuvers import ManeuverBuild, assert_within_envelope
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.paths import PendulumPath
from neural_whoop.reference.segments import (
    AnalyticPathSegment,
    PathSegment,
    RefState,
    Samples,
    Trajectory,
)

SWING_PHASE_LABELS = ["CLIMB", "HOVER", "SWING", "SETTLE", "LAND"]
SWING_PHASE = {name: i for i, name in enumerate(SWING_PHASE_LABELS)}


@dataclass(frozen=True)
class SwingSpec:
    """What the author chooses for a U-swing. Everything else is derived.

    Roll-axis only: :class:`~neural_whoop.reference.paths.PendulumPath` authors the arc in the
    world **y–z** plane, which is the plane a roll sweeps. A pitch-axis swing would be the same
    maneuver rotated 90° and would need the ``"y_c"`` heading construction; it is not offered
    rather than offered and quietly degenerate.

    Attributes:
        arc_length: Rope length ``L`` (m) — the pivot sits this far above the bottom of the arc.
        amplitude_deg: Peak swing angle ``Θ`` off vertical. **Not** the bank angle (~1.4× this).
        freq_scale: Drive frequency as a fraction of the small-angle resonance ``√(g/L)``. 1.0 is
            out of envelope for the shipped sizing — see the module docstring.
        n_swings: Number of full ``sin`` periods. ``ωT = 2π·n`` is what closes the beat exactly.
        z_entry: Altitude of the **bottom** of the arc (m) — where the drone hovers before/after.
        ramp_frac: The amplitude envelope's ramp fraction at each end. 0.25 is not cosmetic — it
            is what *spends* the rate budget. Measured on the shipped sizing: 0.20 is already
            outside the envelope, 0.25 gives 69.3° / 7.94 rad/s, 0.30 gives 58.4° / 5.88 and 0.50
            gives 55.5° / 3.48. A shorter ramp buys a more dramatic swing at the cost of the
            headroom that makes the reference a usable *target*.
    """

    name: str = field(default="swing", init=False, repr=False)
    arc_length: float = 0.9
    amplitude_deg: float = 50.0
    freq_scale: float = 0.8
    n_swings: float = 2.0
    z_entry: float = 0.9
    z_rest: float = WHOOP_REST_Z_M
    ramp_frac: float = 0.25
    rate_cmd_max: float = MAX_RATE_CMD_RPS
    t_climb: float = 1.4
    t_hover: float = 0.4
    t_settle: float = 0.6
    t_land: float = 1.8

    # --- geometry ------------------------------------------------------------------------
    @property
    def amplitude(self) -> float:
        return math.radians(self.amplitude_deg)

    @property
    def resonant_omega(self) -> float:
        return math.sqrt(9.81 / self.arc_length)

    @property
    def omega(self) -> float:
        return self.freq_scale * self.resonant_omega

    def path(self) -> PendulumPath:
        return PendulumPath(
            length=self.arc_length, amplitude=self.amplitude, omega=self.omega,
            n_swings=self.n_swings, z_bottom=self.z_entry, ramp_frac=self.ramp_frac,
        )

    @property
    def axis(self) -> str:
        return "roll"

    @property
    def axis_idx(self) -> int:
        return 0

    @property
    def lateral_idx(self) -> int:
        """The world axis the arc translates along: a roll swings ±y."""
        return 1

    @property
    def heading(self) -> str:
        return "x_c"

    # --- the ManeuverSpec protocol -------------------------------------------------------
    @property
    def phase_labels(self) -> list[str]:
        return list(SWING_PHASE_LABELS)

    @property
    def c2_break_phases(self) -> tuple[tuple[int, int], ...]:
        """**Empty, and that is the claim.** Nothing steps the motor command anywhere here."""
        return ()

    @property
    def metric_window(self) -> tuple[int, int]:
        return (SWING_PHASE["SWING"], SWING_PHASE["SETTLE"])

    @property
    def settle_phase(self) -> int:
        return SWING_PHASE["SETTLE"]

    @property
    def station(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.z_entry])

    @property
    def is_planar(self) -> bool:
        return True

    @property
    def min_thrust_normed(self) -> float:
        """Zero: the swing never authors a throttle floor because it never coasts."""
        return 0.0

    @property
    def target_phi(self) -> float:
        """The swing returns to level, so the net rotation about the roll axis is zero."""
        return 0.0

    @property
    def rotation_window(self) -> None:
        """**None**, and that is correct rather than lenient: a swing rolls both ways by
        construction, so demanding a monotone rotation would be demanding it not be a swing."""
        return None

    def build(self, model: RefModel, *, dt: float = 1e-3, verbose: bool = False) -> ManeuverBuild:
        """Assemble CLIMB → HOVER → SWING → SETTLE → LAND. No solve — flatness authors it all.

        The envelope guard runs on the assembled sequence at a coarse step: with no shoot to
        absorb a bad sizing, an out-of-envelope request must fail here with numbers attached
        rather than ship as an artifact that looks perfect and saturates.
        """
        path = self.path()
        station = self.station
        if not np.allclose(path.start_pos, station, atol=1e-12):
            raise ValueError(f"pendulum start {path.start_pos} != station {station}")
        rest = np.array([0.0, 0.0, self.z_rest])
        h = self.heading
        segs = [
            PathSegment("CLIMB", SWING_PHASE["CLIMB"], self.t_climb, end_pos=station, heading=h),
            PathSegment("HOVER", SWING_PHASE["HOVER"], self.t_hover, end_pos=station, heading=h),
            AnalyticPathSegment("SWING", SWING_PHASE["SWING"], path.duration, path=path,
                                heading=h),
            PathSegment("SETTLE", SWING_PHASE["SETTLE"], self.t_settle, end_pos=station,
                        heading=h),
            PathSegment("LAND", SWING_PHASE["LAND"], self.t_land, end_pos=rest, heading=h),
        ]
        traj = Trajectory(segments=segs, start=RefState.at_rest(rest))
        peaks = assert_within_envelope(
            traj.sample(model, max(dt, 2e-3)), rate_cmd_max=self.rate_cmd_max,
            what=(f"swing (L={self.arc_length:g} m, Θ={self.amplitude_deg:g}°, "
                  f"{self.freq_scale:g}x resonance)"),
        )
        if verbose:
            print(f"  swing: ω={self.omega:.4f} rad/s ({self.freq_scale:g}x resonance "
                  f"{self.resonant_omega:.4f}), period {path.period:.3f} s, "
                  f"{self.n_swings:g} swings -> {path.duration:.3f} s")
            print(f"         half-width ±{path.half_width:.3f} m, rise {path.rise:.3f} m, "
                  f"apex z={self.z_entry + path.rise:.3f} m")
        return ManeuverBuild(traj=traj, solution=None, derived={
            "omega_rps": self.omega,
            "resonant_omega_rps": self.resonant_omega,
            "swing_period_s": path.period,
            "swing_duration_s": path.duration,
            "half_width_m": path.half_width,
            "rise_m": path.rise,
            "apex_altitude_m": self.z_entry + path.rise,
            **peaks,
        })

    def describe(self, solution: object) -> str:
        del solution
        return (
            f"HAND-AUTHORED REFERENCE — not a policy rollout. Roll-axis U-swing: "
            f"L={self.arc_length:g} m, "
            f"Θ={self.amplitude_deg:g}°, {self.freq_scale:g}x resonance, {self.n_swings:g} swings. "
            f"Authored ENTIRELY by differential flatness — no shoot, no boundary-value problem: "
            f"the beat closes on its own start point at machine precision."
        )

    def reference_meta(self, solution: object) -> dict:
        del solution
        path = self.path()
        return {
            "maneuver": "swing", "axis": self.axis, "plane": "yz",
            "lateral_axis": self.lateral_idx,
            "arc_length_m": self.arc_length, "amplitude_deg": self.amplitude_deg,
            "freq_scale": self.freq_scale, "omega_rps": self.omega,
            "n_swings": self.n_swings, "z_entry_m": self.z_entry,
            "half_width_m": path.half_width, "rise_m": path.rise,
            "variant": "fully powered (no coast, no throttle floor)",
            "station": [float(v) for v in self.station],
            "rotation": {
                "kind": "axis", "axis": self.axis_idx, "target_turns": 0.0,
                "label": "roll angle (turns)",
                "note": "the swing returns to level, so net rotation is zero by construction",
            },
        }

    def extra_metrics(self, samples: Samples, model: RefModel) -> dict[str, float]:
        """The swing's own shape. ``peak_bank_deg`` is the number ``amplitude_deg`` is *not*."""
        from neural_whoop.reference.flatness import tilt_from_vertical

        m = (samples.phase >= self.metric_window[0]) & (samples.phase <= self.metric_window[1])
        path = self.path()
        tilt = tilt_from_vertical(samples.quat[m])
        lat = samples.pos[m, self.lateral_idx] - self.station[self.lateral_idx]
        del model
        return {
            "swing_half_width_m": float(np.max(np.abs(lat))),
            "swing_half_width_authored_m": float(path.half_width),
            "swing_rise_m": float(np.max(samples.pos[m, 2]) - self.z_entry),
            "swing_period_s": float(path.period),
            "swing_duration_s": float(path.duration),
            "n_swings": float(self.n_swings),
            "peak_bank_deg": float(np.degrees(np.max(tilt))),
            "peak_bank_over_amplitude": float(np.degrees(np.max(tilt)) / self.amplitude_deg),
            "freq_scale": float(self.freq_scale),
        }

    def caveats(self, model: RefModel) -> list[str]:
        return [
            f"PEAK TILT IS NOT THE AMPLITUDE. --amplitude-deg is the swing angle off vertical; the "
            f"bank the airframe actually holds runs about 1.4x that, because this simulator's drag "
            f"(D/m = {model.drag_per_mass:.3f} 1/s) leans the thrust axis into travel on top of "
            f"the "
            f"centripetal lean. 'Thrust points along the rope, so bank equals theta' is a NO-DRAG "
            f"statement. metrics.peak_bank_deg is the measured number.",
            f"The drive frequency is deliberately {self.freq_scale:g}x resonance, not 1.0x. At "
            f"resonance the same sizing demands ~89 deg of tilt and a 15.45 rad/s rate command "
            f"against an 11.64 ceiling — out of envelope, i.e. untrackable rather than merely "
            f"tight. SwingSpec.build() raises on any sizing that leaves the envelope.",
            "The swing is FULLY POWERED throughout: there is no motors-off coast, so "
            "checks.allocation.min_margin_torqued is comfortable everywhere and "
            "zero_authority_frac "
            "is exactly 0. It therefore does NOT need (and must not implicitly get) a --deployable "
            "variant the way the flip does.",
            "No shoot and no C2 breaks: the beat closes analytically (|p - p0| = 0.00e+00 exactly) "
            "and nothing steps the motor command anywhere, so checks.seams reports no acceleration "
            "step at any seam. That is why this maneuver's open-loop sim replay tracks an order of "
            "magnitude better than the flip's.",
        ]
