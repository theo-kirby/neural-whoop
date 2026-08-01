"""Verification for the hand-authored reference maneuver — **pure numpy, no simulator**.

The whole value of a reference trajectory is that its numbers are true, so every claim the
:mod:`neural_whoop.reference` package makes has a test that produces a number here. Nothing in
this file imports torch or DiffAero; the open-loop sim replay (the one check that genuinely needs
the simulator) lives in ``tests/test_reference_sim.py``.

The solved flip is built **once** per variant and shared, because the shoot is a real Newton
iteration and not something to pay for in every test; the swing and the orbit are shared for the
same reason even though neither needs a solve.

Three maneuvers, three different things worth asserting, and the differences are the interesting
part: the flip's boundary conditions are *solved* and close to ~1e-8, the swing's are *authored*
and close to exactly 0.0, and the orbit's are authored too but the maneuver is not flyable in this
simulator at all — see ``test_rate_loop_stability_discriminates_by_the_fixed_axis``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from neural_whoop.reference import flatness as fl
from neural_whoop.reference import paths, verify
from neural_whoop.reference.emit import decimate, maneuver_mask, reference_metrics
from neural_whoop.reference.imu import specific_force_body
from neural_whoop.reference.limits import (
    DEPLOY_MIN_THRUST_NORMED,
    MAX_BODY_RATE_RP_RPS,
    MAX_BODY_RATE_YAW_RPS,
    MAX_RATE_CMD_RPS,
    MAX_THRUST_NORMED,
    RATE_CMD_HEADROOM,
    WHOOP_REST_Z_M,
    act_v2_from_diffaero,
)
from neural_whoop.reference.maneuvers import (
    PHASE,
    FlipSpec,
    ManeuverSpec,
    RateEnvelopeError,
    assert_planar,
    build_sequence,
    hover_entry_state,
    solve_flip,
)
from neural_whoop.reference.maneuvers_orbit import OrbitSpec
from neural_whoop.reference.maneuvers_swing import SwingSpec
from neural_whoop.reference.model import AnisotropicDragError, RefModel
from neural_whoop.reference.segments import PathSegment, RefState, Trajectory

DT_FINE = 1e-3
DT_REPLAY = 0.02


# =============================================================================================
# The mirrored constants must not drift from the real ones
# =============================================================================================
def test_ref_model_matches_whoop_params():
    """``RefModel`` mirrors ``WhoopParams`` defaults; this fails if someone retunes the airframe.

    The reference is derived against this model and embeds it verbatim in ``reference.json``, so a
    silent drift would leave an artifact claiming to describe an airframe that no longer exists.
    """
    torch = pytest.importorskip("torch")  # noqa: F841 - WhoopParams pulls torch
    from neural_whoop.dynamics.whoop import WhoopParams

    wp, rm = WhoopParams(), RefModel()
    assert wp.mass[0] == rm.mass
    assert wp.arm_l[0] == rm.arm_l
    assert wp.c_tau[0] == rm.c_tau
    assert wp.J_xy[0] == rm.J_xy
    assert wp.J_z[0] == rm.J_z
    assert wp.D_xy[0] == rm.D_xy
    assert wp.D_z[0] == rm.D_z
    assert wp.g == rm.g
    assert wp.K_angvel == rm.K_angvel


def test_limits_mirror_the_contract():
    """The pure ``limits`` mirror must equal ``contract.ActionLimits`` (which pulls torch)."""
    pytest.importorskip("torch")
    from neural_whoop.contract import WHOOP_REST_Z_M as REST_Z
    from neural_whoop.contract import ActionLimits

    lim = ActionLimits()
    assert lim.max_thrust_normed == MAX_THRUST_NORMED
    assert lim.max_body_rate_rp_rps == MAX_BODY_RATE_RP_RPS
    assert lim.max_body_rate_yaw_rps == MAX_BODY_RATE_YAW_RPS
    assert REST_Z == WHOOP_REST_Z_M
    # The deploy floor the acro config / pilot actually clamp at.
    assert DEPLOY_MIN_THRUST_NORMED == 0.25


def test_act_v2_inversion_round_trips():
    """``act_v2_from_diffaero`` must invert ``action_to_diffaero`` exactly."""
    torch = pytest.importorskip("torch")
    from neural_whoop.contract import ActionLimits, action_to_diffaero

    lim = ActionLimits()
    rng = np.random.default_rng(0)
    a = rng.uniform(-1, 1, (64, 4))
    ctbr = action_to_diffaero(torch.tensor(a), lim).numpy()
    back = np.array([act_v2_from_diffaero(c[0], tuple(c[1:])) for c in ctbr])
    assert np.abs(back - a).max() < 1e-6


# =============================================================================================
# 1. Flatness round trip — what catches a sign error in G_vec or the drag term
# =============================================================================================
@pytest.mark.parametrize("heading", ["x_c", "y_c"])
def test_flatness_round_trip(heading):
    """10k random ``(a, v, ψ)``: ``state_to_flat(flat_to_state(·))`` recovers to 1e-12.

    This is THE test for the two places this package would be quietly wrong — the sign of
    ``G_vec`` and the sign of the drag term. Both appear in ``specific_force``, and either flipped
    would break the round trip immediately.
    """
    m = RefModel()
    rng = np.random.default_rng(11)
    n = 10_000
    acc = rng.normal(0, 4.0, (n, 3))
    vel = rng.normal(0, 2.0, (n, 3))
    jerk = rng.normal(0, 10.0, (n, 3))
    psi = rng.uniform(-math.pi, math.pi, n)
    psidot = rng.normal(0, 1.0, n)

    nt = np.linalg.norm(fl.specific_force(acc, vel, m), axis=-1) / m.g
    keep = nt > 0.5                                  # stay clear of the singular guard
    acc, vel, jerk, psi, psidot = (x[keep] for x in (acc, vel, jerk, psi, psidot))
    assert keep.sum() > 8000

    R, omega, nt = fl.flat_to_state(vel, acc, jerk, psi, psidot, m, heading=heading)
    f = fl.specific_force(acc, vel, m)
    fdot = jerk + m.drag_per_mass * acc
    ntd = np.sum(f * fdot, -1) / (m.g * np.linalg.norm(f, axis=-1))

    acc2, jerk2, psi2, psidot2 = fl.state_to_flat(R, nt, ntd, omega, vel, m, heading=heading)
    assert np.abs(acc2 - acc).max() < 1e-12
    assert np.abs(jerk2 - jerk).max() < 1e-11
    dpsi = np.abs((psi2 - psi + math.pi) % (2 * math.pi) - math.pi)
    assert dpsi.max() < 1e-12

    # psi-dot is only recoverable where the heading construction is observable; that is a real
    # property of the map (the attitude becomes independent of psi at 90 deg of tilt toward the
    # reference axis), not a numerical shortcoming — so filter on it rather than assume.
    cond = fl.heading_conditioning(R, psi, heading=heading)
    obs = cond > 0.3
    assert obs.sum() > 6000
    assert np.abs(psidot2 - psidot)[obs].max() < 1e-9


def test_flatness_round_trip_through_inversion():
    """The heading must come back correctly when the drone is UPSIDE DOWN.

    The obvious recovery (``x_C = y_B × ê_z``) is off by exactly π below the horizon, which would
    make the inverse map silently wrong on precisely the half of a flip that matters.
    """
    m = RefModel()
    # A specific force pointing DOWN in world -> the airframe is inverted.
    psi = 0.7
    f_down = np.array([[0.0, 0.0, -2.0 * m.g]])
    R = fl.attitude_from_f(f_down, psi)
    assert R[0, 2, 2] < 0                                   # body +z points down: inverted
    acc = R[..., 2] * 2.0 * m.g - m.g * np.array([0, 0, 1.0])
    _, _, psi2, _ = fl.state_to_flat(
        R, np.array([2.0]), np.array([0.0]), np.zeros((1, 3)), np.zeros((1, 3)), m
    )
    assert float(psi2[0]) == pytest.approx(psi, abs=1e-12)
    del acc


# =============================================================================================
# 2. Hover fixed point — exact, not approximate
# =============================================================================================
def test_hover_is_an_exact_fixed_point():
    m = RefModel()
    R, omega, nt = fl.flat_to_state(np.zeros(3), np.zeros(3), np.zeros(3), 0.0, 0.0, m)
    assert float(nt) == 1.0                                  # exactly, not approximately
    assert np.abs(omega).max() == 0.0
    assert np.abs(R - np.eye(3)).max() == 0.0
    imu = specific_force_body(R, np.zeros(3), m)
    assert imu == pytest.approx([0.0, 0.0, m.g], abs=0.0)    # +1 g on body +z


# =============================================================================================
# 3. Singularity guards raise rather than returning NaN
# =============================================================================================
def test_free_fall_is_singular():
    m = RefModel()
    with pytest.raises(fl.SingularFlatnessError):
        fl.flat_to_state(np.zeros(3), np.array([0.0, 0.0, -m.g]), np.zeros(3), 0.0, 0.0, m)


def test_terminal_velocity_descent_is_singular():
    """The non-obvious one: steady descent at terminal velocity is the SAME statement as free fall.

    Acceleration is zero, so the naive reading is "this is just a hover, thrust ~1". It is not:
    drag is holding the drone up, and the airframe needs no thrust at all.
    """
    m = RefModel()
    v_term = -m.terminal_velocity_mps
    with pytest.raises(fl.SingularFlatnessError):
        fl.flat_to_state(np.array([0.0, 0.0, v_term]), np.zeros(3), np.zeros(3), 0.0, 0.0, m)


def test_anisotropic_drag_is_refused():
    """The closed-form map needs isotropic drag; anisotropy must raise, not silently mislead."""
    with pytest.raises(AnisotropicDragError):
        RefModel(D_xy=0.10, D_z=0.14)


def test_heading_construction_singularity_raises():
    """90° of tilt toward the heading reference is degenerate for that construction."""
    m = RefModel()
    f = np.array([[2.0 * m.g, 0.0, 0.0]])                     # thrust axis along world +x
    with pytest.raises(fl.SingularFlatnessError):
        fl.attitude_from_f(f, 0.0, heading="x_c")             # x_C is +x -> parallel
    R = fl.attitude_from_f(f, 0.0, heading="y_c")             # y_C is +y -> fine
    assert np.isfinite(R).all()


# =============================================================================================
# Septic path segments
# =============================================================================================
def test_septic_matches_boundary_conditions_through_jerk():
    """A quintic matches only to acceleration; the flatness map eats jerk, so we need a septic."""
    m = RefModel()
    start = RefState(
        t=0.0, pos=np.array([0.0, 0.0, 1.0]), vel=np.array([0.1, -0.2, 0.3]),
        acc=np.array([0.4, 0.0, -0.5]), jerk=np.array([1.0, -2.0, 0.5]),
        quat=np.array([0.0, 0.0, 0.0, 1.0]), omega=np.zeros(3), normed_thrust=1.0,
    )
    seg = PathSegment("T", 0, 1.1, end_pos=np.array([0.5, 0.6, 1.4]),
                      end_vel=np.array([0.0, 0.1, 0.0]))
    row = seg.sample(start, m, np.linspace(0.0, 1.1, 1101))
    assert row["pos"][0] == pytest.approx(start.pos, abs=1e-12)
    assert row["vel"][0] == pytest.approx(start.vel, abs=1e-12)
    assert row["acc"][0] == pytest.approx(start.acc, abs=1e-11)
    assert row["jerk"][0] == pytest.approx(start.jerk, abs=1e-9)
    assert row["pos"][-1] == pytest.approx([0.5, 0.6, 1.4], abs=1e-11)
    assert row["vel"][-1] == pytest.approx([0.0, 0.1, 0.0], abs=1e-10)


# =============================================================================================
# The solved flip (built once per variant)
# =============================================================================================
def _build(coast_thrust: float):
    model = RefModel()
    spec = FlipSpec(axis="roll", omega_peak=9.0, z_entry=1.2, coast_thrust=coast_thrust)
    sol = solve_flip(spec, model, hover_entry_state(spec), dt=DT_FINE, try_stage2=False)
    fine = build_sequence(spec, model, sol).sample(model, DT_FINE)
    return model, spec, sol, fine


@pytest.fixture(scope="module")
def ref_motors_off():
    return _build(0.0)


@pytest.fixture(scope="module")
def ref_deployable():
    return _build(DEPLOY_MIN_THRUST_NORMED)


def test_shoot_converges_and_closes_its_boundary_conditions(ref_motors_off):
    """Stage 1 must actually land on (φ = 2π, z = z_entry, vz = 0) — not merely stop iterating."""
    model, spec, sol, fine = ref_motors_off
    assert sol.converged
    assert sol.residual_norm < 1e-5
    assert not sol.bounds_hit, f"a solved parameter is pinned at a bound: {sol.bounds_hit}"
    for name, val in sol.residuals.items():
        assert abs(val) < 1e-5, f"residual {name} = {val}"


def test_rotation_crosses_the_target_exactly_once(ref_motors_off):
    """ω ≥ 0 through the flip, so φ is monotone there and reaches 2π once — no two-turn root.

    Monotonicity is checked over POP..CATCH, not the whole flight: the recover deliberately leans
    to fly the residual lateral offset back, which wobbles the roll angle a couple of degrees
    around 2π. That is the maneuver working, not a defect.
    """
    model, spec, sol, fine = ref_motors_off
    check = verify.check_quaternion(fine, spec)
    assert check["monotone_in_window"]
    assert check["min_dphi_in_window"] >= -1e-12
    assert check["crossings_of_target"] == 1
    assert abs(check["phi_end_error_rad"]) < 1e-6
    assert check["max_norm_error"] < 1e-9
    assert check["sign_flips"] == 0
    # The recover leans ~8.5° to translate 0.18 m back to the station; the bound is here to catch
    # "it tumbled after the flip", not to pin the lean.
    assert check["max_post_window_wobble_rad"] < math.radians(15.0)


def test_planarity_is_asserted_not_assumed(ref_motors_off):
    """ψ ≡ 0 and ω_z ≡ 0 — load-bearing in three places, only one of which fails loudly."""
    model, spec, sol, fine = ref_motors_off
    p = assert_planar(fine, spec)
    assert p["max_abs_omega_z_rps"] == 0.0
    assert p["max_abs_off_axis_rate_rps"] == 0.0
    assert p["max_abs_off_axis_quat"] < 1e-12


def test_within_limits_with_margin(ref_motors_off):
    """Inside the act-v2 envelope with real headroom, so a saturating regression FAILS this."""
    model, spec, sol, fine = ref_motors_off
    lim = verify.check_limits(fine)
    assert lim["within_envelope"]
    assert lim["max_normed_thrust"] <= MAX_THRUST_NORMED
    assert lim["max_abs_rate_cmd_rp_rps"] <= MAX_RATE_CMD_RPS + 1e-9
    assert lim["rate_headroom_frac"] >= RATE_CMD_HEADROOM - 1e-9
    assert lim["max_abs_rate_cmd_yaw_rps"] == 0.0


def test_control_allocation(ref_motors_off, ref_deployable):
    """Four motors must be able to make the commanded torque at the commanded collective.

    The simulator enforces nothing here (``postprocess`` is never called, so torque is unbounded),
    which is exactly why this is worth checking. The structural finding: through the motors-off
    coast the margin is EXACTLY zero — zero thrust demanding zero torque — i.e. no rate authority
    at all, while the deployable variant's 0.25 floor keeps authority alive throughout.
    """
    for _, _, _, fine in (ref_motors_off, ref_deployable):
        a = verify.check_allocation(fine, RefModel())
        assert a["feasible"]
        assert a["min_margin_torqued"] > 0.0

    off = verify.check_allocation(ref_motors_off[3], RefModel())
    dep = verify.check_allocation(ref_deployable[3], RefModel())
    assert off["min_margin"] == 0.0                    # exactly, during the coast
    assert off["zero_authority_frac"] > 0.05           # a real chunk of the flight
    assert dep["min_margin"] == pytest.approx(DEPLOY_MIN_THRUST_NORMED, abs=1e-9)
    assert dep["zero_authority_frac"] == 0.0


def test_dynamics_residual_falls_second_order(ref_motors_off):
    """The emitted arrays satisfy DiffAero's ODE, and the residual is dominated by SAMPLING.

    Run at both 50 Hz and 1 kHz: a second-order central difference must improve by ~(20)² = 400x.
    If it does not, the residual is a modeling error in the flatness map rather than a
    discretization artifact — which is the whole reason this is measured at two rates.
    """
    model, spec, sol, fine = ref_motors_off
    replay = decimate(fine, DT_REPLAY)
    rf = verify.dynamics_residual(fine, model, mask=verify.c2_break_indices(fine))
    rr = verify.dynamics_residual(replay, model, mask=verify.c2_break_indices(replay))
    # Absolute floors are loose on purpose — with 240 m/s³ of jerk through the roll-in, the h²·j/6
    # truncation of a 1 ms central difference is ~4e-5 all by itself. The RATIO is the diagnostic.
    assert rf["pos_max"] < 1e-3
    assert rf["quat_max"] < 1e-2
    assert rf["vel_rms"] < 1e-3
    assert rf["masked_frac"] < 0.01          # 14 frames out of ~6000
    for name in ("pos", "vel", "quat"):
        ratio = rr[f"{name}_rms"] / rf[f"{name}_rms"]
        assert 150.0 < ratio < 900.0, (
            f"{name} residual improved {ratio:.0f}x between 1 kHz and 50 Hz, expected ~400x for a "
            f"second-order difference. Far below that means the residual is a modeling error in "
            f"the flatness map, not a sampling artifact."
        )


def test_two_variants_are_genuinely_different_solves(ref_motors_off, ref_deployable):
    """A 0.25 floor on an inverted drone is downward thrust, so the shoot returns another orbit."""
    _, spec_a, sol_a, fine_a = ref_motors_off
    _, spec_b, sol_b, fine_b = ref_deployable
    assert sol_b.params.t_pop > sol_a.params.t_pop + 1e-3
    ma = reference_metrics(fine_a, spec_a, RefModel())
    mb = reference_metrics(fine_b, spec_b, RefModel())
    assert mb["peak_climb"] > ma["peak_climb"] + 0.02
    assert mb["max_lateral_drift"] > ma["max_lateral_drift"] + 0.02
    assert fine_a.normed_thrust.min() == 0.0
    assert fine_b.normed_thrust.min() == pytest.approx(DEPLOY_MIN_THRUST_NORMED)


def test_metrics_are_sane_and_named_like_acro_flip(ref_motors_off):
    """The four names ``AcroFlipTask.metrics()`` reports must exist and be physically sensible."""
    model, spec, sol, fine = ref_motors_off
    m = reference_metrics(fine, spec, model)
    for key in ("max_lateral_drift", "peak_climb", "altitude_loss", "settle_pos_error"):
        assert key in m
    assert m["rotation_turns"] == pytest.approx(1.0, abs=1e-6)
    assert m["settle_pos_error"] < 1e-6          # RECOVER puts it back on the station exactly
    assert m["altitude_loss"] < 0.01             # the flip never dips below its entry altitude
    assert 0.3 < m["peak_climb"] < 1.2
    assert 0.0 < m["max_lateral_drift"] < 0.6
    assert 0.6 < m["flip_duration_s"] < 1.6
    # The coast IMU is a V, not a flat null: fast at both ends of the arc, ~0 at the apex.
    assert m["imu_coast_min_g"] < 0.3
    assert m["imu_coast_max_g"] > 0.7


def test_sequence_starts_at_liftoff_and_ends_at_touchdown(ref_motors_off):
    """No 'props spooling on the ground' beat: at rest a PathSegment yields thrust 1.0, which
    lifts off (there is no contact model). Start at liftoff, end at touchdown."""
    model, spec, sol, fine = ref_motors_off
    assert fine.pos[0] == pytest.approx([0.0, 0.0, WHOOP_REST_Z_M], abs=1e-9)
    assert fine.pos[-1] == pytest.approx([0.0, 0.0, WHOOP_REST_Z_M], abs=1e-6)
    assert np.abs(fine.vel[0]).max() < 1e-9
    assert np.abs(fine.vel[-1]).max() < 1e-6
    assert fine.normed_thrust[0] == pytest.approx(1.0, abs=1e-12)
    assert fine.pos[:, 2].min() >= WHOOP_REST_Z_M - 1e-9      # never sinks through the floor


def test_coast_body_rate_is_exactly_constant(ref_motors_off):
    """DiffAero applies drag only to LINEAR velocity and both gyroscopic terms vanish on a
    symmetric-inertia axis with ω_z = 0, so this is machine-exact rather than approximate.

    A real whoop would shed 5-15% of its roll rate to blade flapping over a 0.6 s coast. That is
    not modeled, and the artifact says so.
    """
    model, spec, sol, fine = ref_motors_off
    coast = fine.phase == PHASE["COAST"]
    assert coast.sum() > 100
    w = fine.omega[coast, spec.axis_idx]
    assert np.ptp(w) == 0.0
    assert np.abs(fine.omega_dot[coast]).max() == 0.0        # zero COMMANDED torque
    assert np.abs(fine.rate_cmd[coast, spec.axis_idx] - w).max() < 1e-12


def test_exactly_two_c2_breaks_and_they_are_the_motor_cuts(ref_motors_off):
    """Acceleration steps at exactly two seams — the thrust cut and the catch — and nowhere else.

    The honest claim this package makes is "C¹ position with two intentional C² breaks". This is
    that claim as a test, measured seam by seam rather than asserted in a docstring. Every other
    seam must be smooth in acceleration; the rate COMMAND is allowed to step (it does, at
    POP->ROLL-IN), because a step in the motor command *is* the maneuver.
    """
    model, spec, sol, fine = ref_motors_off
    seams = verify.classify_breaks(fine, spec)
    big = [s for s in seams if abs(s["d_acc_mps2"]) > 1.0]
    assert len(big) == 2, [(s["from_phase"], s["to_phase"], s["d_acc_mps2"]) for s in seams]
    assert (big[0]["from_phase"], big[0]["to_phase"]) == ("ROLL-IN", "COAST")
    assert (big[1]["from_phase"], big[1]["to_phase"]) == ("COAST", "CATCH")
    assert all(s["is_c2_break"] for s in big)
    assert not any(s["is_c2_break"] for s in seams if s not in big)
    # The rate command steps at the roll-in; the rate itself never does.
    rollin = next(s for s in seams if s["to_phase"] == "ROLL-IN")
    assert rollin["d_rate_cmd_rps"] > 5.0
    assert rollin["d_omega_rps"] < 1e-9
    # Position and velocity stay continuous across both breaks even though acceleration does not.
    assert np.abs(np.diff(fine.vel, axis=0)).max() < 0.05
    assert np.abs(np.diff(fine.pos, axis=0)).max() < 0.01


def test_decimation_preserves_the_endpoints(ref_motors_off):
    model, spec, sol, fine = ref_motors_off
    replay = decimate(fine, DT_REPLAY)
    assert replay.t[0] == fine.t[0]
    assert replay.t[-1] == fine.t[-1]
    assert np.all(np.diff(replay.t) > 0)
    assert abs(np.median(np.diff(replay.t)) - DT_REPLAY) < 1e-3
    assert set(np.unique(replay.phase)) == set(np.unique(fine.phase))


def test_maneuver_window_excludes_the_stagecraft(ref_motors_off):
    model, spec, sol, fine = ref_motors_off
    m = maneuver_mask(fine, spec)
    assert PHASE["CLIMB"] not in set(fine.phase[m])
    assert PHASE["LAND"] not in set(fine.phase[m])
    assert PHASE["COAST"] in set(fine.phase[m])


def test_pitch_axis_uses_the_other_heading_construction():
    """A pitch flip tilts toward ``x_C``, so it needs the ``y_c`` construction to stay regular."""
    model = RefModel()
    spec = FlipSpec(axis="pitch", omega_peak=9.0)
    assert spec.heading == "y_c"
    sol = solve_flip(spec, model, hover_entry_state(spec), dt=DT_FINE, try_stage2=False)
    fine = build_sequence(spec, model, sol).sample(model, DT_FINE)
    assert_planar(fine, spec)
    assert np.abs(fine.omega[:, 0]).max() == 0.0            # no roll rate at all
    check = verify.check_quaternion(fine, spec)
    assert check["crossings_of_target"] == 1
    assert check["monotone_in_window"]


def test_drag_dominates_the_shape():
    """Re-flying the identical commands at zero drag must change the maneuver a LOT.

    This is the sensitivity column as a test: if the shape were robust to the drag coefficient the
    "these numbers are artifacts of this simulator" caveat would be overcautious. It is not.
    """
    from neural_whoop.reference.emit import drag_sensitivity

    model = RefModel()
    spec = FlipSpec(axis="roll", omega_peak=9.0)
    sol = solve_flip(spec, model, hover_entry_state(spec), dt=DT_FINE, try_stage2=False)
    traj = build_sequence(spec, model, sol)
    sens = drag_sensitivity(traj, spec, model, DT_FINE)
    assert set(sens) == {"sim", "none", "real_est"}
    assert sens["none"]["peak_climb_m"] > 1.8 * sens["sim"]["peak_climb_m"]
    assert sens["none"]["max_lateral_drift_m"] > 2.0 * sens["sim"]["max_lateral_drift_m"]


def test_trajectory_requires_segments():
    with pytest.raises(ValueError):
        Trajectory(segments=[], start=RefState.at_rest(np.zeros(3))).sample(RefModel(), DT_FINE)


# =============================================================================================
# The envelope — what makes the analytic maneuvers' seams silent
# =============================================================================================
def test_septic_envelope_is_flat_through_the_third_derivative():
    """Zero value AND zero first three derivatives at both ends — that is the whole requirement.

    The flatness map turns jerk into body rate, so an envelope whose *third* derivative steps at
    the seam emits a body rate that steps, visibly, on the frame the maneuver starts. A quintic
    smoothstep (flat through the second) is not enough, which is exactly the mistake a septic
    path segment exists to avoid.
    """
    for x in (0.0, 1.0):
        assert paths.septic_smoothstep(np.array([x])) == pytest.approx(x, abs=0.0)
        assert paths.septic_smoothstep_d(np.array([x])) == pytest.approx(0.0, abs=1e-14)
        assert paths.septic_smoothstep_dd(np.array([x])) == pytest.approx(0.0, abs=1e-13)
        assert paths.septic_smoothstep_ddd(np.array([x])) == pytest.approx(0.0, abs=1e-12)
    assert paths.septic_smoothstep_int(np.array([1.0]))[0] == pytest.approx(0.5, abs=1e-15)


def test_envelope_derivatives_match_finite_differences():
    """Every analytic derivative agrees with a central difference to 1e-8.

    The envelope's derivatives are hand-written product-rule algebra; a sign slip in any of them
    would produce a reference that is smooth-looking and physically wrong, and nothing else in the
    package would notice.
    """
    env = paths.Envelope(4.0, 0.25)
    h = 1e-6
    t = np.linspace(0.05, 3.95, 400)

    def W(tt):
        return env.derivatives(tt)[0]

    def Wd(tt):
        return env.derivatives(tt)[1]

    def Wdd(tt):
        return env.derivatives(tt)[2]

    w, wd, wdd, wddd = env.derivatives(t)
    assert np.abs((W(t + h) - W(t - h)) / (2 * h) - wd).max() < 1e-8
    assert np.abs((Wd(t + h) - Wd(t - h)) / (2 * h) - wdd).max() < 1e-6
    assert np.abs((Wdd(t + h) - Wdd(t - h)) / (2 * h) - wddd).max() < 1e-4
    # ...and the closed-form integral, which is what fixes the orbit's revolution count exactly.
    assert np.abs((env.integral(t + h) - env.integral(t - h)) / (2 * h) - w).max() < 1e-8
    assert env.integral(np.array([env.duration]))[0] == pytest.approx(env.area, abs=1e-14)
    assert env.area == pytest.approx(4.0 * 0.75, abs=1e-15)


def test_envelope_is_continuous_across_its_seams():
    """No step in W or its first three derivatives at the ramp/hold joins, or at ``t = 0`` / ``T``.

    The clamp outside ``[0, T]`` is only C³-safe *because* the septic is flat there; this is that
    claim, including at the two interior joins where the ramp meets the hold.
    """
    env = paths.Envelope(4.0, 0.25)
    eps = 1e-9
    for seam in (0.0, env.ramp_s, env.duration - env.ramp_s, env.duration):
        before = np.stack(env.derivatives(np.array([seam - eps])))
        after = np.stack(env.derivatives(np.array([seam + eps])))
        assert np.abs(before - after).max() < 1e-4, f"envelope steps at t={seam}"


# =============================================================================================
# The swing: authored entirely by flatness, and it closes EXACTLY
# =============================================================================================
@pytest.fixture(scope="module")
def ref_swing():
    model = RefModel()
    spec = SwingSpec()
    build = spec.build(model, dt=DT_FINE)
    return model, spec, build, build.traj.sample(model, DT_FINE)


def test_swing_closes_exactly_with_no_shoot():
    """``|p_end − p_start| = |v| = |a| = |j| = 0`` exactly — a real assertion, not a tolerance.

    This is the complement of the flip's structural finding. Flatness cannot author a flip (through
    inversion it would demand negative thrust), so the flip needs a damped-Newton boundary-value
    solve and closes to ~1e-8. The swing needs no solve at all: ``sin`` vanishes at both ends
    because ``ωT = 2π·n``, and the envelope vanishes through its second derivative there, killing
    every ``Ẇ`` cross term. The measured residual is 0.00e+00, so the bound is exact.
    """
    spec = SwingSpec()
    path = spec.path()
    p, v, a, j = path(np.array([0.0, path.duration]))
    assert np.abs(p[-1] - p[0]).max() == 0.0
    assert np.abs(v).max() == 0.0
    assert np.abs(a).max() == 0.0
    assert np.abs(j).max() == 0.0
    assert path.start_pos == pytest.approx(spec.station, abs=0.0)
    # And it is not trivially zero everywhere — the beat really goes somewhere.
    mid = path(np.linspace(0.0, path.duration, 2001))[0]
    assert np.abs(mid[:, 1]).max() == pytest.approx(path.half_width, abs=1e-9)


def test_swing_needs_no_solution_object(ref_swing):
    """``build().solution is None`` — the honest encoding of "there was nothing to solve"."""
    _, _, build, _ = ref_swing
    assert build.solution is None
    assert build.derived["swing_duration_s"] == pytest.approx(4.7578, abs=1e-3)


def test_swing_planarity_is_exact(ref_swing):
    """``ω_z`` and the off-axis quaternion components are **exactly** 0.0, like the flip's."""
    model, spec, _, fine = ref_swing
    p = assert_planar(fine, spec)
    assert p["max_abs_omega_z_rps"] == 0.0
    assert p["max_abs_off_axis_rate_rps"] == 0.0
    assert p["max_abs_off_axis_quat"] == 0.0


