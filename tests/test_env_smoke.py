"""End-to-end env + dynamics + registry smoke tests (CPU, small batch)."""

import torch

from neural_whoop.dynamics.whoop import WhoopDynamics
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import TASK_REGISTRY, make_task
import neural_whoop.tasks  # noqa: F401 - register tasks


def test_gate_race_registered():
    assert "gate_race" in TASK_REGISTRY
    task = make_task("gate_race")
    assert task.name == "gate_race" and task.n_agents == 1 and task.obs_dim == 14


def test_dynamics_hover_is_stable():
    dyn = WhoopDynamics(64, device="cpu")
    ctbr = torch.zeros(64, 4)
    ctbr[:, 0] = 1.0  # weight-cancelling hover
    z0 = dyn.pos[:, 2].clone()
    for _ in range(100):
        dyn.step(ctbr)
    assert torch.isfinite(dyn.model._state).all()
    # Hover (thrust == weight) holds altitude to within a few cm over 100 steps.
    assert (dyn.pos[:, 2] - z0).abs().max() < 0.2


def test_env_step_shapes_and_finite():
    env = MultiAgentDroneEnv(make_task("gate_race"), n_envs=128, device="cpu", seed=0)
    obs = env.reset_all()
    assert obs.shape == (128, env.obs_dim) and torch.isfinite(obs).all()
    for _ in range(50):
        a = torch.randn(env.n_drones, env.act_dim) * 0.3
        obs, r, term, trunc, info = env.step(a)
        assert obs.shape == (128, env.obs_dim)
        assert r.shape == (128,) and term.shape == (128,) and trunc.shape == (128,)
        assert torch.isfinite(obs).all() and torch.isfinite(r).all()
    assert "terminal_obs" in info and "time_outs" in info


def test_env_truncation_resets():
    task = make_task("gate_race", episode_len=10)
    env = MultiAgentDroneEnv(task, n_envs=32, device="cpu", seed=0)
    env.reset_all()
    sawtrunc = False
    for _ in range(12):
        _, _, _, trunc, _ = env.step(torch.zeros(env.n_drones, env.act_dim))
        sawtrunc = sawtrunc or bool(trunc.any())
    assert sawtrunc  # episode_len=10 must truncate within 12 steps
