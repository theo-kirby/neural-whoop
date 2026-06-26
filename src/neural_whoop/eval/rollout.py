"""Batched rollout + metrics: the deterministic eval used to report lap times.

Runs a trained policy (deterministic = ``clip(actor_mean)``) across many parallel envs for a
fixed horizon and aggregates the task's metrics (for ``gate_race``: lap time, laps completed,
completion rate, and the oracle baseline). No rendering on the training path — honest
camera-only eval (DiffAero depth render, Blackwell-OK) is a later hook (``render_depth``).
"""

from __future__ import annotations

import torch

from neural_whoop.envs.base import MultiAgentDroneEnv
from neural_whoop.training.ppo import ActorCritic


@torch.no_grad()
def evaluate(
    env: MultiAgentDroneEnv,
    agent: ActorCritic,
    steps: int = 1500,
    deterministic: bool = True,
) -> dict:
    """Roll out ``agent`` on ``env`` for ``steps`` control steps and return aggregated metrics.

    Args:
        env: The evaluation env (typically built with DR off or eval-DR for an honest number).
        agent: Trained :class:`ActorCritic`.
        steps: Control steps to roll (long enough for several laps).
        deterministic: Use the actor mean (clipped) instead of sampling.

    Returns:
        A metrics dict: the task ``metrics`` plus rollout-wide ``mean_reward``, ``crash_rate``,
        and ``gates_passed_total``.
    """
    dev = env.device
    obs = env.reset_all()
    rew_sum = torch.zeros(env.n_drones, device=dev)
    crashes = torch.zeros(env.n_drones, device=dev)
    gates = torch.zeros(env.n_drones, device=dev)
    for _ in range(steps):
        mean = agent.actor(obs)
        action = mean.clamp(-1.0, 1.0) if deterministic else agent.get_action_and_value(obs)[0]
        obs, reward, term, trunc, info = env.step(action)
        rew_sum += reward
        if "crashed" in info:
            crashes += info["crashed"].float()
        if "passed" in info:
            gates += info["passed"].float()

    m = dict(env.task.metrics(env))
    m["mean_reward"] = (rew_sum / steps).mean().item()
    m["crash_rate_per_step"] = (crashes / steps).mean().item()
    m["gates_passed_total"] = gates.sum().item()
    return m
