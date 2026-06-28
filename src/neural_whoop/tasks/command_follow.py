"""command_follow: 3-way command-conditioned hand following — does the gesture channel SCALE? (hop-26).

`gesture_follow` (`proud-field-5681`) showed a tiny shared policy can hold TWO command-conditioned
behaviours (STOP/GO) from one obs bit. This asks whether the command channel scales to a **vocabulary**:
a 3-way command -- **STOP** (hover), **NEAR** (close-follow at d_near), **FAR** (stand off at d_far) --
encoded as a single obs scalar in {0, 0.5, 1}. The same [128,128] net must read it and produce three
distinct behaviours, switching as the command resamples mid-episode. A step from a stop/go bit toward
a real gesture vocabulary (come / follow / back-off).

Obs (length 12): obs-v4 (11) + the command scalar. Metric: `stop_compliance` (STOP steps slow) +
`near_hold` (NEAR steps within hold_tol of d_near) + `far_hold` (FAR steps within hold_tol of d_far) --
a policy that ignored the command can't score high on all three at once (the targets are different).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import OBS_DIM, world_to_body
from neural_whoop.envs.registry import register_task
from neural_whoop.reward import is_crashed, smoothness_penalty
from neural_whoop.tasks.hand_follow import HandFollowConfig, HandFollowTask


@dataclass
class CommandFollowConfig(HandFollowConfig):
    """`hand_follow` config + the 3-way STOP/NEAR/FAR command vocabulary."""

    d_near: float = 0.7                  # NEAR command standoff (m)
    d_far: float = 1.8                   # FAR command standoff (m)
    command_toggle_prob: float = 0.008   # per-step prob the command resamples (~1 change / 2.5 s)
    stop_speed_sigma: float = 0.5        # hover reward bell width on speed
    stop_bonus: float = 1.5              # weight on the hover reward during STOP
    stop_speed_thresh: float = 0.5       # speed (m/s) below which a STOP step counts as complied


@register_task("command_follow")
class CommandFollowTask(HandFollowTask):
    """STOP / NEAR / FAR on command — a 3-way command-conditioned policy (obs_dim 12)."""

    config_cls = CommandFollowConfig
    obs_dim = OBS_DIM + 1  # 12: obs-v4 + command scalar
    _N_CMD = 3             # 0=STOP, 1=NEAR, 2=FAR

    def setup(self, env) -> None:
        super().setup(env)
        n, dev = env.n_drones, env.device
        self._cmd = torch.zeros(n, device=dev, dtype=torch.long)
        self._n = {k: torch.zeros(n, device=dev) for k in ("stop", "near", "far")}   # per-mode step counts
        self._ok = {k: torch.zeros(n, device=dev) for k in ("stop", "near", "far")}   # per-mode compliant steps

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        d = env.drone_idx(env_idx)
        self._cmd[d] = torch.randint(0, self._N_CMD, (d.numel(),), device=self._dev, generator=env.gen)
        for k in self._n:
            self._n[k][d] = 0.0
            self._ok[k][d] = 0.0

    def _evolve_command(self, env) -> None:
        n = self._cmd.shape[0]
        change = torch.rand(n, device=self._dev, generator=env.gen) < self.cfg.command_toggle_prob
        new = torch.randint(0, self._N_CMD, (n,), device=self._dev, generator=env.gen)
        self._cmd = torch.where(change, new, self._cmd)

    def observe(self, env) -> Tensor:
        self._evolve_command(env)
        obs11 = super().observe(env)
        cmd_scalar = self._cmd.float() / (self._N_CMD - 1)   # {0, 0.5, 1}
        return torch.cat([obs11, cmd_scalar.unsqueeze(-1)], dim=-1).to(torch.float32)

    def reward_and_done(self, env, action: Tensor):
        c = self.cfg
        pos, R, vel = env.dyn.pos, env.dyn.R, env.dyn.vel_world
        rel_body = world_to_body(self._field.position(env.sim_time) - pos, R)  # ground truth
        dist = rel_body.norm(dim=-1)
        safe = dist.clamp_min(1e-6)
        cos_ang = (rel_body[..., 0] / safe).clamp(-1.0, 1.0)
        in_fov = cos_ang >= self._cos_fov
        speed = vel.norm(dim=-1)
        cmd = self._cmd

        def standoff(d_star: float) -> Tensor:
            return (
                c.track_scale * torch.exp(-(((dist - d_star) / c.track_sigma) ** 2))
                + c.in_view_bonus * in_fov.float()
                + c.center_scale * cos_ang.clamp_min(0.0)
            )

        hover = c.stop_bonus * torch.exp(-((speed / c.stop_speed_sigma) ** 2))
        near_r, far_r = standoff(c.d_near), standoff(c.d_far)
        is_stop, is_near, is_far = cmd == 0, cmd == 1, cmd == 2
        reward = torch.where(is_stop, hover, torch.where(is_near, near_r, far_r)) + c.alive_bonus
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Per-command compliance accumulators (ground truth).
        self.steps = self.steps + 1
        self._n["stop"] += is_stop.float(); self._ok["stop"] += (is_stop & (speed < c.stop_speed_thresh)).float()
        self._n["near"] += is_near.float(); self._ok["near"] += (is_near & ((dist - c.d_near).abs() < c.hold_tol)).float()
        self._n["far"] += is_far.float();   self._ok["far"] += (is_far & ((dist - c.d_far).abs() < c.hold_tol)).float()
        self.in_view = self.in_view + in_fov.long()
        self.dist_sum = self.dist_sum + dist
        self.track_err_sum = self.track_err_sum + (dist - c.d_near).abs()  # nominal (NEAR) reference
        self.bearing_sum = self.bearing_sum + cos_ang.clamp(-1.0, 1.0).arccos()

        info = {"crashed": crashed, "in_view": in_fov}
        return reward, crashed, info

    # --- visual scene: inherit the target marker, add the 3-way STOP/NEAR/FAR command channel ---
    def scene_objects(self, env) -> dict:
        scene = super().scene_objects(env)
        scene["command"] = self._cmd              # 0 = STOP, 1 = NEAR, 2 = FAR
        return scene

    def scene_info(self) -> dict:
        info = super().scene_info()
        info["command_labels"] = ["STOP", "NEAR", "FAR"]
        info["d_near"] = float(self.cfg.d_near)
        info["d_far"] = float(self.cfg.d_far)
        return info

    def metrics(self, env) -> dict:
        steps = self.steps.clamp_min(1).float()
        out = {
            "stop_compliance": (self._ok["stop"] / self._n["stop"].clamp_min(1.0)).mean().item(),
            "near_hold": (self._ok["near"] / self._n["near"].clamp_min(1.0)).mean().item(),
            "far_hold": (self._ok["far"] / self._n["far"].clamp_min(1.0)).mean().item(),
            "time_in_view_rate": (self.in_view.float() / steps).mean().item(),
            "mean_distance": (self.dist_sum / steps).mean().item(),
        }
        return out
