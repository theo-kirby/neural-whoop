"""acro_flip: the first agility (acro) task — a learned single-axis barrel roll / flip.

Checks the task seam without training (CPU, tiny batch): the deploy-honest obs (gravity_body +
gyro + phase, length 7), the monotone rotation accumulation that survives a full inversion (the
whole reason phi integrates the gyro instead of reading euler roll), the phase transition +
one-time completion bonus, the reward signs, crash termination, the metrics keys, the
axis-parameterization (roll drives p, pitch drives q), and a small env smoke (no NaN, right
shapes). Mirrors tests/test_hover.py.
"""

import math

import pytest
import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
from neural_whoop.reward import rotation_progress
import neural_whoop.tasks  # noqa: F401 - register tasks

from diffaero.utils.math import euler_to_quaternion


def _env(n_envs=16, dr_cfg=None, **task_kw):
    task = make_task("acro_flip", **task_kw)
    return MultiAgentDroneEnv(task, n_envs=n_envs, device="cpu", seed=0, dr_cfg=dr_cfg)


def _dr_off():
    return DomainRandomizationConfig(enabled=False)


# --- observation ---


def test_obs_dim_and_shapes():
    env = _env(n_envs=16)
    assert env.n_agents == 1
    assert env.n_drones == 16
    assert env.obs_dim == env.base_obs_dim == 7  # [gravity_body(3), p, q, r, rotation_remaining]
    obs = env.reset_all()
    assert obs.shape == (16, 7)
    assert torch.isfinite(obs).all()


def test_obs_layout_at_level_rest():
    # Spawned level and at rest: gravity_body = world-down = [0,0,-1], rates ~0, phase remaining = 1.
    env = _env(n_envs=16, dr_cfg=_dr_off())
    obs = env.reset_all()
    assert torch.allclose(obs[:, 0:3], torch.tensor([0.0, 0.0, -1.0]).expand(16, 3), atol=1e-4)
    assert torch.allclose(obs[:, 3:6], torch.zeros(16, 3), atol=1e-4)
    assert torch.allclose(obs[:, 6], torch.ones(16), atol=1e-5)  # rotation_remaining starts at 1


def test_requires_single_agent():
    task = make_task("acro_flip")
    task.n_agents = 2
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(task, n_envs=4, device="cpu", seed=0)


# --- rotation accumulation (the core mechanic) ---


def test_rotation_accumulates_monotonically_through_inversion():
    # Drive a constant roll rate p and integrate phi by hand-calling reward_and_done (no dynamics
    # advance). Halfway through, force an INVERTED attitude: euler roll wraps at ±π, but phi (a
    # gyro integral) does not — it keeps climbing linearly, and rotation_remaining decreases
    # monotonically to exactly 0.
    env = _env(n_envs=8, dr_cfg=_dr_off())
    env.reset_all()
    n = env.n_drones
    p, dt, Phi = 6.0, env.dt, env.task.target_phi
    steps = int(Phi / (p * dt)) + 5  # a few past completion
    a = torch.zeros(n, 4)

    assert torch.allclose(env.task._rotation_remaining(), torch.ones(n))  # starts at 1
    prev_rem = env.task._rotation_remaining().clone()
    for i in range(steps):
        env.dyn.model._state[:, 10] = p  # keep the roll rate (gyro channel p)
        if i == steps // 2:
            q = euler_to_quaternion(torch.full((n,), math.pi), torch.zeros(n), torch.zeros(n))
            env.dyn.model._state[:, 3:7] = q  # flip upside-down mid-maneuver
        env.task.reward_and_done(env, a)
        rem = env.task._rotation_remaining()
        assert (rem <= prev_rem + 1e-6).all()  # monotone non-increasing, unbroken by the inversion
        prev_rem = rem.clone()

    assert (env.task._rotation_remaining() == 0.0).all()  # saturated at completion
    assert env.task.completed.all()
    # phi is a clean linear gyro integral, unaffected by the euler-wrapping attitude change.
    assert torch.allclose(env.task.phi, torch.full((n,), steps * p * dt), atol=1e-3)


def test_completion_bonus_fires_once():
    env = _env(n_envs=4, dr_cfg=_dr_off())
    env.reset_all()
    n = env.n_drones
    p, dt, Phi = 6.0, env.dt, env.task.target_phi
    a = torch.zeros(n, 4)
    near = int(Phi / (p * dt))  # phi lands just below Phi after this many steps

    for _ in range(near):
        env.dyn.model._state[:, 10] = p
        env.task.reward_and_done(env, a)
    assert (env.task.phi < Phi).all() and not env.task.completed.any()

    env.dyn.model._state[:, 10] = p
    r_cross, _, _ = env.task.reward_and_done(env, a)  # this step crosses Phi
    assert env.task.completed.all()

    env.dyn.model._state[:, 10] = p
    r_after, _, _ = env.task.reward_and_done(env, a)  # already completed -> no second bonus
    # The one-time +10 completion bonus is present at the crossing and gone after (recover terms
    # are O(0.5), so the ~10 gap is unambiguously the bonus).
    assert (r_cross - r_after > 5.0).all()


