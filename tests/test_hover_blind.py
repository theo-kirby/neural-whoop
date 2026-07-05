"""hover_blind: the IMU-only observation ablation of hover (no-flow-deck first flight).

Checks the observation seam (CPU, tiny batch): obs is exactly [roll, pitch, p, q, r] and
matches the dynamics state; everything else (reward, spawn, metrics) is inherited from hover
and covered by test_hover.py.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=16, **kw):
    task = make_task("hover_blind", **kw)
    return MultiAgentDroneEnv(
        task, n_envs=n_envs, device="cpu", seed=0,
        dr_cfg=DomainRandomizationConfig(enabled=False),
    )


def test_obs_dim_and_shapes():
    env = _env(n_envs=16)
    assert env.obs_dim == env.base_obs_dim == 5
    obs = env.reset_all()
    assert obs.shape == (16, 5)
    assert torch.isfinite(obs).all()


def test_obs_is_attitude_and_rates():
    env = _env(n_envs=32)
    obs = env.reset_all()
    rpy, w = env.dyn.rpy, env.dyn.ang_vel_body
    assert torch.allclose(obs[:, 0], rpy[:, 0], atol=1e-5)  # roll
    assert torch.allclose(obs[:, 1], rpy[:, 1], atol=1e-5)  # pitch
    assert torch.allclose(obs[:, 2:5], w, atol=1e-5)        # p, q, r
    # No translational channels: stepping with a lateral push must not leak position into obs.
    env.dyn.add_velocity(torch.tensor([1.0, 0.0, 0.0]).expand(32, 3))
    obs2, *_ = env.step(torch.zeros(32, 4))
    assert obs2.shape == (32, 5)
    assert torch.isfinite(obs2).all()


def test_registered_and_single_agent():
    import pytest

    task = make_task("hover_blind")
    assert task.obs_dim == 5
    task.n_agents = 2
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(task, n_envs=4, device="cpu", seed=0)
