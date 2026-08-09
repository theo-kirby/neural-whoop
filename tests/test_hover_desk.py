"""The desk-scale additions to the hover family: spawn_z_margin, vxy_penalty, the drift metrics.

Desk-Hover (``configs/desk-hover.yaml``) holds 0.10 m over a desk instead of 1.0 m in a 3.5 m
arena, which shrinks every length in the task by ~10x. Three things break or go silent at that
scale, and this file pins all three:

1. ``spawn_z_margin`` — the spawn-z clamp was hard-coded at 0.2 m, which is *larger than the whole
   desk band*. Every spawn, including the pure-hold cohort that is meant to start exactly on its
   setpoint, got clamped ~12 cm above it, and nothing failed.
2. ``vxy_penalty`` — a new (privileged) reward term, so it must be exactly additive and its
   default must be bit-identical to before.
3. ``mean_xy_error`` / ``mean_height`` / ``above_band_rate`` / ``ep_peak_z_m`` — the drift/altitude
   split, which must respect the ``ep_``-prefix discipline (``tests/test_reference_track.py``):
   ``eval/rollout.py`` *means* every per-step tensor over the horizon, so a peak emitted per-step
   would silently be reported as a mean height.
"""

import pytest
import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.randomization import DomainRandomizationConfig
import neural_whoop.tasks  # noqa: F401 - register tasks


#: The Desk-Hover geometry, as the configs set it (see configs/desk-hover.yaml).
DESK = dict(
    arena_radius=0.0,
    z_min=0.08,
    z_max=0.16,
    bound_xy=0.60,
    bound_z_min=0.010,
    bound_z_max=0.60,
    spawn_z_margin=0.005,
)


def _env(n_envs=16, task="hover", seed=0, **task_kw):
    t = make_task(task, **task_kw)
    return MultiAgentDroneEnv(
        t, n_envs=n_envs, device="cpu", seed=seed,
        dr_cfg=DomainRandomizationConfig(enabled=False),
    )


# --- 1. spawn_z_margin ---

def test_spawn_z_margin_is_the_clamp_and_defaults_to_the_old_hard_coded_value():
    """The margin is honoured verbatim; 0.2 (the old literal) is still the default."""
    from neural_whoop.tasks.hover import HoverConfig

    assert HoverConfig().spawn_z_margin == 0.2

    env = _env(n_envs=256, bound_z_min=1.0, bound_z_max=3.0, spawn_z_margin=0.5,
               z_min=1.0, z_max=3.0, spawn_offset=5.0, hold_fraction=0.0)
    env.reset_all()
    z = env.dyn.pos[:, 2]
    assert z.min() >= 1.5 - 1e-6
    assert z.max() <= 2.5 + 1e-6


def test_desk_pure_hold_cohort_spawns_ON_its_setpoint():
    """The regression that motivated the knob.

    With the old hard-coded 0.2 m margin and desk bounds, spawn z clamps to >= 0.21 m while
    setpoints live in 0.08-0.16 m — so the ``hold_fraction`` cohort, whose entire definition is
    "starts on the setpoint, level, at rest", starts ~12 cm above it. Silent: no error, no metric
    moves, the reward just quietly measures a fly-down instead of a hold.
    """
    env = _env(n_envs=256, hold_fraction=1.0, **DESK)
    env.reset_all()
    err = (env.dyn.pos - env.task.setpoint).norm(dim=-1)
    assert err.max() < 1e-6, f"pure-hold cohort spawned {err.max():.4f} m off its setpoint"

    # ...and the old margin is exactly what broke it.
    old = _env(n_envs=256, hold_fraction=1.0, **{**DESK, "spawn_z_margin": 0.2})
    old.reset_all()
    assert (old.dyn.pos[:, 2] - old.task.setpoint[:, 2]).min() > 0.05


