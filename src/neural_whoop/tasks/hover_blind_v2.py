"""hover_blind_v2: IMU-only hover + a leaky acc-integrated climb-rate channel (vz_est).

The 2026-07-06 flight campaign (runs/pilot/flight_*.csv, docs/SIM2REAL.md) showed the deployed
``hover_blind`` stack's remaining ceiling is altitude: the pilot's external acc-z climb damper
and the RPM governor fight each other because the vz estimate carries an in-air vibration DC
bias (−0.6..−1.6 m/s in every hover window). The fix is to make the POLICY consume vz and let
PPO learn what to trust about it: **obs = [roll, pitch, p, q, r, vz_est]** (6), where
``vz_est`` is the same leaky-integrator climb-rate estimate ``scripts/pilot.py`` computes from
the accelerometer — leak-filtered (tau ``vz_tau_s``), clamped (±``vz_clamp``), decay-only (no
new evidence) beyond ``vz_freeze_tilt_deg`` of tilt.

The estimator is simulated here from the TRUE vertical velocity innovation per step (the leaky
high-pass of vz the pilot's acc integral converges to); its real-world DC bias and noise are
deliberately NOT modeled in the task — they come from the per-channel obs-noise/bias DR
(:mod:`neural_whoop.randomization`), so ``--no-dr`` eval gives the noise-free ablation for free.

Estimator state advances in :meth:`reward_and_done` (exactly once per step, post-dynamics), NOT
in :meth:`observe` — the env calls ``observe`` twice on reset steps (terminal frame + post-reset
frame) and stateful updates there would double-integrate. ``observe`` is a pure read.

Everything else (reward, spawn/recovery curriculum, metrics, Studio scene) is inherited from
``hover_blind`` / ``hover``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.envs.registry import register_task
from neural_whoop.tasks.hover import HoverConfig
from neural_whoop.tasks.hover_blind import HoverBlindTask


@dataclass
class HoverBlindV2Config(HoverConfig):
    """Hover config + the deploy-matched vz-estimator constants (pilot.py VZ_* values)."""

    vz_tau_s: float = 4.0            # leak time constant (pilot VZ_LEAK_TAU)
    vz_clamp: float = 2.0            # |vz_est| ceiling, m/s (pilot VZ_CLAMP)
    vz_freeze_tilt_deg: float = 25.0  # beyond this tilt: decay-only, no innovation (pilot VZ_TILT_LIMIT)


@register_task("hover_blind_v2")
class HoverBlindV2Task(HoverBlindTask):
    """IMU-only hover with a deploy-realistic leaky climb-rate estimate as a 6th channel."""

    n_agents = 1
    obs_dim = 6  # [roll, pitch, p, q, r, vz_est]
    config_cls = HoverBlindV2Config

    def setup(self, env) -> None:
        super().setup(env)
        n = env.n_drones
        self.vz_est = torch.zeros(n, device=env.device)
        self._prev_vz = torch.zeros(n, device=env.device)
        self._freeze_rad = math.radians(self.cfg.vz_freeze_tilt_deg)

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        d_idx = env.drone_idx(env_idx)
        self.vz_est[d_idx] = 0.0
        # Seed the innovation reference from the post-spawn velocity so a moving spawn does not
        # inject a phantom first-step climb (mirrors pilot.py arming vz at 0 on the ground).
        self._prev_vz[d_idx] = env.dyn.vel_world[d_idx, 2]

    def observe(self, env) -> Tensor:
        # Pure read — safe to call twice on reset steps.
        base = super().observe(env)
        return torch.cat([base, self.vz_est.unsqueeze(-1)], dim=-1).to(torch.float32)

    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        # Advance the estimator here: runs exactly once per step, post-dynamics, before the env
        # builds the terminal/next observation frames.
        c = self.cfg
        vz_now = env.dyn.vel_world[..., 2]
        rpy = env.dyn.rpy
        upright = (rpy[..., 0].abs() < self._freeze_rad) & (rpy[..., 1].abs() < self._freeze_rad)
        innov = torch.where(upright, vz_now - self._prev_vz, torch.zeros_like(vz_now))
        decay = math.exp(-env.dt / c.vz_tau_s)
        self.vz_est = ((self.vz_est + innov) * decay).clamp(-c.vz_clamp, c.vz_clamp)
        # Tilted steps discard their evidence entirely (pilot integrates acceleration only while
        # upright), so the reference always tracks the current velocity.
        self._prev_vz = vz_now
        return super().reward_and_done(env, action)
