"""Gate / course geometry — batched torch, GPU-resident.

Ported from neural-whoop-lab's pure ``course.py`` and vectorized across ``n_envs``: every env
carries its own procedurally-generated course so a batched rollout sees diverse layouts.

A gate is an **omnidirectional spherical waypoint** (center + radius): the drone "passes" it
the instant its path comes within ``radius`` of the center, from any direction. A robust
segment-sphere test (not a point test) prevents tunnelling through a small sphere at racing
speed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass(frozen=True)
class ArenaSpec:
    """Bounds for procedurally placing gates (meters, world frame).

    Kept well inside the crash bounds so a generated course is always flyable. A whoop flies
    indoors, so the default arena is small.
    """

    radius: float = 4.5
    z_min: float = 0.7
    z_max: float = 2.5
    gate_radius: float = 0.35
    gate_radius_min: float | None = None
    gate_radius_max: float | None = None
    step_min: float = 1.5
    step_max: float = 2.8
    max_turn_deg: float = 60.0
    start_xy: tuple[float, float] = (1.5, 0.0)


#: Named arena presets for the Studio + spread-course training. ``tight`` reproduces the default
#: small indoor arena (gates ~1.5–2.8 m apart); ``spread``/``big``/``giant`` progressively grow the
#: radius **and** the inter-gate hop (``step_min/step_max``) so the gates are genuinely farther
#: apart, not just placed in a bigger circle. Step ranges are kept comfortably inside the radius so
#: a generated walk stays flyable, and ``z_max`` rises with size for more vertical room.
ARENA_PRESETS: dict[str, "ArenaSpec"] = {
    "tight": ArenaSpec(),
    "spread": ArenaSpec(radius=8.0, step_min=3.0, step_max=5.5, z_min=0.7, z_max=3.0),
    "big": ArenaSpec(radius=12.0, step_min=4.5, step_max=7.5, z_min=0.8, z_max=3.5),
    "giant": ArenaSpec(radius=18.0, step_min=6.0, step_max=10.0, z_min=0.8, z_max=4.0),
}


def random_courses(
    n_envs: int,
    n_gates: int,
    arena: ArenaSpec | None = None,
    device: torch.device | str = "cpu",
    generator: torch.Generator | None = None,
) -> tuple[Tensor, Tensor]:
    """Generate ``n_envs`` independent flyable gate courses, vectorized across envs.

    Each course is a bounded random walk (per the lab's ``random_course``): each gate is a
    ``step_min..step_max`` hop from the previous one, turning by at most ``max_turn_deg``, and
    steered back toward the origin if it would leave the arena. The walk runs as ``n_gates``
    vectorized steps across all envs.

    Args:
        n_envs: Number of independent courses.
        n_gates: Gates per course.
        arena: Placement bounds.
        device: Torch device for the returned tensors.
        generator: Optional torch ``Generator`` for reproducibility.

    Returns:
        ``(positions, radii)``: ``positions`` shape ``(n_envs, n_gates, 3)``, ``radii`` shape
        ``(n_envs, n_gates)``.
    """
    arena = arena or ArenaSpec()
    if n_gates < 1:
        raise ValueError(f"n_gates must be >= 1, got {n_gates}")
    dev = torch.device(device)

    def rand(*shape: int, lo: float = 0.0, hi: float = 1.0) -> Tensor:
        return torch.rand(*shape, device=dev, generator=generator) * (hi - lo) + lo

    rad_lo = arena.gate_radius_min if arena.gate_radius_min is not None else arena.gate_radius
    rad_hi = arena.gate_radius_max if arena.gate_radius_max is not None else arena.gate_radius

    pos_xy = torch.tensor(arena.start_xy, device=dev, dtype=torch.float32).expand(n_envs, 2).clone()
    heading = rand(n_envs, lo=-math.pi / 4, hi=math.pi / 4)
    max_turn = math.radians(arena.max_turn_deg)

    positions = torch.empty(n_envs, n_gates, 3, device=dev)
    radii = torch.empty(n_envs, n_gates, device=dev)

    for g in range(n_gates):
        heading = heading + rand(n_envs, lo=-max_turn, hi=max_turn)
        step = rand(n_envs, lo=arena.step_min, hi=arena.step_max)
        nxt = pos_xy + step.unsqueeze(-1) * torch.stack([heading.cos(), heading.sin()], dim=-1)
        # Steer back toward origin where the hop would leave the arena.
        out = nxt.norm(dim=-1) > arena.radius
        if out.any():
            back = torch.atan2(-pos_xy[:, 1], -pos_xy[:, 0]) + rand(n_envs, lo=-0.4, hi=0.4)
            heading = torch.where(out, back, heading)
            nxt2 = pos_xy + step.unsqueeze(-1) * torch.stack([heading.cos(), heading.sin()], dim=-1)
            nxt = torch.where(out.unsqueeze(-1), nxt2, nxt)
        # Hard clamp inside the arena radius.
        dist = nxt.norm(dim=-1, keepdim=True).clamp_min(1e-9)
        scale = (arena.radius / dist).clamp_max(1.0)
        nxt = nxt * scale
        # Re-align heading with actual travel direction.
        delta = nxt - pos_xy
        moved = delta.norm(dim=-1) > 1e-9
        heading = torch.where(moved, torch.atan2(delta[:, 1], delta[:, 0]), heading)
        pos_xy = nxt
        z = rand(n_envs, lo=arena.z_min, hi=arena.z_max)
        positions[:, g, 0] = pos_xy[:, 0]
        positions[:, g, 1] = pos_xy[:, 1]
        positions[:, g, 2] = z
        radii[:, g] = rand(n_envs, lo=float(rad_lo), hi=float(rad_hi)) if rad_hi > rad_lo else rad_lo

    return positions, radii


def gate_passed(center: Tensor, prev_pos: Tensor, curr_pos: Tensor, radius: Tensor) -> Tensor:
    """Batched segment-sphere pass test.

    True where the segment ``prev_pos -> curr_pos`` comes within ``radius`` of ``center``.
    Robust against tunnelling: clamps the projection of the center onto the segment to
    ``[0, 1]`` and compares the closest point's distance to the center.

    Args:
        center: Gate centers, shape ``(..., 3)``.
        prev_pos: Previous positions, shape ``(..., 3)``.
        curr_pos: Current positions, shape ``(..., 3)``.
        radius: Gate radii, shape ``(...)``.

    Returns:
        Bool tensor of shape ``(...)``.
    """
    seg = curr_pos - prev_pos
    seg_len_sq = (seg * seg).sum(-1)
    t = ((center - prev_pos) * seg).sum(-1) / seg_len_sq.clamp_min(1e-18)
    t = t.clamp(0.0, 1.0)
    # Degenerate (zero-length) segments fall back to the endpoint distance via t=0.
    t = torch.where(seg_len_sq < 1e-18, torch.zeros_like(t), t)
    closest = prev_pos + t.unsqueeze(-1) * seg
    return (closest - center).norm(dim=-1) <= radius