def test_inverted_spawn_clamp_raises_instead_of_pinning_every_spawn():
    """``torch.clamp(min>max)`` silently returns ``max`` — a typo would otherwise be invisible."""
    with pytest.raises(ValueError, match="spawn_z_margin"):
        make_task("hover", bound_z_min=0.01, bound_z_max=0.60, spawn_z_margin=0.3)
    # Exactly-no-room is also rejected (the clamp would collapse to a point).
    with pytest.raises(ValueError, match="spawn_z_margin"):
        make_task("hover", bound_z_min=0.0, bound_z_max=1.0, spawn_z_margin=0.5)


# --- 2. vxy_penalty ---

def _rewards(vxy_penalty, n_envs=64):
    env = _env(n_envs=n_envs, vxy_penalty=vxy_penalty, hold_fraction=0.0, spawn_vel=1.5)
    env.reset_all()
    action = torch.zeros(env.n_drones, env.act_dim)
    reward, _, _ = env.task.reward_and_done(env, action)
    return reward, env.dyn.vel_world.clone()


def test_vxy_penalty_subtracts_exactly_k_times_horizontal_speed():
    k = 0.5
    r0, vel0 = _rewards(0.0)
    rk, velk = _rewards(k)
    # Same seed, same construction order -> identical state, so the reward difference is the term.
    assert torch.allclose(vel0, velk, atol=0.0)
    assert torch.allclose(r0 - rk, k * vel0[:, :2].norm(dim=-1), atol=1e-6)


def test_vxy_penalty_default_is_bit_identical_to_before():
    """The default must be a no-op, not a small-op: additions to a shared reward must be additive."""
    r_default, _ = _rewards(0.0)
    env = _env(n_envs=64, hold_fraction=0.0, spawn_vel=1.5)  # config_cls default, term absent
    env.reset_all()
    r_absent, _, _ = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert torch.equal(r_default, r_absent)


# --- 3. the drift / altitude metrics ---

@pytest.mark.parametrize("task", ["hover", "hover_blind", "hover_blind_v2", "hover_tof"])
def test_drift_metrics_are_per_step_tensors_on_every_inherited_task(task):
    env = _env(n_envs=8, task=task)
    env.reset_all()
    _, _, _, _, info = env.step(torch.zeros(env.n_drones, env.act_dim))
    for key in ("mean_xy_error", "mean_height", "above_band_rate"):
        assert key in info["metrics"], f"{task}: {key} must be per-step so eval aggregates it"
        assert info["metrics"][key].shape == (8,)
        assert torch.isfinite(info["metrics"][key]).all()


def test_mean_xy_error_is_horizontal_only():
    env = _env(n_envs=32, hold_fraction=0.0, **DESK)
    env.reset_all()
    _, _, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    expect = (env.task.setpoint[:, :2] - env.dyn.pos[:, :2]).norm(dim=-1)
    assert torch.allclose(info["metrics"]["mean_xy_error"], expect, atol=1e-6)
    # ...and it is NOT the 3-D error (the whole point of splitting them).
    assert not torch.allclose(info["metrics"]["mean_xy_error"], info["metrics"]["mean_pos_error"])


def test_above_band_rate_counts_only_steps_above_the_ceiling():
    env = _env(n_envs=32, band_ceiling_m=0.30, hold_fraction=1.0, **DESK)
    env.reset_all()
    _, _, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert info["metrics"]["above_band_rate"].sum() == 0.0  # pure hold sits at 0.08-0.16 m
    env.dyn.pos[:, 2] = 0.5
    _, _, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert info["metrics"]["above_band_rate"].min() == 1.0


def test_above_band_rate_is_off_by_default():
    env = _env(n_envs=8)
    env.reset_all()
    _, _, info = env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert info["metrics"]["above_band_rate"].sum() == 0.0


