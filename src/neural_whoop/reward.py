"""Reward shaping and termination helpers — batched torch.

Ported from neural-whoop-lab's pure ``reward.py`` and vectorized. Tasks (see
``neural_whoop.tasks``) compose these primitives; the racing task additionally adds a
speed/lap-time term (its optimization playground). Kept small and explicit on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass(frozen=True)
class RewardConfig:
    """Weights for the shared reward primitives."""

    progress_scale: float = 1.0
    gate_bonus: float = 10.0
    crash_penalty: float = 10.0
    time_penalty: float = 0.01
    finish_bonus: float = 25.0
    smoothness_penalty: float = 0.0
    # Pursuit (movable-target) mode.
    pursuit_proximity_scale: float = 1.0
    pursuit_falloff: float = 1.0
    in_view_bonus: float = 0.1


def progress_reward(prev_dist: Tensor, curr_dist: Tensor, scale: float = 1.0) -> Tensor:
    """Reward proportional to distance closed toward the target this step, batched."""
    return scale * (prev_dist - curr_dist)


def smoothness_penalty(action: Tensor, prev_action: Tensor, weight: float) -> Tensor:
    """Squared action-change penalty (anti bang-bang), batched over the last dim.

    Returns a non-negative penalty of shape ``action.shape[:-1]``. ``weight <= 0`` short-
    circuits to zeros.
    """
    if weight <= 0.0:
        return torch.zeros(action.shape[:-1], device=action.device, dtype=action.dtype)
    delta = action - prev_action
    return weight * (delta * delta).sum(-1)


@dataclass(frozen=True)
class Bounds:
    """Axis-aligned arena bounds (meters). Leaving them = crash."""

    xy: float = 6.0
    z_min: float = 0.05
    z_max: float = 4.0


def is_crashed(pos: Tensor, bounds: Bounds | None = None) -> Tensor:
    """Batched crash test: True where the drone left the arena or hit the ground/ceiling.

    Args:
        pos: Positions, shape ``(..., 3)``.
        bounds: Arena :class:`Bounds`.

    Returns:
        Bool tensor of shape ``(...)``.
    """
    bounds = bounds or Bounds()
    x, y, z = pos[..., 0], pos[..., 1], pos[..., 2]
    return (
        (x.abs() > bounds.xy)
        | (y.abs() > bounds.xy)
        | (z < bounds.z_min)
        | (z > bounds.z_max)
    )
