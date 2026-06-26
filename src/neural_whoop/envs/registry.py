"""Task registry: ``name -> task spec`` and the :class:`DroneTask` contract.

A task is a self-contained spec of *what* the policy is learning: its observation, reward,
termination, the oracle that feeds the body-frame target vector, the per-episode reset /
curriculum, and the eval metrics. The :class:`~neural_whoop.envs.base.MultiAgentDroneEnv` is
task-agnostic plumbing (dynamics + DR + reset bookkeeping); it drives a :class:`DroneTask`.

This split is the autonomous agent's main surface: new policies/behaviours in the catalog are
new :class:`DroneTask` subclasses dropped into ``neural_whoop.tasks`` and registered here, with
no env changes. Register with the :func:`register_task` decorator; instantiate with
:func:`make_task`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from torch import Tensor

if TYPE_CHECKING:
    from neural_whoop.envs.base import MultiAgentDroneEnv

#: Registry mapping task name -> task class.
TASK_REGISTRY: dict[str, type["DroneTask"]] = {}


def register_task(name: str) -> Callable[[type["DroneTask"]], type["DroneTask"]]:
    """Class decorator registering a :class:`DroneTask` subclass under ``name``."""

    def deco(cls: type["DroneTask"]) -> type["DroneTask"]:
        if name in TASK_REGISTRY:
            raise ValueError(f"Task {name!r} already registered.")
        cls.name = name
        TASK_REGISTRY[name] = cls
        return cls

    return deco


def make_task(name: str, **kwargs) -> "DroneTask":
    """Instantiate a registered task by name (kwargs forwarded to its constructor)."""
    if name not in TASK_REGISTRY:
        raise KeyError(f"Unknown task {name!r}. Registered: {sorted(TASK_REGISTRY)}")
    return TASK_REGISTRY[name](**kwargs)


class DroneTask(ABC):
    """The contract a task implements; the env calls these hooks.

    Shape conventions: the dynamics batch is ``n_drones = n_envs * n_agents`` (flattened). Per-
    drone tensors are ``(n_drones, ...)``; per-env tensors are ``(n_envs, ...)``. Use
    ``env.to_agents`` / ``env.to_drones`` to reshape between the two when a task needs
    inter-agent structure.

    Attributes:
        name: Registry name (set by :func:`register_task`).
        obs_dim: Observation vector length.
        n_agents: Drones per env (1 = single-drone tasks; >1 = swarm).
        episode_len: Max control steps before truncation.
    """

    name: str = "base"
    obs_dim: int = 11
    n_agents: int = 1
    episode_len: int = 500

    def setup(self, env: "MultiAgentDroneEnv") -> None:
        """One-time allocation of per-env task buffers (courses, progress trackers, ...)."""

    @abstractmethod
    def reset(self, env: "MultiAgentDroneEnv", env_idx: Tensor) -> None:
        """Reset task state and spawn drones for the given env indices."""

    @abstractmethod
    def observe(self, env: "MultiAgentDroneEnv") -> Tensor:
        """Build the current observation, shape ``(n_drones, obs_dim)``."""

    @abstractmethod
    def reward_and_done(
        self, env: "MultiAgentDroneEnv", action: Tensor
    ) -> tuple[Tensor, Tensor, dict]:
        """Compute reward and termination after a step.

        Args:
            env: The driving env (read post-step state via ``env.dyn`` and ``env.prev_pos``).
            action: The normalized action applied this step, shape ``(n_drones, act_dim)``.

        Returns:
            ``(reward, terminated, info)``: ``reward`` per drone ``(n_drones,)``,
            ``terminated`` per env ``(n_envs,)`` bool (crash / task-defined end; time-limit
            truncation is added by the env), and an ``info`` dict of scalar metrics to log.
        """

    def metrics(self, env: "MultiAgentDroneEnv") -> dict:
        """Optional richer eval metrics (defaults to empty)."""
        return {}
