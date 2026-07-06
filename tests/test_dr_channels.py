"""Per-channel obs noise + per-episode obs bias DR (the honest-noise seam).

``obs_noise_std_channels`` overrides the scalar std per channel (the measured whoop gyro floor
is 250x the attitude channels' noise); ``obs_bias_channels`` draws an episode-constant uniform
bias per drone per channel at reset (mount bias / vz DC offset), curriculum-scaled at draw time
like ``thrust_scale``. Both are per-frame pre-stacking, so a bias is automatically constant
across a stacked observation.
"""

import pytest
import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer
import neural_whoop.tasks  # noqa: F401 - register tasks


def _dr(obs_dim=5, n=4096, scale=1.0, seed=0, **kw):
    cfg = DomainRandomizationConfig(enabled=True, **kw)
    dr = DomainRandomizer(cfg, n_drones=n, act_dim=4, dt=0.02, device="cpu",
                          generator=torch.Generator(device="cpu").manual_seed(seed),
                          obs_dim=obs_dim)
    dr.scale = scale
    dr.reset(torch.arange(n))
    return dr


def test_per_channel_std_applied_and_overrides_scalar():
    dr = _dr(obs_noise_std_channels=(0.0, 0.0, 2.5, 0.0, 0.0), obs_noise_std=9.9)
    obs = torch.zeros(4096, 5)
    out = dr.add_obs_noise(obs)
    # Zero-std channels stay exact (the scalar 9.9 is overridden, not blended).
    assert torch.equal(out[:, [0, 1, 3, 4]], obs[:, [0, 1, 3, 4]])
    assert abs(out[:, 2].std().item() - 2.5) < 0.15


def test_per_channel_std_respects_curriculum_scale():
    lo = _dr(scale=0.25, obs_noise_std_channels=(1.0,) * 5)
    obs = torch.zeros(4096, 5)
    assert abs(lo.add_obs_noise(obs).std().item() - 0.25) < 0.02


def test_bias_constant_within_episode_resampled_at_reset():
    dr = _dr(n=256, obs_noise_std_channels=(0.0,) * 5, obs_noise_std=0.0,
             obs_bias_channels=(0.0, 0.0, 0.0, 0.0, 1.0))
    obs = torch.zeros(256, 5)
    a = dr.add_obs_noise(obs)
    b = dr.add_obs_noise(obs)
    assert torch.equal(a, b)                    # constant across steps within an episode
    assert a[:, 4].abs().max() > 0.0            # actually drawn
    assert a[:, 4].abs().max() <= 1.0 + 1e-6    # within the configured range
    assert torch.equal(a[:, :4], obs[:, :4])    # zero-range channels untouched
    before = dr.obs_bias.clone()
    dr.reset(torch.tensor([0, 1]))
    assert not torch.allclose(dr.obs_bias[:2], before[:2])  # resampled for reset drones
    assert torch.equal(dr.obs_bias[2:], before[2:])         # others untouched


def test_bias_zero_at_scale_zero():
    dr = _dr(n=256, scale=0.0, obs_bias_channels=(1.0,) * 5)
    assert (dr.obs_bias == 0).all()


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        _dr(obs_dim=5, obs_noise_std_channels=(0.1,) * 6)
    with pytest.raises(ValueError):
        _dr(obs_dim=5, obs_bias_channels=(0.1,) * 4)


def test_scalar_path_unchanged_when_lists_empty():
    dr = _dr(obs_noise_std=0.0)
    obs = torch.randn(4096, 5)
    assert torch.equal(dr.add_obs_noise(obs), obs)


def test_env_wires_obs_dim_and_bias_is_additive():
    cfg = DomainRandomizationConfig(
        enabled=True, wind_accel_mps2=0.0, action_latency_steps=0, impulse_prob=0.0,
        obs_noise_std=0.0, obs_noise_std_channels=(0.0,) * 5, obs_bias_channels=(0.5,) * 5,
    )
    env = MultiAgentDroneEnv(make_task("hover_blind"), n_envs=8, device="cpu", seed=0,
                             dr_cfg=cfg, obs_stack=3)
    obs = env.reset_all()
    chunks = obs.view(8, 3, 5)
    # The noised frame is exactly the clean observation plus this episode's bias, and the bias
    # (applied per-frame, pre-stacking) is constant across the stacked history.
    assert torch.allclose(chunks[:, 0], env.task.observe(env) + env.dr.obs_bias, atol=1e-6)
    assert torch.allclose(chunks[:, 0], chunks[:, 2])


def test_env_channel_mismatch_raises():
    cfg = DomainRandomizationConfig(enabled=True, obs_noise_std_channels=(0.1,) * 7)
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(make_task("hover_blind"), n_envs=4, device="cpu", seed=0, dr_cfg=cfg)