def test_swing_has_no_c2_breaks_at_all(ref_swing):
    """**Nothing steps the motor command anywhere.** That is a claim, so it is measured.

    The flip has exactly two intentional acceleration steps (the motor cut and the catch). The
    swing has none — it is powered and smooth end to end — which is why its open-loop sim replay
    tracks an order of magnitude better. A regression that put a seam back would fail here.
    """
    model, spec, _, fine = ref_swing
    assert spec.c2_break_phases == ()
    seams = verify.classify_breaks(fine, spec)
    assert seams, "the sequence should have segment joins to check"
    assert not any(s["is_c2_break"] for s in seams)

    # Compared against the maneuver's OWN per-sample change rather than an absolute epsilon, which
    # is the only threshold that means anything here. `Trajectory.sample` drops the duplicated seam
    # row, so the two frames a seam compares are one dt apart and legitimately differ by jerk*dt —
    # a floor that scales with the maneuver, the sample rate and the units. A real break stands out
    # by orders of magnitude: the flip's are 37 and 26 m/s², hundreds of times its own interior
    # step, while every seam here is at most a couple of typical samples.
    def typical(x):
        """p99 of the per-sample change — the maneuver's own smooth scale. Not the max: a real
        break IS a sample, so taking the max would compare the thing to itself."""
        return float(np.percentile(np.abs(np.diff(x, axis=0)), 99.0))

    worst_acc = max(abs(s["d_acc_mps2"]) for s in seams)
    worst_cmd = max(abs(s["d_rate_cmd_rps"]) for s in seams)
    assert worst_acc < 2.0 * typical(fine.acc), (
        f"seam acceleration step {worst_acc:.3e} against a typical sample "
        f"{typical(fine.acc):.3e} m/s²"
    )
    assert worst_cmd < 2.0 * typical(fine.rate_cmd), (
        f"seam rate-command step {worst_cmd:.3e} against a typical sample "
        f"{typical(fine.rate_cmd):.3e} rad/s"
    )
    # The same measure applied to the flip does pick out its two real breaks by three orders of
    # (189x measured, against 0.002x here), so the comparison above is sensitive rather
    # than vacuously satisfied.
    flip_spec = FlipSpec()
    flip = build_sequence(flip_spec, model, solve_flip(
        flip_spec, model, hover_entry_state(flip_spec), dt=DT_FINE, try_stage2=False,
    )).sample(model, DT_FINE)
    flip_seams = verify.classify_breaks(flip, flip_spec)
    assert max(abs(s["d_acc_mps2"]) for s in flip_seams) > 100.0 * typical(flip.acc)


