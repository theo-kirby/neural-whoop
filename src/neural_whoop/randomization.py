"""Batched domain randomization — the sim2real seam, ported and vectorized.

Two layers of DR combine in this lab:

1. **Airframe DR** (mass / inertia / drag / arm length / torque constant) is handled *inside*
   DiffAero's :class:`QuadrotorModel` and refreshed per-episode by
   :class:`~neural_whoop.dynamics.whoop.WhoopDynamics`.
2. **Seam DR** (this module) is everything DiffAero doesn't model, ported from
   neural-whoop-lab's ``randomization.py``: a steady **wind** acceleration, a **rate-gain**
   scale (the unknown Betaflight rate-tune gap), a **thrust** scale (motor-strength spread),
   **observation noise**, and **action latency** (sense->infer->actuate delay). Detector
   error lives in :mod:`neural_whoop.perception`; its magnitudes are carried here.

Each field models a real gap between a perfect sim and a whoop-class drone; training across
them is what makes a tiny policy transferable. All state is per-drone (the dynamics batch is
``n_envs * n_agents`` flattened) and GPU-resident.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.perception.estimator import DetectorNoise


@dataclass(frozen=True)
class DomainRandomizationConfig:
    """Magnitudes (ranges) for the seam-level DR. ``enabled=False`` makes every hook a no-op.

    Attributes:
        enabled: Master switch.
        wind_accel_mps2: Max steady wind acceleration magnitude (m/s^2), per episode.
        rate_gain_frac: Per-drone body-rate command scale drawn from ``1 ± frac``.
        thrust_scale_frac: Per-drone collective-thrust command scale drawn from ``1 ± frac``.
        obs_noise_std: Std of Gaussian noise added to the observation vector.
        action_latency_steps: Max actuation delay in control steps (per-drone 0..max).
        detector_bearing_deg: Detector bearing-noise std (deg); 0 = off.
        detector_range_frac: Detector multiplicative range-error std; 0 = off.
        detector_dropout_prob: Per-step detector dropout probability.
        detector_fov_deg: Detector forward field-of-view (full angle, deg).
        impulse_prob: Per-step Bernoulli probability of a random kick (push / dropped block);
            0 = off. The hover task trains against these so a live editor's shoves are survivable.
        impulse_vel_mps: Max world-frame linear-velocity kick magnitude (m/s) when one fires.
        impulse_rate_rps: Max body-rate kick magnitude (rad/s) — the tumble a dropped block adds.
    """

    enabled: bool = True
    wind_accel_mps2: float = 1.5
    rate_gain_frac: float = 0.15
    thrust_scale_frac: float = 0.10
    obs_noise_std: float = 0.01
    action_latency_steps: int = 1
    detector_bearing_deg: float = 0.0
    detector_range_frac: float = 0.0
    detector_dropout_prob: float = 0.0
    detector_fov_deg: float = 360.0
    impulse_prob: float = 0.0
    impulse_vel_mps: float = 0.0
    impulse_rate_rps: float = 0.0

    @property
    def detector(self) -> DetectorNoise:
        """The :class:`DetectorNoise` magnitudes implied by the detector knobs."""
        return DetectorNoise(
            bearing_std_rad=math.radians(max(0.0, self.detector_bearing_deg)),
            range_frac=max(0.0, self.detector_range_frac),
            dropout_prob=min(max(0.0, self.detector_dropout_prob), 1.0),
            fov_half_rad=math.radians(max(0.0, self.detector_fov_deg) / 2.0),
        )


class DomainRandomizer:
    """Per-drone seam DR state + the per-step hooks the env applies.

    Args:
        cfg: The :class:`DomainRandomizationConfig`.
        n_drones: Flattened dynamics batch size (``n_envs * n_agents``).
        act_dim: Action vector length (for the latency ring buffer).
        dt: Control timestep (s), for the wind acceleration integral.
        device: Torch device.
        generator: Optional torch ``Generator`` for reproducibility.
    """

    def __init__(
        self,
        cfg: DomainRandomizationConfig,
        n_drones: int,
        act_dim: int,
        dt: float,
        device: torch.device | str = "cpu",
        generator: torch.Generator | None = None,
    ):
        self.cfg = cfg
        self.n = n_drones
        self.dt = dt
        self.dev = torch.device(device)
        self.gen = generator
        self.act_dim = act_dim
        self._max_lat = max(0, int(cfg.action_latency_steps)) if cfg.enabled else 0
        # Curriculum scale in [0, 1]: multiplies every seam-DR magnitude (1.0 = full configured
        # strength). The trainer can ramp this 0->1 over training (reliability curriculum); it is
        # applied per-drone at reset (wind/rate/thrust/latency incidence) and per-step for obs noise.
        self.scale = 1.0

        self.wind = torch.zeros(n_drones, 3, device=self.dev)
        self.rate_gain = torch.ones(n_drones, 1, device=self.dev)
        self.thrust_scale = torch.ones(n_drones, 1, device=self.dev)
        self.latency = torch.zeros(n_drones, device=self.dev, dtype=torch.long)
        # Action ring buffer: (max_lat + 1, n, act_dim).
        self._buf = torch.zeros(self._max_lat + 1, n_drones, act_dim, device=self.dev)
        self._step = 0
        self.reset(torch.arange(n_drones, device=self.dev))

    def _rand(self, *shape: int, lo: float = 0.0, hi: float = 1.0) -> Tensor:
        return torch.rand(*shape, device=self.dev, generator=self.gen) * (hi - lo) + lo

    def reset(self, idx: Tensor) -> None:
        """Resample per-drone DR params for drones ``idx`` and clear their latency buffers."""
        if not self.cfg.enabled or idx.numel() == 0:
            return
        c = self.cfg
        n = idx.numel()
        s = self.scale  # curriculum scale: shrinks every magnitude toward 0 early in training
        # Steady wind: random horizontal direction + small vertical component.
        ang = self._rand(n, lo=0.0, hi=2 * math.pi)
        mag = self._rand(n, lo=0.0, hi=c.wind_accel_mps2 * s)
        vert = self._rand(n, lo=-0.15, hi=0.15) * c.wind_accel_mps2 * s
        self.wind[idx] = torch.stack([mag * ang.cos(), mag * ang.sin(), vert], dim=-1)
        self.rate_gain[idx, 0] = self._rand(n, lo=1 - c.rate_gain_frac * s, hi=1 + c.rate_gain_frac * s)
        self.thrust_scale[idx, 0] = self._rand(n, lo=1 - c.thrust_scale_frac * s, hi=1 + c.thrust_scale_frac * s)
        if self._max_lat > 0:
            lat = torch.randint(0, self._max_lat + 1, (n,), device=self.dev, generator=self.gen)
            if s < 1.0:  # ramp latency *incidence* with the curriculum (latency is integer-valued)
                lat = lat * (self._rand(n) < s).long()
            self.latency[idx] = lat
        self._buf[:, idx, :] = 0.0

    def delay_action(self, action: Tensor) -> Tensor:
        """Push ``action`` (n, act_dim) into the ring buffer and return the per-drone delayed one."""
        if self._max_lat == 0 or not self.cfg.enabled:
            return action
        L = self._max_lat + 1
        head = self._step % L
        self._buf[head] = action
        read = (self._step - self.latency) % L  # (n,)
        delayed = self._buf[read, torch.arange(self.n, device=self.dev)]
        self._step += 1
        return delayed

    def perturb_ctbr(self, ctbr: Tensor) -> Tensor:
        """Scale the DiffAero-convention action: thrust by ``thrust_scale``, rates by ``rate_gain``."""
        if not self.cfg.enabled:
            return ctbr
        out = ctbr.clone()
        out[..., 0:1] = ctbr[..., 0:1] * self.thrust_scale
        out[..., 1:] = ctbr[..., 1:] * self.rate_gain
        return out

    def wind_dv(self) -> Tensor:
        """Per-drone velocity delta from steady wind this control step, shape ``(n, 3)``."""
        if not self.cfg.enabled or self.cfg.wind_accel_mps2 <= 0.0:
            return torch.zeros(self.n, 3, device=self.dev)
        return self.wind * self.dt

    def _impulse_mask(self) -> Tensor:
        """Per-drone Bernoulli mask of which drones get kicked this step, shape ``(n, 1)``."""
        p = self.cfg.impulse_prob * self.scale
        return (self._rand(self.n, 1) < p).float()

    def impulse_dv(self) -> Tensor:
        """Random world-frame velocity kick this step (push / dropped block), shape ``(n, 3)``.

        A per-drone Bernoulli mask × random unit direction × random magnitude (curriculum-scaled),
        so the policy trains against the same shoves the live Studio editor throws at it. Mostly
        zeros. Returns zeros when disabled — mirrors :meth:`wind_dv`.
        """
        if not self.cfg.enabled or self.cfg.impulse_prob <= 0.0 or self.cfg.impulse_vel_mps <= 0.0:
            return torch.zeros(self.n, 3, device=self.dev)
        direction = torch.randn(self.n, 3, device=self.dev, generator=self.gen)
        direction = direction / direction.norm(dim=-1, keepdim=True).clamp_min(1e-6)
        mag = self._rand(self.n, 1, lo=0.0, hi=self.cfg.impulse_vel_mps * self.scale)
        return self._impulse_mask() * direction * mag

    def impulse_dw(self) -> Tensor:
        """Random body-rate kick this step (the dropped-block tumble), shape ``(n, 3)``.

        Same Bernoulli incidence as :meth:`impulse_dv` but an independent mask/direction (a kick
        need not always tumble). Returns zeros when disabled.
        """
        if not self.cfg.enabled or self.cfg.impulse_prob <= 0.0 or self.cfg.impulse_rate_rps <= 0.0:
            return torch.zeros(self.n, 3, device=self.dev)
        direction = torch.randn(self.n, 3, device=self.dev, generator=self.gen)
        direction = direction / direction.norm(dim=-1, keepdim=True).clamp_min(1e-6)
        mag = self._rand(self.n, 1, lo=0.0, hi=self.cfg.impulse_rate_rps * self.scale)
        return self._impulse_mask() * direction * mag

    def add_obs_noise(self, obs: Tensor) -> Tensor:
        """Add Gaussian observation noise (no-op if disabled / std==0 / curriculum scale==0)."""
        std = self.cfg.obs_noise_std * self.scale
        if not self.cfg.enabled or std <= 0.0:
            return obs
        return obs + torch.randn(obs.shape, device=obs.device, generator=self.gen) * std