# --- reward signs / termination ---


def test_reward_is_alive_bonus_at_level_rest():
    # Level, at rest, on z0, zero action: rotate progress 0, not completed, alt error 0, no crash
    # -> reward is exactly the alive bonus.
    env = _env(n_envs=8, dr_cfg=_dr_off())
    env.reset_all()
    n = env.n_drones
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(n, 4))
    assert reward.shape == (n,)
    assert not terminated.any()
    assert torch.allclose(reward, torch.full((n,), env.task.cfg.alive_bonus), atol=1e-3)


def test_crash_terminates():
    env = _env(n_envs=4, dr_cfg=_dr_off())
    env.reset_all()
    env.dyn.model._state[0, 0:3] = torch.tensor([0.0, 0.0, -1.0])  # below the floor -> crash
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, 4))
    assert bool(terminated[0]) and bool(info["crashed"][0])
    assert reward[0].item() < 0


# --- axis parameterization ---


def test_axis_selects_the_rate_channel():
    # A pitch-axis flip integrates q (channel 1), NOT p (channel 0).
    env = _env(n_envs=4, dr_cfg=_dr_off(), axis="pitch")
    env.reset_all()
    env.dyn.model._state[:, 11] = 6.0  # q (pitch rate)
    env.task.reward_and_done(env, torch.zeros(env.n_drones, 4))
    assert (env.task.phi > 0).all()

    other = _env(n_envs=4, dr_cfg=_dr_off(), axis="pitch")
    other.reset_all()
    other.dyn.model._state[:, 10] = 6.0  # p (roll rate) must NOT advance a pitch flip
    other.task.reward_and_done(other, torch.zeros(other.n_drones, 4))
    assert (other.task.phi == 0.0).all()


def test_invalid_axis_raises():
    with pytest.raises(ValueError):
        make_task("acro_flip", axis="yaw")


# --- metrics / scene ---


def test_metrics_keys():
    env = _env(n_envs=16)
    env.reset_all()
    env.step(torch.zeros(env.n_drones, 4))
    m = env.task.metrics(env)
    for key in (
        "flip_success_rate",
        "mean_completion_time",
        "mean_altitude_loss",
        "post_recovery_tilt_deg",
        "crash_rate_per_step",
    ):
        assert key in m
    assert 0.0 <= m["flip_success_rate"] <= 1.0
    assert m["mean_altitude_loss"] >= 0.0
    assert math.isfinite(m["post_recovery_tilt_deg"])


def test_scene_command_is_rotation_remaining():
    env = _env(n_envs=8, dr_cfg=_dr_off())
    env.reset_all()
    scene = env.task.scene_objects(env)
    assert "command" in scene and scene["command"].shape == (8,)
    assert torch.allclose(scene["command"], torch.ones(8), atol=1e-5)  # remaining = 1 at spawn


# --- env smoke (no NaN through the full step path) ---


def test_env_smoke_random_actions():
    env = _env(n_envs=16)
    obs = env.reset_all()
    assert obs.shape == (16, 7)
    for _ in range(5):
        action = torch.rand(env.n_drones, 4) * 2 - 1
        obs, reward, term, trunc, info = env.step(action)
        assert obs.shape == (16, 7)
        assert torch.isfinite(obs).all()
        assert torch.isfinite(reward).all()
        assert reward.shape == (16,)


# --- the pure rotation-progress primitive ---


def test_rotation_progress_saturates_and_floors():
    Phi = 6.0
    # normal progress passes through
    assert torch.allclose(rotation_progress(torch.tensor([1.0]), torch.tensor([2.0]), Phi), torch.tensor([1.0]))
    # saturates at the target (only the sub-target portion counts)
    assert torch.allclose(rotation_progress(torch.tensor([5.5]), torch.tensor([7.0]), Phi), torch.tensor([0.5]))
    # entirely past the target -> zero (can't farm over-spin)
    assert torch.allclose(rotation_progress(torch.tensor([6.5]), torch.tensor([8.0]), Phi), torch.tensor([0.0]))
    # below zero -> zero (counter-rotation earns nothing)
    assert torch.allclose(rotation_progress(torch.tensor([-2.0]), torch.tensor([-1.0]), Phi), torch.tensor([0.0]))
    # scale applies
    assert torch.allclose(rotation_progress(torch.tensor([1.0]), torch.tensor([2.0]), Phi, 3.0), torch.tensor([3.0]))