def test_ep_peak_z_m_is_a_true_max_not_a_mean():
    env = _env(n_envs=8, episode_len=10_000, hold_fraction=0.0, spawn_vel=1.5,
               bound_xy=1e6, bound_z_min=-1e6, bound_z_max=1e6)
    obs = env.reset_all()
    seen = [env.dyn.pos[:, 2].clone()]
    for _ in range(12):
        env.step(torch.zeros(env.n_drones, env.act_dim))
        seen.append(env.dyn.pos[:, 2].clone())
    peak = torch.stack(seen).max(dim=0).values
    assert torch.allclose(env.task.peak_z, peak, atol=1e-6)
    m = env.task.metrics(env)
    assert abs(m["ep_peak_z_m"] - peak.mean().item()) < 1e-6
    # A mean would sit strictly below the max for a population that moved at all.
    assert m["ep_peak_z_m"] > m["mean_height"]
    assert obs is not None


def test_ep_peak_z_m_resets_with_the_episode():
    env = _env(n_envs=8, episode_len=4, hold_fraction=1.0, **DESK)
    env.reset_all()
    env.dyn.pos[:, 2] = 0.55
    env.task.reward_and_done(env, torch.zeros(env.n_drones, env.act_dim))
    assert env.task.peak_z.min() > 0.5
    env.reset_all()
    assert env.task.peak_z.max() < 0.2  # reseeded from the fresh desk-band spawn


@pytest.mark.parametrize("task", ["hover", "hover_blind", "hover_blind_v2", "hover_tof"])
def test_no_unprefixed_episode_windowed_name_leaks_into_metrics(task):
    """The trap this whole discipline exists for.

    ``eval/rollout.py`` overrides ``metrics()`` values with the full-horizon mean of the same-named
    per-step tensor. A key that has no per-step twin is therefore *unreachable* by that override
    and silently reports the reset-biased episode window — while reading like a headline result.
    So: every non-``ep_`` key must have a per-step twin (``crash_rate_per_step`` excepted, which
    the rollout computes itself from ``info["crashed"]``).
    """
    env = _env(n_envs=8, task=task)
    env.reset_all()
    _, _, _, _, info = env.step(torch.zeros(env.n_drones, env.act_dim))
    per_step = set(info["metrics"])
    for key in env.task.metrics(env):
        if key.startswith("ep_") or key == "crash_rate_per_step":
            continue
        assert key in per_step, (
            f"{task}.metrics()['{key}'] is episode-windowed but reads like a headline result; "
            f"prefix it ep_ or emit it per-step so eval/rollout.py's override reaches it"
        )
    assert "peak_z_m" not in env.task.metrics(env)
    assert "ep_peak_z_m" in env.task.metrics(env)


# --- 4. the setpoint marker scales with the arena ---

def test_scene_info_marker_radius_scales_with_the_arena():
    """A fixed marker size is a real bug at desk scale, and it hid the subject in the first video.

    ``geometry.js::buildMarker`` defaults to a 0.16 m RADIUS sphere, chosen against this task's
    default ``bound_xy 6.0``. On the desk config (``bound_xy 0.60``) that is a 32 cm ball marking a
    setpoint the policy holds to 4.7 cm, next to an 82 mm airframe — it fills the frame. The task
    now derives the radius from its own arena, keeping the ratio the historical default implies.
    """
    from neural_whoop.envs.registry import make_task

    # The 6.0 m default arena reproduces the renderer's historical 0.16 EXACTLY (no regression).
    assert make_task("hover").scene_info()["marker_radius"] == pytest.approx(0.16)

    # The desk shrinks it proportionally: small enough to never dwarf an 82 mm airframe.
    desk = make_task("hover_tof", **DESK).scene_info()["marker_radius"]
    assert desk == pytest.approx(0.60 * 0.16 / 6.0)
    assert desk < 0.082 / 2, "the marker must stay under the airframe's half-footprint at desk scale"

    # It rides meta.scene_info, the documented seam, on every inherited task.
    for name in ("hover", "hover_blind", "hover_blind_v2", "hover_tof"):
        info = make_task(name, **DESK).scene_info()
        assert info["standoff"] == 0.0
        assert info["marker_radius"] > 0.0
