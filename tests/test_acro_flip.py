"""acro_flip: the first agility (acro) task — a learned single-axis barrel roll / flip.

Checks the task seam without training (CPU, tiny batch): the deploy-honest obs (gravity_body +
gyro + rotation phase + the v2 maneuver CLOCK, length 8), the monotone rotation accumulation that
survives a full inversion (the whole reason phi integrates the gyro instead of reading euler roll),
the phase transition + one-time completion bonus, the v2 point-in-space reward signs (lateral
station-keeping; asymmetric altitude, where a pop inside ``pop_allow`` is FREE and a sink is not),
crash termination, the metrics keys, the axis-parameterization (roll drives p, pitch drives q), and
a small env smoke (no NaN, right shapes). Mirrors tests/test_hover.py.
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
    # obs-8: [gravity_body(3), p, q, r, rotation_remaining, maneuver_phase]
    assert env.obs_dim == env.base_obs_dim == 8
    obs = env.reset_all()
    assert obs.shape == (16, 8)
    assert torch.isfinite(obs).all()


def test_obs_layout_at_level_rest():
    # Spawned level and at rest: gravity_body = world-down = [0,0,-1], rates ~0, both phase
    # channels at 1 (nothing rotated yet, no time elapsed on the maneuver clock).
    env = _env(n_envs=16, dr_cfg=_dr_off())
    obs = env.reset_all()
    assert torch.allclose(obs[:, 0:3], torch.tensor([0.0, 0.0, -1.0]).expand(16, 3), atol=1e-4)
    assert torch.allclose(obs[:, 3:6], torch.zeros(16, 3), atol=1e-4)
    assert torch.allclose(obs[:, 6], torch.ones(16), atol=1e-5)  # rotation_remaining starts at 1
    assert torch.allclose(obs[:, 7], torch.ones(16), atol=1e-5)  # maneuver_phase starts at 1


# --- the maneuver clock (obs channel 7, the v2 addition) ---


def test_maneuver_phase_runs_one_to_zero_and_clamps():
    """The clock is a pure function of time since the trigger: 1 -> 0 over maneuver_len_s, then 0.

    This is the channel that makes the pre-roll pop learnable at all — with obs-7 a level, at-rest
    drone is a fixed point (gravity_body is pure attitude, carrying no specific force), so the
    policy cannot tell "just spawned" from "0.2 s into a pop".
    """
    T = 0.5
    env = _env(n_envs=4, dr_cfg=_dr_off(), maneuver_len_s=T)
    env.reset_all()
    n, dt = env.n_drones, env.dt
    a = torch.zeros(n, 4)
    steps = int(T / dt)

    assert torch.allclose(env.task._maneuver_phase(env), torch.ones(n))
    prev = env.task._maneuver_phase(env).clone()
    for i in range(steps):
        env.task.reward_and_done(env, a)
        ph = env.task._maneuver_phase(env)
        assert (ph <= prev + 1e-6).all()                      # monotone non-increasing
        expected = max(0.0, 1.0 - (i + 1) * dt / T)
        assert torch.allclose(ph, torch.full((n,), expected), atol=1e-5)
        prev = ph.clone()

    assert torch.allclose(env.task._maneuver_phase(env), torch.zeros(n), atol=1e-6)
    # Well past the window it CLAMPS at 0 — never negative, never wrapping.
    for _ in range(20):
        env.task.reward_and_done(env, a)
    assert (env.task._maneuver_phase(env) == 0.0).all()


def test_maneuver_phase_is_independent_of_rotation():
    """The clock is time, not angle — spinning fast must not run it down any quicker."""
    env = _env(n_envs=4, dr_cfg=_dr_off())
    env.reset_all()
    n, a = env.n_drones, torch.zeros(env.n_drones, 4)
    for _ in range(10):
        env.dyn.model._state[:, 10] = 12.0     # a hard roll rate: rotation_remaining plummets
        env.task.reward_and_done(env, a)
    spun = env.task._maneuver_phase(env).clone()
    rot = env.task._rotation_remaining()

    still = _env(n_envs=4, dr_cfg=_dr_off())
    still.reset_all()
    for _ in range(10):
        still.task.reward_and_done(still, a)

    assert torch.allclose(spun, still.task._maneuver_phase(still))   # same elapsed time -> same clock
    assert (rot < still.task._rotation_remaining()).all()            # but the ANGLE phase differs
    assert torch.allclose(still.task._rotation_remaining(), torch.ones(n))


def test_invalid_maneuver_len_raises():
    with pytest.raises(ValueError):
        make_task("acro_flip", maneuver_len_s=0.0)


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
    # Level, at rest, ON the spawn point: rotate progress 0, not completed, zero lateral drift,
    # zero altitude error, no crash -> reward is exactly the alive bonus. Every v2 station-keeping
    # term is zero at the reference point by construction, which is what makes it *the* reference.
    env = _env(n_envs=8, dr_cfg=_dr_off())
    env.reset_all()
    n = env.n_drones
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(n, 4))
    assert reward.shape == (n,)
    assert not terminated.any()
    assert torch.allclose(reward, torch.full((n,), env.task.cfg.alive_bonus), atol=1e-3)


# --- the v2 point-in-space terms (lateral station-keeping + asymmetric altitude) ---


def _reward_at(env, *, dxy=(0.0, 0.0), dz=0.0):
    """Reward for a drone displaced from its spawn point, everything else at rest/level."""
    env.dyn.model._state[:, 0] = env.task.xy0[:, 0] + dxy[0]
    env.dyn.model._state[:, 1] = env.task.xy0[:, 1] + dxy[1]
    env.dyn.model._state[:, 2] = env.task.z0 + dz
    r, _, _ = env.task.reward_and_done(env, torch.zeros(env.n_drones, 4))
    return r


def test_lateral_drift_is_penalized_linearly():
    """v1 had NO lateral term at all — which is exactly why it threw a wide barrel roll."""
    env = _env(n_envs=4, dr_cfg=_dr_off(), lat_scale=1.0)
    env.reset_all()
    base = _reward_at(env, dxy=(0.0, 0.0)).clone()
    near = _reward_at(env, dxy=(0.2, 0.0)).clone()
    far = _reward_at(env, dxy=(0.0, 0.6)).clone()
    assert (near < base).all() and (far < near).all()
    # −lat_scale·‖xy − xy0‖: the penalty is the Euclidean distance, in either horizontal direction.
    assert torch.allclose(base - near, torch.full_like(base, 0.2), atol=1e-4)
    assert torch.allclose(base - far, torch.full_like(base, 0.6), atol=1e-4)


def test_altitude_is_asymmetric_a_pop_is_free_and_a_sink_is_not():
    """The load-bearing v2 change: rising within pop_allow costs NOTHING, sinking always costs.

    v1's symmetric ``alt_scale·|z − z0|`` punished exactly the pre-roll pop the tight flip needs
    while under-punishing the sink that made the old roll shed ~0.4 m.
    """
    env = _env(n_envs=4, dr_cfg=_dr_off(),
               lat_scale=1.0, sink_scale=1.0, rise_scale=0.2, pop_allow=0.4)
    env.reset_all()
    base = _reward_at(env, dz=0.0).clone()

    # Rising inside the free headroom: exactly free.
    assert torch.allclose(_reward_at(env, dz=0.2), base, atol=1e-4)
    assert torch.allclose(_reward_at(env, dz=0.4), base, atol=1e-4)
    # Past it: taxed at rise_scale on the EXCESS only.
    assert torch.allclose(base - _reward_at(env, dz=0.6), torch.full_like(base, 0.2 * 0.2), atol=1e-4)
    # Sinking: taxed at sink_scale from the very first millimetre, with no allowance.
    assert torch.allclose(base - _reward_at(env, dz=-0.2), torch.full_like(base, 1.0 * 0.2), atol=1e-4)
    # And the asymmetry is the point: an equal-magnitude sink costs far more than a rise.
    assert (_reward_at(env, dz=-0.3) < _reward_at(env, dz=0.3)).all()


def test_settle_term_is_gated_to_the_recover_phase():
    """Return-and-stop only applies AFTER the rotation completes — mid-flip it must not fight it.

    Every other phased term is zeroed here so the settle delta is the ONLY thing that can move.
    """
    env = _env(n_envs=4, dr_cfg=_dr_off(), settle_scale=0.5, lat_scale=0.0, sink_scale=0.0,
               rise_scale=0.0, upright_scale=0.0, spin_penalty=0.0, completion_bonus=0.0)
    env.reset_all()
    before = _reward_at(env, dxy=(0.3, 0.0)).clone()          # not completed -> ungated, no cost
    # Force the recover phase: phi past Φ, and already-completed so no crossing bonus fires.
    env.task.phi = torch.full_like(env.task.phi, env.task.target_phi * 2)
    env.task.completed = torch.ones_like(env.task.completed)
    after = _reward_at(env, dxy=(0.3, 0.0)).clone()
    # settle_scale·(‖xy − xy0‖ + |z − z0| + ‖vel‖) = 0.5·(0.3 + 0 + 0), and nothing else changed.
    assert torch.allclose(before - after, torch.full_like(before, 0.15), atol=1e-4)


def test_alive_bonus_no_longer_dominates_the_episode():
    """v1's 0.1 x 200 steps = 20 was the largest term in the episode and swamped all shaping."""
    cfg = make_task("acro_flip").cfg
    assert cfg.alive_bonus * cfg.episode_len < cfg.completion_bonus


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
        "max_lateral_drift",     # v2: the shape metrics the point-in-space claim is graded on
        "peak_climb",
        "settle_pos_error",
        "post_recovery_tilt_deg",
        "crash_rate_per_step",
    ):
        assert key in m
    assert 0.0 <= m["flip_success_rate"] <= 1.0
    assert m["mean_altitude_loss"] >= 0.0
    assert m["max_lateral_drift"] >= 0.0
    assert m["peak_climb"] >= 0.0                 # a POP is a success here, not a regression
    assert m["settle_pos_error"] >= 0.0
    assert math.isfinite(m["post_recovery_tilt_deg"])


def test_scene_marks_the_station_keeping_point():
    """The spawn point rides the replay's `scene.target` so "in place" is visible, not just measured."""
    env = _env(n_envs=8, dr_cfg=_dr_off())
    env.reset_all()
    scene = env.task.scene_objects(env)
    assert scene["target"].shape == (8, 3)
    assert torch.allclose(scene["target"][:, :2], env.task.xy0)
    assert torch.allclose(scene["target"][:, 2], env.task.z0)
    # At spawn the marker IS where the drone is.
    assert torch.allclose(scene["target"], env.dyn.pos, atol=1e-5)


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
    assert obs.shape == (16, 8)
    for _ in range(5):
        action = torch.rand(env.n_drones, 4) * 2 - 1
        obs, reward, term, trunc, info = env.step(action)
        assert obs.shape == (16, 8)
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