def test_swing_resonance_is_refused(ref_swing):
    """``freq_scale = 1.0`` must **raise**, so nobody can "simplify" the 0.8 back out.

    "Thrust points along the rope, so bank equals θ" is a no-drag statement. With this simulator's
    drag the same sizing at resonance demands ~89° of tilt and a 15.45 rad/s rate command against
    an 11.64 ceiling — untrackable, not merely tight. Without this test the generator would happily
    emit it and every other check in the package would still pass.
    """
    model, _, _, _ = ref_swing
    with pytest.raises(RateEnvelopeError) as exc:
        SwingSpec(freq_scale=1.0).build(model, dt=2e-3)
    assert "outside the act-v2 envelope" in str(exc.value)
    # The shipped 0.8 is comfortably inside, with real headroom rather than a tie.
    lim = verify.check_limits(ref_swing[3])
    assert lim["within_envelope"]
    assert lim["max_abs_rate_cmd_rp_rps"] == pytest.approx(7.94, abs=0.05)
    assert lim["rate_headroom_frac"] > 0.30


def test_swing_peak_tilt_is_not_the_amplitude(ref_swing):
    """Peak bank runs ~1.4× the authored swing angle, because drag leans the axis into travel."""
    model, spec, _, fine = ref_swing
    m = reference_metrics(fine, spec, model)
    assert m["peak_bank_deg"] == pytest.approx(69.3, abs=0.5)
    assert m["peak_bank_over_amplitude"] > 1.3
    assert m["swing_half_width_m"] == pytest.approx(spec.path().half_width, abs=1e-5)
    assert m["settle_pos_error"] < 1e-9
    assert m["altitude_loss"] < 1e-9              # a pendulum only ever climbs from its bottom


