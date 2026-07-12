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
