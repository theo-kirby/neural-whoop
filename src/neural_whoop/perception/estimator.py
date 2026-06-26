"""Target estimators: the render-free perception seam — batched torch.

Ported from neural-whoop-lab's pure ``perception/estimator.py`` and vectorized. The
:class:`OracleEstimator` returns the simulator's ground-truth body-frame target-relative
vector — no pixels — which is the whole render-free training trick: the flight policy is fed
``[gx, gy, gz]`` directly, so training is GPU-cheap and never touches the (Blackwell-broken)
camera path. :func:`apply_detector_noise` models a real detector's failure modes (bearing
noise, range error, FOV limit, dropout/stale-hold) on that oracle vector, so the policy still
learns to survive detection noise without rendering.

Body-frame convention (matching :mod:`neural_whoop.contract`): **+x forward** (camera axis),
**+y left**, **+z up**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import Tensor


class OracleEstimator:
    """Returns the ground-truth body-frame target-relative vector, batched.

    The env computes the true ``rel_body`` (target minus drone, rotated into the body frame);
    this estimator just passes it through, with confidence 1. It is the training/reward signal
    and the fidelity baseline a real detector is measured against.
    """

    def estimate(self, rel_body: Tensor) -> tuple[Tensor, Tensor]:
        conf = torch.ones(rel_body.shape[:-1], device=rel_body.device, dtype=rel_body.dtype)
        return rel_body, conf


@dataclass(frozen=True)
class DetectorNoise:
    """Detector error model applied per control step (batched), in the body frame.

    Models a cheap blob/depth detector's failure modes on the oracle vector during training
    (no rendering): bearing noise, multiplicative range error, a forward FOV cone outside
    which the target is unseen, and per-step dropout. On a miss the estimate **stale-holds**
    the last valid fix.

    Attributes:
        bearing_std_rad: Std of angular (bearing) noise on the target direction.
        range_frac: Std of multiplicative range error (fraction of true distance).
        dropout_prob: Per-step probability the detector fails (-> stale-hold).
        fov_half_rad: Half-angle of the forward field of view (target outside -> stale-hold).
    """

    bearing_std_rad: float = 0.0
    range_frac: float = 0.0
    dropout_prob: float = 0.0
    fov_half_rad: float = math.radians(35.0)

    @property
    def is_identity(self) -> bool:
        return (
            self.bearing_std_rad == 0.0
            and self.range_frac == 0.0
            and self.dropout_prob == 0.0
            and self.fov_half_rad >= math.pi  # full sphere FOV == never culled
        )


def apply_detector_noise(
    rel_body: Tensor,
    det: DetectorNoise,
    last_valid: Tensor,
    generator: torch.Generator | None = None,
) -> tuple[Tensor, Tensor]:
    """Corrupt a batched body-frame target vector with the detector error model.

    The forward (camera) axis is body **+x**. A target is "seen" only when it lies inside the
    forward FOV cone and the per-step dropout roll passes; otherwise the estimate stale-holds
    ``last_valid``. When seen, the bearing is perturbed by tangential angular noise and the
    range by a multiplicative error.

    Args:
        rel_body: True body-frame target vectors, shape ``(..., 3)``.
        det: Detector magnitudes for this episode.
        last_valid: Previous returned estimate (stale-hold source), shape ``(..., 3)``.
        generator: Optional torch ``Generator``.

    Returns:
        ``(estimate, fresh)``: the (possibly stale) estimate ``(..., 3)`` and a bool mask
        ``(...)`` of which envs produced a fresh detection this step.
    """
    dev = rel_body.device
    dist = rel_body.norm(dim=-1, keepdim=True)
    safe = dist.clamp_min(1e-9)
    direction = rel_body / safe

    # Forward-FOV check: angle from body +x.
    cos_ang = direction[..., 0].clamp(-1.0, 1.0)
    in_fov = cos_ang >= math.cos(det.fov_half_rad)
    if det.dropout_prob > 0.0:
        roll = torch.rand(rel_body.shape[:-1], device=dev, generator=generator)
        dropped = roll < det.dropout_prob
    else:
        dropped = torch.zeros(rel_body.shape[:-1], device=dev, dtype=torch.bool)
    fresh = in_fov & (~dropped)

    new_dir = direction
    if det.bearing_std_rad > 0.0:
        noise = torch.randn(direction.shape, device=dev, generator=generator) * det.bearing_std_rad
        # Project noise onto the tangent plane (perpendicular to direction).
        noise = noise - (noise * direction).sum(-1, keepdim=True) * direction
        new_dir = direction + noise
        new_dir = new_dir / new_dir.norm(dim=-1, keepdim=True).clamp_min(1e-9)

    new_range = dist
    if det.range_frac > 0.0:
        scale = 1.0 + torch.randn(dist.shape, device=dev, generator=generator) * det.range_frac
        new_range = (dist * scale).clamp_min(0.0)

    fresh_est = new_dir * new_range
    est = torch.where(fresh.unsqueeze(-1), fresh_est, last_valid)
    return est, fresh