def test_swing_is_fully_powered(ref_swing):
    """No coast means no zero-authority stretch — so no ``--deployable`` variant is warranted."""
    model, spec, _, fine = ref_swing
    alloc = verify.check_allocation(fine, model)
    assert alloc["feasible"]
    assert alloc["zero_authority_frac"] == 0.0
    assert alloc["min_margin_torqued"] == pytest.approx(0.646, abs=0.02)
    assert spec.min_thrust_normed == 0.0


# =============================================================================================
# The orbit: 3D, and the one that breaks psi == 0
# =============================================================================================
@pytest.fixture(scope="module")
def ref_orbit():
    model = RefModel()
    spec = OrbitSpec()
    build = spec.build(model, dt=DT_FINE)
    return model, spec, build, build.traj.sample(model, DT_FINE)


def test_orbit_axis_pointing_error_matches_its_closed_form(ref_orbit):
    """The measured median error equals ``atan((D/m)/Ω)``, and is **unchanged across radii**.

    This is the check that keeps the honest caveat honest. "The top face points at the axis" is
    wrong by a specific, derivable amount in this simulator, and if the measurement ever stopped
    matching the prediction, one of the two would be wrong and the artifact would be shipping a
    number nobody could reproduce.
    """
    model, spec, _, fine = ref_orbit
    m = reference_metrics(fine, spec, model)
    predicted = math.degrees(math.atan2(model.drag_per_mass, spec.omega_orbit))
    assert predicted == pytest.approx(24.06, abs=0.05)
    assert m["axis_pointing_error_deg"] == pytest.approx(predicted, abs=0.5)
    assert m["axis_pointing_error_predicted_deg"] == pytest.approx(predicted, abs=1e-9)

    # Radius-independent: R*Omega^2 over (D/m)*R*Omega cancels R. Three radii, same answer.
    errs = []
    for radius in (0.25, 0.375, 0.5):
        s = OrbitSpec(radius=radius)
        f = s.build(model, dt=2e-3).traj.sample(model, 2e-3)
        errs.append(reference_metrics(f, s, model)["axis_pointing_error_deg"])
    assert max(errs) - min(errs) < 0.5, f"error moved with radius: {errs}"
    assert all(e == pytest.approx(predicted, abs=0.5) for e in errs)


