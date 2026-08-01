"""The **orbit**: a banked revolution about an invisible vertical anchor axis.

Hover on the circle, wind up to a 70°-banked orbit with the top face pointed at the axis, three
revolutions, wind back down, land. The nose points **inward at the anchor**, so the lean is a pitch
and the drone travels sideways around the ring.

This is the first maneuver in the package that is genuinely **3D**, and the one that breaks
``ψ ≡ 0``. Both facts are the point rather than a defect: the flip and the swing are planar by
construction and the whole ``ψ ≡ 0``-is-load-bearing argument has never been tested against a
maneuver that violates it. This one does, and what it exposes is real — see below.

The phase program::

    CLIMB      PathSegment          rest -> z, on the circle at phi = -pi
    HOVER      PathSegment          hold, identity heading, anchor R metres off the nose
    WIND-UP    AnalyticPathSegment  phidot ramps 0 -> Omega          }  one continuous authored
    ORBIT      AnalyticPathSegment  full rate                        }  path, carved into three
    WIND-DOWN  AnalyticPathSegment  phidot ramps Omega -> 0          }  beats for the captions
    SETTLE     PathSegment          hold, level
    LAND       PathSegment          z -> rest

The three orbit beats evaluate the **same** analytic function at different time offsets, so the
joins between them are exact to the last bit — they are labels, not seams.

===========================================================================================
THE ORBIT FOUND A REAL BUG IN THE SUBSTRATE'S RATE LOOP — NOW FIXED (2026-08-01)
===========================================================================================

``third_party/diffaero/dynamics/controller.py`` used to compute the *measured* body rate as
``R_i2b @ w``, but ``w`` is already body-frame (``quadrotor.py`` uses ``q̇ = ½q⊗[w,0]`` and
``M = τ − w×Jw``, both body-frame). The closed loop was therefore ``ω̇ = K(u − R·ω)``, whose
eigenvalues are ``−K`` and ``−K·e^{±iθ}`` with ``θ`` the attitude's rotation angle from identity —
so the **real part is ``−K·cos θ`` and the loop went unstable past 90° of attitude.**

Measured, not asserted, on this exact trajectory:

======================================== ==========================
legacy loop, open-loop, 3.85 s           **17.6 m / 180°**
patched fork (``actual_angvel_b = w``)   **1.8 cm / 0.65°**
======================================== ==========================

(It did not actually reach NaN: ``WhoopDynamics`` saturates body rate and velocity every step, so
the blow-up was *bounded* — which is worse for a reader, because the output still looked like a
finite trajectory. 17.6 m of error on a 1 m circle is the number to quote.)

The predicted onset matched the observed one — attitude crosses 90° at t = 0.78 s and divergence
appeared between 0.4 s and 1.0 s — and it did not improve as ``dt → 1 ms``, so it was instability
and not discretization. **The flip survived only because its ω lies on ``R``'s fixed axis**, the
one eigenvalue that stays ``−K`` regardless of θ. That is why every planar maneuver in this repo
tracked fine while the substrate was wrong, and why it took a genuinely 3D maneuver to expose it —
sharper than "the frame bug is a no-op here", and the reason ``ψ ≡ 0`` was load-bearing.

**The fork is now patched** and the orbit is a first-class RL target like the others. Both arms of
the control experiment — the corrected fork *and* a local re-implementation of the legacy loop —
are pinned in ``tests/test_reference_sim.py`` so the fix cannot silently regress.
``verify.check_rate_loop_stability`` still ships on every maneuver: it now answers "would the
legacy loop have tracked this", which is what a reader of any pre-fix artifact needs.

The other honest caveat is geometric: **"the top face points at the axis" has a closed-form error
and it is not zero.** Drag is tangential, so the thrust axis leans into travel by exactly
``atan((D/m)/Ω)`` — 24.1° here, and **independent of radius**. The shipped drag-sensitivity column
re-flies the identical path and measures it collapse: 24.1° at the sim's drag, **8.0°** at the
``real_est`` bracket (still *linear*, scaled to a 10 m/s terminal velocity), **0.0°** at zero drag.
A genuinely *quadratic* drag with the same 10 m/s terminal velocity would be ~2.8° at this 3.5 m/s
orbit speed — a different law, so it is quoted as a separate number rather than substituted for the
8.0° the column actually reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from neural_whoop.reference.limits import (
    MAX_BODY_RATE_YAW_RPS,
    MAX_RATE_CMD_RPS,
    WHOOP_REST_Z_M,
)
from neural_whoop.reference.maneuvers import ManeuverBuild, assert_within_envelope
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.paths import OrbitPath
from neural_whoop.reference.segments import (
    AnalyticPathSegment,
    PathSegment,
    RefState,
    Samples,
    Trajectory,
)

ORBIT_PHASE_LABELS = ["CLIMB", "HOVER", "WIND-UP", "ORBIT", "WIND-DOWN", "SETTLE", "LAND"]
ORBIT_PHASE = {name: i for i, name in enumerate(ORBIT_PHASE_LABELS)}


@dataclass(frozen=True)
class OrbitSpec:
    """What the author chooses for a banked revolution. Everything else is derived.

    Attributes:
        radius: Orbit radius (m). The anchor axis is at the origin, so the drone starts at
            ``(−radius, 0, z_entry)`` with ``ψ = 0`` — take-off and hover happen at identity
            heading with the anchor straight off the nose, and the yaw winds from there.
        omega_orbit: Steady-state orbital rate ``Ω`` (rad/s). Speed is ``radius·Ω``; bank is set
            by ``atan(RΩ²/g)`` plus the drag lean, so this is the aggression knob.
        n_revs: Number of full revolutions.
        z_entry: Orbit altitude (m).
        nose: ``"in"`` (nose at the anchor — the lean is a pitch) or ``"out"``.
        ramp_frac: Fraction of the run spent winding up / down at each end.
    """

    name: str = field(default="orbit", init=False, repr=False)
    radius: float = 0.5
    omega_orbit: float = 7.0
    n_revs: float = 3.0
    z_entry: float = 0.9
    nose: str = "in"
    z_rest: float = WHOOP_REST_Z_M
    ramp_frac: float = 0.3
    rate_cmd_max: float = MAX_RATE_CMD_RPS
    yaw_cmd_max: float = MAX_BODY_RATE_YAW_RPS
    t_climb: float = 1.4
    t_hover: float = 0.4
    t_settle: float = 0.6
    t_land: float = 1.8

    # --- geometry ------------------------------------------------------------------------
    def path(self) -> OrbitPath:
        return OrbitPath(
            radius=self.radius, omega=self.omega_orbit, n_revs=self.n_revs, z=self.z_entry,
            anchor_xy=(0.0, 0.0), nose=self.nose, ramp_frac=self.ramp_frac,
        )

    @property
    def anchor(self) -> np.ndarray:
        """The point on the anchor axis at orbit altitude — what the nose points at."""
        return np.array([0.0, 0.0, self.z_entry])

    @property
    def heading(self) -> str:
        """``"y_c"``: the lean is toward ``x_C`` (a pitch), which is exactly where the ``"x_c"``
        construction goes degenerate. Same reasoning as a pitch-axis flip."""
        return "y_c"

    @property
    def axis_idx(self) -> int:
        """Nominally pitch — the lean axis. Meaningless as a *rotation* axis: the orbit is not
        planar and :func:`~neural_whoop.reference.verify.check_quaternion` does not use it."""
        return 1

    @property
    def lateral_idx(self) -> int:
        return 0

    # --- the ManeuverSpec protocol -------------------------------------------------------
    @property
    def phase_labels(self) -> list[str]:
        return list(ORBIT_PHASE_LABELS)

    @property
    def c2_break_phases(self) -> tuple[tuple[int, int], ...]:
        """Empty: the wind-up/orbit/wind-down joins are the same analytic function, not steps."""
        return ()

    @property
    def metric_window(self) -> tuple[int, int]:
        return (ORBIT_PHASE["WIND-UP"], ORBIT_PHASE["SETTLE"])

    @property
    def settle_phase(self) -> int:
        return ORBIT_PHASE["SETTLE"]

    @property
    def station(self) -> np.ndarray:
        return self.path().start_pos

    @property
    def is_planar(self) -> bool:
        return False

    @property
    def min_thrust_normed(self) -> float:
        return 0.0

    def build(self, model: RefModel, *, dt: float = 1e-3, verbose: bool = False) -> ManeuverBuild:
        """Assemble CLIMB → HOVER → WIND-UP → ORBIT → WIND-DOWN → SETTLE → LAND. No solve."""
        path = self.path()
        station = self.station
        rest = np.array([station[0], station[1], self.z_rest])
        h = self.heading
        T, tau = path.duration, path.envelope.ramp_s
        segs = [
            PathSegment("CLIMB", ORBIT_PHASE["CLIMB"], self.t_climb, end_pos=station, heading=h),
            PathSegment("HOVER", ORBIT_PHASE["HOVER"], self.t_hover, end_pos=station, heading=h),
            AnalyticPathSegment("WIND-UP", ORBIT_PHASE["WIND-UP"], tau, path=path,
                                psi_fn=path.psi, heading=h, t_offset=0.0),
            AnalyticPathSegment("ORBIT", ORBIT_PHASE["ORBIT"], T - 2.0 * tau, path=path,
                                psi_fn=path.psi, heading=h, t_offset=tau),
            AnalyticPathSegment("WIND-DOWN", ORBIT_PHASE["WIND-DOWN"], tau, path=path,
                                psi_fn=path.psi, heading=h, t_offset=T - tau),
            PathSegment("SETTLE", ORBIT_PHASE["SETTLE"], self.t_settle, end_pos=station,
                        heading=h),
            PathSegment("LAND", ORBIT_PHASE["LAND"], self.t_land, end_pos=rest, heading=h),
        ]
        traj = Trajectory(segments=segs, start=RefState.at_rest(rest))
        peaks = assert_within_envelope(
            traj.sample(model, max(dt, 2e-3)), rate_cmd_max=self.rate_cmd_max,
            yaw_cmd_max=self.yaw_cmd_max,
            what=f"orbit (R={self.radius:g} m, Ω={self.omega_orbit:g} rad/s, nose {self.nose})",
        )
        err = math.degrees(path.axis_pointing_error_rad(model.drag_per_mass))
        if verbose:
            print(f"  orbit: R={self.radius:g} m, Ω={self.omega_orbit:g} rad/s -> "
                  f"{path.speed:.2f} m/s, rev {path.rev_period:.3f} s, {self.n_revs:g} revs "
                  f"-> {T:.3f} s")
            print(f"         predicted axis-pointing error atan((D/m)/Ω) = {err:.2f}° "
                  f"(radius-independent — it is this sim's drag, not the maneuver)")
        return ManeuverBuild(traj=traj, solution=None, derived={
            "orbit_duration_s": T,
            "rev_period_s": path.rev_period,
            "speed_mps": path.speed,
            "windup_s": tau,
            "predicted_axis_pointing_error_deg": err,
            **peaks,
        })

    def describe(self, solution: object) -> str:
        del solution
        return (
            f"HAND-AUTHORED REFERENCE — not a policy rollout. Banked revolution: "
            f"R={self.radius:g} m, "
            f"Ω={self.omega_orbit:g} rad/s, {self.n_revs:g} revs, nose {self.nose} at a vertical "
            f"anchor axis. Authored by differential flatness with a winding psi — the first "
            f"maneuver in this package that is genuinely 3D and breaks psi == 0, and the one that "
            f"exposed the rate-loop frame bug fixed in controller.py on 2026-08-01; see checks."
            f"rate_loop_stability."
        )

    def reference_meta(self, solution: object) -> dict:
        del solution
        path = self.path()
        return {
            "maneuver": "orbit", "plane": "xy", "lateral_axis": self.lateral_idx,
            "radius_m": self.radius, "omega_orbit_rps": self.omega_orbit,
            "n_revs": self.n_revs, "nose": self.nose, "z_entry_m": self.z_entry,
            "speed_mps": path.speed, "rev_period_s": path.rev_period,
            "anchor": [float(v) for v in self.anchor],
            "station": [float(v) for v in self.station],
            "variant": "fully powered (no coast, no throttle floor)",
            "rotation": {
                "kind": "heading", "axis": 2, "target_turns": float(self.n_revs),
                "label": "heading (turns)",
                "note": ("measured as the unwrapped azimuth of body +x, NOT euler yaw: at 70 deg "
                         "of bank the ZYX yaw is a gimbal artifact"),
            },
        }

    def extra_metrics(self, samples: Samples, model: RefModel) -> dict[str, float]:
        """The orbit's own shape, including the axis-pointing error against its closed form."""
        from neural_whoop.reference.flatness import (
            heading_azimuth,
            tilt_from_vertical,
        )

        path = self.path()
        m = (samples.phase >= self.metric_window[0]) & (samples.phase <= self.metric_window[1])
        full = samples.phase == ORBIT_PHASE["ORBIT"]
        pos = samples.pos[m]
        r = np.linalg.norm(pos[:, :2] - self.anchor[:2], axis=-1)
        tilt = tilt_from_vertical(samples.quat[m])
        az = heading_azimuth(samples.quat)
        err = axis_pointing_error(samples.quat[full], samples.pos[full], self.anchor)
        predicted = math.degrees(path.axis_pointing_error_rad(model.drag_per_mass))
        return {
            "orbit_radius_m": float(np.max(r)),
            "orbit_radius_authored_m": float(self.radius),
            "orbit_speed_mps": float(np.max(np.linalg.norm(samples.vel[m], axis=-1))),
            "revolutions": float((az[-1] - az[0]) / (2.0 * np.pi)),
            "rev_period_s": float(path.rev_period),
            "peak_bank_deg": float(np.degrees(np.max(tilt))),
            "axis_pointing_error_deg": float(np.degrees(np.median(err))),
            "axis_pointing_error_max_deg": float(np.degrees(np.max(err))),
            "axis_pointing_error_predicted_deg": predicted,
            "orbit_duration_s": float(path.duration),
        }

    def caveats(self, model: RefModel) -> list[str]:
        path = self.path()
        err = math.degrees(path.axis_pointing_error_rad(model.drag_per_mass))
        return [
            "THIS MANEUVER EXPOSED A REAL BUG IN THE SUBSTRATE, FIXED 2026-08-01. controller.py "
            "used to compute the measured body rate as R_i2b @ w while w is ALREADY body-frame, so "
            "the closed loop was wdot = K(u - R w), whose eigenvalues are -K and -K*exp(+-i*theta) "
            "— real part -K*cos(theta), unstable past 90 degrees of attitude. Measured on this "
            "exact trajectory over its 3.85 s: 17.6 m of position error under the legacy loop "
            "(WhoopDynamics's state clamps bound the blow-up instead of letting it reach NaN, so "
            "the output still LOOKED like a finite trajectory), versus 1.8 cm / 0.65 deg on the "
            "patched fork. It did not improve as dt -> 1 ms, so it was instability, not "
            "discretization. The fork now reads actual_angvel_b = w and this maneuver is a "
            "first-class RL target; artifacts generated BEFORE that date were flown on the "
            "divergent loop and should be read accordingly. See checks.rate_loop_stability.",
            f"'The top face points at the anchor axis' has a closed-form error and it is NOT zero: "
            f"drag is tangential, so the thrust axis leans into travel by exactly "
            f"atan((D/m)/Omega) = {err:.1f} deg here — INDEPENDENT OF RADIUS (the centripetal "
            f"demand is R*Omega^2 and "
            f"the drag is (D/m)*R*Omega, so R cancels). It is this simulator's drag, not the "
            f"maneuver. Two brackets, and they are different laws: the shipped drag_sensitivity "
            f"'real_est' row is still LINEAR drag scaled to a 10 m/s terminal velocity and gives "
            f"8.0 deg; a genuinely QUADRATIC drag with the same 10 m/s terminal velocity has an "
            f"effective (D/m) of only g*v/v_term^2 = 0.34 1/s at this 3.5 m/s orbit speed, i.e. "
            f"~2.8 deg. Zero drag gives exactly 0.0 deg. Do not quote one for the other.",
            "The heading construction is at its worst conditioning here (~0.37 of 1.0): the "
            "FORWARD flatness map is unaffected — it only multiplies by that quantity — but "
            "state_to_flat divides by it, so any round-trip test on this maneuver must filter on "
            "heading_conditioning rather than assume psi-dot always comes back.",
            "The orbit is FULLY POWERED throughout: no motors-off coast, so zero_authority_frac is "
            "exactly 0 and it does NOT need a --deployable variant.",
        ]


