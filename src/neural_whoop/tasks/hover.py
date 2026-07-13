"""hover: single-drone auto-stabilization / station-keeping with disturbance recovery.

The reliability beachhead (docs/TASK_CATALOG.md). Where ``gate_race`` flies a course and
``target_follow`` chases a mover, ``hover`` has the simplest possible objective — **hold this
point and reject disturbances**: wind, shoves (push impulses), and dropped-block tumbles
(linear + body-rate kicks). It is the policy the live Studio editor pokes at, so it must be
trained against the very disturbances the editor throws — the impulse seam in
:mod:`neural_whoop.randomization` (``impulse_dv``/``impulse_dw``) drives both training and the
editor through the *same* :meth:`~neural_whoop.dynamics.whoop.WhoopDynamics.add_velocity` /
``add_body_rate`` pathway.

It is gateless, single-drone, state/oracle-based (no pixels), obs-v4 unchanged (length 11): the
"target" is the world-frame hover **setpoint**, fed body-frame like every other task's target
vector. The live editor rewrites :attr:`HoverTask.setpoint` on click to relocate the hover point.

Reward (per step) = a position bell ``exp(-(dist/σ)²)`` (peaks on the setpoint) + an upright
term (reward level, penalize ``roll²+pitch²``) + a velocity-damping penalty + a spin penalty +
alive − action-smoothness − crash. No time/progress term — this is a hold, not a race.
Termination = crash (out of arena / ground / ceiling); truncation = env time limit.

Metrics (all ground truth): ``mean_pos_error``, ``mean_z_error`` (vertical-only — the altitude
story the blind/ToF obs ablations are about), ``mean_speed``, ``mean_tilt_deg``, ``hold_rate``
(fraction of steps within ``hold_radius`` of the setpoint), ``crash_rate_per_step``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import OBS_DIM, world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.reward import Bounds, is_crashed, smoothness_penalty


@dataclass
class HoverConfig:
    """Tunable config for :class:`HoverTask` (the reward/curriculum playground)."""

    episode_len: int = 500          # steps; at dt=0.02 -> 10 s of holding
    # Reward weights.
    pos_sigma: float = 0.6          # width of the position bell exp(-(dist/σ)²) (m)
    pos_scale: float = 2.0          # weight on the position bell (fine holding, peaks on-setpoint) —
                                    # made dominant so position beats the cheap upright+alive floor
    dist_penalty: float = 0.4       # −kd·dist linear pull-in: a gradient toward the setpoint at ANY
                                    # range (the bell is flat far out, so without this an offset
                                    # spawn never learns to approach — it just sits level and still)
    upright_scale: float = 0.3      # weight on the level reward exp(-((roll²+pitch²)/σ_up²)) — kept
                                    # below pos_scale so leveling never competes with holding station
    upright_sigma: float = 0.5      # width of the upright bell (rad of combined tilt)
    vel_penalty: float = 0.02       # −kv·|vel| velocity-damping penalty (small: don't deter approach)
    spin_penalty: float = 0.01      # −kw·|ω| body-rate (spin) penalty
    # Privileged decoupling terms (H2, off by default). Both use GROUND-TRUTH state the deployed
    # policy cannot observe — legitimate as *training* signals only (reward shaping, not obs).
    # Motivation: honest-amplitude gyro obs noise biases the learned mean hover thrust (the policy's
    # thrust output couples to the noisy rate inputs), sinking the open-loop trim. A direct |vz|
    # penalty gives PPO an unambiguous gradient against sinking that needs no noisy estimate, and a
    # thrust-constancy penalty decouples the throttle channel from the gyro jitter. Keep small —
    # over-weighting kills legitimate tilt-compensation throttle moves.
    vz_penalty: float = 0.0         # −k·|vz| privileged vertical-velocity penalty
    thrust_const_penalty: float = 0.0  # −k·(a_t[0]−a_{t−1}[0])² thrust-channel constancy penalty
    alive_bonus: float = 0.1        # per-step alive bonus
    smoothness_penalty: float = 0.001
    crash_penalty: float = 10.0
    # Hold metric.
    hold_radius: float = 0.35       # within this distance of the setpoint counts as "holding" (m)
    # Setpoint sampling band (within the arena).
    arena_radius: float = 3.5       # horizontal radius the setpoint is sampled in (m)
    z_min: float = 0.8
    z_max: float = 2.2
    # Spawn randomization (recovery training). A fraction of episodes spawn ON the setpoint (pure
    # hold); the rest spawn offset + perturbed (fly-to-point + recover).
    hold_fraction: float = 0.35     # fraction of episodes spawned on-setpoint, level, at rest
    spawn_offset: float = 1.5       # max horizontal/vertical offset from the setpoint (m)
    spawn_vel: float = 1.5          # max initial speed (m/s)
    spawn_tilt_deg: float = 30.0    # max initial roll/pitch (deg)
    spawn_rate: float = 2.0         # max initial body-rate magnitude (rad/s)
    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0


@register_task("hover")
class HoverTask(DroneTask):
    """Hold a world-frame setpoint and recover from wind / push / dropped-block disturbances."""

    n_agents = 1
    obs_dim = OBS_DIM  # obs-v4 (11), unchanged — the setpoint vector replaces the gate/target vector
    config_cls = HoverConfig

    def __init__(self, **kwargs):
        self.cfg = self.config_cls(**kwargs)
        self.episode_len = self.cfg.episode_len
        self._bounds = Bounds(
            xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("hover is single-drone (n_agents must be 1).")
        n, dev = env.n_drones, env.device
        # The hover setpoint (world frame). n_drones == n_envs here (single-drone). The live editor
        # overwrites rows of this on click; reset resamples the finished envs' rows.
        self.setpoint = torch.zeros(n, 3, device=dev)
        # Episode accumulators (GPU-resident; reset per env, read at log cadence by metrics()).
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.held = torch.zeros(n, device=dev, dtype=torch.long)
        self.pos_err_sum = torch.zeros(n, device=dev)
        self.z_err_sum = torch.zeros(n, device=dev)
        self.speed_sum = torch.zeros(n, device=dev)
        self.tilt_sum = torch.zeros(n, device=dev)
        self.crash_sum = torch.zeros(n, device=dev, dtype=torch.long)
        self._dev = dev

    def _sample_setpoint(self, k: int, gen) -> Tensor:
        """Sample ``k`` setpoints uniformly in the arena disk within the height band."""
        c = self.cfg
        ang = torch.rand(k, device=self._dev, generator=gen) * (2 * math.pi)
        r = torch.rand(k, device=self._dev, generator=gen).sqrt() * c.arena_radius
        z = torch.rand(k, device=self._dev, generator=gen) * (c.z_max - c.z_min) + c.z_min
        return torch.stack([r * ang.cos(), r * ang.sin(), z], dim=-1)

    def reset(self, env, env_idx: Tensor) -> None:
        c = self.cfg
        k = env_idx.numel()
        gen = env.gen
        d_idx = env.drone_idx(env_idx)
        sp = self._sample_setpoint(k, gen)
        self.setpoint[d_idx] = sp

        # Mix episodes: a fraction spawn exactly on-setpoint, level and at rest (pure hold); the rest
        # spawn offset + perturbed in velocity/tilt/body-rate (fly-to-point + recovery).
        hold = torch.rand(k, device=self._dev, generator=gen) < c.hold_fraction
        recover = (~hold).float().unsqueeze(-1)

        off_ang = torch.rand(k, device=self._dev, generator=gen) * (2 * math.pi)
        off_r = torch.rand(k, device=self._dev, generator=gen) * c.spawn_offset
        off_z = (torch.rand(k, device=self._dev, generator=gen) * 2 - 1) * c.spawn_offset
        offset = torch.stack([off_r * off_ang.cos(), off_r * off_ang.sin(), off_z], dim=-1)
        spawn = sp + recover * offset
        spawn[:, 2] = spawn[:, 2].clamp(c.bound_z_min + 0.2, c.bound_z_max - 0.2)

        vel = (torch.rand(k, 3, device=self._dev, generator=gen) * 2 - 1) * c.spawn_vel * recover
        ang_vel = (torch.rand(k, 3, device=self._dev, generator=gen) * 2 - 1) * c.spawn_rate * recover
        yaw = torch.rand(k, device=self._dev, generator=gen) * (2 * math.pi)
        # Tilt: a random initial roll/pitch (the recovery cohort starts off-level).
        tilt = math.radians(c.spawn_tilt_deg)
        roll = (torch.rand(k, device=self._dev, generator=gen) * 2 - 1) * tilt * recover.squeeze(-1)
        pitch = (torch.rand(k, device=self._dev, generator=gen) * 2 - 1) * tilt * recover.squeeze(-1)
        env.spawn(d_idx, spawn, vel=vel, yaw=yaw, ang_vel=ang_vel, roll=roll, pitch=pitch)

        self.steps[d_idx] = 0
        self.held[d_idx] = 0
        self.pos_err_sum[d_idx] = 0.0
        self.z_err_sum[d_idx] = 0.0
        self.speed_sum[d_idx] = 0.0
        self.tilt_sum[d_idx] = 0.0
        self.crash_sum[d_idx] = 0

    # --- observation ---
    def observe(self, env) -> Tensor:
        pos, vel, R, rpy, w = (
            env.dyn.pos, env.dyn.vel_world, env.dyn.R, env.dyn.rpy, env.dyn.ang_vel_body,
        )
        rel_body = world_to_body(self.setpoint - pos, R)
        vel_b = world_to_body(vel, R)
        obs = torch.cat([rel_body, vel_b, rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        return obs.to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos, vel, rpy, w = env.dyn.pos, env.dyn.vel_world, env.dyn.rpy, env.dyn.ang_vel_body

        dist = (self.setpoint - pos).norm(dim=-1)
        z_err = (self.setpoint[..., 2] - pos[..., 2]).abs()
        pos_bell = torch.exp(-((dist / c.pos_sigma) ** 2))
        tilt_sq = rpy[..., 0] ** 2 + rpy[..., 1] ** 2  # roll² + pitch²
        upright = torch.exp(-(tilt_sq / (c.upright_sigma ** 2)))
        speed = vel.norm(dim=-1)
        spin = w.norm(dim=-1)

        reward = c.pos_scale * pos_bell + c.upright_scale * upright + c.alive_bonus
        reward = reward - c.dist_penalty * dist
        reward = reward - c.vel_penalty * speed - c.spin_penalty * spin
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        # Privileged decoupling terms (H2): ground-truth vz + thrust-channel constancy (see config).
        if c.vz_penalty > 0.0:
            reward = reward - c.vz_penalty * vel[..., 2].abs()
        if c.thrust_const_penalty > 0.0:
            reward = reward - c.thrust_const_penalty * (action[..., 0] - env.prev_action[..., 0]) ** 2

        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Episode accumulators (ground truth).
        held = dist < c.hold_radius
        tilt = tilt_sq.clamp_min(0.0).sqrt()
        self.steps = self.steps + 1
        self.held = self.held + held.long()
        self.pos_err_sum = self.pos_err_sum + dist
        self.z_err_sum = self.z_err_sum + z_err
        self.speed_sum = self.speed_sum + speed
        self.tilt_sum = self.tilt_sum + tilt
        self.crash_sum = self.crash_sum + crashed.long()

        terminated_env = crashed  # n_agents == 1 -> per-drone == per-env
        # Per-step metric tensors (no CPU sync): the eval rollout aggregates these over the FULL
        # horizon, immune to the accumulator zeroing at episode auto-resets (which otherwise
        # garbles metrics() when a lockstep no-crash population resets right at the eval horizon).
        info = {
            "crashed": crashed,
            "metrics": {
                "mean_pos_error": dist,
                "mean_z_error": z_err,
                "mean_speed": speed,
                "mean_tilt_deg": tilt * (180.0 / math.pi),
                "hold_rate": held.float(),
            },
        }
        return reward, terminated_env, info

    # --- visual scene (replay `scene` channel) ---
    def scene_objects(self, env) -> dict:
        """The hover setpoint per drone — drawn with the same ``target`` marker the follow tasks use."""
        return {"target": self.setpoint}

    def scene_info(self) -> dict:
        """Zero standoff (the setpoint is the point to sit on, not a distance to hold)."""
        return {"standoff": 0.0}

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        return {
            "mean_pos_error": (self.pos_err_sum / steps).mean().item(),
            "mean_z_error": (self.z_err_sum / steps).mean().item(),
            "mean_speed": (self.speed_sum / steps).mean().item(),
            "mean_tilt_deg": math.degrees((self.tilt_sum / steps).mean().item()),
            "hold_rate": (self.held.float() / steps).mean().item(),
            "crash_rate_per_step": (self.crash_sum.float() / steps).mean().item(),
        }
