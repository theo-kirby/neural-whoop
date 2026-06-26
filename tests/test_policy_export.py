"""Tiny policy + the deploy export path (TorchScript round-trip)."""

import torch

from neural_whoop.policies.tiny_policy import TinyPolicy, TinyPolicyConfig
from neural_whoop.training.export import DeployPolicy, export_torchscript


def test_tiny_policy_shape_and_bounds():
    pol = TinyPolicy(TinyPolicyConfig(obs_dim=14, act_dim=4, output="tanh"))
    out = pol(torch.randn(32, 14))
    assert out.shape == (32, 4)
    assert (out.abs() <= 1.0 + 1e-6).all()
    assert pol.num_parameters() < 20_000  # stays tiny


def test_tiny_policy_deterministic():
    pol = TinyPolicy(TinyPolicyConfig(obs_dim=11, act_dim=4)).eval()
    x = torch.randn(4, 11)
    assert torch.allclose(pol(x), pol(x))


def test_deploy_torchscript_roundtrip(tmp_path):
    actor = TinyPolicy(TinyPolicyConfig(obs_dim=14, act_dim=4, output="none"))
    dep = DeployPolicy(actor)
    path = export_torchscript(dep, 14, str(tmp_path / "p.pt"))
    loaded = torch.jit.load(path)
    x = torch.randn(8, 14)
    assert torch.allclose(loaded(x), dep(x), atol=1e-5)
    assert (dep(x).abs() <= 1.0 + 1e-6).all()  # clamped to action space
