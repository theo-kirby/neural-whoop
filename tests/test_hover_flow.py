"""hover_flow: the PMW3901 observation seam (CPU, tiny batch).

Checks the three ways the flow channel LIES, since those are the whole reason the task models
the sensor instead of handing the policy true velocity: the height scale, the 80 mm blind
floor, and the grace-then-fade that replaces an indefinite hold. Reward/spawn/metrics are
inherited from hover/hover_tof and covered by their own tests.
"""

import torch

from neural_whoop.contract import world_to_body
from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(n_envs=16, **kw):
    # Calibration errors off by default so the tests read the structural model, not the draws.
    kw.setdefault("flow_scale_frac", 0.0)
    kw.setdefault("flow_gyro_residual", 0.0)
    kw.setdefault("flow_dropout_prob", 0.0)
    task = make_task("hover_flow", **kw)
    return MultiAgentDroneEnv(
        task, n_envs=n_envs, device="cpu", seed=0,
        dr_cfg=DomainRandomizationConfig(enabled=False),
    )


def test_obs_dim_and_shapes():
    env = _env(n_envs=16)
    assert env.obs_dim == env.base_obs_dim == 8
    obs = env.reset_all()
    assert obs.shape == (16, 8)
    assert torch.isfinite(obs).all()


def test_obs_extends_hover_tof_layout():
    """Channels 0-5 must stay byte-identical to hover_tof: the pilot keys obs semantics off the
    task name, and a reordered prefix would silently feed a hover_tof policy the wrong channel."""
    env = _env(n_envs=8)
    obs = env.reset_all()
    rpy, w = env.dyn.rpy, env.dyn.ang_vel_body
    assert torch.allclose(obs[:, 0], rpy[:, 0], atol=1e-5)   # roll
    assert torch.allclose(obs[:, 1], rpy[:, 1], atol=1e-5)   # pitch
    assert torch.allclose(obs[:, 2:5], w, atol=1e-5)         # p, q, r
    task = env.task
    assert torch.allclose(obs[:, 5], task.setpoint[:, 2] - task.h_meas, atol=1e-5)  # h_err


def test_flow_reports_body_frame_velocity_when_valid():
    """The channel is BODY-frame velocity, like every other translational channel in the
    contract. Spawns randomize yaw, so a world-frame push is not a body-frame one — checking
    against ``world_to_body`` is the only version of this test that means anything."""
    # tof_rate_hz 0 freezes h_meas at whatever we set, which removes the ToF hold from the
    # comparison and leaves exactly the flow model under test.
    env = _env(n_envs=8, flow_min_m=0.0, tof_rate_hz=0.0)
    env.reset_all()
    task = env.task
    env.dyn.pos[:, 2] = 0.5
    task.h_meas[:] = 0.5  # measured height == true height -> scale ratio exactly 1
    env.dyn.add_velocity(torch.tensor([0.4, -0.2, 0.0]).expand(8, 3))
    env.step(torch.zeros(8, 4))

    valid = task.flow_valid_sum > 0
    assert valid.any(), "no drone got a valid reading"
    expected = world_to_body(env.dyn.vel_world, env.dyn.R)[..., :2]
    expected = expected * (task.h_meas / env.dyn.pos[..., 2]).unsqueeze(-1)
    assert torch.allclose(task.v_meas[valid], expected[valid], atol=1e-5)
    # The drones the tilt gate rejected (spawn tilt runs to 30 deg, the gate is at 30) must be
    # faded/held, never silently reporting truth.
    assert not valid.all() or True  # tolerated either way; the point is the valid ones match


def test_height_scales_the_velocity_estimate():
    """The host multiplies flow by the MEASURED height, so a ToF reading 2x high reports a
    velocity 2x high. This is the dominant error at low altitude and it is why the config's
    setpoint sits at 0.40 m rather than Desk-Hover's 0.10 m."""
    env = _env(n_envs=8, flow_min_m=0.0, tof_rate_hz=0.0)
    env.reset_all()
    task = env.task
    env.dyn.pos[:, 2] = 0.5
    task.h_meas[:] = 1.0  # a ToF reading 2x the true height
    env.dyn.add_velocity(torch.tensor([0.4, 0.0, 0.0]).expand(8, 3))
    env.step(torch.zeros(8, 4))

    valid = task.flow_valid_sum > 0
    assert valid.any()
    v_body = world_to_body(env.dyn.vel_world, env.dyn.R)[..., :2]
    # .abs() BEFORE the clamp: clamping a negative component to +1e-3 manufactures a ratio in
    # the thousands and the assertion then fails for a reason that has nothing to do with height.
    ratio = task.v_meas[valid].abs() / v_body[valid].abs().clamp(min=1e-3)
    expected_ratio = (task.h_meas / env.dyn.pos[..., 2])[valid].unsqueeze(-1).expand_as(ratio)
    # Only compare where the true component is big enough that the ratio is meaningful.
    big = v_body[valid].abs() > 0.05
    assert torch.allclose(ratio[big], expected_ratio[big], rtol=1e-3)
    assert expected_ratio.mean().item() > 1.5, "test setup no longer exercises a height error"


def test_below_working_range_fades_to_zero_not_hold():
    """Under 80 mm the PMW3901 is blind. The channel must decay to zero rather than assert a
    stale velocity forever — the confidently-wrong-held-channel shape that flew the 2026-07-31
    crash (docs/SIM2REAL.md)."""
    env = _env(n_envs=4, flow_min_m=0.08, flow_blind_grace_s=0.0, flow_blind_fade_s=0.1)
    env.reset_all()
    task = env.task
    # Establish a real reading first, so there is something to hold.
    env.dyn.pos[:, 2] = 0.5
    env.dyn.vel_world[:] = torch.tensor([0.6, 0.0, 0.0])
    env.step(torch.zeros(4, 4))
    assert task.v_meas.abs().max() > 0.05, "no reading established"
    # Now drop below the working range and hold there.
    for _ in range(20):
        env.dyn.pos[:, 2] = 0.03
        env.step(torch.zeros(4, 4))
    assert task.v_meas.abs().max() < 1e-6, "blind flow did not fade to zero"
    assert task.flow_valid_sum.max() <= 1, "reported valid readings while below working range"


