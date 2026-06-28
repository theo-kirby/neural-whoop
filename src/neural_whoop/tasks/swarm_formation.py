"""swarm_formation: N drones hold a ring formation around a slowly-moving anchor (the second swarm
task; Flywheel hop-15).

Where ``swarm_race`` (hop-13) has the swarm share ONE gate course (shared-track congestion, whose
throughput the density curve `proud-wood-6049` showed is capped at n=3), ``swarm_formation`` gives
each drone its OWN assigned slot on a ring around a common moving anchor. There is no shared track,
so the coupling is purely the formation geometry + collision avoidance — the density node flagged
this as the way to "sidestep the shared-track congestion entirely". Pure task-layer (the env already
flattens ``(n_envs, n_agents) -> n_drones`` and keeps collision/relative-obs in the task); no env
changes.

Anchor motion reuses :mod:`neural_whoop.target` (orbit / lissajous mover), one anchor per env shared
by the env's agents. Agent ``i`` holds slot ``i`` = ``anchor + formation_radius * [cos θ_i, sin θ_i,
0]`` with ``θ_i = 2πi/n_agents`` (an even ring in the world xy-plane; slots are spaced >
``collision_radius`` so a held formation is collision-free).

Observation (length 17): obs-v4 (11) with the body-frame vector to the drone's OWN slot replacing
the gate vector, + the nearest in-env neighbour's body-frame relative pos (3) and vel (3). (obs_dim
17 -> MCU deploy-size flag, per CLAUDE.md; smaller than swarm_race's 20 — no next-gate lookahead.)

Reward (per step) = formation-keeping bell ``exp(-(slot_err/σ)²)`` (peaks when the drone sits on its
slot) + alive − collision penalty − action-smoothness − boundary crash. No time penalty (a holding
task). Termination = per-env shared fate (any drone out of arena, or a collision when
``collision_terminates``).

Metric: ``mean_formation_error`` (mean distance to the assigned slot) ↓ + ``formation_hold_rate``
(frac of steps within ``hold_tol`` of slot) ↑, at a bounded ``collision_rate_per_step``. GREEN = the
ring forms and holds; RED = it can't hold / collapses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop import course as course_mod
from neural_whoop import target as target_mod
from neural_whoop.contract import OBS_DIM, world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.reward import Bounds, is_crashed, smoothness_penalty


@dataclass
class SwarmFormationConfig:
    """Tunable config for :class:`SwarmFormationTask`."""

    n_agents: int = 3
    episode_len: int = 600           # steps; dt=0.02 -> 12 s
    # Anchor motion (see neural_whoop.target.sample_target_field).
    motion: str = "mixed"            # static / orbit / lissajous / mixed (per-env)
    anchor_speed: float = 1.0        # m/s anchor speed (slow — a held formation)
    anchor_radius: float = 1.5       # orbit / lissajous extent (m)
    # Formation geometry.
    formation_radius: float = 1.0    # ring radius of the slots around the anchor (m)
    track_sigma: float = 0.6         # width of the slot-keeping reward bell (m)
    hold_tol: float = 0.4            # m; within this of the slot counts as "in formation" (metric)
    # Reward weights.
    formation_scale: float = 1.0
    alive_bonus: float = 0.01
    smoothness_penalty: float = 0.001
    collision_penalty: float = 10.0
    collision_radius: float = 0.25
    collision_terminates: bool = True
    crash_penalty: float = 10.0
    # Arena / spawn.
    arena_radius: float = 4.5
    z_min: float = 0.7
    z_max: float = 2.3
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0
    spawn_jitter: float = 0.15       # m; spawn near the slot but not exactly on it


@register_task("swarm_formation")
class SwarmFormationTask(DroneTask):
    """Hold a ring formation around a moving anchor (second swarm task)."""

    obs_dim = OBS_DIM + 6  # obs-v4 (11, slot vector replaces gate) + neighbour rel pos+vel (6) = 17

    def __init__(self, **kwargs):
        self.cfg = SwarmFormationConfig(**kwargs)
        if self.cfg.n_agents < 2:
            raise ValueError("swarm_formation needs n_agents >= 2 (it is a multi-drone task).")
        self.n_agents = self.cfg.n_agents
        self.episode_len = self.cfg.episode_len
        self._arena = course_mod.ArenaSpec(
            radius=self.cfg.arena_radius, z_min=self.cfg.z_min, z_max=self.cfg.z_max,
        )
        self._bounds = Bounds(xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max)
        # Per-agent ring offsets (na, 3) in the world xy-plane.
        na = self.cfg.n_agents
        ang = (2.0 * math.pi / na) * torch.arange(na)
        self._offsets_cpu = torch.stack([ang.cos(), ang.sin(), torch.zeros_like(ang)], dim=-1) * self.cfg.formation_radius

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != self.cfg.n_agents:
            raise ValueError(f"swarm_formation expects n_agents={self.cfg.n_agents} (env has {env.n_agents}).")
        n, dev = env.n_drones, env.device
        self._dev = dev
        self._offsets = self._offsets_cpu.to(dev)                     # (na, 3)
        # One anchor per env (n_envs == n_drones / n_agents).
        self._field = target_mod.sample_target_field(
            env.n_envs, motion=self.cfg.motion, arena=self._arena,
            speed=self.cfg.anchor_speed, radius=self.cfg.anchor_radius,
            device=dev, generator=env.gen,
        )
        # Episode accumulators (GPU-resident; read at log cadence by metrics()).
        self.err_sum = torch.zeros(n, device=dev)
        self.hold_sum = torch.zeros(n, device=dev)
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.collision_count = torch.zeros(n, device=dev)
        self.last_min_sep = torch.full((n,), float("nan"), device=dev)
        self._step_count = 0

    def _slots(self, env, t) -> Tensor:
        """World-frame assigned slot for every drone: ``(n_drones, 3)`` (env-major)."""
        anchor = self._field.position(t)                              # (n_envs, 3)
        slot = anchor.unsqueeze(1) + self._offsets.unsqueeze(0)       # (n_envs, na, 3)
        return slot.reshape(env.n_drones, 3)

    def reset(self, env, env_idx: Tensor) -> None:
        k = env_idx.numel()
        na = self.cfg.n_agents
        # Resample the anchor motion for just the finished envs.
        sub = target_mod.sample_target_field(
            k, motion=self.cfg.motion, arena=self._arena,
            speed=self.cfg.anchor_speed, radius=self.cfg.anchor_radius,
            device=self._dev, generator=env.gen,
        )
        self._field.kind[env_idx] = sub.kind
        for key, val in sub.p.items():
            self._field.p[key][env_idx] = val
        anchor0 = sub.position(0.0)                                   # (k, 3)
        slot0 = anchor0.unsqueeze(1) + self._offsets.unsqueeze(0)     # (k, na, 3)
        slot0[..., 2] = slot0[..., 2].clamp(self.cfg.z_min + 0.2, self.cfg.z_max - 0.2)

        d_idx = env.drone_idx(env_idx)
        jit = (torch.rand(k, na, 3, device=self._dev, generator=env.gen) - 0.5) * 2 * self.cfg.spawn_jitter
        spawn = (slot0 + jit).reshape(k * na, 3)
        # Face the anchor centre so the slot vector starts roughly ahead.
        anchor_d = anchor0.repeat_interleave(na, dim=0)
        yaw = torch.atan2(anchor_d[:, 1] - spawn[:, 1], anchor_d[:, 0] - spawn[:, 0])
        env.spawn(d_idx, spawn, yaw=yaw)

        self.err_sum[d_idx] = 0.0
        self.hold_sum[d_idx] = 0.0
        self.steps[d_idx] = 0

    # --- neighbour geometry (mirrors swarm_race) ---
    def _nearest_neighbour(self, env) -> tuple[Tensor, Tensor, Tensor]:
        na = self.cfg.n_agents
        pos = env.to_agents(env.dyn.pos)
        vel = env.to_agents(env.dyn.vel_world)
        diff = pos.unsqueeze(1) - pos.unsqueeze(2)
        dist = diff.norm(dim=-1)
        eye = torch.eye(na, device=self._dev, dtype=torch.bool)
        dist = dist.masked_fill(eye.unsqueeze(0), float("inf"))
        _, nn = dist.min(dim=1)
        nn_exp = nn.unsqueeze(-1).expand(-1, -1, 3)
        nbr_pos = torch.gather(pos, 1, nn_exp)
        nbr_vel = torch.gather(vel, 1, nn_exp)
        rel_pos = env.to_drones(nbr_pos - pos)
        rel_vel = env.to_drones(nbr_vel - vel)
        min_dist = dist.min(dim=1).values
        return rel_pos, rel_vel, env.to_drones(min_dist)

    # --- observation ---
    def observe(self, env) -> Tensor:
        pos, vel, R, rpy, w = (
            env.dyn.pos, env.dyn.vel_world, env.dyn.R, env.dyn.rpy, env.dyn.ang_vel_body,
        )
        slot = self._slots(env, env.sim_time)
        slot_rel_body = world_to_body(slot - pos, R)
        vel_b = world_to_body(vel, R)
        obs11 = torch.cat([slot_rel_body, vel_b, rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        rel_pos_w, rel_vel_w, _ = self._nearest_neighbour(env)
        nbr_pos_b = world_to_body(rel_pos_w, R)
        nbr_vel_b = world_to_body(rel_vel_w, R)
        return torch.cat([obs11, nbr_pos_b, nbr_vel_b], dim=-1).to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos = env.dyn.pos
        slot = self._slots(env, env.sim_time)
        slot_err = (slot - pos).norm(dim=-1)

        track = torch.exp(-((slot_err / c.track_sigma) ** 2))
        reward = c.formation_scale * track + c.alive_bonus
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)

        _, _, min_sep = self._nearest_neighbour(env)
        collided = min_sep < c.collision_radius
        reward = reward - c.collision_penalty * collided.float()
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Accumulators (ground truth; not zeroed on reset for the rate metrics).
        self.steps = self.steps + 1
        self.err_sum = self.err_sum + slot_err
        self.hold_sum = self.hold_sum + (slot_err < c.hold_tol).float()
        self.collision_count = self.collision_count + collided.float()
        self.last_min_sep = min_sep
        self._step_count += 1

        drone_fail = (crashed | collided) if c.collision_terminates else crashed
        terminated_env = env.to_agents(drone_fail).any(dim=1)
        info = {"crashed": crashed, "collided": collided}
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        sep = self.last_min_sep[torch.isfinite(self.last_min_sep)]
        denom = max(1, self._step_count) * env.n_drones
        return {
            "mean_formation_error": (self.err_sum / steps).mean().item(),
            "formation_hold_rate": (self.hold_sum / steps).mean().item(),
            "collision_rate_per_step": self.collision_count.sum().item() / denom,
            "mean_min_separation": sep.mean().item() if sep.numel() else float("nan"),
            "n_agents": float(self.cfg.n_agents),
        }
