"""Timing oracles — target lap times for the gate-race course (the optimality yardstick).

Two references over the **closed** gate loop ``g0 -> g1 -> ... -> g_{n-1} -> g0``:

- :func:`pathlen_lap_time` — the original point-mass reference: closed path length / ``v_ref``.
  Speed-neutral and geometry-blind; a competent policy beats it (it cruises *above* ``v_ref``),
  so it no longer bounds optimality. Kept for reproducibility (the historical baseline).

- :func:`feasible_lap_time` — an **honest, dynamically-feasible** reference. It times the same
  fixed polygonal path but respects what the airframe can actually do: a top speed ``v_max``, a
  tangential accel/brake limit ``a_max`` (trapezoidal speed profiles on the straights), and a
  cornering speed cap from a max **lateral** accel ``a_lat`` via a junction-deviation model
  (sharper turns force a slower corner). This is the classic time-optimal speed profile along a
  fixed path: per-vertex corner caps, a forward pass (can't out-accelerate ``a_max``), a backward
  pass (must brake into the next corner), then trapezoidal per-segment times. Calibrate the three
  limits from flown telemetry so the reference is grounded in achievable dynamics, not invented.

Both are pure, batched, GPU-resident, and free of per-step CPU syncs — they run over the static
gate layout at reset, exactly like the existing oracle. ``n_gates`` is small (the ring sweeps are
a short Python loop over gates); everything inside is vectorized across envs.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor


def _closed_segments(gate_pos: Tensor) -> tuple[Tensor, Tensor]:
    """Closed-loop segment vectors and lengths for ``g0..g_{n-1} -> g0``.

    Args:
        gate_pos: ``(n_envs, n_gates, 3)`` gate centers.

    Returns:
        ``(seg, seg_len)`` where ``seg`` is ``(n_envs, n_gates, 3)`` (segment ``i`` goes from
        gate ``i`` to gate ``i+1 mod n``) and ``seg_len`` is ``(n_envs, n_gates)``.
    """
    nxt = torch.roll(gate_pos, shifts=-1, dims=1)
    seg = nxt - gate_pos
    seg_len = seg.norm(dim=-1)
    return seg, seg_len


def pathlen_lap_time(gate_pos: Tensor, v_ref: float) -> Tensor:
    """Original oracle: closed path length / ``v_ref``. Shape ``(n_envs,)``."""
    _, seg_len = _closed_segments(gate_pos)
    return seg_len.sum(dim=-1) / max(v_ref, 1e-3)


@dataclass(frozen=True)
class FeasibleOracle:
    """Airframe limits for the dynamically-feasible timing reference (SI units).

    Defaults are p95 values calibrated from the tp=0.05 baseline flown replay (see
    ``flywheel node bd57f350``): the whoop sustains ~2.5 g of tangential / lateral accel and
    cruises in the ~7 m/s range during racing.
    """

    v_max: float = 7.0       # m/s top speed (p95 of flown speed)
    a_max: float = 25.0      # m/s^2 tangential accel/brake (p95 of flown |a_tang|)
    a_lat: float = 23.0      # m/s^2 lateral accel for cornering (p95 of flown |a_lat|)
    corner_dev: float = 0.45 # m junction deviation allowed at a corner (~gate_radius)


def _corner_speed_cap(gate_pos: Tensor, seg: Tensor, seg_len: Tensor, o: FeasibleOracle) -> Tensor:
    """Per-vertex cornering speed cap from the turn angle and a junction-deviation model.

    At gate ``i`` the path deflects by angle ``theta`` between the incoming segment ``i-1`` and
    the outgoing segment ``i``. An inscribed arc tangent to both segments that stays within
    ``corner_dev`` of the vertex has radius ``R = corner_dev * cos(t/2) / (1 - cos(t/2))``; the
    cornering speed cap is ``sqrt(a_lat * R)``, clamped to ``v_max``. Straight-through
    (``theta -> 0``) imposes no cap; a reversal (``theta -> pi``) forces ``v -> 0``.

    Returns ``(n_envs, n_gates)`` caps aligned to gate index.
    """
    inc = torch.roll(seg, shifts=1, dims=1)              # segment arriving at gate i (i-1 -> i)
    inc_len = torch.roll(seg_len, shifts=1, dims=1)
    out_dir = seg / seg_len.clamp_min(1e-9).unsqueeze(-1)
    inc_dir = inc / inc_len.clamp_min(1e-9).unsqueeze(-1)
    cos_theta = (inc_dir * out_dir).sum(dim=-1).clamp(-1.0, 1.0)
    half = 0.5 * torch.arccos(cos_theta)                 # half deflection angle
    cos_half = torch.cos(half).clamp_min(1e-6)
    one_minus = (1.0 - cos_half).clamp_min(1e-6)         # -> 0 for straight, -> 1 for reversal
    radius = o.corner_dev * cos_half / one_minus         # huge when straight, ~0 at reversal
    v_corner = torch.sqrt(o.a_lat * radius)
    return v_corner.clamp_max(o.v_max)


def _segment_time(L: Tensor, v_in: Tensor, v_out: Tensor, a: float, v_max: float) -> Tensor:
    """Min time to traverse length ``L`` from speed ``v_in`` to ``v_out``, |accel| <= ``a``,
    speed <= ``v_max`` (trapezoidal / triangular profile). All tensors broadcast; ``(n_envs,)``.
    """
    a = max(a, 1e-6)
    # Unconstrained peak (no v_max): accelerate then brake to meet at v_peak.
    v_peak_tri = torch.sqrt(torch.clamp((2.0 * a * L + v_in**2 + v_out**2) * 0.5, min=0.0))
    v_peak = torch.minimum(v_peak_tri, torch.full_like(v_peak_tri, v_max))
    d_acc = (v_peak**2 - v_in**2) / (2.0 * a)
    d_dec = (v_peak**2 - v_out**2) / (2.0 * a)
    d_cruise = (L - d_acc - d_dec).clamp_min(0.0)
    t_acc = (v_peak - v_in).clamp_min(0.0) / a
    t_dec = (v_peak - v_out).clamp_min(0.0) / a
    t_cruise = d_cruise / v_peak.clamp_min(1e-6)
    return t_acc + t_dec + t_cruise


def feasible_lap_time(
    gate_pos: Tensor, oracle: FeasibleOracle | None = None, sweeps: int = 2
) -> Tensor:
    """Dynamically-feasible target lap time over the closed gate loop. Shape ``(n_envs,)``.

    Forward/backward speed-profile passes around the ring (periodic, so a couple of sweeps
    converge for the small gate counts here), then trapezoidal per-segment times summed.
    """
    o = oracle or FeasibleOracle()
    seg, seg_len = _closed_segments(gate_pos)
    n = gate_pos.shape[1]
    v_cap = _corner_speed_cap(gate_pos, seg, seg_len, o)   # (n_envs, n_gates) at each vertex
    v = v_cap.clone()

    # Forward+backward relaxation around the closed ring. Segment i connects vertex i -> i+1.
    for _ in range(max(sweeps, 1)):
        for i in range(n):                                 # forward: limit by accel out of i-1
            j = (i - 1) % n
            reach = torch.sqrt(v[:, j] ** 2 + 2.0 * o.a_max * seg_len[:, j])
            v[:, i] = torch.minimum(v[:, i], torch.minimum(reach, v_cap[:, i]))
        for i in range(n - 1, -1, -1):                     # backward: must brake into i+1
            j = (i + 1) % n
            reach = torch.sqrt(v[:, j] ** 2 + 2.0 * o.a_max * seg_len[:, i])
            v[:, i] = torch.minimum(v[:, i], reach)

    total = torch.zeros(gate_pos.shape[0], device=gate_pos.device)
    for i in range(n):
        j = (i + 1) % n
        total = total + _segment_time(seg_len[:, i], v[:, i], v[:, j], o.a_max, o.v_max)
    return total
