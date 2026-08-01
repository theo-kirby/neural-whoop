"""Open-loop sim replay: feed each reference's own commands to DiffAero and see where it goes.

This is the only reference file that needs the simulator, and it is the one that closes the loop on
everything else. Every other check asks "is the reference self-consistent?"; this one asks "if you
actually *sent* these commands to the thing the reference claims to describe, would you get this
trajectory?"

It is also a **well-aimed tripwire** rather than noise, and with three maneuvers it now measures
both sides of that tripwire. DiffAero's ``RateController`` computes the *measured* rate as
``R_i2b @ w`` (``controller.py:93``) while ``w`` is already body-frame — so the closed loop is
``ω̇ = K(u − R·ω)``, whose eigenvalues are ``−K`` and ``−K·e^{±iθ}``: the real part is
``−K·cos θ``, **positive past 90° of attitude**.

- The **flip** and the **swing** are planar, so their ω lies on ``R``'s fixed axis — the one
  eigenvalue that stays ``−K`` regardless of θ. They track to centimetres, the flip *through* 180°
  of inversion. That, precisely, is why ``ψ ≡ 0`` is load-bearing.
- The **orbit** is not planar, and it **diverges: 17.6 m of position error on a 1 m circle**.
  Asserting only that would be a weak test — it would still pass if the reference itself were
  wrong — so it is paired with the control experiment: the identical command stream through an
  identical loop with ``R_i2b`` removed tracks to 1.8 cm. One of those two numbers is about the
  reference; the other is about the simulator, and running both is the only way to tell them apart.

  Note it does *not* reach NaN. ``WhoopDynamics`` saturates body rate and velocity every step
  (``dynamics/whoop.py``), so the blow-up is bounded — which is worse for a reader, because the
  output still looks like a finite trajectory. Every assertion here is therefore on the error
  magnitude, never on ``isfinite``.

Per the project's decision the vendored fork is **not** patched: the corrected loop here is a local
re-implementation used purely as a measurement.

Expect a few cm and a few degrees over ~6-9 s on the stable maneuvers, dominated by DiffAero's
100 Hz RK4 against the reference's 1 kHz and by the zero-order hold.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from neural_whoop.dynamics.whoop import WhoopDynamics, WhoopParams  # noqa: E402
from neural_whoop.reference import flatness as fl  # noqa: E402
from neural_whoop.reference.emit import (  # noqa: E402
    decimate,
    decimate_indices,
    step_hold_commands,
)
from neural_whoop.reference.maneuvers import (  # noqa: E402
    FlipSpec,
    build_sequence,
    hover_entry_state,
    solve_flip,
)
from neural_whoop.reference.maneuvers_orbit import OrbitSpec  # noqa: E402
from neural_whoop.reference.maneuvers_swing import SwingSpec  # noqa: E402
from neural_whoop.reference.model import RefModel  # noqa: E402

DT_FINE = 1e-3
DT_REPLAY = 0.02


@pytest.fixture(scope="module")
def reference():
    model = RefModel()
    spec = FlipSpec(axis="roll", omega_peak=9.0, z_entry=1.2)
    sol = solve_flip(spec, model, hover_entry_state(spec), dt=DT_FINE, try_stage2=False)
    fine = build_sequence(spec, model, sol).sample(model, DT_FINE)
    return model, spec, sol, fine


@pytest.fixture(scope="module")
def swing():
    model = RefModel()
    spec = SwingSpec()
    return model, spec, None, spec.build(model, dt=DT_FINE).traj.sample(model, DT_FINE)


@pytest.fixture(scope="module")
def orbit():
    model = RefModel()
    spec = OrbitSpec()
    return model, spec, None, spec.build(model, dt=DT_FINE).traj.sample(model, DT_FINE)


def _rollout(fine, dt: float):
    """Push the reference's own emitted commands through ``WhoopDynamics.step()``.

    Uses exactly what the replay carries: the **impulse-matched** zero-order hold from
    :func:`step_hold_commands`. That choice is load-bearing — sampling the instantaneous command at
    the frame time instead drifts ~1 m over this sequence, because the thrust cut is one control
    step wide. See that function's docstring for the measured table.
    """
    idx = decimate_indices(fine, dt)
    replay = decimate(fine, dt)
    hold_thrust, hold_rate = step_hold_commands(fine, idx)

    dev = torch.device("cpu")
    dyn = WhoopDynamics(1, params=WhoopParams(randomize_airframe=False, dt=dt), device=dev)
    dyn.set_state(
        torch.arange(1, device=dev),
        pos=torch.tensor(replay.pos[0:1], dtype=torch.float32),
        vel=torch.tensor(replay.vel[0:1], dtype=torch.float32),
        quat_xyzw=torch.tensor(replay.quat[0:1], dtype=torch.float32),
        ang_vel=torch.tensor(replay.omega[0:1], dtype=torch.float32),
    )
    n = len(replay)
    pos = np.zeros((n, 3))
    quat = np.zeros((n, 4))
    wz = np.zeros(n)
    pos[0], quat[0] = replay.pos[0], replay.quat[0]
    for k in range(n - 1):
        ctbr = np.array([[hold_thrust[k], *hold_rate[k]]], dtype=np.float32)
        dyn.step(torch.from_numpy(ctbr))
        pos[k + 1] = dyn.pos[0].numpy()
        quat[k + 1] = dyn.quat_xyzw[0].numpy()
        wz[k + 1] = float(dyn.ang_vel_body[0, 2])
    return replay, pos, quat, wz


def _attitude_error_deg(qa: np.ndarray, qb: np.ndarray) -> np.ndarray:
    """Geodesic angle between two quaternion sequences (deg), sign-ambiguity safe."""
    d = np.abs(np.sum(qa * qb, axis=-1)).clip(0.0, 1.0)
    return np.degrees(2.0 * np.arccos(d))


def test_params_match_the_reference_model(reference):
    """The sim we replay into must be the airframe the reference was derived against."""
    model, *_ = reference
    p = WhoopParams(randomize_airframe=False)
    assert (p.mass[0], p.J_xy[0], p.D_xy[0], p.g) == (model.mass, model.J_xy, model.D_xy, model.g)
    assert p.K_angvel == model.K_angvel


def test_open_loop_replay_tracks_the_reference(reference):
    """Send the reference's own emitted commands to DiffAero; measure the divergence.

    Asserted loosely and **published**: the point is to have the number, not to pin it. What is
    left after the impulse-matched hold is DiffAero's 100 Hz RK4 against the reference's 1 kHz,
    plus float32 state, accumulated over ~6 s of open-loop flight with no feedback of any kind.
    """
    model, spec, sol, fine = reference
    replay, pos, quat, _ = _rollout(fine, DT_REPLAY)

    pos_err = np.linalg.norm(pos - replay.pos, axis=-1)
    att_err = _attitude_error_deg(quat, replay.quat)
    print(f"\nopen-loop replay over {replay.t[-1]:.2f} s @ {1/DT_REPLAY:.0f} Hz: "
          f"pos max {pos_err.max()*100:.2f} cm (final {pos_err[-1]*100:.2f} cm), "
          f"attitude max {att_err.max():.2f}° (final {att_err[-1]:.2f}°)")

    assert np.isfinite(pos).all() and np.isfinite(quat).all()
    assert pos_err.max() < 0.05, f"position drifted {pos_err.max()*100:.1f} cm"
    assert att_err.max() < 10.0, f"attitude drifted {att_err.max():.1f}°"


def test_impulse_matched_hold_is_what_makes_it_track(reference):
    """The emitted hold must beat the naive instantaneous sample by an order of magnitude.

    This is the test that pins the *reason* the replay tracks. A left-edge hold is first-order and
    fails exactly where this maneuver lives — the thrust cut is one control step wide, so holding
    the pre-cut collective for an extra 20 ms injects a velocity error that never comes back.
    Without this test, someone could "simplify" ``step_hold_commands`` back to an instantaneous
    lookup and every other test here would still pass while the artifact quietly drifted a metre.
    """
    model, spec, sol, fine = reference
    idx = decimate_indices(fine, DT_REPLAY)
    replay = decimate(fine, DT_REPLAY)
    hold_thrust, hold_rate = step_hold_commands(fine, idx)

    def drift(thrust, rate):
        dev = torch.device("cpu")
        dyn = WhoopDynamics(1, params=WhoopParams(randomize_airframe=False, dt=DT_REPLAY),
                            device=dev)
        dyn.set_state(
            torch.arange(1, device=dev),
            pos=torch.tensor(replay.pos[0:1], dtype=torch.float32),
            vel=torch.tensor(replay.vel[0:1], dtype=torch.float32),
            quat_xyzw=torch.tensor(replay.quat[0:1], dtype=torch.float32),
            ang_vel=torch.tensor(replay.omega[0:1], dtype=torch.float32),
        )
        worst = 0.0
        for k in range(len(replay) - 1):
            dyn.step(torch.from_numpy(np.array([[thrust[k], *rate[k]]], dtype=np.float32)))
            worst = max(worst, float(np.linalg.norm(dyn.pos[0].numpy() - replay.pos[k + 1])))
        return worst

    held = drift(hold_thrust, hold_rate)
    naive = drift(replay.normed_thrust, replay.rate_cmd)
    print(f"\nhold comparison @ {1/DT_REPLAY:.0f} Hz: impulse-matched {held*100:.2f} cm vs "
          f"instantaneous {naive*100:.2f} cm ({naive/held:.0f}x worse)")
    assert held < naive / 5.0


def test_open_loop_error_is_flat_across_control_rates(reference):
    """The residual must NOT grow as the control rate falls — that is what "no ZOH error" means.

    A first-order hold error would scale with ``dt``; a systematic error (a flipped drag term, a
    wrong thrust convention) would ignore ``dt`` entirely but be large. Flat *and small* is the
    signature of a correctly discretized reference, so this is the check that tells all three
    explanations apart.
    """
    model, spec, sol, fine = reference
    errs = {}
    for dt in (DT_REPLAY, DT_REPLAY / 2, DT_REPLAY / 4):
        replay, pos, _, _ = _rollout(fine, dt)
        errs[dt] = float(np.linalg.norm(pos - replay.pos, axis=-1).max())
    print("\nhold-rate sweep: " + ", ".join(f"{k*1e3:.1f} ms -> {v*100:.2f} cm"
                                           for k, v in errs.items()))
    assert max(errs.values()) < 0.05
    assert max(errs.values()) < 3.0 * min(errs.values())     # flat, not dt-scaling


def test_yaw_and_yaw_rate_stay_dead_in_the_sim(reference):
    """``|ω_z| < 1e-9`` and no off-axis attitude **in the simulator**, not just in the generator.

    These are the two failures that would silently ruin the reference. ψ ≡ 0 is what makes the
    ``RateController`` frame bug (``controller.py:93``) a no-op; the moment yaw wakes up, the same
    constant CTBR command produces a saturated tumble instead of a clean roll (measured in
    ``scripts/hero_takeoff_flip_land.py``: 12 rad/s at yaw 0, a 40/40/16 rad/s tumble at yaw −22°).
    So this test is a well-aimed tripwire, not a formality.
    """
    model, spec, sol, fine = reference
    _, _, quat, wz = _rollout(fine, DT_REPLAY)
    max_wz = float(np.max(np.abs(wz)))
    max_qy = float(np.max(np.abs(quat[:, 1])))     # a roll flip must not develop pitch...
    max_qz = float(np.max(np.abs(quat[:, 2])))     # ...or yaw
    print(f"\nplanarity in-sim: max |ω_z| {max_wz:.2e} rad/s, max |q_y| {max_qy:.2e}, "
          f"max |q_z| {max_qz:.2e}")
    assert max_wz < 1e-9
    assert max_qz < 1e-9
    assert max_qy < 1e-9


def test_reference_rotation_is_reproduced_in_sim(reference):
    """The sim, driven open-loop, still comes round exactly once — the maneuver is trackable."""
    model, spec, sol, fine = reference
    _, _, quat, _ = _rollout(fine, DT_REPLAY)
    phi = fl.rotation_angle_about(fl.enforce_quat_continuity(quat), spec.axis_idx)
    turns = phi[-1] / (2.0 * math.pi)
    print(f"\nsim rotation: {turns:.4f} turns (reference 1.0000)")
    assert abs(turns - 1.0) < 0.05


# =============================================================================================
# The swing: the same test, and it should do BETTER than the flip
# =============================================================================================
def test_swing_tracks_better_than_the_flip(swing, reference):
    """The swing must track to under 2 cm — and beat the flip, for a stated reason.

    The flip's residual is dominated by its two intentional C² breaks: the thrust cut is one
    control step wide, so even an impulse-matched hold leaves a step the 50 Hz stream cannot
    represent exactly. The swing has **no** command steps anywhere, so that error source simply is
    not present. Asserting the ordering (not just the absolute number) is what ties the measurement
    to the explanation — if a seam ever crept into the swing this would fail even if 2 cm still
    passed.
    """
    model, spec, _, fine = swing
    replay, pos, quat, wz = _rollout(fine, DT_REPLAY)
    pos_err = np.linalg.norm(pos - replay.pos, axis=-1)
    att_err = _attitude_error_deg(quat, replay.quat)
    print(f"\nswing open-loop replay over {replay.t[-1]:.2f} s @ {1/DT_REPLAY:.0f} Hz: "
          f"pos max {pos_err.max()*100:.2f} cm (final {pos_err[-1]*100:.2f} cm), "
          f"attitude max {att_err.max():.2f}°")

    assert np.isfinite(pos).all() and np.isfinite(quat).all()
    assert pos_err.max() < 0.02, f"swing drifted {pos_err.max()*100:.2f} cm"
    assert att_err.max() < 2.0, f"swing attitude drifted {att_err.max():.2f}°"
    assert float(np.max(np.abs(wz))) < 1e-9        # planar in the simulator, not just on paper

    _, flip_pos, _, _ = _rollout(reference[3], DT_REPLAY)
    flip_replay = decimate(reference[3], DT_REPLAY)
    flip_err = np.linalg.norm(flip_pos - flip_replay.pos, axis=-1).max()
    print(f"swing {pos_err.max()*100:.2f} cm vs flip {flip_err*100:.2f} cm "
          f"({flip_err/pos_err.max():.1f}x)")
    assert pos_err.max() < flip_err


# =============================================================================================
# The orbit: it must diverge — AND the corrected loop must not. That pairing is the experiment.
# =============================================================================================
def _corrected_rollout(fine, dt: float):
    """The identical command stream through DiffAero's own ODE with the rate-loop frame bug removed.

    A local re-implementation, deliberately: the project's decision is to **report** the vendored
    controller's frame bug, not patch the fork. This exists purely as the control arm of the
    measurement, and it is a faithful one — ``quadrotor.py``'s ``M = τ − ω×Jω`` cancels the
    controller's own ``ω×Jω`` term exactly, so DiffAero's rotational dynamics reduce to
    ``ω̇ = K(u − ω_measured)`` and the *only* difference from the vendored path is dropping the
    ``R_i2b`` that should not be there. Everything else — the drag law, the gravity sign, the
    thrust convention, RK4, the substep count — is the same.
    """
    idx = decimate_indices(fine, dt)
    replay = decimate(fine, dt)
    hold_thrust, hold_rate = step_hold_commands(fine, idx)
    m = RefModel()
    K = np.array(m.K_angvel)
    e_z = np.array([0.0, 0.0, 1.0])
    n_sub = 2                                     # matches WhoopParams.n_substeps (100 Hz physics)

    def deriv(y, u_thrust, u_rate):
        v, q, w = y[3:6], y[6:10] / np.linalg.norm(y[6:10]), y[10:13]
        z_B = fl.quat_xyzw_to_rotmat(q)[:, 2]
        return np.concatenate([
            v,
            u_thrust * m.g * z_B - m.g * e_z - m.drag_per_mass * v,
            fl.quat_derivative(q, w),
            K * (u_rate - w),                     # <- the corrected loop: no R_i2b
        ])

    n = len(replay)
    pos = np.zeros((n, 3))
    quat = np.zeros((n, 4))
    y = np.concatenate([replay.pos[0], replay.vel[0], replay.quat[0], replay.omega[0]])
    pos[0], quat[0] = replay.pos[0], replay.quat[0]
    h = dt / n_sub
    for k in range(n - 1):
        ut, ur = float(hold_thrust[k]), np.asarray(hold_rate[k], dtype=np.float64)
        for _ in range(n_sub):
            k1 = deriv(y, ut, ur)
            k2 = deriv(y + h / 2 * k1, ut, ur)
            k3 = deriv(y + h / 2 * k2, ut, ur)
            k4 = deriv(y + h * k3, ut, ur)
            y = y + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
            y[6:10] /= np.linalg.norm(y[6:10])
        pos[k + 1], quat[k + 1] = y[0:3], y[6:10]
    return replay, pos, quat


def test_orbit_diverges_in_diffaero_but_not_through_a_corrected_rate_loop(orbit):
    """**The control experiment.** Both halves are required; either alone proves nothing.

    Asserting only "the orbit diverges" would still pass if the *reference* were wrong — a garbage
    trajectory diverges too. Asserting only "the corrected loop tracks" would not establish that
    anything is wrong with the substrate. Running the identical command stream through both, and
    changing exactly one line of the controller between them, is what isolates the cause.

    Measured over the orbit's 3.85 s: **17.6 m** of position error as vendored versus **1.8 cm**
    corrected. Note it does not reach NaN — ``WhoopDynamics`` saturates body rate and velocity
    every step, so the divergence is bounded and the output still *looks* like a trajectory. That
    is why the assertion is on the error magnitude rather than on ``isfinite``.
    """
    model, spec, _, fine = orbit
    replay, pos, quat, _ = _rollout(fine, DT_REPLAY)
    finite = np.isfinite(pos).all(axis=-1)
    worst_before_nan = float(np.max(np.linalg.norm(
        pos[finite] - replay.pos[finite], axis=-1))) if finite.any() else float("inf")
    print(f"\norbit through DiffAero AS VENDORED: worst error {worst_before_nan:.2f} m "
          f"({'reached NaN' if not np.isfinite(pos).all() else 'bounded by the state clamps'})")
    assert not np.isfinite(pos).all() or worst_before_nan > 1.0, (
        "the orbit tracked in the vendored simulator — either controller.py:93 was fixed (in "
        "which case this finding is resolved and the caveats should come out of the artifacts) or "
        "the maneuver was resized below 90 deg of attitude."
    )

    replay_c, pos_c, quat_c = _corrected_rollout(fine, DT_REPLAY)
    err = np.linalg.norm(pos_c - replay_c.pos, axis=-1)
    att = _attitude_error_deg(quat_c, replay_c.quat)
    print(f"orbit through an identical loop with R_i2b REMOVED: "
          f"pos max {err.max()*100:.2f} cm, attitude max {att.max():.2f}°")
    assert np.isfinite(pos_c).all()
    assert err.max() < 0.05, f"the corrected loop drifted {err.max()*100:.1f} cm"
    assert att.max() < 5.0


def test_orbit_divergence_is_instability_not_discretization(orbit):
    """It must **not** improve as ``dt → 1 ms``. That is what tells the two explanations apart.

    A discretization error shrinks with the step; a positive eigenvalue does not. Without this the
    obvious reading of the NaN would be "the control rate is too low", which would send the next
    person to tune ``dt`` instead of reading ``controller.py:93``.
    """
    model, spec, _, fine = orbit
    worst = {}
    for dt in (DT_REPLAY, DT_REPLAY / 4, 1e-3):
        replay, pos, _, _ = _rollout(fine, dt)
        finite = np.isfinite(pos).all(axis=-1)
        err = np.linalg.norm(pos[finite] - replay.pos[finite], axis=-1)
        worst[dt] = float(err.max()) if err.size else float("inf")
    print("\norbit vendored-loop error vs control rate: " +
          ", ".join(f"{k*1e3:.1f} ms -> {v:.2f} m" for k, v in worst.items()))
    assert all(v > 1.0 for v in worst.values()), (
        f"the divergence shrank with the step ({worst}), which would make it a discretization "
        f"artifact rather than the instability the eigenvalue argument predicts"
    )


def test_the_flip_survives_because_its_omega_is_on_the_fixed_axis(reference, orbit):
    """The mechanism, measured on both: alignment 1.0 survives 180°; alignment ~0 does not.

    The flip goes just as far from identity as the orbit — both reach ~180° — so "how rotated is
    it" cannot be what separates them. What separates them is whether ω lies on ``R``'s rotation
    axis, the eigenvector whose loop eigenvalue stays ``−K`` regardless of θ.
    """
    from neural_whoop.reference.verify import check_rate_loop_stability

    model = RefModel()
    flip = check_rate_loop_stability(reference[3], model)
    orb = check_rate_loop_stability(orbit[3], model)
    print(f"\nflip:  attitude {flip['max_attitude_from_identity_deg']:.1f}°, ω-axis alignment "
          f"{flip['min_omega_fixed_axis_alignment']:.9f} -> stable={flip['vendored_loop_stable']}")
    print(f"orbit: attitude {orb['max_attitude_from_identity_deg']:.1f}°, ω-axis alignment "
          f"{orb['min_omega_fixed_axis_alignment']:.9f} -> stable={orb['vendored_loop_stable']}")

    assert flip["max_attitude_from_identity_deg"] > 170.0
    assert orb["max_attitude_from_identity_deg"] > 170.0
    assert flip["min_omega_fixed_axis_alignment"] > 1.0 - 1e-12
    assert orb["min_omega_fixed_axis_alignment"] < 0.05
    # ...and the simulator agrees with the prediction on both.
    _, flip_pos, _, _ = _rollout(reference[3], DT_REPLAY)
    _, orb_pos, _, _ = _rollout(orbit[3], DT_REPLAY)
    assert np.isfinite(flip_pos).all()
    flip_err = np.linalg.norm(flip_pos - decimate(reference[3], DT_REPLAY).pos, axis=-1).max()
    orb_err = np.linalg.norm(orb_pos - decimate(orbit[3], DT_REPLAY).pos, axis=-1).max()
    print(f"in-sim error: flip {flip_err*100:.2f} cm vs orbit {orb_err:.1f} m")
    assert flip_err < 0.05
    assert orb_err > 1.0
