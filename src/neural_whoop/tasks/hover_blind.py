"""hover_blind: fully-autonomous IMU-only hover — the no-flow-deck first-flight task.

``hover`` assumes a position/velocity source (Stage-1 flow deck). This variant observes ONLY
what the real Air65 II already provides over MSP today: attitude (roll, pitch) + body rates —
**obs = [roll, pitch, p, q, r]** (5). No position, no velocity, no yaw (unobservable offboard
and irrelevant to a hover).

Physics honesty (docs/SIM2REAL.md): with no translational feedback, altitude/position are
OPEN-LOOP. The policy can only learn (a) tight attitude stabilization + disturbance recovery
(fully observable via gyro/attitude) and (b) a precisely-calibrated hover-thrust trim
(optimized in expectation across the thrust/mass DR — which is therefore kept TIGHT here,
anchored by the bench-measured hover throttle). Expect a level, slowly-drifting hover good for
tens of seconds — a tethered first-flight demo, not a station-hold. The reward is unchanged
hover reward: position terms still shape the trim (altitude error IS position error), and the
crash bounds pressure-test it (bad trim exits the z band and eats the crash penalty).

Same dynamics, spawn/recovery curriculum, metrics, and Studio scene as ``hover`` — this is a
pure observation ablation, so a checkpoint here deploys against ``scripts/pilot.py`` with
MSP_ATTITUDE + MSP_RAW_IMU as the entire sensor suite.
"""

from __future__ import annotations

import torch
from torch import Tensor

from neural_whoop.envs.registry import register_task
from neural_whoop.tasks.hover import HoverConfig, HoverTask


@register_task("hover_blind")
class HoverBlindTask(HoverTask):
    """IMU-only hover: attitude + body rates in, everything else unobservable."""

    n_agents = 1
    obs_dim = 5  # [roll, pitch, p, q, r]
    config_cls = HoverConfig

    def observe(self, env) -> Tensor:
        rpy, w = env.dyn.rpy, env.dyn.ang_vel_body
        obs = torch.cat([rpy[..., 0:1], rpy[..., 1:2], w], dim=-1)
        return obs.to(torch.float32)