def test_orbit_axis_pointing_error_collapses_without_drag(ref_orbit):
    """Re-flying the identical authored path at zero drag must take the error to **exactly 0**.

    That is what makes "this is the simulator's drag, not the maneuver" a measurement rather than
    an assertion. The shipped ``real_est`` bracket is still *linear* drag, so it lands at ~8°, not
    the ~2.8° a genuinely quadratic law would give — the two are quoted separately on purpose.
    """
    from neural_whoop.reference.emit import drag_sensitivity

    model, spec, build, _ = ref_orbit
    sens = drag_sensitivity(build.traj, spec, model, 2e-3)
    assert sens["none"]["axis_pointing_error_deg"] == pytest.approx(0.0, abs=1e-6)
    assert sens["sim"]["axis_pointing_error_deg"] == pytest.approx(24.06, abs=0.5)
    assert sens["real_est"]["axis_pointing_error_deg"] == pytest.approx(8.0, abs=0.5)
    # The geometry is identical under every model — only what the airframe must do changes.
    assert sens["none"]["max_lateral_drift_m"] == pytest.approx(
        sens["sim"]["max_lateral_drift_m"], abs=1e-9)


def test_orbit_stays_inside_the_envelope_and_stays_conditioned(ref_orbit):
    """Thrust ≤ 4.0, roll/pitch ≤ 11.64, yaw ≤ 6.0, and the heading map never goes singular.

    Conditioning is the non-obvious one. The *forward* flatness map only ever multiplies by
    ``|∂ω_z/∂ψ̇|``, so it is fine at 0.37; only ``state_to_flat`` divides by it. Asserting it stays
    positive is what says the attitude the reference publishes is well defined at all.
    """
    model, spec, _, fine = ref_orbit
    lim = verify.check_limits(fine)
    assert lim["within_envelope"]
    assert lim["max_normed_thrust"] == pytest.approx(2.913, abs=0.02)
    assert lim["max_abs_rate_cmd_rp_rps"] == pytest.approx(7.044, abs=0.05)
    assert lim["max_abs_rate_cmd_yaw_rps"] == pytest.approx(3.637, abs=0.05)
    assert lim["max_abs_rate_cmd_yaw_rps"] <= MAX_BODY_RATE_YAW_RPS

    R = fl.quat_xyzw_to_rotmat(fine.quat)
    psi = np.array([spec.path().psi(np.array([t]))[0][0] for t in
                    np.linspace(0.0, spec.path().duration, 200)])
    cond = fl.heading_conditioning(R[:len(fine)], 0.0, heading=spec.heading)
    assert float(np.min(cond)) > 0.0, "the heading construction went singular"
    del psi


