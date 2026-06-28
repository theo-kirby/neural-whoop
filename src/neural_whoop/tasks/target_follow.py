"""target_follow: single-drone moving-target following through a noisy detector (perception beachhead).

The first perception-seam task in the catalog (docs/TASK_CATALOG.md). Where ``gate_race`` flies a
fixed geometric course, ``target_follow`` keeps a **moving target** in camera view at a desired
standoff distance — the canonical render-free follow behaviour the moving-target motion models
(:mod:`neural_whoop.target`) and the detector-error seam (:mod:`neural_whoop.perception`) were built
for. It is state/oracle-based like the rest of the lab (no pixels): the policy is fed the body-frame
target-relative vector, optionally corrupted by the :class:`~neural_whoop.perception.estimator`
``DetectorNoise`` model (bearing/range/FOV/dropout + stale-hold). Training **with that seam on** is
how a tiny policy survives real detection error without rendering — the dominant un-bracketed sim2real
gap for every oracle-fed policy in the graph (Flywheel idea node 96fbd7ef).

Observation (length 11): obs-v4 unchanged — ``[gx, gy, gz]`` is the (possibly stale) body-frame
estimate of the target, the rest is body-frame velocity + attitude + rates. The stale-hold is
invisible to the policy (deploy-faithful: a real detector just hands over its last fix).

Reward (per step) = standoff shaping ``exp(-((d - d*)/σ)²)`` (peaks at the desired distance ``d*``)
+ an in-FOV/centering bonus (target near the body +x camera axis) + alive − action-smoothness −
crash. There is **no time penalty** — this is a holding/tracking task, not a race. Termination =
crash (out of arena / ground / ceiling); truncation = episode time limit (env-applied).

Metric: ``time_in_view_rate`` (fraction of steps the target is inside the camera FOV) and
``mean_track_error`` (mean ``|distance − d*|``) — both computed from ground truth, not the noisy
estimate, so detector noise can't game the score.
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
from neural_whoop.perception.estimator import OracleEstimator, apply_detector_noise
from neural_whoop.reward import Bounds, is_crashed, smoothness_penalty


@dataclass
class TargetFollowConfig:
    """Tunable config for :class:`TargetFollowTask` (the reward/curriculum playground)."""

    episode_len: int = 600          # steps; at dt=0.02 -> 12 s of tracking
    # Target motion (see neural_whoop.target.sample_target_field).
    motion: str = "mixed"           # static / orbit / lissajous / mixed (per-env)
    target_speed: float = 1.5       # plausible held-target speed (m/s)
    target_radius: float = 1.5      # orbit / lissajous horizontal extent (m)
    # Follow geometry.
    d_desired: float = 1.5          # desired standoff distance (m) to the target
    track_sigma: float = 0.6        # width of the standoff reward bell (m)
    fov_deg: float = 110.0          # camera FOV (full angle) defining "in view" for the reward
    # Reward weights.
    track_scale: float = 1.0        # weight on the standoff bell exp(-((d-d*)/σ)²)
    in_view_bonus: float = 0.5      # per-step bonus when the target is inside the FOV cone
    center_scale: float = 0.3       # bonus for centering (cos of the bearing off the +x axis)
    # Anti-back-off penalty (Flywheel old-leaf-3989). The detector-hardened policy bought robustness
    # by sitting FAR (d >> d*), where the target rarely exits the FOV — cheap insurance the wide bell
    # permits. This linear penalty on excess distance (d > d*) makes back-off cost; pair it with a
    # tighter track_sigma so standoff accuracy survives detector training. Default 0.0 (off).
    over_distance_penalty: float = 0.0
    # Precision-filtering of the detector estimate (Flywheel nameless-bar-9184). The detector-regime
    # sweep showed the standoff back-off is set by per-fix bearing/range PRECISION (not dropout/FOV):
    # the policy sits far because every fresh fix is noisy. An EMA on the body-frame estimate
    # (in-place, so obs-v4 stays length 11 / MCU-clean) trades a little lag for lower per-fix variance,
    # which should let the policy hold closer safely. alpha = weight on history; 0.0 = off (raw fix).
    estimate_ema_alpha: float = 0.0
    # Predictive alpha-beta filter (Flywheel hop-21). A steady-state constant-velocity Kalman: it
    # tracks the estimate AND its velocity, predicting one step ahead, so it smooths the noisy fix
    # WITHOUT the pure-lag penalty a plain EMA pays on a moving target (the wandering-mode-7957
    # envelope). When ab_alpha>0 it REPLACES the EMA. ab_alpha = position gain (on the residual),
    # ab_beta = velocity gain. Body-frame approximation (the frame rotates; fine for slow follow).
    ab_alpha: float = 0.0
    ab_beta: float = 0.0
    # World-frame alpha-beta (Flywheel hop-22). The body-frame predictor (autumn-cherry-1696) was a
    # NO-GO because the body frame rotates -> velocity is corrupted by ego-motion. This filters the
    # target estimate in the INERTIAL WORLD frame (convert the noisy body fix to a world target-pos
    # estimate, alpha-beta on world pos+vel, transform back to body for the obs). World velocity is
    # smooth, so the prediction is meaningful -- the proper way to beat the EMA's lag. Takes precedence.
    world_ab_alpha: float = 0.0
    world_ab_beta: float = 0.0
    alive_bonus: float = 0.0
    smoothness_penalty: float = 0.001
    crash_penalty: float = 10.0
    # Arena / spawn.
    arena_radius: float = 4.5
    z_min: float = 0.7
    z_max: float = 2.3
    bound_xy: float = 6.0
    bound_z_min: float = 0.15
    bound_z_max: float = 4.0


@register_task("target_follow")
class TargetFollowTask(DroneTask):
    """Keep a moving target in view at a desired standoff distance, through a noisy detector."""

    n_agents = 1
    obs_dim = OBS_DIM  # obs-v4 (11), unchanged — the target vector replaces the gate vector
    config_cls = TargetFollowConfig  # subclasses (hand_follow) override with their own config

    def __init__(self, **kwargs):
        self.cfg = self.config_cls(**kwargs)
        self.episode_len = self.cfg.episode_len
        self._oracle = OracleEstimator()
        self._arena = course_mod.ArenaSpec(
            radius=self.cfg.arena_radius, z_min=self.cfg.z_min, z_max=self.cfg.z_max,
        )
        self._bounds = Bounds(xy=self.cfg.bound_xy, z_min=self.cfg.bound_z_min, z_max=self.cfg.bound_z_max)
        self._cos_fov = math.cos(math.radians(self.cfg.fov_deg) / 2.0)

    # --- lifecycle ---
    def setup(self, env) -> None:
        if env.n_agents != 1:
            raise ValueError("target_follow is single-drone (n_agents must be 1).")
        n, dev = env.n_drones, env.device
        # Persistent per-env target field (n_drones == n_envs here). Sampled once, rows overwritten
        # on reset so partial resets only resample the envs that finished.
        self._field = target_mod.sample_target_field(
            n, motion=self.cfg.motion, arena=self._arena,
            speed=self.cfg.target_speed, radius=self.cfg.target_radius,
            device=dev, generator=env.gen,
        )
        self.last_valid = torch.zeros(n, 3, device=dev)   # detector stale-hold (body frame)
        self._est_ema = torch.zeros(n, 3, device=dev)     # EMA precision filter state (body frame)
        self._ab_x = torch.zeros(n, 3, device=dev)        # alpha-beta position estimate (body frame)
        self._ab_v = torch.zeros(n, 3, device=dev)        # alpha-beta velocity estimate (body frame)
        self._wx = torch.zeros(n, 3, device=dev)          # world-frame target position estimate
        self._wv = torch.zeros(n, 3, device=dev)          # world-frame target velocity estimate
        self._dt = float(getattr(env, "dt", 0.02))        # sim step for the predictor
        # Episode accumulators (GPU-resident; reset per env, read at log cadence by metrics()).
        self.steps = torch.zeros(n, device=dev, dtype=torch.long)
        self.in_view = torch.zeros(n, device=dev, dtype=torch.long)
        self.track_err_sum = torch.zeros(n, device=dev)
        self.dist_sum = torch.zeros(n, device=dev)
        self.bearing_sum = torch.zeros(n, device=dev)
        self._dev = dev

    def reset(self, env, env_idx: Tensor) -> None:
        k = env_idx.numel()
        c = self.cfg
        # Resample the motion params for just the finished envs and write them into the field.
        sub = target_mod.sample_target_field(
            k, motion=c.motion, arena=self._arena,
            speed=c.target_speed, radius=c.target_radius,
            device=self._dev, generator=env.gen,
        )
        self._field.kind[env_idx] = sub.kind
        for key, val in sub.p.items():
            self._field.p[key][env_idx] = val
        tgt0 = sub.position(0.0)  # (k, 3) target world position at episode start

        # Spawn at the desired standoff along a random horizontal bearing, facing the target so it
        # starts centered in the FOV. Height clamped into the operating band.
        d_idx = env.drone_idx(env_idx)
        ang = torch.rand(k, device=self._dev, generator=env.gen) * (2 * math.pi)
        offset = torch.stack([ang.cos(), ang.sin(), torch.zeros_like(ang)], dim=-1) * c.d_desired
        spawn = tgt0 - offset
        spawn[:, 2] = tgt0[:, 2].clamp(c.z_min + 0.2, c.z_max - 0.2)
        yaw = torch.atan2(tgt0[:, 1] - spawn[:, 1], tgt0[:, 0] - spawn[:, 0])
        env.spawn(d_idx, spawn, yaw=yaw)
        # Seed the stale-hold with the body-frame target vector at spawn. The drone spawns level
        # (roll=pitch=0) yawed straight at the target, so body +x points along the horizontal
        # offset: the target sits at [d_desired (horizontal), 0, vertical_diff] in body frame.
        seed = torch.zeros(k, 3, device=self._dev)
        seed[:, 0] = c.d_desired
        seed[:, 2] = tgt0[:, 2] - spawn[:, 2]
        self.last_valid[d_idx] = seed
        self._est_ema[d_idx] = seed   # seed the precision filter with the spawn estimate
        self._ab_x[d_idx] = seed      # seed the alpha-beta filter (vel starts at 0)
        self._ab_v[d_idx] = 0.0
        self._wx[d_idx] = tgt0        # seed the world-frame filter at the true target world pos
        self._wv[d_idx] = 0.0

        self.steps[d_idx] = 0
        self.in_view[d_idx] = 0
        self.track_err_sum[d_idx] = 0.0
        self.dist_sum[d_idx] = 0.0
        self.bearing_sum[d_idx] = 0.0

    # --- observation ---
    def observe(self, env) -> Tensor:
        pos, vel, R, rpy, w = (
            env.dyn.pos, env.dyn.vel_world, env.dyn.R, env.dyn.rpy, env.dyn.ang_vel_body,
        )
        tgt = self._field.position(env.sim_time)        # (n_envs, 3) world
        rel_body = world_to_body(tgt - pos, R)
        rel_body, _ = self._oracle.estimate(rel_body)
        det = env.dr.cfg.detector
        if env.dr.cfg.enabled and not det.is_identity:
            rel_body, _ = apply_detector_noise(rel_body, det, self.last_valid, env.gen)
            self.last_valid = rel_body
        # Precision filtering of the noisy fix (in-place, so obs-v4 stays length 11). Precedence:
        # world-frame alpha-beta > body-frame alpha-beta > EMA.
        if self.cfg.world_ab_alpha > 0.0:
            # Convert the noisy body-frame fix to a WORLD target-position estimate, run alpha-beta on
            # world pos+vel (velocity is meaningful in the inertial frame), then back to body for obs.
            dt = self._dt
            world_meas = pos + torch.matmul(R, rel_body.unsqueeze(-1)).squeeze(-1)  # body_to_world + pos
            x_pred = self._wx + self._wv * dt
            resid = world_meas - x_pred
            self._wx = x_pred + self.cfg.world_ab_alpha * resid
            self._wv = self._wv + (self.cfg.world_ab_beta / dt) * resid
            rel_body = world_to_body(self._wx - pos, R)
        elif self.cfg.ab_alpha > 0.0:
            # Alpha-beta predictor-corrector: predict one step ahead with the velocity estimate, then
            # correct toward the measurement -- smooths noise WITHOUT the EMA's pure lag on a mover.
            dt = self._dt
            x_pred = self._ab_x + self._ab_v * dt
            resid = rel_body - x_pred
            self._ab_x = x_pred + self.cfg.ab_alpha * resid
            self._ab_v = self._ab_v + (self.cfg.ab_beta / dt) * resid
            rel_body = self._ab_x
        elif self.cfg.estimate_ema_alpha > 0.0:
            # EMA precision filter: smooth successive noisy fixes (Flywheel nameless-bar-9184).
            a = self.cfg.estimate_ema_alpha
            self._est_ema = a * self._est_ema + (1.0 - a) * rel_body
            rel_body = self._est_ema
        vel_b = world_to_body(vel, R)
        obs = torch.cat([rel_body, vel_b, rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        return obs.to(torch.float32)

    # --- reward / termination ---
    def reward_and_done(self, env, action: Tensor) -> tuple[Tensor, Tensor, dict]:
        c = self.cfg
        pos, R = env.dyn.pos, env.dyn.R
        tgt = self._field.position(env.sim_time)        # (n_envs, 3) world

        # Ground-truth geometry (reward never sees the noisy estimate, so noise can't be gamed).
        rel_body = world_to_body(tgt - pos, R)
        dist = rel_body.norm(dim=-1)
        safe = dist.clamp_min(1e-6)
        cos_ang = (rel_body[..., 0] / safe).clamp(-1.0, 1.0)  # alignment with the body +x camera axis
        in_fov = cos_ang >= self._cos_fov

        track = torch.exp(-(((dist - c.d_desired) / c.track_sigma) ** 2))
        reward = c.track_scale * track + c.alive_bonus
        reward = reward + c.in_view_bonus * in_fov.float()
        reward = reward + c.center_scale * cos_ang.clamp_min(0.0)
        if c.over_distance_penalty > 0.0:
            reward = reward - c.over_distance_penalty * (dist - c.d_desired).clamp_min(0.0)
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)

        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Episode accumulators for the metrics (ground truth).
        self.steps = self.steps + 1
        self.in_view = self.in_view + in_fov.long()
        self.track_err_sum = self.track_err_sum + (dist - c.d_desired).abs()
        self.dist_sum = self.dist_sum + dist
        self.bearing_sum = self.bearing_sum + cos_ang.clamp(-1.0, 1.0).arccos()

        terminated_env = crashed  # n_agents == 1 -> per-drone == per-env
        info = {"crashed": crashed, "in_view": in_fov}
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        return {
            "time_in_view_rate": (self.in_view.float() / steps).mean().item(),
            "mean_track_error": (self.track_err_sum / steps).mean().item(),
            "mean_distance": (self.dist_sum / steps).mean().item(),
            "mean_bearing_deg": math.degrees((self.bearing_sum / steps).mean().item()),
        }
