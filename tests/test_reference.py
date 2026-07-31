"""Verification for the hand-authored reference maneuver — **pure numpy, no simulator**.

The whole value of a reference trajectory is that its numbers are true, so every claim the
:mod:`neural_whoop.reference` package makes has a test that produces a number here. Nothing in
this file imports torch or DiffAero; the open-loop sim replay (the one check that genuinely needs
the simulator) lives in ``tests/test_reference_flip.py``.

The solved flip is built **once** per variant and shared, because the shoot is a real Newton
iteration and not something to pay for in every test.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from neural_whoop.reference import flatness as fl
from neural_whoop.reference import verify
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
    assert_planar,
    build_sequence,
    hover_entry_state,
    solve_flip,
)
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
    assert check["monotone_in_flip"]
    assert check["min_dphi_in_flip"] >= -1e-12
    assert check["crossings_of_target"] == 1
    assert abs(check["phi_end_error_rad"]) < 1e-6
    assert check["max_norm_error"] < 1e-9
    assert check["sign_flips"] == 0
    # The recover leans ~8.5° to translate 0.18 m back to the station; the bound is here to catch
    # "it tumbled after the flip", not to pin the lean.
    assert check["max_post_flip_wobble_rad"] < math.radians(15.0)


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
    seams = verify.classify_breaks(fine)
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
    m = maneuver_mask(fine)
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
    assert check["monotone_in_flip"]


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