def test_orbit_is_genuinely_3d(ref_orbit):
    """``ω_z`` is large and the attitude reaches 180° — both are the point, not a defect."""
    model, spec, _, fine = ref_orbit
    assert not spec.is_planar
    assert float(np.max(np.abs(fine.omega[:, 2]))) == pytest.approx(3.34, abs=0.1)
    q = verify.check_quaternion(fine, spec)
    assert q["kind"] == "heading"
    assert q["heading_turns"] == pytest.approx(3.0, abs=1e-6)
    assert q["monotone_heading"]
    assert q["max_norm_error"] < 1e-9
    assert q["sign_flips"] == 0
    assert q["max_attitude_from_identity_deg"] > 170.0
    # assert_planar must refuse rather than report a failure for a maneuver that never claimed it.
    with pytest.raises(ValueError):
        assert_planar(fine, spec)


# =============================================================================================
# The rate-loop finding — about the SUBSTRATE, not about any one maneuver
# =============================================================================================
def test_rate_loop_stability_discriminates_by_the_fixed_axis(ref_motors_off, ref_swing, ref_orbit):
    """The 90° threshold alone is not the answer, and the flip is the proof.

    A roll flip spends ~6% of its frames past 90° of attitude and tracks to 2.15 cm anyway,
    because its ω lies on ``R``'s **fixed axis** — the eigenvector whose loop eigenvalue stays
    ``−K`` no matter what θ is. The orbit's ω does not, and it diverges. A check that reported only
    "attitude exceeded 90°" would call the flip unstable and be useless; this pins the mechanism.
    """
    model = RefModel()
    flip = verify.check_rate_loop_stability(ref_motors_off[3], model)
    swing = verify.check_rate_loop_stability(ref_swing[3], model)
    orbit = verify.check_rate_loop_stability(ref_orbit[3], model)

    # The flip goes right past 90 deg and is stable anyway — for a stated, measured reason.
    assert flip["max_attitude_from_identity_deg"] > 170.0
    assert flip["frac_above_90deg"] > 0.0
    assert flip["min_omega_fixed_axis_alignment"] == pytest.approx(1.0, abs=1e-12)
    assert flip["omega_on_fixed_axis"]
    assert flip["vendored_loop_stable"]

    # The swing never gets near 90 deg AND is on the fixed axis: stable twice over.
    assert swing["max_attitude_from_identity_deg"] < 90.0
    assert swing["vendored_loop_stable"]

    # The orbit is the one that breaks it, and both conditions fail together.
    assert not orbit["omega_on_fixed_axis"]
    assert orbit["min_omega_fixed_axis_alignment"] < 0.05
    assert orbit["frac_above_90deg"] > 0.1
    assert not orbit["vendored_loop_stable"]
    assert orbit["worst_offaxis_eigenvalue_real_part_per_s"] > 0.0
    # The predicted onset: the eigenvalue turns positive exactly when theta crosses 90 deg.
    # first_crossing_t_s is absolute (it includes the climb and hover stagecraft), so measure it
    # against the frame the maneuver actually starts on.
    fine = ref_orbit[3]
    lo = ref_orbit[1].metric_window[0]
    t0 = float(fine.t[int(np.flatnonzero(fine.phase >= lo)[0])])
    assert 0.4 < orbit["first_crossing_t_s"] - t0 < 1.2


