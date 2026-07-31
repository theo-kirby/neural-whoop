"""Open-loop sim replay of the reference: feed its own commands to DiffAero and see where it goes.

This is the only reference test that needs the simulator, and it is the one that closes the loop
on everything else. Every other check asks "is the reference self-consistent?"; this one asks "if
you actually *sent* these commands to the thing the reference claims to describe, would you get
this trajectory?"

It is also a **well-aimed tripwire** rather than noise. DiffAero's ``RateController`` measures the
rate error as ``desired_body − R_i2b @ w`` (``controller.py:93``) while the rest of the repo treats
``_state[10:13]`` as already body-frame — a known bug that makes the loop correct only at
``R == I``. For a rotation about the same axis the rate is on, ``R_i2b @ w == w`` **exactly**, so
the bug is an exact no-op for this maneuver and any drift we measure is real integration error.
Break ``ψ ≡ 0`` and this test would blow up immediately, which is precisely what we want it to do.

Expect a few cm and a few degrees over ~6 s, dominated by DiffAero's 100 Hz RK4 against the
reference's 1 kHz, and by the zero-order hold: the reference is a *continuous* command profile
sampled at 50 Hz, while the simulator holds each action for the whole 20 ms step.
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
