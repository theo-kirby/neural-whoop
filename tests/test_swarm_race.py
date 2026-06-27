"""swarm_race: the first multi-drone task (Flywheel hop-13).

Checks the swarm seam without training: obs shape (neighbour channel), well-separated spawns,
nearest-neighbour geometry, collision detection -> per-env shared-fate termination, and the swarm
metrics. CPU, tiny batch.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=8, n_agents=3):
    task = make_task("swarm_race", n_agents=n_agents, collision_radius=0.25, spawn_spread=0.6)
    return MultiAgentDroneEnv(task, n_envs=n_envs, device="cpu", seed=0)


def test_obs_dim_and_drone_count():
    env = _env(n_envs=8, n_agents=3)
    assert env.n_agents == 3
    assert env.n_drones == 24
    assert env.obs_dim == env.base_obs_dim == 20  # 11 + 3 lookahead + 6 neighbour
    obs = env.reset_all()
    assert obs.shape == (24, 20)
    assert torch.isfinite(obs).all()


def test_requires_multi_agent():
    import pytest

    with pytest.raises(ValueError):
        make_task("swarm_race", n_agents=1)


def test_spawn_well_separated():
    # Fresh spawns must start above the collision radius (no instant collision).
    env = _env(n_envs=16, n_agents=3)
    _, _, min_sep = env.task._nearest_neighbour(env)
    assert min_sep.min().item() > env.task.cfg.collision_radius


def test_nearest_neighbour_geometry():
    env = _env(n_envs=4, n_agents=3)
    # Place env 0's three drones at known points; nearest of drone 0 is drone 1 (1 m away).
    st = env.dyn.model._state
    st[0, 0:3] = torch.tensor([0.0, 0.0, 1.0])
    st[1, 0:3] = torch.tensor([1.0, 0.0, 1.0])
    st[2, 0:3] = torch.tensor([5.0, 0.0, 1.0])
    rel_pos, _, min_sep = env.task._nearest_neighbour(env)
    assert abs(min_sep[0].item() - 1.0) < 1e-5
    # rel = neighbour - self, world frame -> drone 0 sees +x neighbour.
    assert torch.allclose(rel_pos[0], torch.tensor([1.0, 0.0, 0.0]), atol=1e-5)


def test_collision_terminates_env_and_penalizes():
    env = _env(n_envs=4, n_agents=3)
    env.reset_all()
    st = env.dyn.model._state
    # Collide env 1's drones 0 and 1 (flat drone idx 3 and 4); keep env 0,2,3 separated already.
    st[3, 0:3] = torch.tensor([1.0, 1.0, 1.0])
    st[4, 0:3] = torch.tensor([1.05, 1.0, 1.0])  # 5 cm apart < 0.25 collision radius
    env.prev_pos = env.dyn.pos.clone()
    action = torch.zeros(env.n_drones, env.act_dim)
    reward, terminated_env, info = env.task.reward_and_done(env, action)
    assert terminated_env.shape == (4,)
    assert bool(terminated_env[1])           # env 1 ends on the collision (shared fate)
    assert bool(info["collided"][3]) and bool(info["collided"][4])
    # The two colliding drones are penalized.
    assert reward[3].item() < 0 and reward[4].item() < 0


def test_metrics_keys():
    env = _env(n_envs=8, n_agents=3)
    env.reset_all()
    env.step(torch.zeros(env.n_drones, env.act_dim))
    m = env.task.metrics(env)
    for key in (
        "best_lap_time", "lap_completion_rate", "collision_rate_per_step",
        "mean_min_separation", "n_agents",
    ):
        assert key in m
    assert m["n_agents"] == 3.0
    assert 0.0 <= m["collision_rate_per_step"] <= 1.0


def test_step_runs_and_shapes():
    env = _env(n_envs=8, n_agents=3)
    obs = env.reset_all()
    for _ in range(5):
        obs, reward, term, trunc, info = env.step(torch.zeros(env.n_drones, env.act_dim))
    assert obs.shape == (24, 20)
    assert reward.shape == (24,)
    assert term.shape == (24,)  # per-drone (env repeat_interleaved by the env)
