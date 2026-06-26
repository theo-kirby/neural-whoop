"""Batched target field + a minimal PPO update loop (CPU, tiny)."""

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.envs.registry import make_task
from neural_whoop.target import KIND_STATIC, sample_target_field
from neural_whoop.training.ppo import PPOConfig, train_ppo
import neural_whoop.tasks  # noqa: F401


def test_target_field_shapes():
    tf = sample_target_field(16, "mixed", device="cpu", generator=torch.Generator().manual_seed(0))
    p = tf.position(0.0)
    assert p.shape == (16, 3)
    p2 = tf.position(1.0)
    assert p2.shape == (16, 3)


def test_static_target_ignores_time():
    tf = sample_target_field(8, "static", device="cpu", generator=torch.Generator().manual_seed(0))
    assert (tf.kind == KIND_STATIC).all()
    assert torch.allclose(tf.position(0.0), tf.position(5.0))


def test_ppo_runs_a_few_updates():
    env = MultiAgentDroneEnv(make_task("gate_race", episode_len=40), n_envs=64, device="cpu", seed=0)
    cfg = PPOConfig(num_steps=8, total_steps=64 * 8 * 2, num_minibatches=2, update_epochs=1)
    agent = train_ppo(env, cfg, run_dir="/tmp/nw_test_ppo", device="cpu", log=lambda *a, **k: None)
    # Policy produces finite, bounded deterministic actions after training.
    out = agent.actor(env.reset_all()).clamp(-1, 1)
    assert out.shape == (64, env.act_dim) and torch.isfinite(out).all()