# =============================================================================================
# The axis-pointing measurement
# =============================================================================================
def axis_pointing_error(quat: np.ndarray, pos: np.ndarray, anchor: np.ndarray) -> np.ndarray:
    """Angle (rad) between the horizontal lean of body **+z** and the direction to the anchor.

    "The top face points at the axis" means the thrust axis, projected onto the horizontal plane,
    should point from the drone toward the anchor. This measures exactly that, per frame, so the
    24° the artifact reports is a *measurement* checked against the closed-form prediction
    ``atan((D/m)/Ω)`` rather than a claim.

    Args:
        quat: ``(N, 4)`` xyzw.
        pos: ``(N, 3)`` world positions.
        anchor: The anchor point (only its horizontal position is used).

    Returns:
        ``(N,)`` angles in radians. ``NaN`` on any frame where the airframe is level (no
        horizontal lean at all, so "which way does the top face point" has no answer).
    """
    from neural_whoop.reference.flatness import quat_xyzw_to_rotmat

    z_b = quat_xyzw_to_rotmat(np.asarray(quat, dtype=np.float64))[:, :, 2]
    lean = z_b[:, :2]
    to_axis = np.asarray(anchor, dtype=np.float64)[:2] - np.asarray(pos, dtype=np.float64)[:, :2]
    nl = np.linalg.norm(lean, axis=-1)
    na = np.linalg.norm(to_axis, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = np.sum(lean * to_axis, axis=-1) / (nl * na)
    return np.arccos(np.clip(cos, -1.0, 1.0))
