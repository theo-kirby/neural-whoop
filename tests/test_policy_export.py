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
    dep = DeployPolicy(actor, std=torch.full((4,), 0.5))
    path = export_torchscript(dep, 14, str(tmp_path / "p.pt"))
    loaded = torch.jit.load(path)
    x = torch.randn(8, 14)
    assert torch.allclose(loaded(x), dep(x), atol=1e-5)
    assert (dep(x).abs() <= 1.0 + 1e-6).all()  # effective mean stays inside the action space


def test_clipped_gaussian_mean_matches_monte_carlo():
    """The closed form must equal the empirical mean of clip(N(mu, sigma)) — the quantity PPO
    actually optimized. This is the hover_blind trim-bias fix: deploying raw clip(mu) is biased
    wherever mu sits within ~2 sigma of a bound."""
    from neural_whoop.training.ppo import clipped_gaussian_mean

    gen = torch.Generator().manual_seed(0)
    mu = torch.tensor([-0.5616, 0.0, 0.9, -1.4, 2.0])
    sigma = torch.tensor([0.478, 0.3, 0.6, 0.5, 0.1])
    samples = torch.randn(2_000_000, 5, generator=gen) * sigma + mu
    mc = samples.clamp(-1.0, 1.0).mean(0)
    closed = clipped_gaussian_mean(mu, sigma)
    assert torch.allclose(closed, mc, atol=2e-3)
    # Deep-interior mean (mu=0, 3+ sigma from both bounds) is unbiased: correction ~= identity.
    assert abs(closed[1].item()) < 1e-3


def test_deploy_matches_act_deterministic():
    """DeployPolicy (exported path) and ActorCritic.act_deterministic (eval path) must agree."""
    from neural_whoop.training.export import build_deploy_policy
    from neural_whoop.training.ppo import ActorCritic, PPOConfig

    agent = ActorCritic(obs_dim=5, act_dim=4, cfg=PPOConfig()).eval()
    dep = build_deploy_policy(agent)
    x = torch.randn(16, 5)
    with torch.no_grad():
        assert torch.allclose(dep(x), agent.act_deterministic(x), atol=1e-6)