def test_rate_loop_eigenvalue_formula_is_what_the_controller_implements():
    """``−K·cos θ`` is not a guess about ``R_i2b @ w`` — it is the eigenvalue, computed directly.

    Builds a random rotation, forms ``−K·R``, and checks that its eigenvalues really are ``−K``
    and ``−K·e^{±iθ}``. That is the whole argument the finding rests on, so it is worth two lines
    of linear algebra rather than a citation.
    """
    rng = np.random.default_rng(3)
    for _ in range(20):
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        theta = rng.uniform(0.1, np.pi - 0.1)
        q = np.concatenate([axis * math.sin(theta / 2), [math.cos(theta / 2)]])
        R = fl.quat_xyzw_to_rotmat(q[None])[0]
        K = 16.0
        eig = np.linalg.eigvals(-K * R)
        expected = np.sort_complex(
            np.array([-K, -K * np.exp(1j * theta), -K * np.exp(-1j * theta)]))
        assert np.allclose(np.sort_complex(eig), expected, atol=1e-9)
        # The real part that decides stability, and the 90 deg threshold it implies.
        assert float(np.max(eig.real)) == pytest.approx(max(-K, -K * math.cos(theta)), abs=1e-9)
        assert (float(np.max(eig.real)) > 0.0) == (theta > math.pi / 2 + 1e-12)


