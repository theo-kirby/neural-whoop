"""hover: the reliability beachhead (auto-stabilization / station-keeping with disturbance recovery).

Checks the task seam without training (CPU, tiny batch): obs shape (clean obs-v4), the setpoint
observation/scene, the station-keeping reward sign, crash termination, the hold metrics — plus the
shared impulse seam (``DomainRandomizer.impulse_dv``/``impulse_dw`` and
``WhoopDynamics.add_body_rate``) that both training and the live editor drive.
"""

import math

import torch

from neural_whoop.contract import world_to_body
from neural_whoop.dynamics.whoop import WhoopDynamics
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=16, dr_cfg=None, **task_kw):
    task = make_task("hover", **task_kw)
    return MultiAgentDroneEnv(task, n_envs=n_envs, device="cpu", seed=0, dr_cfg=dr_cfg)


def test_obs_dim_and_shapes():
    env = _env(n_envs=16)
    assert env.n_agents == 1
    assert env.n_drones == 16
    assert env.obs_dim == env.base_obs_dim == 11  # clean obs-v4, unchanged
    obs = env.reset_all()
    assert obs.shape == (16, 11)
    assert torch.isfinite(obs).all()


def test_requires_single_agent():
    import pytest

    task = make_task("hover")
    task.n_agents = 2
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(task, n_envs=4, device="cpu", seed=0)


def test_setpoint_observation_matches_state():
    # The first 3 obs channels are the body-frame vector to the setpoint.
    env = _env(n_envs=32, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    pos, R = env.dyn.pos, env.dyn.R
    rel_body = world_to_body(env.task.setpoint - pos, R)
    obs = env.task.observe(env)
    assert torch.allclose(obs[:, 0:3], rel_body.to(torch.float32), atol=1e-5)
    # scene_objects surfaces the setpoint under the reused "target" marker key.
    scene = env.task.scene_objects(env)
    assert "target" in scene and scene["target"].shape == (32, 3)


def test_reward_high_when_on_setpoint_and_level():
    # Spawn on-setpoint, level, at rest -> position bell ~1 + upright ~1 + alive, no penalties.
    env = _env(n_envs=32, hold_fraction=1.0, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    env.prev_pos = env.dyn.pos.clone()
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert reward.shape == (32,)
    assert not terminated.any()
    # pos_scale(1)*~1 + upright_scale(0.5)*~1 + alive(0.1) ~= 1.6, minus tiny vel/spin -> > 1.0
    assert (reward > 1.0).all()


def test_crash_terminates():
    env = _env(n_envs=4, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    env.dyn.model._state[0, 0:3] = torch.tensor([0.0, 0.0, -1.0])  # below the floor -> crash
    env.prev_pos = env.dyn.pos.clone()
    reward, terminated, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert bool(terminated[0]) and bool(info["crashed"][0])
    assert reward[0].item() < 0


def test_metrics_keys():
    env = _env(n_envs=16)
    env.reset_all()
    env.step(torch.zeros(env.n_drones, env.act_dim))
    m = env.task.metrics(env)
    for key in ("mean_pos_error", "mean_speed", "mean_tilt_deg", "hold_rate", "crash_rate_per_step"):
        assert key in m
    assert 0.0 <= m["hold_rate"] <= 1.0
    assert m["mean_pos_error"] >= 0.0
    assert math.isfinite(m["mean_tilt_deg"])


def test_step_info_exposes_per_step_metric_tensors():
    env = _env(n_envs=8, dr_cfg=DomainRandomizationConfig(enabled=False))
    env.reset_all()
    _, _, _, _, info = env.step(torch.zeros(env.n_drones, env.act_dim))
    m = info["metrics"]
    for key in ("mean_pos_error", "mean_speed", "mean_tilt_deg", "hold_rate"):
        assert m[key].shape == (8,)
        assert torch.isfinite(m[key]).all()
    assert ((m["hold_rate"] == 0.0) | (m["hold_rate"] == 1.0)).all()


def test_evaluate_metrics_survive_lockstep_truncation_boundary():
    # Regression: the task's episode accumulators zero on auto-reset. With no crashes (huge
    # bounds) every env truncates in lockstep, and a horizon that's an exact multiple of
    # episode_len used to clobber the accumulators right before evaluate() read them,
    # reporting ~0 pos error / ~0 hold rate. The rollout-wide info["metrics"] aggregation
    # must report the real (nonzero) falling-drone position error instead.
    from neural_whoop.eval.rollout import evaluate

    env = _env(
        n_envs=8,
        episode_len=5,
        bound_xy=1e6,
        bound_z_min=-1e6,
        bound_z_max=1e6,
        dr_cfg=DomainRandomizationConfig(enabled=False),
    )

    class _ZeroAgent:
        def actor(self, obs):
            return torch.zeros(obs.shape[0], env.act_dim)

        def act_deterministic(self, obs):
            return self.actor(obs)

    m = evaluate(env, _ZeroAgent(), steps=10)  # 2 lockstep episodes exactly
    assert m["mean_pos_error"] > 0.05  # drones drift/fall: real error, not the post-reset zeros
    assert m["crash_rate_per_step"] == 0.0


# --- the shared impulse seam (training + live editor) ---


def test_impulse_disabled_by_default_is_zero():
    # Existing tasks must be unchanged: impulse defaults to off -> always-zero deltas.
    dr = DomainRandomizer(DomainRandomizationConfig(enabled=True), n_drones=64, act_dim=4, dt=0.02)
    assert torch.count_nonzero(dr.impulse_dv()) == 0
    assert torch.count_nonzero(dr.impulse_dw()) == 0


def test_impulse_fires_and_is_bounded():
    cfg = DomainRandomizationConfig(
        enabled=True, impulse_prob=1.0, impulse_vel_mps=3.0, impulse_rate_rps=5.0
    )
    dr = DomainRandomizer(cfg, n_drones=256, act_dim=4, dt=0.02)
    dv, dw = dr.impulse_dv(), dr.impulse_dw()
    assert dv.shape == (256, 3) and dw.shape == (256, 3)
    # prob=1.0 -> every drone kicked; magnitudes within their configured caps.
    assert (dv.norm(dim=-1) > 0).all()
    assert (dv.norm(dim=-1) <= 3.0 + 1e-5).all()
    assert (dw.norm(dim=-1) <= 5.0 + 1e-5).all()


def test_impulse_scales_with_curriculum():
    cfg = DomainRandomizationConfig(
        enabled=True, impulse_prob=1.0, impulse_vel_mps=4.0, impulse_rate_rps=0.0
    )
    dr = DomainRandomizer(cfg, n_drones=512, act_dim=4, dt=0.02)
    dr.scale = 0.25  # curriculum: shrink both incidence and magnitude
    dv = dr.impulse_dv()
    assert (dv.norm(dim=-1) <= 4.0 * 0.25 + 1e-5).all()


def test_add_body_rate_clamps():
    dyn = WhoopDynamics(n_drones=8, device="cpu")
    before = dyn.ang_vel_body.clone()
    dyn.add_body_rate(torch.full((8, 3), 1.0))
    assert torch.allclose(dyn.ang_vel_body, before + 1.0, atol=1e-5)
    # A huge kick is clamped to ±w_max (the saturation guard), not left unbounded.
    dyn.add_body_rate(torch.full((8, 3), 1e3))
    assert (dyn.ang_vel_body.abs() <= dyn._w_max + 1e-3).all()
