"""acro_flip: a learned single-axis flip/roll — the first *agility* (acro) task.

The hover family solved attitude stabilization + open-loop trim; nothing in the catalog yet asks
the policy to throw the airframe through a large, deliberate rotation and catch it. ``acro_flip``
is that headline capability, and it needs **zero new hardware**: pure IMU + the existing act-v2
CTBR contract. The rate envelope is already acro-capable (``contract.py``
``ActionLimits.max_body_rate_rp_rps = 12`` rad/s ≈ 690°/s; the dynamics saturation at 40 rad/s
never bites), so no dynamics/contract changes are needed — just a new reward that *rewards the
rotation*.

The maneuver is a single learned behaviour discovered by reward shaping (no reference trajectory):
spin about the maneuver ``axis`` (roll → body-rate ``p``; pitch → ``q``) until an accumulated
signed rotation reaches ``Φ = 2π·n_rotations``, then return to stable, level flight. v1 is a fixed
single **barrel roll** (``axis="roll"``, ``n_rotations=1``, fixed direction); a pitch-flip is just
``configs/acro_flip_pitch.yaml``.

Observation (obs_dim 7, deploy-honest — IMU only)::

    [gravity_body(3), p, q, r, rotation_remaining(1)]

``gravity_body`` = world-down in the body frame (``Rᵀ·[0,0,-1]``) is unambiguous through a full
inversion, unlike euler roll/pitch which wrap / gimbal-lock mid-flip. ``p,q,r`` are the gyro
(valid even at high acro rates). ``rotation_remaining`` ∈ [1→0] is the phase signal (how much of
the maneuver is left), tracked internally here and supplied by the pilot's maneuver clock at
deploy. There is **no altitude channel** — IMU-only has no reliable onboard altitude, so altitude
stays open-loop for the brief maneuver (the RPM thrust anchor defends it at deploy). Altitude is
used only in the *reward* (privileged ground truth, the same pattern as ``hover``'s H2 terms).

Reward (per step, phased): a monotone, saturating rotation-progress term toward Φ (rewards the
spin, can't be farmed by over-spinning) + a one-time completion bonus on crossing Φ + a recover
term (upright bell − spin penalty, gated to *after* completion) + a generous privileged
altitude-keep penalty throughout − smoothness − crash. Termination = crash (arena bounds);
truncation = ``episode_len``. Spawn = level hover at ``z0``, at rest (the flip is the *learned*
behaviour, not an initial condition).

Metrics (ground truth): ``flip_success_rate`` (reached Φ **and** recovered level, no crash),
``mean_completion_time``, ``mean_altitude_loss`` (max ``z0 − z``), ``post_recovery_tilt_deg``,
``crash_rate_per_step``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import world_to_body
from neural_whoop.envs.registry import DroneTask, register_task
from neural_whoop.reward import Bounds, is_crashed, rotation_progress, smoothness_penalty

_AXIS_IDX = {"roll": 0, "pitch": 1}  # body-rate channel driven for each maneuver axis (p / q)


@dataclass
class AcroFlipConfig:
    """Tunable config for :class:`AcroFlipTask` (the acro reward/curriculum playground)."""

    axis: str = "roll"              # maneuver axis: "roll" (drives p) or "pitch" (drives q)
    n_rotations: float = 1.0        # target rotations → Φ = 2π·n_rotations (1 = a single barrel roll)
    episode_len: int = 200          # steps; at dt=0.02 → 4 s (ample for a sub-second flip + recover)
    # Reward weights.
    rot_scale: float = 1.0          # weight on the rotation-progress term (total ≈ rot_scale·Φ over the flip)
    completion_bonus: float = 10.0  # one-time bonus on crossing φ ≥ Φ (the "you did it" signal)
    upright_scale: float = 0.4      # weight on the recover-phase level bell exp(-(tilt/σ)²) (after completion)
    upright_sigma: float = 0.5      # width of the upright bell (rad of tilt from vertical)
    spin_penalty: float = 0.01      # −kw·|ω| recover-phase spin penalty (settle, don't keep spinning)
    alt_scale: float = 0.1          # −k·|z − z0| privileged altitude-keep penalty (generous: a flip loses height)
    alive_bonus: float = 0.1        # per-step alive bonus
    smoothness_penalty: float = 0.001
    crash_penalty: float = 10.0
    # Success metric.
    success_tilt_deg: float = 15.0  # a completed flip counts as recovered when tilt < this (deg)
    # Spawn band (level hover, at rest).
    arena_radius: float = 1.0       # horizontal radius the spawn point is sampled in (m)
    z_min: float = 1.2              # spawn height band — headroom below for the flip's altitude loss
    z_max: float = 2.2
    # Crash bounds.
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0


@register_task("acro_flip")
class AcroFlipTask(DroneTask):
    """Learned single-axis flip: spin about ``axis`` to Φ = 2π·n_rotations, then recover level."""

    n_agents = 1
    obs_dim = 7  # [gravity_body(3), p, q, r, rotation_remaining]
    config_cls = AcroFlipConfig

    def __init__(self, **kwargs):
        self.cfg = self.config_cls(**kwargs)
        if self.cfg.axis not in _AXIS_IDX:
            raise ValueError(f"axis must be one of {sorted(_AXIS_IDX)}, got {self.cfg.axis!r}.")
        self.episode_len = self.cfg.episode_len
        self.axis_idx = _AXIS_IDX[self.cfg.axis]
        self.direction = 1.0  # v1: fixed rotation direction
        self.target_phi = 2.0 * math.pi * self.cfg.n_rotations
        self._bounds = Bounds(
            xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max
        )

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("acro_flip is single-drone (n_agents must be 1).")
        n, dev = env.n_drones, env.device
        self._dev = dev
        self._down = torch.tensor([0.0, 0.0, -1.0], device=dev)  # world-down (for gravity_body)
        # Signed accumulated rotation about the maneuver axis, in the intended direction (monotone,
        # no euler wrap). Advanced once per step in reward_and_done; observe() is a pure read.
        self.phi = torch.zeros(n, device=dev)
        # Episode accumulators / trackers (GPU-resident; reset per env, read at log cadence).
        self.z0 = torch.zeros(n, device=dev)               # spawn altitude (altitude-keep reference)
        self.completed = torch.zeros(n, device=dev, dtype=torch.bool)   # reached Φ this episode
        self.succeeded = torch.zeros(n, device=dev, dtype=torch.bool)   # completed AND recovered level
        self.completion_step = torch.zeros(n, device=dev, dtype=torch.long)  # step of first completion
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.crash_sum = torch.zeros(n, device=dev, dtype=torch.long)
        self.max_alt_loss = torch.zeros(n, device=dev)     # max (z0 − z) over the episode
        self.last_tilt = torch.zeros(n, device=dev)        # current tilt from vertical (rad)

    def reset(self, env, env_idx: Tensor) -> None:
        c = self.cfg
        k = env_idx.numel()
        gen = env.gen
        d_idx = env.drone_idx(env_idx)
        # Spawn level, at rest, in a small disk within the height band — the flip is the learned
        # behaviour, not an initial condition.
        ang = torch.rand(k, device=self._dev, generator=gen) * (2 * math.pi)
        r = torch.rand(k, device=self._dev, generator=gen).sqrt() * c.arena_radius
        z = torch.rand(k, device=self._dev, generator=gen) * (c.z_max - c.z_min) + c.z_min
        spawn = torch.stack([r * ang.cos(), r * ang.sin(), z], dim=-1)
        env.spawn(d_idx, spawn)  # vel / ang_vel / roll / pitch default to zero (level, at rest)

        self.z0[d_idx] = z
        self.phi[d_idx] = 0.0
        self.completed[d_idx] = False
        self.succeeded[d_idx] = False
        self.completion_step[d_idx] = 0
        self.steps[d_idx] = 0
        self.crash_sum[d_idx] = 0
        self.max_alt_loss[d_idx] = 0.0
        self.last_tilt[d_idx] = 0.0

    # --- observation ---
    def _gravity_body(self, env) -> Tensor:
        """World-down in the body frame (``Rᵀ·[0,0,-1]``) — inversion-safe attitude, ``(n, 3)``."""
        R = env.dyn.R
        return world_to_body(self._down.expand(R.shape[0], 3), R)

    def _rotation_remaining(self) -> Tensor:
        """Phase signal ``(Φ − clamp(φ,0,Φ))/Φ`` ∈ [1→0], per drone ``(n,)``."""
        return (self.target_phi - self.phi.clamp(0.0, self.target_phi)) / self.target_phi

    def observe(self, env) -> Tensor:
        grav_b = self._gravity_body(env)
        w = env.dyn.ang_vel_body
        remaining = self._rotation_remaining().unsqueeze(-1)
        obs = torch.cat([grav_b, w, remaining], dim=-1)
        return obs.to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos, w = env.dyn.pos, env.dyn.ang_vel_body
        z = pos[..., 2]
        grav_b = self._gravity_body(env)
        # Tilt from vertical: 0 = level, π = inverted (unambiguous through a full flip).
        tilt = torch.arccos((-grav_b[..., 2]).clamp(-1.0, 1.0))

        Phi = self.target_phi
        # Advance the signed rotation about the maneuver axis in the intended direction.
        rate_axis = w[..., self.axis_idx] * self.direction
        prev_phi = self.phi
        new_phi = prev_phi + rate_axis * env.dt
        self.phi = new_phi

        completed_now = new_phi >= Phi
        newly_completed = completed_now & (~self.completed)
        recover = completed_now.float()  # recover-phase gate (after completion)

        # Rotate phase: monotone, saturating progress toward Φ (can't farm infinite spin).
        reward = rotation_progress(prev_phi, new_phi, Phi, c.rot_scale)
        # Completion bonus (one-time on crossing Φ).
        reward = reward + c.completion_bonus * newly_completed.float()
        # Recover phase (gated): return to level + stop spinning.
        upright = torch.exp(-((tilt / c.upright_sigma) ** 2))
        spin = w.norm(dim=-1)
        reward = reward + recover * (c.upright_scale * upright - c.spin_penalty * spin)
        # Altitude-keep throughout (privileged ground-truth shaping — no onboard altitude at deploy).
        reward = reward - c.alt_scale * (z - self.z0).abs()
        # Alive − smoothness − crash.
        reward = reward + c.alive_bonus
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Episode bookkeeping (ground truth).
        tol = math.radians(c.success_tilt_deg)
        success_now = completed_now & (tilt < tol) & (~crashed)
        self.completion_step = torch.where(newly_completed, self.steps + 1, self.completion_step)
        self.completed = self.completed | completed_now
        self.succeeded = self.succeeded | success_now
        alt_loss = (self.z0 - z).clamp_min(0.0)
        self.max_alt_loss = torch.maximum(self.max_alt_loss, alt_loss)
        self.last_tilt = tilt
        self.steps = self.steps + 1
        self.crash_sum = self.crash_sum + crashed.long()

        terminated_env = crashed  # n_agents == 1 → per-drone == per-env
        # Per-step metric tensors (no CPU sync): the eval rollout aggregates these over the FULL
        # horizon, immune to the accumulator zeroing at episode auto-resets (see hover.py).
        info = {
            "crashed": crashed,
            "metrics": {
                "flip_success_rate": self.succeeded.float(),
                "rotation_frac": (new_phi / Phi).clamp(0.0, 1.0),
                "altitude_loss": alt_loss,
            },
        }
        return reward, terminated_env, info

    # --- visual scene (replay `scene` channel) ---
    def scene_objects(self, env) -> dict:
        """Surface ``rotation_remaining`` as the on-screen command chip (per-drone scalar)."""
        return {"command": self._rotation_remaining()}

    def scene_info(self) -> dict:
        """Descriptor for the command chip (the maneuver-phase scalar)."""
        return {"command_label": f"{self.cfg.axis}-flip phase (remaining)"}

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        completed = self.completed.float()
        n_completed = completed.sum().clamp_min(1.0)
        comp_time = (self.completion_step.float() * env.dt * completed).sum() / n_completed
        tilt_completed = (self.last_tilt * completed).sum() / n_completed
        return {
            "flip_success_rate": self.succeeded.float().mean().item(),
            "mean_completion_time": comp_time.item(),
            "mean_altitude_loss": self.max_alt_loss.mean().item(),
            "post_recovery_tilt_deg": math.degrees(tilt_completed.item()),
            "crash_rate_per_step": (self.crash_sum.float() / steps).mean().item(),
        }
