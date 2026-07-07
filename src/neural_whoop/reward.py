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


def rotation_progress(
    prev_phi: Tensor, curr_phi: Tensor, target: float, scale: float = 1.0
) -> Tensor:
    """Reward for signed rotation gained toward ``target`` this step, saturating at ``target``.

    The acro sibling of :func:`progress_reward`: ``phi`` is a signed accumulated rotation about the
    maneuver axis (already resolved into the intended direction). Reward is proportional to the
    increase in ``clamp(phi, 0, target)`` — monotone progress that can't be farmed by over-spinning
    past ``target`` (clamped above) or by counter-rotating below 0 (clamped below). Batched over any
    leading shape.

    Args:
        prev_phi: Accumulated signed rotation before this step, shape ``(...)``.
        curr_phi: Accumulated signed rotation after this step, shape ``(...)``.
        target: The rotation goal Φ (radians); the reward saturates once ``phi`` reaches it.
        scale: Weight on the progress term.

    Returns:
        Progress reward of shape ``(...)`` (zero once saturated, zero while below 0).
    """
    prev_c = prev_phi.clamp(0.0, target)
    curr_c = curr_phi.clamp(0.0, target)
    return scale * (curr_c - prev_c)


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


def boundary_proximity_penalty(
    pos: Tensor, bounds: Bounds, margin: float, weight: float
) -> Tensor:
    """Per-step *near-miss* penalty: ramps 0 -> ``weight`` per axis as ``pos`` enters the last
    ``margin`` meters before any crash bound.

    A reliability-shaping term (Flywheel hop-11): under domain randomization, wind/latency push
    the drone toward the walls/floor/ceiling, and those excursions become crashes. Penalizing the
    approach teaches the policy to keep margin and survive disturbances. ``margin`` is chosen below
    the operating region (the lowest gate) so normal flight is untouched; only genuine danger-zone
    excursions are taxed. ``weight <= 0`` or ``margin <= 0`` short-circuits to zeros (default-off).

    Args:
        pos: Positions, shape ``(..., 3)``.
        bounds: Arena crash :class:`Bounds`.
        margin: Danger-zone thickness in meters (the band just inside each bound).
        weight: Max per-axis penalty (reached at the bound).

    Returns:
        Non-negative penalty of shape ``(...)`` (summed over the 3 axes).
    """
    if weight <= 0.0 or margin <= 0.0:
        return torch.zeros(pos.shape[:-1], device=pos.device, dtype=pos.dtype)
    mx = bounds.xy - pos[..., 0].abs()
    my = bounds.xy - pos[..., 1].abs()
    mz = torch.minimum(pos[..., 2] - bounds.z_min, bounds.z_max - pos[..., 2])
    m = torch.stack([mx, my, mz], dim=-1).clamp_min(0.0)  # remaining margin to each bound
    near = (1.0 - m / margin).clamp(0.0, 1.0)             # 0 outside the band, 1 at the bound
    return weight * near.sum(dim=-1)


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
