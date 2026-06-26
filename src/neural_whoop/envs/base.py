"""MultiAgentDroneEnv: the batched, GPU-resident, task-agnostic drone env.

Owns the dynamics (DiffAero whoop), the seam domain randomization, and all reset/step
bookkeeping; delegates *what* is being learned to a :class:`~neural_whoop.envs.registry.DroneTask`.

The env is a thin vectorized RL interface — there is no per-env Python loop. Each of the
``n_drones = n_envs * n_agents`` drones is one sample for PPO (shared-policy parameter sharing
across agents); episodes reset per-env (all agents in an env share the course and reset
together). On a done step the env returns the *post-reset* observation and stashes the true
terminal observation in ``info["terminal_obs"]`` plus ``info["time_outs"]`` so the trainer can
bootstrap value at time-limit truncations (but not at crashes).
"""

from __future__ import annotations

import torch
from torch import Tensor

from neural_whoop.contract import ACT_DIM, ActionLimits, action_to_diffaero
from neural_whoop.dynamics.whoop import WhoopDynamics, WhoopParams
from neural_whoop.envs.registry import DroneTask
from neural_whoop.randomization import DomainRandomizationConfig, DomainRandomizer

import neural_whoop  # noqa: F401 - vendored diffaero on path
from diffaero.utils.math import euler_to_quaternion


