"""hover_tof: IMU + measured-height hover — the first task with a real exteroceptive channel.

The VL53L1X on the bridge (docs/SIM2REAL.md "Measured height", 2026-07-13) gives the pilot a
*measured* height above the floor — the first non-IMU-integrated state channel, and the direct
answer to the vz_est DC-bias ceiling every blind flight hit. This task closes the altitude loop
in the obs: **obs = [roll, pitch, p, q, r, height_err]** (6), where ``height_err`` is the
setpoint's z minus the *measured* height — the same "target minus measurement" convention as
obs-v4's ``target_rel``, so positive means "climb".

Deploy contract (``neural_whoop.pilot``): the pilot feeds ``target_height_m − h`` with
``h = tof_range · cos(roll) · cos(pitch)`` (the flat-floor tilt correction — the ray leaves along
body −z, so slant·cosθ IS the height), zero-order-held at the last valid reading whenever the
sensor is stale/invalid. The sim mirrors exactly that estimator structure:

- **Update rate**: the sensor ranges at ~``tof_rate_hz`` (40) against the 50 Hz control loop —
  each step each drone refreshes with probability ``tof_rate_hz · dt``, else holds.
- **Saturation**: short-distance mode is trustworthy to ~``tof_max_m`` (1.3 m) slant range; a
  longer ray returns status != 0 on the real part → the pilot holds. Here: hold.
- **Tilt gating**: past ``tof_tilt_limit_deg`` the ray misses the spot under the drone (and the
  cos correction degrades) → hold.

When fresh + valid the sim reading is the TRUE ``z`` (the deploy cos-correction recovers exactly
z over a flat floor); ranging noise and mount/surface bias are deliberately NOT modeled here —
they ride the per-channel obs-noise/bias DR (:mod:`neural_whoop.randomization`), so ``--no-dr``
eval is the noise-free ablation for free. (Approximation: the DR draws fresh noise even on held
steps, where the real sensor would freeze the reading noise with the hold. The hold windows are
1–2 steps at 40 vs 50 Hz, so the spectrum error is small.)

Sensor state advances in :meth:`reward_and_done` (exactly once per step, post-dynamics), NOT in
:meth:`observe` — the env calls ``observe`` twice on reset steps and a stateful draw there would
double-advance the hold process. ``observe`` is a pure read (same discipline as hover_blind_v2).

Everything else (reward, spawn/recovery curriculum, metrics, Studio scene) is inherited from
``hover_blind`` / ``hover``. Configs should keep the setpoint z band inside the sensor's valid
band (e.g. 0.5–1.1 m); spawns above ``tof_max_m`` are useful saturation-recovery exposure.
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
class HoverTofConfig(HoverConfig):
    """Hover config + the bridge VL53L1X sensor model (firmware/xiao_bridge short-distance mode)."""

    tof_rate_hz: float = 40.0        # ranging rate (bridge short-distance timing budget)
    tof_max_m: float = 1.3           # trustworthy slant range in short mode (ambient-robust band)
    tof_tilt_limit_deg: float = 45.0  # beyond this tilt: reading invalid -> hold


@register_task("hover_tof")
class HoverTofTask(HoverBlindTask):
    """IMU + measured-height hover: the deploy-held ToF height error as a 6th channel."""

    n_agents = 1
    obs_dim = 6  # [roll, pitch, p, q, r, height_err]
    config_cls = HoverTofConfig

    def setup(self, env) -> None:
        super().setup(env)
        c = self.cfg
        n = env.n_drones
        self.h_meas = torch.zeros(n, device=env.device)
        self._p_update = min(1.0, c.tof_rate_hz * env.dt)
        self._cos_limit = math.cos(math.radians(c.tof_tilt_limit_deg))

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        # Seed the hold state with the spawn height clamped into the sensor band — "the last valid
        # reading on the way here" (deploy: the estimator tracks continuously from takeoff, where
        # the sensor always ranges; sim episodes have no takeoff, so the seed stands in for it).
        d_idx = env.drone_idx(env_idx)
        self.h_meas[d_idx] = env.dyn.pos[d_idx, 2].clamp(0.0, self.cfg.tof_max_m)

    def observe(self, env) -> Tensor:
        # Pure read — safe to call twice on reset steps.
        base = super().observe(env)
        err = (self.setpoint[:, 2] - self.h_meas).unsqueeze(-1)
        return torch.cat([base, err], dim=-1).to(torch.float32)

    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        # Advance the sensor here: exactly once per step, post-dynamics, before the env builds
        # the terminal/next observation frames.
        c = self.cfg
        z = env.dyn.pos[..., 2]
        rpy = env.dyn.rpy
        cos_tilt = torch.cos(rpy[..., 0]) * torch.cos(rpy[..., 1])
        slant = z / cos_tilt.clamp_min(1e-3)
        valid = (cos_tilt > self._cos_limit) & (slant <= c.tof_max_m) & (slant >= 0.0)
        ranged = torch.rand(z.shape, device=z.device, generator=env.gen) < self._p_update
        self.h_meas = torch.where(ranged & valid, z, self.h_meas)
        return super().reward_and_done(env, action)
