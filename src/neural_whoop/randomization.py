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
        obs_noise_std: Std of Gaussian noise added to the observation vector (all channels).
        obs_noise_std_channels: Per-channel noise stds (length == the task's ``obs_dim``);
            when non-empty this OVERRIDES the scalar ``obs_noise_std``. Lets the noise model
            be honest per channel — e.g. the measured whoop gyro vibration floor (~2.5 rad/s)
            vs a quiet attitude estimate (~0.02 rad).
        obs_noise_ar_channels: Per-channel AR(1) coefficients ``rho in [0, 1)`` (length ==
            ``obs_dim``); when non-empty the per-channel noise becomes a marginal-preserving
            AR(1) process (``state = rho*state + sqrt(1-rho^2)*sigma*randn`` -> ``Var = sigma^2``
            exactly, autocorrelation ``rho^k``) instead of fresh i.i.d. white noise each step.
            Models a *filtered* real sensor stream — the deployed gyro is Betaflight-LPF/notch-
            filtered (``gyroADCf``), so its noise is time-correlated; injecting the measured
            amplitude as white noise matches the marginal but not the spectrum. ``rho=0`` on a
            channel reproduces white noise. Requires ``obs_noise_std_channels``. Empty = legacy
            white noise.
        obs_bias_channels: Per-channel, per-episode constant observation bias ranges (length ==
            ``obs_dim``); each drone draws ``uniform(±range)`` per channel at reset. Models the
            slowly-varying DC errors real sensors carry (attitude mount bias, vz vibration DC
            offset) that per-step noise can't represent. Empty = off.
        obs_noise_amp_range: Per-episode noise AMPLITUDE randomization ``(lo, hi)``: each drone
            draws a scalar factor ``uniform(lo, hi)`` at reset that multiplies its per-channel
            obs noise (white or AR(1)) for the whole episode. Empty = off (factor 1). Models the
            real uncertainty in the vibration-noise level (throttle, battery, prop wear, and how
            much bridge-side oversampling actually averages out) — the d50 M1-live diagnostic
            showed a fixed-amplitude-trained policy's thrust trim is a steep function of the
            noise sd (81%/43%/0.3% survival at 0.8x/1.0x/1.2x the trained amplitude), so training
            across an amplitude band is what forces an amplitude-invariant/adaptive trim. The
            factor deliberately does NOT scale ``obs_bias_channels`` (a DC error is not vibration).
            Requires ``obs_noise_std_channels``.
        obs_noise_amp_curriculum: If True, the amp band itself rides the DR curriculum scale:
            at scale ``s`` the per-episode factor is drawn from the band interpolated from
            ``(1, 1)`` toward ``(lo, hi)`` — ``(1-(1-lo)*s, 1+(hi-1)*s)`` — so early training
            masters the nominal amplitude before the tail widens (the w-ladder showed nominal
            leveling and tail robustness compete when both are trained from step 0). Default
            False = the legacy fixed-spread band from step 0.
        action_latency_steps: Max actuation delay in control steps (per-drone 0..max).
        action_latency_dist: Per-STEP jittered actuation delay — probability weights for packet
            age 0..len-1 (steps), replacing the per-episode-constant model when non-empty. Each
            step each drone samples the age of its freshest-arrived command packet from these
            weights; the applied command index is clamped monotonic (a newer command, once
            applied, is never rolled back — the latest-packet zero-order-hold a real FC link
            implements). Models a jittering radio link (e.g. the measured ESP32 bridge: obs-age
            p50 24 ms / p99 112 ms at 50 Hz) instead of the harsher constant-delay hedge.
            APPROXIMATION note: the sampled age is the freshest-packet age *before* the monotonic
            clamp, so effective ages are <= sampled — calibrate the weights to the measured
            percentiles and flag them until bench-validated.
        uplink_latency_steps: Max staleness (control steps, per-drone 0..max) of the task's
            *uplinked* obs channels (``DroneTask.uplink_slices``) — the onboard-hybrid split
            where state obs are locally fresh but the target channel rides a radio uplink.
        uplink_interval_steps: Uplink sender period in control steps (zero-order hold between
            arrivals); 1 = every step (no hold). ~30 Hz uplink at 50 Hz control -> 2.
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
    obs_noise_std_channels: tuple[float, ...] = ()
    obs_noise_ar_channels: tuple[float, ...] = ()
    obs_bias_channels: tuple[float, ...] = ()
    obs_noise_amp_range: tuple[float, ...] = ()
    obs_noise_amp_curriculum: bool = False
    action_latency_steps: int = 1
    action_latency_dist: tuple[float, ...] = ()
    uplink_latency_steps: int = 0
    uplink_interval_steps: int = 1
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
        uplink_slices: Obs channel slices that ride the radio uplink (``DroneTask.uplink_slices``);
            empty -> the uplink hooks are no-ops.
        obs_dim: The task's (pre-stacking) observation length; required (non-zero) when the
            per-channel ``obs_noise_std_channels`` / ``obs_bias_channels`` are configured.
    """

    def __init__(
        self,
        cfg: DomainRandomizationConfig,
        n_drones: int,
        act_dim: int,
        dt: float,
        device: torch.device | str = "cpu",
        generator: torch.Generator | None = None,
        uplink_slices: tuple[slice, ...] = (),
        obs_dim: int = 0,
    ):
        self.cfg = cfg
        self.n = n_drones
        self.dt = dt
        self.dev = torch.device(device)
        self.gen = generator
        self.act_dim = act_dim
        # Jittered-link mode: per-step sampled packet ages override the per-episode-constant
        # latency; the ring buffer is sized by the distribution's support instead.
        if len(cfg.action_latency_dist) > 0 and cfg.enabled:
            w = torch.tensor(cfg.action_latency_dist, dtype=torch.float32)
            if (w < 0).any() or w.sum() <= 0:
                raise ValueError("action_latency_dist weights must be non-negative and sum > 0")
            self._lat_dist = (w / w.sum()).to(torch.device(device))
            self._max_lat = len(cfg.action_latency_dist) - 1
        else:
            self._lat_dist = None
            self._max_lat = max(0, int(cfg.action_latency_steps)) if cfg.enabled else 0
        # Latest-applied command index per drone (jitter mode): monotonic zero-order hold.
        self._applied_idx = torch.zeros(n_drones, dtype=torch.long, device=torch.device(device))
        # Curriculum scale in [0, 1]: multiplies every seam-DR magnitude (1.0 = full configured
        # strength). The trainer can ramp this 0->1 over training (reliability curriculum); it is
        # applied per-drone at reset (wind/rate/thrust/latency incidence) and per-step for obs noise.
        self.scale = 1.0

        # Per-channel obs noise/bias (both are per-frame, PRE-stacking — the env noises each raw
        # frame, so a drawn bias is automatically constant across the stacked history, matching a
        # physical mount/DC bias). Tuple lengths must match the task's obs_dim exactly.
        for name, chans in (("obs_noise_std_channels", cfg.obs_noise_std_channels),
                            ("obs_noise_ar_channels", cfg.obs_noise_ar_channels),
                            ("obs_bias_channels", cfg.obs_bias_channels)):
            if len(chans) > 0 and len(chans) != obs_dim:
                raise ValueError(
                    f"{name} has {len(chans)} entries but the task obs_dim is {obs_dim}"
                )
        if len(cfg.obs_noise_ar_channels) > 0:
            if not cfg.obs_noise_std_channels:
                raise ValueError("obs_noise_ar_channels requires obs_noise_std_channels")
            if any(not (0.0 <= r < 1.0) for r in cfg.obs_noise_ar_channels):
                raise ValueError("obs_noise_ar_channels entries must be in [0, 1)")
        if len(cfg.obs_noise_amp_range) > 0:
            if len(cfg.obs_noise_amp_range) != 2:
                raise ValueError("obs_noise_amp_range must be (lo, hi)")
            lo, hi = cfg.obs_noise_amp_range
            if not (0.0 <= lo <= hi):
                raise ValueError("obs_noise_amp_range requires 0 <= lo <= hi")
            if not cfg.obs_noise_std_channels:
                raise ValueError("obs_noise_amp_range requires obs_noise_std_channels")
        self._noise_std = (
            torch.tensor(cfg.obs_noise_std_channels, device=self.dev, dtype=torch.float32)
            if cfg.obs_noise_std_channels else None
        )
        self._noise_ar = (
            torch.tensor(cfg.obs_noise_ar_channels, device=self.dev, dtype=torch.float32)
            if (cfg.obs_noise_ar_channels and cfg.enabled) else None
        )
        # AR(1) colored-noise state, in unscaled sigma units (curriculum scale applies at read
        # time, like the white path). Advanced exactly once per control step by step_noise();
        # add_obs_noise() is then a pure read — _raw_obs() runs twice on terminal steps and a
        # stateful draw there would double-advance the process.
        self._noise_state = (
            torch.zeros(n_drones, obs_dim, device=self.dev) if self._noise_ar is not None else None
        )
        self._bias_range = (
            torch.tensor(cfg.obs_bias_channels, device=self.dev, dtype=torch.float32)
            if cfg.obs_bias_channels else None
        )
        # Per-episode noise-amplitude factor, (n, 1); ones = off. Multiplies the per-channel
        # noise at read time (white draw or AR state) but never the DC obs_bias.
        self._amp_range = (
            tuple(cfg.obs_noise_amp_range) if (cfg.obs_noise_amp_range and cfg.enabled) else None
        )
        self._noise_amp = torch.ones(n_drones, 1, device=self.dev)
        self.obs_bias = torch.zeros(n_drones, obs_dim, device=self.dev)

        self.wind = torch.zeros(n_drones, 3, device=self.dev)
        self.rate_gain = torch.ones(n_drones, 1, device=self.dev)
        self.thrust_scale = torch.ones(n_drones, 1, device=self.dev)
        self.latency = torch.zeros(n_drones, device=self.dev, dtype=torch.long)
        # Action ring buffer: (max_lat + 1, n, act_dim).
        self._buf = torch.zeros(self._max_lat + 1, n_drones, act_dim, device=self.dev)
        self._step = 0

        # Uplink obs staleness (onboard-hybrid split): the task-declared uplink channels are
        # delayed per-drone and zero-order-held between sender periods, while every other obs
        # channel stays fresh. Mirrors the action ring buffer.
        self._max_ulat = max(0, int(cfg.uplink_latency_steps)) if cfg.enabled else 0
        self._uint = max(1, int(cfg.uplink_interval_steps)) if cfg.enabled else 1
        self._uslices = tuple(uplink_slices) if (self._max_ulat > 0 or self._uint > 1) else ()
        self._udim = sum(s.stop - s.start for s in self._uslices)
        self.uplink_lat = torch.zeros(n_drones, device=self.dev, dtype=torch.long)
        if self._udim > 0:
            # Buffer depth covers the max age = max_lat + (interval - 1).
            self._ubuf = torch.zeros(self._max_ulat + self._uint, n_drones, self._udim, device=self.dev)
            # Per-drone floor: never read across an episode reset (fresh episodes hold their
            # first computed value until the first delayed packet "arrives").
            self._ufloor = torch.zeros(n_drones, device=self.dev, dtype=torch.long)
            self._ustep = 0

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
        if self._bias_range is not None:
            self.obs_bias[idx] = (self._rand(n, self._bias_range.numel()) * 2 - 1) * self._bias_range * s
        if self._amp_range is not None:
            lo, hi = self._amp_range
            if c.obs_noise_amp_curriculum:
                # The amp *spread* rides the curriculum: band interpolates (1,1) -> (lo,hi) with
                # s, so the nominal amplitude is mastered before the tail widens.
                lo, hi = 1.0 - (1.0 - lo) * s, 1.0 + (hi - 1.0) * s
            # else: NOT curriculum-scaled — the overall noise level already ramps via `scale` at
            # read time; the amplitude spread is the thing being trained against and stays fixed.
            self._noise_amp[idx, 0] = self._rand(n, lo=lo, hi=hi)
        if self._noise_state is not None:
            # Fresh episodes start the AR(1) noise at its stationary marginal N(0, sigma^2)
            # (not zero), so the read-time variance is exactly sigma^2 from t=0 — a real filtered
            # sensor stream has no quiet warm-up window at an episode boundary.
            self._noise_state[idx] = (
                torch.randn(n, self._noise_state.shape[1], device=self.dev, generator=self.gen)
                * self._noise_std
            )
        if self._max_lat > 0 and self._lat_dist is None:
            lat = torch.randint(0, self._max_lat + 1, (n,), device=self.dev, generator=self.gen)
            if s < 1.0:  # ramp latency *incidence* with the curriculum (latency is integer-valued)
                lat = lat * (self._rand(n) < s).long()
            self.latency[idx] = lat
        if self._lat_dist is not None:
            # Fresh episodes carry no packet backlog: the applied-index floor starts at "now".
            self._applied_idx[idx] = self._step
        self._buf[:, idx, :] = 0.0
        if self._udim > 0:
            if self._max_ulat > 0:
                ulat = torch.randint(0, self._max_ulat + 1, (n,), device=self.dev, generator=self.gen)
                if s < 1.0:  # same incidence ramp as action latency (interval is not ramped)
                    ulat = ulat * (self._rand(n) < s).long()
                self.uplink_lat[idx] = ulat
            self._ufloor[idx] = self._ustep

    def delay_action(self, action: Tensor) -> Tensor:
        """Push ``action`` (n, act_dim) into the ring buffer and return the per-drone delayed one.

        Constant mode: per-episode latency drawn at reset. Jitter mode (``action_latency_dist``):
        each step each drone samples its freshest-packet age and applies the newest command it
        has "received", monotonically (an applied command is never rolled back to an older one).
        """
        if self._max_lat == 0 or not self.cfg.enabled:
            return action
        L = self._max_lat + 1
        head = self._step % L
        self._buf[head] = action
        if self._lat_dist is not None:
            age = torch.multinomial(self._lat_dist.expand(self.n, -1), 1, replacement=True,
                                    generator=self.gen).squeeze(-1)
            if self.scale < 1.0:  # curriculum: ramp jitter incidence like the constant path
                age = age * (self._rand(self.n) < self.scale).long()
            cand = self._step - age
            self._applied_idx = torch.maximum(self._applied_idx, cand)
            read = self._applied_idx % L
        else:
            read = (self._step - self.latency) % L  # (n,)
        delayed = self._buf[read, torch.arange(self.n, device=self.dev)]
        self._step += 1
        return delayed

    def delay_uplink(self, obs: Tensor) -> Tensor:
        """Replace the uplink obs channels with their delayed + zero-order-held values.

        Push the current (already noised — measurement noise travels with the packet and is
        frozen across holds) uplink channels into the ring buffer, then read back, per drone,
        the value the uplink sender computed at ``floor((t - lat) / interval) * interval``
        (clamped to this drone's episode start). No-op when no uplink channels or DR disabled.
        """
        if self._udim == 0 or not self.cfg.enabled:
            return obs
        vals = torch.cat([obs[:, sl] for sl in self._uslices], dim=-1)
        L = self._ubuf.shape[0]
        t = self._ustep
        self._ubuf[t % L] = vals
        src = ((t - self.uplink_lat) // self._uint) * self._uint  # per-drone sender step
        src = torch.maximum(src, self._ufloor)
        stale = self._ubuf[src % L, torch.arange(self.n, device=self.dev)]
        self._ustep = t + 1
        out = obs.clone()
        ofs = 0
        for sl in self._uslices:
            w = sl.stop - sl.start
            out[:, sl] = stale[:, ofs : ofs + w]
            ofs += w
        return out

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

    def step_noise(self) -> None:
        """Advance the AR(1) colored-noise state by one control step (no-op on the white paths).

        Marginal-preserving update: ``state = rho*state + sqrt(1-rho^2)*sigma*randn`` keeps
        ``Var(state) = sigma^2`` exactly at every step with autocorrelation ``rho^k``. Must be
        called exactly ONCE per env control step (the env owns this); :meth:`add_obs_noise` is a
        pure read of the current state, so the double ``_raw_obs()`` on terminal steps cannot
        double-advance the process.
        """
        if self._noise_state is None:
            return
        innov = torch.randn(
            self._noise_state.shape, device=self.dev, generator=self.gen
        ) * (self._noise_std * torch.sqrt(1.0 - self._noise_ar**2))
        self._noise_state.mul_(self._noise_ar).add_(innov)

    def add_obs_noise(self, obs: Tensor) -> Tensor:
        """Add Gaussian observation noise + the per-episode channel bias.

        Per-channel path (``obs_noise_std_channels`` set): each channel gets its own noise std
        (curriculum-scaled per step) plus this drone's episode-constant ``obs_bias`` (curriculum-
        scaled at draw time, like ``thrust_scale``). With ``obs_noise_ar_channels`` set the
        per-channel noise is the AR(1) state advanced by :meth:`step_noise` (a pure read here).
        Legacy scalar path unchanged. No-op if disabled.
        """
        if not self.cfg.enabled:
            return obs
        if self._noise_state is not None:
            out = obs + self._noise_state * (self._noise_amp * self.scale)
        elif self._noise_std is not None:
            out = obs + torch.randn(obs.shape, device=obs.device, generator=self.gen) * (
                self._noise_std * (self._noise_amp * self.scale)
            )
        else:
            std = self.cfg.obs_noise_std * self.scale
            out = obs if std <= 0.0 else (
                obs + torch.randn(obs.shape, device=obs.device, generator=self.gen) * std
            )
        if self._bias_range is not None:
            out = out + self.obs_bias
        return out
