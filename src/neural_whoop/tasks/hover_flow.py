"""hover_flow: IMU + measured height + measured horizontal velocity — the first CLOSED-LOOP hover.

``hover_blind`` observes attitude only, ``hover_tof`` adds the measured height. Both leave the
horizontal axis **open-loop**: with no position or velocity channel, drift is set entirely by
leveling quality and nothing in the obs can see it happening. Every desk-scale result in this
lab carries that caveat (``configs/desk-hover.yaml``: "clean pure-hold drift 0.069 m ... under
sensor noise alone both arms drift 0.55-0.77 m"). This task is the answer: the PMW3901 on the
bridge (``firmware/xiao_bridge/``, ``MSP_BRIDGE_FLOW``) makes horizontal velocity *measured*, so
**obs = [roll, pitch, p, q, r, height_err, vx, vy]** (8) — body-frame, heading-invariant, and
still nothing the real drone cannot supply.

It is deliberately velocity and NOT position. Integrating flow to a position would be free here
and dishonest: on hardware that integral drifts without bound and nothing observes the drift, so
a policy trained on it would learn to trust a channel that decays. Velocity is what the sensor
actually measures. The consequence is that this is a *drift-rate* controller, not a station-keep
— it can hold still, it cannot return to a point it has already left. Saying otherwise would
repeat the mistake the ``hover_blind`` docs were written to avoid.

Deploy contract (``neural_whoop.pilot``). The bridge reports raw counts; the host forms

    v = (counts / dt) * rad_per_count * height

with ``rad_per_count`` MEASURED on the bench (the ``flow_probe`` slide test) and ``height`` the
ToF's. Three structural consequences are modeled here, because each one is a way the channel
lies rather than merely a way it is noisy:

- **Height multiplies straight into the velocity scale.** The host has no true height, only
  ``h_meas`` — so the sim scales the true velocity by ``h_meas / z``. This is free (the ToF hold
  state is already tracked by ``hover_tof``) and it is the dominant error at desk scale: the
  measured +23.9 mm ToF offset is 24% of a 0.10 m setpoint, hence 24% of velocity.
- **Below ``flow_min_m`` the sensor is blind.** The PMW3901's working range starts at 80 mm.
  This is a hard optical limit, not a noise floor, and it is the reason this task's setpoint
  band sits well above Desk-Hover's 0.10 m.
- **A featureless floor returns no motion at full frame rate.** Dropout is modeled explicitly
  (``flow_dropout_prob``) because "frames arriving, counts meaningless" is invisible to every
  freshness check.

**Blind handling is grace-then-fade to zero, not hold** — the same guard the deployed pilot
applies to a stale ToF (``--tof-blind-grace/--tof-blind-fade``, docs/SIM2REAL.md). Holding a
stale velocity indefinitely is precisely the confidently-wrong-held-channel shape that flew the
2026-07-31 crash; and unlike a held height error, a faded velocity decays to a HONEST neutral
("I don't know that I'm moving"), so the fade costs nothing.

Ranging noise, bias and the flow scale calibration error ride the per-channel obs-noise/bias DR
(:mod:`neural_whoop.randomization`) exactly as ``hover_tof``'s height does, so ``--no-dr`` eval
is the noise-free ablation for free. The one flow error that is NOT Gaussian — a per-episode
multiplicative scale error, i.e. "``rad_per_count`` was calibrated 8% off" — is drawn in-task
(``flow_scale_frac``), because a multiplicative error on the signal is not something an additive
DR channel can express.

Sensor state advances in :meth:`reward_and_done` (exactly once per step, post-dynamics), NOT in
:meth:`observe`, which stays a pure read — the env calls ``observe`` twice on reset steps and a
stateful draw there would double-advance. Same discipline as ``hover_tof`` / ``hover_blind_v2``.

Everything else (reward, spawn/recovery curriculum, metrics, Studio scene) is inherited.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import world_to_body
from neural_whoop.envs.registry import register_task
from neural_whoop.tasks.hover_tof import HoverTofConfig, HoverTofTask


@dataclass
class HoverFlowConfig(HoverTofConfig):
    """hover_tof config + the bridge PMW3901 sensor model (firmware/xiao_bridge/pmw3901.h)."""

    flow_rate_hz: float = 50.0        # counts ACCUMULATE between reads, so the host gets a fresh
                                      # interval every control tick — unlike the ToF, which holds.
                                      # Placeholder until a flight measures the delivered rate the
                                      # way 2026-07-30 measured the ToF's 40 -> 25.
    flow_min_m: float = 0.08          # PMW3901 working range starts here (datasheet). HARD limit.
    flow_tilt_limit_deg: float = 30.0  # tighter than the ToF's 45: tilt rotates the measured
                                      # ground plane out from under the flat-floor assumption
                                      # faster than it degrades a single ranging ray.
    flow_dropout_prob: float = 0.02   # per-step chance the surface returns nothing usable (low
                                      # texture / low light). PLACEHOLDER — the calibration flight
                                      # measures it from the logged squal.
    flow_scale_frac: float = 0.10     # per-episode multiplicative scale error on the measured
                                      # rad_per_count, drawn uniform in +-this.
    flow_gyro_residual: float = 0.05  # per-episode residual fraction of the ROTATIONAL flow the
                                      # host's gyro compensation fails to remove (imperfect gyro
                                      # scale / timing sync). Error in velocity units is
                                      # frac * omega * height, so it grows with both.
    flow_blind_grace_s: float = 0.2   # hold the last estimate this long after going blind ...
    flow_blind_fade_s: float = 0.3    # ... then fade it linearly to zero over this long.


@register_task("hover_flow")
class HoverFlowTask(HoverTofTask):
    """IMU + measured height + measured body-frame horizontal velocity (obs 8)."""

    n_agents = 1
    obs_dim = 8  # [roll, pitch, p, q, r, height_err, vx, vy]
    config_cls = HoverFlowConfig

    def setup(self, env) -> None:
        super().setup(env)
        c = self.cfg
        n = env.n_drones
        self.v_meas = torch.zeros(n, 2, device=env.device)   # the estimate the policy sees
        self._v_hold = torch.zeros(n, 2, device=env.device)  # last estimate from a VALID reading
        self._blind_s = torch.zeros(n, device=env.device)    # seconds since the last valid reading
        self._scale = torch.ones(n, device=env.device)       # per-episode calibration error
        self._gyro_res = torch.zeros(n, device=env.device)   # per-episode gyro-compensation residual
        # NOT `_p_update` — that name belongs to HoverTofTask and holds the TOF refresh
        # probability. Reusing it here silently ran the ToF at flow_rate_hz (50) instead of the
        # hardware-measured tof_rate_hz (25), i.e. handed the policy a height channel twice as
        # fresh as the one it gets in flight. Exactly the error the 2026-07-30 sensor
        # characterization was written to prevent; caught by test_height_scales_the_velocity_estimate.
        self._flow_p_update = min(1.0, c.flow_rate_hz * env.dt)
        self._flow_cos_limit = math.cos(math.radians(c.flow_tilt_limit_deg))
        self.flow_valid_sum = torch.zeros(n, device=env.device)

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        c = self.cfg
        d_idx = env.drone_idx(env_idx)
        k = d_idx.numel()
        self.v_meas[d_idx] = 0.0
        self._v_hold[d_idx] = 0.0
        self._blind_s[d_idx] = 0.0
        self.flow_valid_sum[d_idx] = 0.0
        # Per-episode calibration errors. Both are SIGNED and drawn per drone: the bench
        # measurement of rad_per_count is one number for one lens at one height, and the true
        # value in flight is a draw around it. A fixed error would just be a units change the
        # policy could absorb; a per-episode draw is what makes it robustness.
        u = lambda: torch.rand(k, device=env.device, generator=env.gen) * 2.0 - 1.0  # noqa: E731
        self._scale[d_idx] = 1.0 + c.flow_scale_frac * u()
        self._gyro_res[d_idx] = c.flow_gyro_residual * u()

    def observe(self, env) -> Tensor:
        # Pure read — safe to call twice on reset steps.
        base = super().observe(env)
        return torch.cat([base, self.v_meas], dim=-1).to(torch.float32)

    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        # Advance the flow estimator BEFORE super(), which advances the ToF and builds the
        # reward: the flow scale reads h_meas, and reading it after would use a height sampled
        # from the post-step state the deploy path could not have had yet.
        c = self.cfg
        z = env.dyn.pos[..., 2]
        rpy = env.dyn.rpy
        w = env.dyn.ang_vel_body
        cos_tilt = torch.cos(rpy[..., 0]) * torch.cos(rpy[..., 1])

        valid = (
            (cos_tilt > self._flow_cos_limit)
            & (z >= c.flow_min_m)
            & (z <= c.tof_max_m)  # the SCALE comes from the ToF: no height, no velocity
            & (torch.rand(z.shape, device=z.device, generator=env.gen) >= c.flow_dropout_prob)
            & (torch.rand(z.shape, device=z.device, generator=env.gen) < self._flow_p_update)
        )

        # True body-frame horizontal velocity, then the three deploy error terms.
        v_body = world_to_body(env.dyn.vel_world, env.dyn.R)[..., :2]
        height_ratio = self.h_meas / z.clamp_min(1e-3)  # the host scales by the MEASURED height
        # Rotational flow the gyro compensation leaves behind: body-x flow pairs with pitch rate
        # q, body-y with roll rate p. The residual's SIGN is a per-episode draw because the real
        # sign depends on gyro-scale and timing errors that are not known in advance.
        rot = torch.stack([w[..., 1], -w[..., 0]], dim=-1) * self.h_meas.unsqueeze(-1)
        v_est = v_body * (self._scale * height_ratio).unsqueeze(-1) + self._gyro_res.unsqueeze(-1) * rot

        # Grace-then-fade: hold briefly (a dropout is usually one or two frames), then decay to
        # zero rather than asserting a stale velocity forever.
        self._blind_s = torch.where(valid, torch.zeros_like(self._blind_s), self._blind_s + env.dt)
        self._v_hold = torch.where(valid.unsqueeze(-1), v_est, self._v_hold)
        fade = (1.0 - (self._blind_s - c.flow_blind_grace_s) / max(c.flow_blind_fade_s, 1e-6))
        self.v_meas = self._v_hold * fade.clamp(0.0, 1.0).unsqueeze(-1)

        self.flow_valid_sum += valid.float()
        return super().reward_and_done(env, action)

    def metrics(self, env) -> dict:
        m = super().metrics(env)
        steps = self.steps.clamp_min(1).float()
        # The fraction of steps the flow channel actually carried a reading. A policy can look
        # fine on mean_xy_error while flying most of the episode on a faded-to-zero channel, and
        # those are very different results — this is the number that tells them apart.
        m["flow_valid_rate"] = (self.flow_valid_sum / steps).mean().item()
        return m
