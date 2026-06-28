"""gesture_follow: command-conditioned hand following (STOP/GO gesture channel) — Flywheel hop-25.

The catalog's planned `hand_follow` extension: append a discrete **gesture command** to the obs and
make the tiny shared policy switch behaviour on it. GO (1) -> follow the jerky hand (the `hand_follow`
reward); STOP (0) -> hover in place (reward low speed, ignore the hand). The command is a piecewise-
constant per-env bit that flips at random, so within one episode the policy must read obs[-1] and
switch between two distinct behaviours -- the first *conditional* / command-driven policy in the lab,
a step toward gesture-controlled flight.

Obs (length 12): obs-v4 (11) + the gesture bit. This is the first obs_dim growth on the follow seam
(MCU note: +1 channel for the command). Everything else -- the zigzag hand, detector seam, EMA filter
-- is inherited from `hand_follow`.

Metric: `follow_hold_rate` (frac of GO steps within hold_tol of d*) + `stop_compliance` (frac of STOP
steps with speed < stop_speed_thresh) -- both ground truth; a good policy scores high on BOTH, which
requires actually using the command channel.
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
class GestureFollowConfig(HandFollowConfig):
    """`hand_follow` config + the STOP/GO command channel."""

    gesture_toggle_prob: float = 0.008   # per-step prob the STOP/GO command flips (~1 flip / 2.5 s)
    stop_speed_sigma: float = 0.5        # width of the hover (low-speed) reward bell on STOP
    stop_bonus: float = 1.5              # weight on the hover reward during STOP (~matches follow peak)
    stop_speed_thresh: float = 0.5       # speed (m/s) below which a STOP step counts as "complied"


@register_task("gesture_follow")
class GestureFollowTask(HandFollowTask):
    """Follow the hand on GO, hover on STOP — a command-conditioned policy (obs_dim 12)."""

    config_cls = GestureFollowConfig
    obs_dim = OBS_DIM + 1  # 12: obs-v4 + the gesture command bit

    # --- lifecycle ---
    def setup(self, env) -> None:
        super().setup(env)
        n, dev = env.n_drones, env.device
        self._gesture = torch.ones(n, device=dev)          # 1 = GO (follow), 0 = STOP (hover)
        self._go_steps = torch.zeros(n, device=dev)         # metric accumulators (GO / STOP split)
        self._stop_steps = torch.zeros(n, device=dev)
        self._stop_ok = torch.zeros(n, device=dev)          # STOP steps with speed < thresh

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        d = env.drone_idx(env_idx)
        self._gesture[d] = (torch.rand(d.numel(), device=self._dev, generator=env.gen) > 0.5).float()
        self._go_steps[d] = 0.0
        self._stop_steps[d] = 0.0
        self._stop_ok[d] = 0.0

    def _evolve_gesture(self, env) -> None:
        flip = torch.rand(self._gesture.shape[0], device=self._dev, generator=env.gen) < self.cfg.gesture_toggle_prob
        self._gesture = torch.where(flip, 1.0 - self._gesture, self._gesture)

    # --- observation: obs-v4 (11) + gesture bit (12) ---
    def observe(self, env) -> Tensor:
        self._evolve_gesture(env)
        obs11 = super().observe(env)
        return torch.cat([obs11, self._gesture.unsqueeze(-1)], dim=-1).to(torch.float32)

    # --- reward / termination: switch on the command ---
    def reward_and_done(self, env, action: Tensor):
        c = self.cfg
        pos, R, vel = env.dyn.pos, env.dyn.R, env.dyn.vel_world
        tgt = self._field.position(env.sim_time)
        rel_body = world_to_body(tgt - pos, R)        # ground truth (reward never sees the noisy fix)
        dist = rel_body.norm(dim=-1)
        safe = dist.clamp_min(1e-6)
        cos_ang = (rel_body[..., 0] / safe).clamp(-1.0, 1.0)
        in_fov = cos_ang >= self._cos_fov
        speed = vel.norm(dim=-1)
        go = self._gesture                            # 1 = follow, 0 = hover

        # GO: the hand_follow standoff/centering reward. STOP: reward being slow (hover).
        follow_r = (
            c.track_scale * torch.exp(-(((dist - c.d_desired) / c.track_sigma) ** 2))
            + c.in_view_bonus * in_fov.float()
            + c.center_scale * cos_ang.clamp_min(0.0)
        )
        stop_r = c.stop_bonus * torch.exp(-((speed / c.stop_speed_sigma) ** 2))
        reward = go * follow_r + (1.0 - go) * stop_r + c.alive_bonus
        reward = reward - smoothness_penalty(action, env.prev_action, c.smoothness_penalty)
        crashed = is_crashed(pos, self._bounds)
        reward = reward - c.crash_penalty * crashed.float()

        # Command-gated metrics (ground truth).
        self.steps = self.steps + 1
        is_go = go > 0.5
        self._go_steps = self._go_steps + is_go.float()
        self._stop_steps = self._stop_steps + (~is_go).float()
        self.hold = self.hold + (is_go & ((dist - c.d_desired).abs() < c.hold_tol)).long()
        self._stop_ok = self._stop_ok + ((~is_go) & (speed < c.stop_speed_thresh)).float()
        self.in_view = self.in_view + in_fov.long()
        self.track_err_sum = self.track_err_sum + (dist - c.d_desired).abs()
        self.dist_sum = self.dist_sum + dist
        self.bearing_sum = self.bearing_sum + cos_ang.clamp(-1.0, 1.0).arccos()

        info = {"crashed": crashed, "in_view": in_fov}
        return reward, crashed, info

    def metrics(self, env) -> dict:
        m = super().metrics(env)
        go = self._go_steps.clamp_min(1.0)
        stop = self._stop_steps.clamp_min(1.0)
        # follow_hold_rate redefined as a GO-only rate; add stop_compliance + the GO fraction.
        m["follow_hold_rate"] = (self.hold.float() / go).mean().item()
        m["stop_compliance"] = (self._stop_ok / stop).mean().item()
        m["go_fraction"] = (self._go_steps / self.steps.clamp_min(1).float()).mean().item()
        return m
