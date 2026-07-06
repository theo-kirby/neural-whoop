"""hover_blind_v2: the vz_est channel + its deploy-matched leaky climb-rate estimator.

The estimator must mirror scripts/pilot.py exactly (leaky high-pass of true vz, tilt-freeze,
clamp), advance exactly once per step (in reward_and_done — observe() is called twice on reset
steps and must be a pure read), zero at reset, and stack cleanly (obs_dim 6 -> 18 at stack 3).
Reward/spawn/metrics are inherited from hover_blind/hover and covered by their tests.
"""

import math

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=8, obs_stack=1, **kw):
    task = make_task("hover_blind_v2", **kw)
    return MultiAgentDroneEnv(
        task, n_envs=n_envs, device="cpu", seed=0,
        dr_cfg=DomainRandomizationConfig(enabled=False),
        obs_stack=obs_stack,
    )


def test_obs_dim_and_stacking():
    env = _env(n_envs=8, obs_stack=3)
    assert make_task("hover_blind_v2").obs_dim == 6
    assert env.base_obs_dim == 6 and env.obs_dim == 18
    obs = env.reset_all()
    assert obs.shape == (8, 18)
    assert torch.isfinite(obs).all()


def test_observe_is_pure_read():
    # The env calls observe() twice on reset steps (terminal + post-reset frame): a stateful
    # estimator there would double-integrate. Two consecutive reads must be identical.
    env = _env(n_envs=8)
    env.reset_all()
    env.step(torch.zeros(8, 4))
    o1 = env.task.observe(env)
    o2 = env.task.observe(env)
    assert torch.equal(o1, o2)


def test_obs_channels_are_base_plus_vz():
    env = _env(n_envs=8)
    obs = env.reset_all()
    task = env.task
    assert torch.allclose(obs[:, 5], task.vz_est)  # zeroed at reset
    rpy, w = env.dyn.rpy, env.dyn.ang_vel_body
    assert torch.allclose(obs[:, 0], rpy[:, 0], atol=1e-5)
    assert torch.allclose(obs[:, 2:5], w, atol=1e-5)


def test_estimator_matches_leaky_highpass():
    # Closed-form reference on a real velocity profile: hover spawn (level, at rest), zero
    # action = 2x hover thrust -> a clean upward-accelerating vz. No crashes in 20 steps.
    env = _env(n_envs=4, hold_fraction=1.0, z_min=1.0, z_max=1.2)
    env.reset_all()
    task = env.task
    decay = math.exp(-env.dt / task.cfg.vz_tau_s)
    ref = task.vz_est.clone()
    prev = env.dyn.vel_world[:, 2].clone()
    for _ in range(20):
        env.step(torch.zeros(4, 4))
        assert (env.t > 0).all()  # no env reset mid-check (would re-seed the estimator)
        vz_now = env.dyn.vel_world[:, 2]
        ref = ((ref + (vz_now - prev)) * decay).clamp(-task.cfg.vz_clamp, task.cfg.vz_clamp)
        prev = vz_now.clone()
        assert torch.allclose(task.vz_est, ref, atol=1e-5)
    assert task.vz_est.abs().max() > 0.05  # the profile actually exercised the estimator


def test_freeze_on_tilt_decays_only():
    env = _env(n_envs=4, hold_fraction=1.0)
    env.reset_all()
    task = env.task
    # Tilt past the freeze limit, then arrange a would-be innovation: it must be discarded.
    d_idx = torch.arange(4)
    env.spawn(d_idx, env.dyn.pos.clone(), roll=torch.full((4,), math.radians(40.0)))
    task.vz_est = torch.full((4,), 0.5)
    task._prev_vz = torch.full((4,), -1.0)  # innovation of +1 m/s if not frozen
    task.reward_and_done(env, torch.zeros(4, 4))
    decay = math.exp(-env.dt / task.cfg.vz_tau_s)
    assert torch.allclose(task.vz_est, torch.full((4,), 0.5 * decay), atol=1e-6)
    # The reference still tracks current velocity (tilted evidence is dropped, not deferred).
    assert torch.allclose(task._prev_vz, env.dyn.vel_world[:, 2], atol=1e-6)


def test_clamp():
    env = _env(n_envs=4, hold_fraction=1.0)  # level spawns: innovation is not tilt-frozen
    env.reset_all()
    task = env.task
    task._prev_vz = torch.full((4,), -100.0)  # absurd innovation
    task.reward_and_done(env, torch.zeros(4, 4))
    assert torch.allclose(task.vz_est, torch.full((4,), task.cfg.vz_clamp))
    task._prev_vz = torch.full((4,), 100.0)
    task.reward_and_done(env, torch.zeros(4, 4))
    assert torch.allclose(task.vz_est, torch.full((4,), -task.cfg.vz_clamp))


def test_reset_zeroes_and_seeds_prev_vz():
    env = _env(n_envs=8, hold_fraction=0.0, spawn_vel=1.5)  # moving spawns: seed is meaningful
    env.reset_all()
    task = env.task
    task.vz_est = torch.ones(8)
    idx = torch.tensor([0, 3])
    env.reset_idx(idx)
    assert (task.vz_est[idx] == 0).all()
    assert task.vz_est[1] == 1.0  # untouched env keeps its state
    # _prev_vz seeded from the post-spawn velocity: no phantom first-step innovation.
    assert torch.allclose(task._prev_vz[idx], env.dyn.vel_world[idx, 2], atol=1e-6)
