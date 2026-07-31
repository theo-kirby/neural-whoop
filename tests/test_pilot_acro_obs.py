"""Pilot acro obs-7 parity — the make-or-break gate for the blind flip deploy.

The acro policy trains on ``gravity_body = world_to_body([0,0,-1], R)`` (``tasks/acro_flip.py``); at
deploy the pilot must feed it the SAME vector, rebuilt from MSP attitude by a pure-stdlib port of the
sim's ``euler_to_quaternion`` + ``quaternion_to_matrix``. If the two disagree the policy sees a
different obs than it trained on and the flip is unsafe. This asserts byte-parity (< 1e-6) across a
grid of roll/pitch/yaw — the yaw sweep simultaneously proves the deploy port's yaw-invariance
(``obs_from_msp_acro`` passes yaw=0, but the sim R here carries full yaw). Mirrors the pure-vs-torch
parity approach in ``tests/test_contract.py``.
"""

from __future__ import annotations

import math

import pytest
import torch

from neural_whoop.contract import world_to_body  # noqa: F401 - also makes diffaero importable
from neural_whoop.pilot.policy import obs_from_msp_acro

# neural_whoop's import hook prepends third_party/ to sys.path, so these resolve the vendored fork.
from diffaero.utils.math import euler_to_quaternion  # noqa: E402
from diffaero.utils.p3d_compat import quaternion_to_matrix  # noqa: E402


def _sim_gravity_body(roll: float, pitch: float, yaw: float) -> list[float]:
    """The sim's gravity_body: R from full-euler quat (xyzw -> wxyz), then world_to_body([0,0,-1])."""
    quat_xyzw = euler_to_quaternion(
        torch.tensor([roll]), torch.tensor([pitch]), torch.tensor([yaw])
    )
    R = quaternion_to_matrix(quat_xyzw.roll(1, dims=-1))  # dynamics core feeds q.roll(1) (wxyz)
    down = torch.tensor([[0.0, 0.0, -1.0]])
    return world_to_body(down, R)[0].tolist()


def test_gravity_body_parity_across_attitude_grid():
    worst = 0.0
    for roll_deg in range(-180, 181, 20):
        for pitch_deg in range(-80, 81, 20):
            for yaw_deg in range(-180, 181, 45):
                roll, pitch, yaw = map(math.radians, (roll_deg, pitch_deg, yaw_deg))
                want = _sim_gravity_body(roll, pitch, yaw)
                # obs_from_msp_acro rebuilds gravity_body from att degrees (yaw not supplied).
                att = {"roll_deg": roll_deg, "pitch_deg": pitch_deg}
                imu = {"gyro_raw": (0, 0, 0)}
                got = obs_from_msp_acro(att, imu, 1.0)[:3]
                worst = max(worst, max(abs(g - w) for g, w in zip(got, want)))
    assert worst < 1e-6, f"gravity_body parity broke: worst |Δ| {worst:.2e}"


def test_obs_from_msp_acro_layout_and_gyro_signs():
    """obs-7 layout [gravity_body(3), p, q, r, rot_rem] with the empirical gyro sign convention."""
    # Level, at rest: gravity points straight down in the body frame -> [0, 0, -1].
    obs = obs_from_msp_acro({"roll_deg": 0.0, "pitch_deg": 0.0}, {"gyro_raw": (0, 0, 0)}, 0.7)
    assert len(obs) == 7
    assert obs[0] == 0.0 and obs[1] == 0.0
    assert abs(obs[2] - (-1.0)) < 1e-9
    assert obs[6] == 0.7  # rotation_remaining passthrough
    # Gyro raw -> rad/s with the deploy scale, no axis flips (matches obs_from_msp p/q/r).
    from neural_whoop.pilot.config import GYRO_RAW_TO_DPS

    obs = obs_from_msp_acro({"roll_deg": 0.0, "pitch_deg": 0.0}, {"gyro_raw": (1000, -500, 250)}, 1.0)
    assert abs(obs[3] - math.radians(1000 * GYRO_RAW_TO_DPS)) < 1e-9
    assert abs(obs[4] - math.radians(-500 * GYRO_RAW_TO_DPS)) < 1e-9
    assert abs(obs[5] - math.radians(250 * GYRO_RAW_TO_DPS)) < 1e-9


def test_obs_8_appends_the_maneuver_clock_and_obs_7_is_unchanged():
    """v2's 8th channel is the pilot's TIME clock; omitting it must leave the v1 frame byte-identical.

    The clock is what makes the pre-roll pop learnable — with obs-7 a level, at-rest airframe is a
    fixed point, so a vertical thrust burst is invisible to the policy. It costs no hardware: the
    pilot already owns the maneuver clock, exactly like ``rotation_remaining``.
    """
    att = {"roll_deg": 12.0, "pitch_deg": -7.0}
    imu = {"gyro_raw": (1000, -500, 250)}
    v1 = obs_from_msp_acro(att, imu, 0.6)
    v2 = obs_from_msp_acro(att, imu, 0.6, 0.35)
    assert len(v1) == 7 and len(v2) == 8
    assert v2[:7] == v1                      # the v1 frame is a strict prefix — no channel moved
    assert v2[7] == 0.35                     # maneuver_phase passthrough
    # Both phase channels are pure passthrough: the pilot's signals, never re-derived here.
    assert obs_from_msp_acro(att, imu, 0.0, 1.0)[6:] == [0.0, 1.0]


def test_acro_family_guard_accepts_7_and_8_and_rejects_the_rest():
    """The dim IS the version gate — an obs-7 file must fail loudly where obs-8 is expected."""
    import types

    from neural_whoop.pilot.policy import check_policy_family_acro

    def _pol(base: int, stack: int = 1):
        return types.SimpleNamespace(base_obs_dim=base, obs_stack=stack)

    check_policy_family_acro(_pol(7))        # v1
    check_policy_family_acro(_pol(8))        # v2
    for bad in (5, 6, 9, 11):
        with pytest.raises(SystemExit):
            check_policy_family_acro(_pol(bad))
    with pytest.raises(SystemExit):          # the acro family is single-frame
        check_policy_family_acro(_pol(8, stack=2))
