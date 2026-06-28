"""Moving-target motion models — batched torch, GPU-resident.

Ported from neural-whoop-lab's pure ``target.py`` and vectorized across ``n_envs`` for the
follow/pursuit tasks in the catalog (camera-only follow, hand/gesture follow). Each env
carries its own per-episode motion parameters; :meth:`TargetField.position` returns every
env's target world position at sim time ``t`` in one batched, closed-form call (no per-step
RNG, so paths are reproducible — randomness lives only in :func:`sample_target_field`).

Smooth closed-form motions are provided (static / orbit / lissajous / mixed). Polyline
random-walk/waypoint paths (which need per-env arc-length bookkeeping) are intentionally
left for the follow-task author to add — the gate course already covers waypoint following.
"""

from __future__ import annotations

import math

import torch
from torch import Tensor

from neural_whoop.course import ArenaSpec

# Motion-kind integer codes (stored per env so position() can branch with torch.where).
KIND_STATIC = 0
KIND_ORBIT = 1
KIND_LISSAJOUS = 2
KIND_ZIGZAG = 3  # triangle-wave per axis: piecewise-linear with SHARP direction reversals (the
#                  "hand" mover for hand_follow — abrupt direction changes, still closed-form).
_KIND_NAMES = {
    "static": KIND_STATIC, "orbit": KIND_ORBIT, "lissajous": KIND_LISSAJOUS, "zigzag": KIND_ZIGZAG,
}


def _triangle(x: Tensor) -> Tensor:
    """Unit triangle wave in [-1, 1], period 2*pi: ``(2/pi) * asin(sin(x))``.

    Piecewise-linear with sharp corners -> velocity is piecewise-constant and flips sign
    instantly at each peak (an abrupt direction reversal), unlike the smooth orbit/lissajous.
    """
    return (2.0 / math.pi) * torch.asin(torch.sin(x).clamp(-1.0, 1.0))


class TargetField:
    """Per-env batched target motion: ``position(t) -> (n_envs, 3)`` world positions.

    Holds one set of motion parameters per env (mixed kinds allowed). All arithmetic is
    batched; ``static`` envs ignore ``t``. Parameters are usually built by
    :func:`sample_target_field`.
    """

    def __init__(self, kind: Tensor, params: dict[str, Tensor]):
        self.kind = kind  # (n_envs,) int
        self.p = params   # each (n_envs, ...) tensor; see sample_target_field for keys

    @property
    def n_envs(self) -> int:
        return self.kind.shape[0]

    def position(self, t: float | Tensor) -> Tensor:
        """World target position for every env at sim time ``t`` (scalar or ``(n_envs,)``)."""
        p = self.p
        tt = t if isinstance(t, Tensor) else torch.as_tensor(t, device=self.kind.device)
        tt = tt.expand(self.n_envs) if tt.ndim else tt.repeat(self.n_envs)

        # Orbit: center + radius * [cos, sin] with vertical bob.
        ang = p["phase0"] + p["ang_speed"] * tt
        orbit = torch.stack(
            [
                p["center"][:, 0] + p["radius"] * ang.cos(),
                p["center"][:, 1] + p["radius"] * ang.sin(),
                p["center"][:, 2] + p["z_amp"] * (p["z_freq"] * tt).sin(),
            ],
            dim=-1,
        )
        # Lissajous: center + amp * sin(freq * t + phase), per axis.
        liss = p["center"] + p["amp"] * (p["freq"] * tt.unsqueeze(-1) + p["phase"]).sin()
        # Zigzag: center + amp * triangle(freq * t + phase), per axis (sharp direction reversals).
        zig = p["center"] + p["amp"] * _triangle(p["freq"] * tt.unsqueeze(-1) + p["phase"])
        # Static: just the center.
        stat = p["center"]

        out = stat.clone()
        out = torch.where((self.kind == KIND_ORBIT).unsqueeze(-1), orbit, out)
        out = torch.where((self.kind == KIND_LISSAJOUS).unsqueeze(-1), liss, out)
        out = torch.where((self.kind == KIND_ZIGZAG).unsqueeze(-1), zig, out)
        return out


def sample_target_field(
    n_envs: int,
    motion: str = "mixed",
    arena: ArenaSpec | None = None,
    speed: float = 1.5,
    radius: float = 1.5,
    device: torch.device | str = "cpu",
    generator: torch.Generator | None = None,
) -> TargetField:
    """Sample a batched per-episode :class:`TargetField`, bounded by ``arena``.

    Args:
        n_envs: Number of independent targets.
        motion: ``"static"``, ``"orbit"``, ``"lissajous"``, or ``"mixed"`` (random per env).
        arena: Bounds (reused from the gate course).
        speed: Plausible held-target speed (m/s); sets orbit/lissajous angular rates.
        radius: Orbit / lissajous horizontal extent (m).
        device: Torch device.
        generator: Optional torch ``Generator``.
    """
    arena = arena or ArenaSpec()
    dev = torch.device(device)

    def rand(*shape: int, lo: float = 0.0, hi: float = 1.0) -> Tensor:
        return torch.rand(*shape, device=dev, generator=generator) * (hi - lo) + lo

    if motion == "mixed":
        kind = torch.randint(KIND_ORBIT, KIND_LISSAJOUS + 1, (n_envs,), device=dev, generator=generator)
    else:
        if motion not in _KIND_NAMES:
            raise ValueError(f"Unknown target motion {motion!r}; expected one of {sorted(_KIND_NAMES)} or 'mixed'.")
        kind = torch.full((n_envs,), _KIND_NAMES[motion], device=dev, dtype=torch.long)

    max_extent = max(0.5, arena.radius - 0.5)
    rad = min(radius, max_extent)

    center = torch.stack(
        [rand(n_envs, lo=-0.5, hi=0.5), rand(n_envs, lo=-0.5, hi=0.5),
         rand(n_envs, lo=arena.z_min + 0.2, hi=arena.z_max - 0.2)],
        dim=-1,
    )
    radius_t = torch.full((n_envs,), float(max(0.5, rad)), device=dev)
    ang_speed = (speed / radius_t) * torch.where(rand(n_envs) > 0.5, 1.0, -1.0)
    base = speed / max(rad, 0.5)
    amp = torch.stack([rand(n_envs, lo=0.5 * rad, hi=rad), rand(n_envs, lo=0.5 * rad, hi=rad),
                       rand(n_envs, lo=0.0, hi=0.4)], dim=-1)
    freq = torch.stack([base * rand(n_envs, lo=0.7, hi=1.3), base * rand(n_envs, lo=0.7, hi=1.3),
                        base * rand(n_envs, lo=0.4, hi=0.9)], dim=-1)
    phase = rand(n_envs, 3, lo=0.0, hi=2 * math.pi)

    params = {
        "center": center, "radius": radius_t, "ang_speed": ang_speed,
        "phase0": rand(n_envs, lo=0.0, hi=2 * math.pi),
        "z_amp": rand(n_envs, lo=0.0, hi=0.3), "z_freq": rand(n_envs, lo=0.3, hi=1.0),
        "amp": amp, "freq": freq, "phase": phase,
    }
    return TargetField(kind=kind, params=params)
