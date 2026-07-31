"""What the onboard accelerometer would read: body-frame **specific force**.

An IMU does not measure acceleration — it measures the non-gravitational force per unit mass, in
the body frame. So::

    imu = Rᵀ·(a_world − G_vec) = Rᵀ·(a_world + g·ê_z)

At rest that is ``(0, 0, +9.81)`` — **+1 g on body +z** — which is the sign convention the real
pilot's ``az_ref`` calibration establishes (``pilot/controller.py``), so a reference trace and a
real flight log can be laid on top of each other without a sign argument.

Substituting the simulator's own acceleration equation makes the flip's IMU trace legible::

    imu = normed_thrust·g·ê_3 − (D/m)·Rᵀ·v

The first term is pure thrust on body +z; the second is drag, rotated into the body frame. Two
consequences worth stating before anyone reads the chart:

- **The coast is not a flat free-fall null — it is a V.** At zero thrust the first term vanishes
  but the drag term does not, and drag is proportional to *speed*, which on a ballistic arc is
  large at both ends and zero at the apex. Measured on the shipped reference the magnitude runs
  **~1.06 g at the coast entry -> ~0.09 g at the apex -> ~0.7 g on the way back down**. So there
  is a genuine free-fall null, but only for the instant the drone is motionless at the top.
  Anyone expecting a flat null across the whole coast will think the generator is broken; it is
  the simulator's (large, linear) drag talking — see
  :class:`~neural_whoop.reference.model.RefModel`.
- The body-z component goes **strongly negative** at the coast entry (about −10 m/s² on the
  shipped reference), which is not a sign error: the drone is climbing fast along its own +z, so
  drag pushes back along −z and that is exactly what an accelerometer bolted to the frame reads.
- On the ``--deployable`` variant the coast term is ``0.25·g`` on body +z on top of that, which is
  the throttle floor showing up in the accelerometer exactly as it would on the real airframe.
"""

from __future__ import annotations

import numpy as np

from neural_whoop.reference.model import RefModel

_E_Z = np.array([0.0, 0.0, 1.0])

#: Describes the sign/frame convention, carried in ``meta.imu_info`` so a consumer never has to
#: guess which way "up" reads.
IMU_INFO = {
    "units": "m/s^2",
    "frame": "body (+x forward / +y left / +z up), same as angvel",
    "convention": "specific force f = R^T (a_world + g*e_z); +1 g (+9.81) on body +z at rest",
    "note": "not acceleration — an accelerometer reads non-gravitational force per unit mass",
}


def specific_force_body(R: np.ndarray, acc_world: np.ndarray, model: RefModel) -> np.ndarray:
    """The accelerometer reading, ``Rᵀ(a_world + g·ê_z)``, shape ``(..., 3)``.

    Args:
        R: Body->world rotation matrices ``(..., 3, 3)``.
        acc_world: World-frame acceleration ``(..., 3)``.
        model: The airframe (only ``g`` is used).

    Returns:
        Body-frame specific force in m/s².
    """
    R = np.asarray(R, dtype=np.float64)
    a = np.asarray(acc_world, dtype=np.float64)
    return np.einsum("...ji,...j->...i", R, a + model.g * _E_Z)
