"""target_follow: the perception-beachhead task (moving-target following through a noisy detector).

Checks the task seam without training, CPU + tiny batch: obs shape (clean obs-v4), spawn at the
desired standoff centered on the target, the detector-noise observation path, the standoff/in-view
reward, crash termination, and the perception metrics.
"""

import math

import torch

from neural_whoop.contract import world_to_body
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=16, dr_cfg=None, **task_kw):
    task = make_task("target_follow", **task_kw)
    return MultiAgentDroneEnv(task, n_envs=n_envs, device="cpu", seed=0, dr_cfg=dr_cfg)


def test_obs_dim_and_shapes():
    env = _env(n_envs=16)
    assert env.n_agents == 1
    assert env.n_drones == 16
    assert env.obs_dim == env.base_obs_dim == 11  # clean obs-v4, no extra channels
    obs = env.reset_all()
    assert obs.shape == (16, 11)
    assert torch.isfinite(obs).all()


def test_requires_single_agent():
    import pytest

    # n_agents is a DroneTask attribute; the env enforces single-drone in setup().
    task = make_task("target_follow")
    task.n_agents = 2
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(task, n_envs=4, device="cpu", seed=0)


def test_spawn_at_standoff_and_centered():
    # Orbit targets sit at their center height at t=0, so the spawn has ~zero vertical offset and the
    # drone starts exactly d_desired away, facing the target (target centered in the FOV).
    env = _env(n_envs=32, motion="orbit", d_desired=1.5)
    pos, R = env.dyn.pos, env.dyn.R
    tgt = env.task._field.position(env.sim_time)
    rel_body = world_to_body(tgt - pos, R)
    dist = rel_body.norm(dim=-1)
    cos_ang = rel_body[..., 0] / dist.clamp_min(1e-6)
    assert torch.allclose(dist, torch.full_like(dist, 1.5), atol=1e-4)
    assert (cos_ang > 0.999).all()  # target dead-ahead (+x body axis)


def test_detector_noise_path_runs():
    # With the detector seam on, observe() routes through apply_detector_noise + stale-hold.
    dr = DomainRandomizationConfig(
        enabled=True, wind_accel_mps2=0.0, rate_gain_frac=0.0, thrust_scale_frac=0.0,
        obs_noise_std=0.0, action_latency_steps=0,
        detector_bearing_deg=3.0, detector_range_frac=0.1,
        detector_dropout_prob=0.5, detector_fov_deg=110.0,
    )
    env = _env(n_envs=64, dr_cfg=dr, motion="orbit")
    assert not env.dr.cfg.detector.is_identity
    obs = env.reset_all()
    for _ in range(5):
        obs, reward, term, trunc, info = env.step(torch.zeros(env.n_drones, env.act_dim))
    assert obs.shape == (64, 11) and torch.isfinite(obs).all()
    # last_valid stale-hold buffer stays finite (dropout exercised at p=0.5).
    assert torch.isfinite(env.task.last_valid).all()


def test_reward_high_when_tracking():
    # At standoff + centered (fresh spawn, no DR), the standoff bell + in-view + centering terms
    # dominate: reward is strongly positive and every drone is in view.
    env = _env(n_envs=32, motion="orbit", d_desired=1.5, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    env.prev_pos = env.dyn.pos.clone()
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert reward.shape == (32,)
    assert info["in_view"].all()
    # track(1.5==d*)=1.0 * track_scale(1) + in_view_bonus(0.5) + center_scale(0.3)*~1 ≈ 1.8
    assert (reward > 1.0).all()


def test_crash_terminates():
    env = _env(n_envs=4, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    env.dyn.model._state[0, 0:3] = torch.tensor([0.0, 0.0, -1.0])  # below the floor -> crash
    env.prev_pos = env.dyn.pos.clone()
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert terminated.shape == (4,)
    assert bool(terminated[0]) and bool(info["crashed"][0])
    assert reward[0].item() < 0


def test_metrics_keys():
    env = _env(n_envs=16, motion="orbit")
    env.reset_all()
    env.step(torch.zeros(env.n_drones, env.act_dim))
    m = env.task.metrics(env)
    for key in ("time_in_view_rate", "mean_track_error", "mean_distance", "mean_bearing_deg"):
        assert key in m
    assert 0.0 <= m["time_in_view_rate"] <= 1.0
    assert m["mean_track_error"] >= 0.0
    assert math.isfinite(m["mean_bearing_deg"])
