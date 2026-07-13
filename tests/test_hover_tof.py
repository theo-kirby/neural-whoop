"""hover_tof: the measured-height channel + its deploy-matched sensor model.

The sensor must mirror the pilot's estimator structure exactly (tilt-corrected reading ==
true z over a flat floor, zero-order-held when stale/saturated/tilted), advance exactly once
per step (in reward_and_done — observe() is called twice on reset steps and must be a pure
read), seed from the clamped spawn height at reset, and stack cleanly (obs_dim 6 -> 48 at
stack 8). Reward/spawn/metrics are inherited from hover_blind/hover and covered by their tests.
"""

import math

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=8, obs_stack=1, **kw):
    task = make_task("hover_tof", **kw)
    return MultiAgentDroneEnv(
        task, n_envs=n_envs, device="cpu", seed=0,
        dr_cfg=DomainRandomizationConfig(enabled=False),
        obs_stack=obs_stack,
    )


def test_obs_dim_and_stacking():
    env = _env(n_envs=8, obs_stack=8)
    assert make_task("hover_tof").obs_dim == 6
    assert env.base_obs_dim == 6 and env.obs_dim == 48
    obs = env.reset_all()
    assert obs.shape == (8, 48)
    assert torch.isfinite(obs).all()


def test_observe_is_pure_read():
    # The env calls observe() twice on reset steps (terminal + post-reset frame): a stateful
    # sensor draw there would double-advance the hold process. Two reads must be identical.
    env = _env(n_envs=8)
    env.reset_all()
    env.step(torch.zeros(8, 4))
    o1 = env.task.observe(env)
    o2 = env.task.observe(env)
    assert torch.equal(o1, o2)


def test_obs_channel_is_height_error():
    env = _env(n_envs=8)
    obs = env.reset_all()
    task = env.task
    # Channel 5 = setpoint_z - h_meas, the same "target minus measurement" sign as target_rel.
    assert torch.allclose(obs[:, 5], task.setpoint[:, 2] - task.h_meas, atol=1e-6)
    rpy, w = env.dyn.rpy, env.dyn.ang_vel_body
    assert torch.allclose(obs[:, 0], rpy[:, 0], atol=1e-5)
    assert torch.allclose(obs[:, 2:5], w, atol=1e-5)


def test_fresh_valid_reading_tracks_true_z():
    # In-band, level, always-ranging (rate >> control rate -> p_update 1): h_meas == true z.
    env = _env(n_envs=4, hold_fraction=1.0, z_min=0.6, z_max=1.0, tof_rate_hz=1000.0)
    env.reset_all()
    task = env.task
    for _ in range(10):
        env.step(torch.zeros(4, 4))  # zero action = 2x hover thrust: a clean climb, no crash
        assert (env.t > 0).all()     # no env reset mid-check (would re-seed the sensor)
        assert torch.allclose(task.h_meas, env.dyn.pos[:, 2], atol=1e-6)


def test_rate_zero_never_updates():
    env = _env(n_envs=4, hold_fraction=1.0, z_min=0.6, z_max=1.0, tof_rate_hz=0.0)
    env.reset_all()
    task = env.task
    seed = task.h_meas.clone()
    for _ in range(10):
        env.step(torch.zeros(4, 4))
        assert (env.t > 0).all()
    assert torch.equal(task.h_meas, seed)  # p_update 0: pure hold forever


def test_saturation_holds_at_last_valid():
    # Spawn far above the sensor band: the seed clamps to tof_max and no reading ever lands —
    # the channel reports the held 1.3, never true z. (This is the honest saturation pathology:
    # configs keep SETPOINTS inside the band; only spawns/excursions go above it.)
    env = _env(n_envs=4, hold_fraction=1.0, z_min=2.0, z_max=2.2, tof_rate_hz=1000.0,
               tof_max_m=1.3)
    obs = env.reset_all()
    task = env.task
    assert torch.allclose(task.h_meas, torch.full((4,), 1.3))
    assert torch.allclose(obs[:, 5], task.setpoint[:, 2] - 1.3, atol=1e-6)
    for _ in range(5):
        env.step(torch.zeros(4, 4))
        assert (env.t > 0).all()
        assert (env.dyn.pos[:, 2] > 1.3).all()  # still above range (zero action climbs)
        assert torch.allclose(task.h_meas, torch.full((4,), 1.3))


def test_tilt_gates_the_reading():
    env = _env(n_envs=4, hold_fraction=1.0, z_min=0.6, z_max=1.0, tof_rate_hz=1000.0,
               tof_tilt_limit_deg=45.0)
    env.reset_all()
    task = env.task
    # Tilt past the gate, then arrange an obvious would-be innovation: it must be held.
    d_idx = torch.arange(4)
    env.spawn(d_idx, env.dyn.pos.clone(), roll=torch.full((4,), math.radians(60.0)))
    task.h_meas = torch.full((4,), 0.123)
    task.reward_and_done(env, torch.zeros(4, 4))
    assert torch.allclose(task.h_meas, torch.full((4,), 0.123))


def test_reset_seeds_clamped_spawn_height():
    env = _env(n_envs=8, hold_fraction=1.0, z_min=0.6, z_max=1.0)
    env.reset_all()
    task = env.task
    task.h_meas = torch.full((8,), 9.9)
    idx = torch.tensor([0, 3])
    env.reset_idx(idx)
    z = env.dyn.pos[idx, 2]
    assert torch.allclose(task.h_meas[idx], z.clamp(0.0, task.cfg.tof_max_m), atol=1e-6)
    assert task.h_meas[1] == 9.9  # untouched env keeps its state


def test_hover_metrics_include_z_error():
    env = _env(n_envs=4)
    env.reset_all()
    env.step(torch.zeros(4, 4))
    m = env.task.metrics(env)
    assert "mean_z_error" in m and math.isfinite(m["mean_z_error"])