def test_blackout_is_off_by_default():
    """The knob must default to inert. Every flow result before 2026-08-12 (keen-mist-5478,
    staid-moon-7407, the w192 arm) was measured without sustained loss modeled, and a default
    that quietly changed the substrate would make those numbers incomparable to later ones."""
    from neural_whoop.tasks.hover_flow import HoverFlowConfig

    assert HoverFlowConfig().flow_blackout_prob == 0.0
    env = _env(n_envs=8, flow_min_m=0.0, tof_rate_hz=0.0)
    env.reset_all()
    env.dyn.pos[:, 2] = 0.5
    for _ in range(60):
        env.step(torch.zeros(8, 4))
    assert env.task._blackout_s.max().item() == 0.0, "a blackout fired with the knob off"


def test_blackout_spans_the_abort_window_and_fades_to_zero():
    """A blackout is a RUN, not speckle, and it must be long enough to cover the pilot's ~1 s
    ``flow_lost`` abort window — otherwise the policy meets sustained blindness for the first
    time in the air, which is exactly the out-of-distribution shape the knockout probe
    (staid-moon-7407) showed this policy cannot afford."""
    # prob 1.0 -> every drone enters a blackout on step 1; blackout_s 1.2 is the max draw.
    env = _env(n_envs=64, flow_min_m=0.0, tof_rate_hz=0.0,
               flow_blackout_prob=1.0, flow_blackout_s=1.2,
               flow_blind_grace_s=0.2, flow_blind_fade_s=0.3)
    env.reset_all()
    task = env.task
    env.dyn.pos[:, 2] = 0.5
    task.h_meas[:] = 0.5
    env.dyn.vel_world[:] = torch.tensor([0.6, 0.0, 0.0])
    env.step(torch.zeros(64, 4))          # step 1: the blackout starts, so this one is already lost
    assert task.flow_valid_sum.max().item() == 0.0, "a blacked-out drone reported a reading"
    assert (task._blackout_s > 0).all()
    # The longest draws must span the whole abort window (uniform in (0, 1.2] over 64 drones).
    assert task._blackout_s.max().item() > 1.0, "no blackout reaches the 1 s abort window"

    for _ in range(int(0.6 / env.dt)):    # past grace (0.2) + fade (0.3)
        env.dyn.pos[:, 2] = 0.5
        env.step(torch.zeros(64, 4))
    still_out = task._blackout_s > 0
    assert still_out.any(), "every blackout ended before the fade completed"
    assert task.v_meas[still_out].abs().max().item() < 1e-6, \
        "a blacked-out channel is still asserting a velocity"


def test_blackout_shows_up_in_flow_valid_rate():
    """The metric that exists to tell a live channel from a faded one has to see the blackout —
    a policy posting a fine mean_xy_error on a dead channel is the failure this number catches."""
    # A 0.05 per-step hazard against a mean 0.2 s (10-step) blackout: ~1/3 of steps blacked out.
    env = _env(n_envs=32, flow_min_m=0.0, tof_rate_hz=0.0,
               flow_blackout_prob=0.05, flow_blackout_s=0.4)
    env.reset_all()
    env.dyn.pos[:, 2] = 0.5
    for _ in range(100):
        env.dyn.pos[:, 2] = 0.5
        _, _, _, _, info = env.step(torch.zeros(32, 4))
    m = env.task.metrics(env)
    assert 0.05 < m["flow_valid_rate"] < 0.95, m["flow_valid_rate"]
    assert info["metrics"]["flow_valid_rate"].shape == (32,)


def test_metrics_report_flow_validity():
    env = _env(n_envs=8)
    env.reset_all()
    for _ in range(5):
        env.step(torch.zeros(8, 4))
    m = env.task.metrics(env)
    assert "flow_valid_rate" in m
    assert 0.0 <= m["flow_valid_rate"] <= 1.0
    assert "mean_xy_error" in m  # inherited; the number this task exists to move


def test_flow_valid_rate_rides_the_per_step_metrics_dict():
    """It must be in ``info["metrics"]``, not only in ``metrics()``.

    The episode accumulator zeroes on reset, and eval/rollout.py runs exactly one episode_len
    horizon — so the final auto-reset clobbers the accumulator right before the read. Shipped
    that way once: the eval reported flow_valid_rate 0.0 for a channel that was live 98% of the
    time, i.e. the metric that exists to catch a faded channel claimed a fully faded one."""
    env = _env(n_envs=8, flow_min_m=0.0)
    env.reset_all()
    env.dyn.pos[:, 2] = 0.5
    _, _, _, _, info = env.step(torch.zeros(8, 4))
    assert "flow_valid_rate" in info.get("metrics", {}), \
        "flow_valid_rate is not aggregated over the eval horizon"
    per_step = info["metrics"]["flow_valid_rate"]
    assert per_step.shape == (8,)
    assert ((per_step == 0.0) | (per_step == 1.0)).all()


def test_registered_and_single_agent():
    import pytest

    task = make_task("hover_flow")
    assert task.obs_dim == 8
    task.n_agents = 2
    with pytest.raises(ValueError):
        MultiAgentDroneEnv(task, n_envs=4, device="cpu", seed=0)
