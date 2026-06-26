"""Frame-stacking / latency-aware observations (Flywheel hop-12).

The env can feed the policy the last ``obs_stack`` observation frames concatenated, so it can infer
the latency/velocity a single frame hides. ``obs_stack=1`` (default) must be an exact no-op; a larger
stack multiplies obs_dim and, at reset, repeats the fresh frame across the whole stack.
"""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
import neural_whoop.tasks  # noqa: F401 - register tasks


def _env(stack):
    return MultiAgentDroneEnv(make_task("gate_race"), n_envs=64, device="cpu", seed=0, obs_stack=stack)


def test_default_stack_is_noop_dim():
    env = _env(1)
    assert env.obs_stack == 1
    assert env.obs_dim == env.base_obs_dim == 14
    obs = env.reset_all()
    assert obs.shape == (64, 14)


def test_stacked_obs_dim_and_reset_repeats_frame():
    k = 3
    env = _env(k)
    assert env.obs_dim == env.base_obs_dim * k == 42
    obs = env.reset_all()
    assert obs.shape == (64, 42)
    # At reset the stack is the same frame repeated -> the k base-dim chunks are identical.
    chunks = obs.view(64, k, env.base_obs_dim)
    assert torch.allclose(chunks[:, 0], chunks[:, 1])
    assert torch.allclose(chunks[:, 1], chunks[:, 2])


def test_step_shifts_history_newest_last():
    k = 3
    env = _env(k)
    env.reset_all()
    act = torch.zeros(64, env.act_dim)
    act[:, 0] = 1.0  # hover-ish
    obs, *_ = env.step(act)
    assert obs.shape == (64, 42)
    chunks = obs.view(64, k, env.base_obs_dim)
    # After one real step the newest frame (last chunk) generally differs from the oldest.
    assert not torch.allclose(chunks[:, 0], chunks[:, -1])