# =============================================================================================
# The generalized package: every spec satisfies the protocol, and the flip still behaves
# =============================================================================================
@pytest.mark.parametrize("spec", [FlipSpec(), SwingSpec(), OrbitSpec()],
                         ids=["flip", "swing", "orbit"])
def test_every_spec_satisfies_the_maneuver_protocol(spec):
    """``emit`` and ``verify`` work against "a maneuver", so every spec must actually provide one.

    Cheap, and it catches the failure mode the generalization introduced: a new maneuver that looks
    complete until the moment the emitter asks it for a phase label it never defined.
    """
    assert isinstance(spec, ManeuverSpec)
    labels = spec.phase_labels
    assert labels and all(isinstance(s, str) for s in labels)
    lo, hi = spec.metric_window
    assert 0 <= lo <= hi < len(labels)
    assert 0 <= spec.settle_phase < len(labels)
    assert np.asarray(spec.station).shape == (3,)
    assert spec.z_entry > spec.z_rest
    meta = spec.reference_meta(None)
    assert meta["maneuver"] == spec.name
    assert meta["plane"] in ("yz", "xz", "xy")
    assert set(meta["rotation"]) >= {"kind", "axis", "target_turns", "label"}
    assert isinstance(spec.describe(None), str)
    assert spec.caveats(RefModel())
    for a, b in spec.c2_break_phases:
        assert 0 <= a < len(labels) and 0 <= b < len(labels)


def test_analytic_segment_refuses_a_discontinuous_entry():
    """A ``PathSegment`` cannot teleport (it starts from the state it is handed); an analytic one
    could, since it ignores that state. So it asserts instead of silently jumping."""
    from neural_whoop.reference.segments import AnalyticPathSegment

    def path(t):
        t = np.asarray(t)
        p = np.stack([np.zeros_like(t), np.zeros_like(t), np.full_like(t, 5.0)], axis=-1)
        return p, np.zeros_like(p), np.zeros_like(p), np.zeros_like(p)

    seg = AnalyticPathSegment("X", 0, 1.0, path=path)
    with pytest.raises(ValueError, match="teleport"):
        seg.sample(RefState.at_rest(np.zeros(3)), RefModel(), np.linspace(0, 1, 3))


@pytest.mark.parametrize("maneuver", ["swing", "orbit"])
def test_analytic_maneuvers_converge_second_order(maneuver):
    """The emitted arrays satisfy DiffAero's ODE, and the residual is dominated by SAMPLING.

    Same diagnostic as the flip's, and stricter in one way: there are no authored command steps to
    mask here at all, so the masked fraction must be ~0 and the convergence ratio must be close to
    the ideal 400× rather than the flip's 254×.
    """
    model = RefModel()
    spec = SwingSpec() if maneuver == "swing" else OrbitSpec()
    fine = spec.build(model, dt=DT_FINE).traj.sample(model, DT_FINE)
    replay = decimate(fine, DT_REPLAY)
    mask_f = verify.c2_break_indices(fine)
    rf = verify.dynamics_residual(fine, model, mask=mask_f)
    rr = verify.dynamics_residual(replay, model, mask=verify.c2_break_indices(replay))
    # Nothing steps, so nothing at the masked frames is worse than the smooth interior.
    for name in ("pos", "vel", "quat"):
        assert rf[f"{name}_max_at_breaks"] < 10.0 * max(rf[f"{name}_max"], 1e-12), (
            f"{name} residual spikes at a seam of a maneuver that claims to have no command steps"
        )
        ratio = rr[f"{name}_rms"] / rf[f"{name}_rms"]
        assert 250.0 < ratio < 600.0, f"{name} improved {ratio:.0f}x, expected ~400x"
    assert rf["vel_rms"] < 1e-3
