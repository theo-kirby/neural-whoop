"""Reward primitives + the render-free perception seam (oracle + detector noise)."""

import math

import torch

from neural_whoop.perception.estimator import DetectorNoise, OracleEstimator, apply_detector_noise
from neural_whoop.reward import Bounds, is_crashed, progress_reward, smoothness_penalty


def test_progress_reward():
    assert torch.allclose(progress_reward(torch.tensor([2.0]), torch.tensor([1.5])), torch.tensor([0.5]))


def test_smoothness_penalty():
    a = torch.zeros(3, 4)
    b = torch.ones(3, 4)
    pen = smoothness_penalty(a, b, weight=1.0)
    assert torch.allclose(pen, torch.full((3,), 4.0))  # ||0-1||^2 over 4 dims
    assert torch.allclose(smoothness_penalty(a, b, 0.0), torch.zeros(3))


def test_is_crashed_bounds():
    b = Bounds(xy=5.0, z_min=0.1, z_max=4.0)
    pos = torch.tensor([[0.0, 0.0, 1.0], [6.0, 0.0, 1.0], [0.0, 0.0, 0.0], [0.0, 0.0, 5.0]])
    out = is_crashed(pos, b)
    assert out.tolist() == [False, True, True, True]


def test_oracle_passthrough():
    rel = torch.randn(10, 3)
    est, conf = OracleEstimator().estimate(rel)
    assert torch.allclose(est, rel) and torch.allclose(conf, torch.ones(10))


def test_detector_fov_cull_stale_holds():
    # Target behind the drone (body -x) is outside any forward FOV -> stale-hold.
    rel = torch.tensor([[-1.0, 0.0, 0.0]])
    last = torch.tensor([[9.0, 9.0, 9.0]])
    det = DetectorNoise(fov_half_rad=math.radians(30.0))
    est, fresh = apply_detector_noise(rel, det, last)
    assert not fresh.item()
    assert torch.allclose(est, last)


def test_detector_forward_target_seen():
    rel = torch.tensor([[2.0, 0.0, 0.0]])  # straight ahead
    det = DetectorNoise(fov_half_rad=math.radians(40.0))
    est, fresh = apply_detector_noise(rel, det, torch.zeros(1, 3))
    assert fresh.item()
    assert torch.allclose(est, rel, atol=1e-5)
