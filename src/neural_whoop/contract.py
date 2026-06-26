"""The policy <-> env contract: obs-v4 builder and act-v2 (CTBR) rescaling, **batched torch**.

This is the simulator-independent seam ported from neural-whoop-lab, rewritten to operate on
batched GPU tensors (leading ``(..., )`` dims of any shape — typically ``(n_envs, n_agents)``).
Keeping the (bug-prone) interface math here, pure and unit-tested, means it is identical in
sim and on hardware: the env fills these from DiffAero state; a real whoop would fill them
from onboard estimates.

obs-v4  (length 11): body-frame, heading-invariant, no absolute-yaw oracle::

    [gx, gy, gz,   target-relative vector, body frame (next gate / movable-target estimate)
     vx, vy, vz,   linear velocity, body frame
     roll, pitch,  gravity-tilt (yaw dropped — not observable without a magnetometer)
     p, q, r]      body angular rates (gyro)

act-v2  (length 4): CTBR (Betaflight acro), normalized to [-1, 1]::

    [collective_thrust, body_rate_x(roll), body_rate_y(pitch), body_rate_z(yaw)]

DiffAero's ``RateController`` consumes ``[normed_thrust, roll_rate, pitch_rate, yaw_rate]``
where ``normed_thrust == 1.0`` is a weight-cancelling hover and the rates are in rad/s. The
:func:`action_to_diffaero` map turns our symmetric ``[-1, 1]`` action into that convention.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

OBS_DIM = 11
ACT_DIM = 4

# obs-v2 (vision): proprio-only body-frame state (minus the target oracle), for camera tasks.
PROPRIO_DIM = 8


def world_to_body(vec_w: Tensor, R: Tensor) -> Tensor:
    """Rotate a world-frame vector into the body frame, batched.

    Args:
        vec_w: World-frame vectors, shape ``(..., 3)``.
        R: Body->world rotation matrices, shape ``(..., 3, 3)`` (columns are body axes in world).

    Returns:
        Body-frame vectors ``(..., 3)``: ``R^T @ vec_w``.
    """
    return torch.matmul(R.transpose(-1, -2), vec_w.unsqueeze(-1)).squeeze(-1)


def build_observation(
    target_rel_world: Tensor,
    velocity_world: Tensor,
    rpy: Tensor,
    ang_velocity_body: Tensor,
    R: Tensor,
) -> Tensor:
    """Assemble the obs-v4 (body-frame, length-11) vector, batched.

    Args:
        target_rel_world: Vector from drone to the target (next gate center / target estimate),
            world frame, shape ``(..., 3)``.
        velocity_world: Linear velocity, world frame, shape ``(..., 3)``.
        rpy: Roll/pitch/yaw (radians), shape ``(..., 3)``. Yaw is dropped from the obs.
        ang_velocity_body: Body angular velocity ``[p, q, r]`` (rad/s), shape ``(..., 3)``.
        R: Body->world rotation matrices, shape ``(..., 3, 3)``.

    Returns:
        float32 obs-v4 tensor of shape ``(..., 11)``.
    """
    gate_b = world_to_body(target_rel_world, R)
    vel_b = world_to_body(velocity_world, R)
    roll = rpy[..., 0:1]
    pitch = rpy[..., 1:2]
    obs = torch.cat([gate_b, vel_b, roll, pitch, ang_velocity_body], dim=-1)
    return obs.to(torch.float32)


@dataclass(frozen=True)
class ActionLimits:
    """Physical limits the normalized ``[-1, 1]`` CTBR action maps onto.

    Defaults are tuned for a tiny whoop-class quad: high agility (acro rates) but a bounded
    thrust envelope. ``hover_thrust_normed`` is DiffAero's weight-cancelling thrust (==1.0 in
    its controller); the thrust channel spans ``[0, max_thrust_normed]`` in those units.

    Attributes:
        max_thrust_normed: Max collective thrust in DiffAero normed units (1.0 == hover).
            With a TWR ceiling of ~4, the policy can pull up to 4x weight.
        hover_thrust_normed: Thrust that cancels gravity (DiffAero convention, ==1.0).
        max_body_rate_rp_rps: Max |roll/pitch rate| commanded (rad/s).
        max_body_rate_yaw_rps: Max |yaw rate| commanded (rad/s).
    """

    max_thrust_normed: float = 4.0
    hover_thrust_normed: float = 1.0
    max_body_rate_rp_rps: float = 12.0   # ~690 deg/s — aggressive acro for a whoop
    max_body_rate_yaw_rps: float = 6.0   # ~340 deg/s yaw


def action_to_diffaero(action: Tensor, limits: ActionLimits | None = None) -> Tensor:
    """Map a normalized act-v2 tensor in ``[-1, 1]`` to DiffAero's CTBR action convention.

    Returns ``[normed_thrust, roll_rate, pitch_rate, yaw_rate]`` where ``normed_thrust`` is in
    DiffAero units (1.0 == hover) and the rates are rad/s. The thrust channel maps the input
    ``[-1, 1]`` affinely onto ``[0, max_thrust_normed]``; rates map linearly onto their limits.
    Inputs are clipped to ``[-1, 1]`` first (defensive — policy output should already be tanh'd).

    Args:
        action: Normalized action, shape ``(..., 4)``.
        limits: Physical :class:`ActionLimits`.

    Returns:
        DiffAero-convention action, same leading shape, last dim 4.
    """
    limits = limits or ActionLimits()
    a = action.clamp(-1.0, 1.0)
    thrust = (a[..., 0:1] + 1.0) * 0.5 * limits.max_thrust_normed
    wx = a[..., 1:2] * limits.max_body_rate_rp_rps
    wy = a[..., 2:3] * limits.max_body_rate_rp_rps
    wz = a[..., 3:4] * limits.max_body_rate_yaw_rps
    return torch.cat([thrust, wx, wy, wz], dim=-1)