class MultiAgentDroneEnv:
    """A batched multi-agent drone environment driving a :class:`DroneTask`.

    Args:
        task: The :class:`DroneTask` to run.
        n_envs: Number of parallel environments.
        device: Torch device (``"cuda"`` for the 5090).
        seed: RNG seed for reproducible courses/DR.
        dr_cfg: Seam domain-randomization config (``None`` -> defaults).
        whoop_params: Airframe params (``None`` -> :class:`WhoopParams` defaults).
        action_limits: Physical CTBR limits the normalized action maps onto.
    """

    def __init__(
        self,
        task: DroneTask,
        n_envs: int,
        device: torch.device | str = "cuda",
        seed: int = 0,
        dr_cfg: DomainRandomizationConfig | None = None,
        whoop_params: WhoopParams | None = None,
        action_limits: ActionLimits | None = None,
    ):
        self.task = task
        self.n_envs = n_envs
        self.n_agents = task.n_agents
        self.n_drones = n_envs * self.n_agents
        self.device = torch.device(device)
        self.act_dim = ACT_DIM
        self.obs_dim = task.obs_dim
        self.episode_len = task.episode_len
        self.limits = action_limits or ActionLimits()

        self.gen = torch.Generator(device=self.device).manual_seed(seed)
        self.dyn = WhoopDynamics(self.n_drones, whoop_params, self.device, self.gen)
        self.dt = self.dyn.dt
        self.dr = DomainRandomizer(
            dr_cfg or DomainRandomizationConfig(), self.n_drones, self.act_dim, self.dt,
            self.device, self.gen,
        )

        self.t = torch.zeros(n_envs, device=self.device, dtype=torch.long)
        self.sim_time = torch.zeros(n_envs, device=self.device)
        self.prev_action = torch.zeros(self.n_drones, self.act_dim, device=self.device)
        self.prev_pos = torch.zeros(self.n_drones, 3, device=self.device)

        self.task.setup(self)
        self.reset_all()

    # --- shape helpers between flat-drone and (env, agent) views ---
    def to_agents(self, x: Tensor) -> Tensor:
        """Reshape ``(n_drones, ...)`` -> ``(n_envs, n_agents, ...)``."""
        return x.reshape(self.n_envs, self.n_agents, *x.shape[1:])

    def to_drones(self, x: Tensor) -> Tensor:
        """Reshape ``(n_envs, n_agents, ...)`` -> ``(n_drones, ...)``."""
        return x.reshape(self.n_drones, *x.shape[2:])

    def drone_idx(self, env_idx: Tensor) -> Tensor:
        """Map env indices to the flat drone indices of all their agents."""
        offs = torch.arange(self.n_agents, device=self.device)
        return (env_idx.unsqueeze(-1) * self.n_agents + offs).reshape(-1)

    # --- spawn helper for tasks ---
    def spawn(
        self,
        drone_idx: Tensor,
        pos: Tensor,
        vel: Tensor | None = None,
        yaw: Tensor | None = None,
        ang_vel: Tensor | None = None,
    ) -> None:
        """Set the spawn state for the given flat ``drone_idx``.

        ``pos`` is ``(k, 3)``; ``vel``/``ang_vel`` default to zero; ``yaw`` (``(k,)`` rad)
        sets the initial heading (roll/pitch zero). Quaternions are real-last (xyzw).
        """
        k = drone_idx.numel()
        z = torch.zeros(k, device=self.device)
        vel = vel if vel is not None else torch.zeros(k, 3, device=self.device)
        ang_vel = ang_vel if ang_vel is not None else torch.zeros(k, 3, device=self.device)
        yaw = yaw if yaw is not None else z
        quat = euler_to_quaternion(z, z, yaw)  # (k, 4) xyzw
        self.dyn.set_state(drone_idx, pos, vel, quat, ang_vel)

    # --- reset / step ---
    def reset_all(self) -> Tensor:
        """Reset every env and return the initial observation ``(n_drones, obs_dim)``."""
        self.reset_idx(torch.arange(self.n_envs, device=self.device))
        return self.dr.add_obs_noise(self.task.observe(self))

    def reset_idx(self, env_idx: Tensor) -> None:
        """Reset the given environments (all their agents)."""
        if env_idx.numel() == 0:
            return
        d_idx = self.drone_idx(env_idx)
        self.dr.reset(d_idx)
        self.dyn.refresh_airframe(d_idx)
        self.task.reset(self, env_idx)
        self.t[env_idx] = 0
        self.sim_time[env_idx] = 0.0
        self.prev_action[d_idx] = 0.0

    def step(self, action: Tensor) -> tuple[Tensor, Tensor, Tensor, Tensor, dict]:
        """Advance one control step.

        Args:
            action: Normalized actions ``(n_drones, act_dim)`` in ``[-1, 1]``.

        Returns:
            ``(obs, reward, terminated, truncated, info)`` — ``obs`` ``(n_drones, obs_dim)`` is
            post-reset for done drones; ``reward``/``terminated``/``truncated`` are per drone;
            ``info`` carries ``terminal_obs`` and ``time_outs`` for value bootstrapping.
        """
        a = action.clamp(-1.0, 1.0)
        self.prev_pos = self.dyn.pos.clone()

        a_eff = self.dr.delay_action(a)
        ctbr = action_to_diffaero(a_eff, self.limits)
        ctbr = self.dr.perturb_ctbr(ctbr)
        self.dyn.step(ctbr)
        self.dyn.add_velocity(self.dr.wind_dv())
        self.dyn.detach()  # PPO: dynamics graph is not differentiated across steps

        self.t += 1
        self.sim_time += self.dt

        reward, terminated_env, info = self.task.reward_and_done(self, a)
        truncated_env = self.t >= self.episode_len
        done_env = terminated_env | truncated_env

        term = terminated_env.repeat_interleave(self.n_agents)
        trunc = truncated_env.repeat_interleave(self.n_agents)
        done = done_env.repeat_interleave(self.n_agents)

        obs_term = self.dr.add_obs_noise(self.task.observe(self))
        info["terminal_obs"] = obs_term
        info["time_outs"] = trunc

        self.prev_action = a
        if bool(done_env.any()):
            self.reset_idx(done_env.nonzero(as_tuple=False).flatten())
            obs_next = self.dr.add_obs_noise(self.task.observe(self))
            obs_next = torch.where(done.unsqueeze(-1), obs_next, obs_term)
        else:
            obs_next = obs_term

        return obs_next, reward, term, trunc, info
