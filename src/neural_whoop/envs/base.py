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
        obs_stack: int = 1,
    ):
        self.task = task
        self.n_envs = n_envs
        self.n_agents = task.n_agents
        self.n_drones = n_envs * self.n_agents
        self.device = torch.device(device)
        self.act_dim = ACT_DIM
        # Frame stacking (latency-aware policy): the policy sees the last ``obs_stack`` observation
        # frames concatenated, so it can infer the velocity/latency a single frame hides. ``1`` is a
        # no-op (the deployed obs is one frame). A larger stack grows obs_dim -> MCU deploy-size flag.
        self.obs_stack = max(1, int(obs_stack))
        self.base_obs_dim = task.obs_dim
        self.obs_dim = self.base_obs_dim * self.obs_stack
        self._frames: Tensor | None = None  # (obs_stack, n_drones, base_obs_dim), oldest->newest
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

        # Optional fixed course (gate_pos (ng,3), gate_rad (ng,)) broadcast to ALL envs instead
        # of per-env random courses — set by the Studio rollout so a chosen track is flown. The
        # default (``None``) keeps the training path on procedurally-generated per-env courses.
        self.fixed_course: tuple[Tensor, Tensor] | None = None
        # Course-scale curriculum progress in ``[0, 1]`` (1.0 = full configured scale range). The
        # trainer ramps this 0->1 over training; a scale-randomizing task reads it to grow the
        # course-size range from tight to full. Default 1.0 -> no curriculum effect (eval / non-
        # curriculum runs see the full range).
        self.course_scale_progress = 1.0

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

    # --- DR curriculum ---
    def set_dr_scale(self, scale: float) -> None:
        """Set the seam-DR curriculum scale in ``[0, 1]`` (1.0 = full configured magnitudes).

        The trainer ramps this 0->1 over training to harden DR-on reliability without crippling
        early learning. Takes effect per-drone on the next reset (and immediately for obs noise).
        """
        self.dr.scale = float(min(1.0, max(0.0, scale)))

    def set_course_scale(self, frac: float) -> None:
        """Set the course-scale curriculum progress in ``[0, 1]`` (1.0 = full configured range).

        A scale-randomizing task reads this on reset to grow the sampled course-size range from
        tight toward full, so early training masters the small (high-value) regime before the big
        cruise-and-brake courses are added. Takes effect on the next reset.
        """
        self.course_scale_progress = float(min(1.0, max(0.0, frac)))

    # --- observation (with optional frame stacking) ---
    def _raw_obs(self) -> Tensor:
        """One noisy observation frame ``(n_drones, base_obs_dim)``."""
        return self.dr.add_obs_noise(self.task.observe(self))

    def _flat_frames(self) -> Tensor:
        """Concatenate the frame stack into the policy obs ``(n_drones, obs_dim)`` (oldest->newest)."""
        return self._frames.permute(1, 0, 2).reshape(self.n_drones, self.obs_dim)

    # --- reset / step ---
    def reset_all(self) -> Tensor:
        """Reset every env and return the initial observation ``(n_drones, obs_dim)``."""
        self.reset_idx(torch.arange(self.n_envs, device=self.device))
        raw = self._raw_obs()
        self._frames = raw.unsqueeze(0).expand(self.obs_stack, -1, -1).contiguous()
        return self._flat_frames()

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

        # Terminal frame (post-dynamics, pre-reset): push it onto the stack for bootstrapping.
        raw_term = self._raw_obs()
        self._frames = torch.cat([self._frames[1:], raw_term.unsqueeze(0)], dim=0)
        obs_term = self._flat_frames()
        info["terminal_obs"] = obs_term
        info["time_outs"] = trunc

        self.prev_action = a
        if bool(done_env.any()):
            self.reset_idx(done_env.nonzero(as_tuple=False).flatten())
            raw_next = self._raw_obs()  # post-reset for done drones
            # Done drones start a fresh history (all frames = the post-reset frame); others continue.
            done_b = done.view(1, -1, 1)
            self._frames = torch.where(done_b, raw_next.unsqueeze(0).expand_as(self._frames), self._frames)
            obs_next = self._flat_frames()
        else:
            obs_next = obs_term

        return obs_next, reward, term, trunc, info
