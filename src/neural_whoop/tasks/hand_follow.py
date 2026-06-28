"""hand_follow: close-follow a *jerky* hand target through a noisy detector (perception, Flywheel hop-23).

The sibling of :mod:`~neural_whoop.tasks.target_follow`. Where ``target_follow`` holds a STANDOFF from a
**smooth** orbit/lissajous mover, ``hand_follow`` follows CLOSE to a **zigzag** target — the
``KIND_ZIGZAG`` triangle-wave mover (sharp, abrupt direction reversals), the closest closed-form
stand-in for a held hand being moved around. The catalog distinguishes it by *responsiveness to
direction changes*: a smooth-motion filter (the validated EMA precision primitive,
``flat-waterfall-0121``) is exactly the thing whose lag should bite hardest when the target suddenly
reverses — so this task is the abrupt-motion stress test of the perception seam, not a new geometry.

Reuses the whole ``target_follow`` machinery (obs-v4, detector seam, EMA/alpha-beta filters, reward
shape) via subclassing; only the config defaults differ (zigzag motion, close standoff) and a
``follow_hold_rate`` responsiveness metric is added (fraction of steps within ``hold_tol`` of d*,
which a policy can only sustain through reversals if it tracks responsively).

Metric: ``follow_hold_rate`` ↑ (responsiveness) + ``mean_track_error`` ↓ + ``time_in_view_rate`` ↑,
all from ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor

from neural_whoop.contract import world_to_body
from neural_whoop.envs.registry import register_task
from neural_whoop.tasks.target_follow import TargetFollowConfig, TargetFollowTask


@dataclass
class HandFollowConfig(TargetFollowConfig):
    """``target_follow`` config with the hand-follow defaults (jerky mover, close standoff)."""

    motion: str = "zigzag"          # the abrupt "hand" mover (sharp triangle-wave reversals)
    target_speed: float = 1.8       # a hand moves a touch quicker than a held standoff target
    target_radius: float = 1.2      # tighter workspace than the orbit task
    d_desired: float = 0.8          # follow CLOSE to the hand (not a 1.5 m standoff)
    track_sigma: float = 0.5        # tighter bell — close following needs accuracy
    hold_tol: float = 0.4           # |dist - d*| < hold_tol counts as "tracking" (responsiveness)


@register_task("hand_follow")
class HandFollowTask(TargetFollowTask):
    """Follow a jerky hand target close-in; the metric emphasizes responsiveness to direction changes."""

    config_cls = HandFollowConfig

    def setup(self, env) -> None:
        super().setup(env)
        self.hold = torch.zeros(env.n_drones, device=env.device, dtype=torch.long)  # responsiveness acc

    def reset(self, env, env_idx: Tensor) -> None:
        super().reset(env, env_idx)
        self.hold[env.drone_idx(env_idx)] = 0

    def reward_and_done(self, env, action: Tensor):
        reward, terminated_env, info = super().reward_and_done(env, action)
        # Responsiveness accumulator: fraction of steps held within hold_tol of d* (ground truth).
        rel_body = world_to_body(self._field.position(env.sim_time) - env.dyn.pos, env.dyn.R)
        dist = rel_body.norm(dim=-1)
        self.hold = self.hold + ((dist - self.cfg.d_desired).abs() < self.cfg.hold_tol).long()
        return reward, terminated_env, info

    def metrics(self, env) -> dict:
        m = super().metrics(env)
        steps = self.steps.clamp_min(1).float()
        m["follow_hold_rate"] = (self.hold.float() / steps).mean().item()
        return m
