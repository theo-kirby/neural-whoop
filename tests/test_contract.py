"""Contract: batched obs-v4 builder + act-v2 (CTBR) mapping."""

import torch

from neural_whoop.contract import (
    ACT_DIM,
    OBS_DIM,
    ActionLimits,
    action_to_diffaero,
    build_observation,
    world_to_body,
)


def test_world_to_body_identity():
    R = torch.eye(3).expand(5, 3, 3)
    v = torch.randn(5, 3)
    assert torch.allclose(world_to_body(v, R), v, atol=1e-6)


def test_world_to_body_yaw():
    # 90deg yaw: body x-axis points along world +y, so a world +x vector reads as body -y.
    R = torch.tensor([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]).expand(2, 3, 3)
    v = torch.tensor([1.0, 0.0, 0.0]).expand(2, 3)
    out = world_to_body(v, R)
    assert torch.allclose(out, torch.tensor([0.0, -1.0, 0.0]).expand(2, 3), atol=1e-6)


def test_build_observation_shape_and_layout():
    B = 7
    obs = build_observation(
        torch.randn(B, 3), torch.randn(B, 3), torch.randn(B, 3), torch.randn(B, 3),
        torch.eye(3).expand(B, 3, 3),
    )
    assert obs.shape == (B, OBS_DIM) and obs.dtype == torch.float32


def test_action_to_diffaero_hover_and_limits():
    lim = ActionLimits()
    # thrust channel -1 -> 0, +1 -> max; rates scale to limits.
    a = torch.tensor([[-1.0, 0.0, 0.0, 0.0], [1.0, 1.0, -1.0, 1.0]])
    out = action_to_diffaero(a, lim)
    assert out.shape == (2, ACT_DIM)
    assert torch.isclose(out[0, 0], torch.tensor(0.0))
    assert torch.isclose(out[1, 0], torch.tensor(lim.max_thrust_normed))
    assert torch.isclose(out[1, 1], torch.tensor(lim.max_body_rate_rp_rps))
    assert torch.isclose(out[1, 3], torch.tensor(lim.max_body_rate_yaw_rps))


def test_action_clipping():
    out = action_to_diffaero(torch.tensor([[5.0, -9.0, 9.0, 0.0]]))
    lim = ActionLimits()
    assert torch.isclose(out[0, 0], torch.tensor(lim.max_thrust_normed))  # +5 clipped to +1
    assert torch.isclose(out[0, 1], torch.tensor(-lim.max_body_rate_rp_rps))
