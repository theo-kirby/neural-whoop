"""Pure-torch drop-in for the handful of ``pytorch3d.transforms`` functions DiffAero's
dynamics core uses.

neural-whoop vendors DiffAero and runs its differentiable batched quadrotor on Blackwell
(sm_120 / RTX 5090). pytorch3d is a heavy compiled CUDA extension that is painful-to-
impossible to build against cu128/cu130 wheels, and the dynamics path needs only two
trivial quaternion ops from it. This module reimplements exactly those in pure torch so the
vendored fork imports and runs with no pytorch3d present. (This is the "our edits live here"
seam: the four DiffAero import sites point here instead of at ``pytorch3d.transforms``.)

pytorch3d quaternion convention is **real-part-first** ``(w, x, y, z)``.
"""

from __future__ import annotations

import torch
from torch import Tensor


def quaternion_to_matrix(quaternions: Tensor) -> Tensor:
    """Convert real-first ``(w, x, y, z)`` quaternions to ``(..., 3, 3)`` rotation matrices.

    Matches ``pytorch3d.transforms.quaternion_to_matrix`` (assumes unit quaternions; it
    normalises defensively, as pytorch3d does via the ``two_s`` scaling).
    """
    r, i, j, k = torch.unbind(quaternions, -1)
    two_s = 2.0 / (quaternions * quaternions).sum(-1)
    o = torch.stack(
        (
            1 - two_s * (j * j + k * k),
            two_s * (i * j - k * r),
            two_s * (i * k + j * r),
            two_s * (i * j + k * r),
            1 - two_s * (i * i + k * k),
            two_s * (j * k - i * r),
            two_s * (i * k - j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(quaternions.shape[:-1] + (3, 3))


def quaternion_raw_multiply(a: Tensor, b: Tensor) -> Tensor:
    """Hamilton product of two real-first ``(w, x, y, z)`` quaternions (no normalisation).

    Matches ``pytorch3d.transforms.quaternion_raw_multiply``.
    """
    aw, ax, ay, az = torch.unbind(a, -1)
    bw, bx, by, bz = torch.unbind(b, -1)
    ow = aw * bw - ax * bx - ay * by - az * bz
    ox = aw * bx + ax * bw + ay * bz - az * by
    oy = aw * by - ax * bz + ay * bw + az * bx
    oz = aw * bz + ax * by - ay * bx + az * bw
    return torch.stack((ow, ox, oy, oz), -1)


def matrix_to_quaternion(matrix: Tensor) -> Tensor:
    """Convert ``(..., 3, 3)`` rotation matrices to real-first ``(w, x, y, z)`` quaternions.

    Provided for completeness; mirrors pytorch3d's numerically-stable branch selection.
    """
    if matrix.shape[-2:] != (3, 3):
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    batch = matrix.shape[:-2]
    m = matrix.reshape(batch + (9,))
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(m, -1)
    q_abs = torch.stack(
        [
            1.0 + m00 + m11 + m22,
            1.0 + m00 - m11 - m22,
            1.0 - m00 + m11 - m22,
            1.0 - m00 - m11 + m22,
        ],
        dim=-1,
    ).clamp_min(0.0).sqrt()
    quat_by_rijk = torch.stack(
        [
            torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], dim=-1),
            torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], dim=-1),
            torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], dim=-1),
            torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], dim=-1),
        ],
        dim=-2,
    )
    flr = torch.tensor(0.1, dtype=q_abs.dtype, device=q_abs.device)
    quat_candidates = quat_by_rijk / (2.0 * q_abs[..., None].max(flr))
    idx = q_abs.argmax(dim=-1, keepdim=True)
    idx = idx[..., None].expand(idx.shape + (4,))
    return torch.gather(quat_candidates, -2, idx).squeeze(-2)
