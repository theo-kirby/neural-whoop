"""Does the reference actually satisfy the physics it claims to? Checks, with numbers.

A hand-authored trajectory is only worth anything if it is *checkable*, so every claim this
package makes has a check that produces a number rather than a boolean. The results land in
``verify.json`` next to the artifact.

The checks, and what each one is really for:

- :func:`check_quaternion` — unit norm, no sign flips, and the unwrapped rotation angle monotone
  and terminating on 2π. Catches a renderer-visible defect (a slerp across a sign flip spins the
  drone backwards for a frame) that no other check would notice.
- :func:`check_limits` — every frame inside the act-v2 envelope **with margin**. Margin, not
  membership: a reference that sits exactly on its own rate ceiling cannot detect a regression
  that silently saturates.
- :func:`check_allocation` — can four motors actually *produce* the commanded torque at the
  commanded collective? This is the most valuable check in the set precisely because the simulator
  enforces nothing here: ``BaseController.postprocess`` (``controller.py:33-44``) is never called,
  so DiffAero will happily apply an unbounded torque that no real airframe could make.
- :func:`dynamics_residual` — the honest one. Central-difference the emitted ``pos``/``vel``/
  ``quat`` and confirm they satisfy ``quadrotor.py:111-142``. Run at both 50 Hz and 1 kHz: with a
  second-order difference the residual must fall by ~(20)² = 400x, and **if it doesn't, the bug is
  in the flatness map rather than in the sampling** — which is exactly what makes running it at
  two rates diagnostic instead of decorative.
"""

from __future__ import annotations

import numpy as np

from neural_whoop.reference import flatness as fl
from neural_whoop.reference.limits import (
    MAX_BODY_RATE_RP_RPS,
    MAX_BODY_RATE_YAW_RPS,
    MAX_THRUST_NORMED,
    RATE_CMD_HEADROOM,
)
from neural_whoop.reference.maneuvers import C2_BREAK_PHASES, FlipSpec
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.segments import Samples

_E_Z = np.array([0.0, 0.0, 1.0])
_E_3 = np.array([0.0, 0.0, 1.0])
_SQRT2 = np.sqrt(2.0)


def _nonuniform_derivative(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Second-order central difference on a **non-uniform** grid, ``(N, ...)`` -> same shape.

    Segment durations are not multiples of the sample step, so each segment gets its own exact
    subdivision and the global time base is monotone but very slightly non-uniform at seams.
    Assuming a fixed step there would manufacture an error at every join and muddy the one
    measurement this module exists to make. Endpoints fall back to one-sided differences.
    """
    t = np.asarray(t, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = len(t)
    d = np.empty_like(y)
    h1 = (t[1:-1] - t[:-2]).reshape(-1, *([1] * (y.ndim - 1)))
    h2 = (t[2:] - t[1:-1]).reshape(-1, *([1] * (y.ndim - 1)))
    d[1:-1] = (
        -h2 / (h1 * (h1 + h2)) * y[:-2]
        + (h2 - h1) / (h1 * h2) * y[1:-1]
        + h1 / (h2 * (h1 + h2)) * y[2:]
    )
    d[0] = (y[1] - y[0]) / (t[1] - t[0])
    d[-1] = (y[-1] - y[-2]) / (t[-1] - t[-2])
    del n
    return d


def c2_break_indices(samples: Samples, *, halo: int = 1) -> list[int]:
    """Indices whose central difference straddles an authored **command step**.

    Derived from the maneuver's own structure — every segment seam — rather than by eyeball or by
    thresholding the residual, so the excluded set is reproducible and gets published in
    ``verify.json``.

    It would be tidier to mask only the two thrust steps named in
    :data:`~neural_whoop.reference.maneuvers.C2_BREAK_PHASES`, and that was the first attempt. It
    is not enough: the **rate command** steps too (``ω̇`` jumps from 0 to ~186 rad/s² when the
    roll-in's constant command switches on), and while ``ω`` stays continuous there, a central
    difference of the quaternion is only second-order accurate while ``ω̇`` is. Masking the thrust
    seams alone left a 2e-2 quaternion residual sitting in plain sight. So: mask every seam, and
    let :func:`classify_breaks` report *which* channel actually stepped at each one.

    At 1 kHz this excludes ~0.2% of the stream; at 50 Hz ~5%. Both counts are reported.
    """
    n = len(samples)
    out: list[int] = []
    for a, _ in samples.segment_bounds()[1:]:
        out.extend(range(max(0, a - halo), min(n, a + halo)))
    return sorted(set(out))


def classify_breaks(samples: Samples) -> list[dict]:
    """Per-seam report: what actually steps at each segment boundary, measured not assumed."""
    from neural_whoop.reference.maneuvers import PHASE_LABELS

    out: list[dict] = []
    for a, _ in samples.segment_bounds()[1:]:
        d_thrust = float(samples.normed_thrust[a] - samples.normed_thrust[a - 1])
        d_acc = float(np.linalg.norm(samples.acc[a] - samples.acc[a - 1]))
        d_cmd = float(np.max(np.abs(samples.rate_cmd[a] - samples.rate_cmd[a - 1])))
        d_omega = float(np.max(np.abs(samples.omega[a] - samples.omega[a - 1])))
        p0, p1 = int(samples.phase[a - 1]), int(samples.phase[a])
        out.append({
            "index": int(a),
            "t_s": float(samples.t[a]),
            "from_phase": PHASE_LABELS[p0] if p0 < len(PHASE_LABELS) else str(p0),
            "to_phase": PHASE_LABELS[p1] if p1 < len(PHASE_LABELS) else str(p1),
            "d_normed_thrust": d_thrust,
            "d_acc_mps2": d_acc,
            "d_rate_cmd_rps": d_cmd,
            "d_omega_rps": d_omega,
            "is_c2_break": bool((p0, p1) in C2_BREAK_PHASES),
        })
    return out


def check_quaternion(samples: Samples, spec: FlipSpec) -> dict:
    """Unit norm, sign continuity, and a rotation that reaches the target angle exactly once.

    **Monotonicity is asserted over the flip window (POP..CATCH), not the whole flight**, and that
    is not a loosened test — it is the correct one. Through the recover the airframe deliberately
    leans to fly the residual lateral offset back to the station, so the roll angle wobbles a
    couple of degrees either side of 2π. Demanding global monotonicity would be demanding that the
    drone never translate again. The wobble is reported (``max_post_flip_wobble_rad``) rather than
    forbidden.

    The target crossing is counted against ``target − tol`` for the same reason a float comparison
    against an exactly-achieved value is a trap: φ lands on 2π to machine precision, so a bare
    ``phi >= 2π`` toggles on rounding noise and reports dozens of "crossings".
    """
    q = samples.quat
    norms = np.linalg.norm(q, axis=-1)
    dots = np.einsum("ij,ij->i", q[1:], q[:-1])
    phi = fl.rotation_angle_about(q, spec.axis_idx)

    from neural_whoop.reference.maneuvers import PHASE

    flip = (samples.phase >= PHASE["POP"]) & (samples.phase <= PHASE["CATCH"])
    idx = np.flatnonzero(flip)
    dphi_flip = np.diff(phi[idx]) if idx.size > 1 else np.zeros(1)
    # Counted INSIDE the flip window, for the same reason monotonicity is: after the flip the
    # recover leans and φ oscillates a couple of degrees about 2π, so a whole-flight count would
    # report every one of those wobbles as a "crossing". The claim being tested is that the flip
    # reaches its target angle once and does not over-rotate and come back.
    tol = 1e-6
    crossings = int(np.count_nonzero(
        np.diff((phi[idx] >= spec.target_phi - tol).astype(np.int8))
    )) if idx.size > 1 else 0
    post = phi[int(idx[-1]):] if idx.size else phi
    return {
        "max_norm_error": float(np.max(np.abs(norms - 1.0))),
        "sign_flips": int(np.count_nonzero(dots < 0.0)),
        "min_dphi_in_flip": float(np.min(dphi_flip)),
        "monotone_in_flip": bool(np.all(dphi_flip >= -1e-12)),
        "phi_end_rad": float(phi[-1]),
        "phi_end_error_rad": float(phi[-1] - spec.target_phi),
        "phi_end_turns": float(phi[-1] / (2.0 * np.pi)),
        "crossings_of_target": crossings,
        "max_post_flip_wobble_rad": float(np.max(np.abs(post - spec.target_phi))),
        "wobble_note": (
            "post-flip wobble is the RECOVER phase leaning to fly the residual lateral offset "
            "back to the station — expected, not a defect."
        ),
    }


def check_limits(samples: Samples, *, min_thrust_normed: float = 0.0) -> dict:
    """Every frame inside the act-v2 envelope, reported as **headroom** rather than pass/fail."""
    nt = samples.normed_thrust
    u = samples.rate_cmd
    rp = float(np.max(np.abs(u[:, :2])))
    yaw = float(np.max(np.abs(u[:, 2])))
    return {
        "max_normed_thrust": float(np.max(nt)),
        "min_normed_thrust": float(np.min(nt)),
        "thrust_ceiling": MAX_THRUST_NORMED,
        "thrust_headroom_frac": float(1.0 - np.max(nt) / MAX_THRUST_NORMED),
        "thrust_floor_respected": bool(np.min(nt) >= min_thrust_normed - 1e-12),
        "max_abs_rate_cmd_rp_rps": rp,
        "rate_cmd_ceiling_rps": MAX_BODY_RATE_RP_RPS,
        "rate_headroom_frac": float(1.0 - rp / MAX_BODY_RATE_RP_RPS),
        "rate_headroom_target_frac": RATE_CMD_HEADROOM,
        "max_abs_rate_cmd_yaw_rps": yaw,
        "yaw_cmd_ceiling_rps": MAX_BODY_RATE_YAW_RPS,
        "max_abs_body_rate_rps": float(np.max(np.abs(samples.omega))),
        "within_envelope": bool(
            np.max(nt) <= MAX_THRUST_NORMED + 1e-9
            and rp <= MAX_BODY_RATE_RP_RPS * (1.0 - RATE_CMD_HEADROOM) + 1e-9
            and yaw <= MAX_BODY_RATE_YAW_RPS + 1e-9
        ),
    }


def check_allocation(samples: Samples, model: RefModel) -> dict:
    """Can four motors produce the commanded torque at the commanded collective?

    A single-axis torque ``τ = J·ω̇`` comes from a differential ``ΔT = τ/(arm_l/√2)`` between the
    two motor pairs (``quadrotor.py:116``). Since no motor can push backwards, that differential
    can never exceed the total thrust, so the airframe is allocation-feasible iff::

        c_req = J_xy·|ω̇| / (arm_l/√2) / (m·g)  ≤  normed_thrust

    Two margins are reported, and the difference between them is the interesting part:

    - ``min_margin`` over every frame. On the motors-off variant this is **exactly 0.0** through
      the whole coast — zero thrust demanding zero torque. That is feasible only in the degenerate
      sense: the airframe has *no rate authority at all* while the motors are off, so nothing could
      be corrected if it drifted. It is the same failure recorded in ``docs/SIM2REAL.md`` as the
      AIRMODE flip stall, where a whoop at idle throttle loses rate authority mid-flip.
    - ``min_margin_torqued`` over only the frames that actually demand torque. That is the number
      to read when asking "can the airframe fly this?", and it is where the 0.25 throttle floor
      earns its keep.
    """
    tau = model.J_xy * np.abs(samples.omega_dot[:, :2]).max(axis=1)
    c_req = tau / (model.arm_l / _SQRT2) / (model.mass * model.g)
    margin = samples.normed_thrust - c_req
    worst = int(np.argmin(margin))
    torqued = c_req > 1e-12
    if np.any(torqued):
        idx = np.flatnonzero(torqued)
        wt = int(idx[np.argmin(margin[torqued])])
    else:
        wt = worst
    return {
        "max_required_normed_collective": float(np.max(c_req)),
        "min_margin": float(np.min(margin)),
        "feasible": bool(np.min(margin) >= 0.0),
        "worst_index": worst,
        "worst_t_s": float(samples.t[worst]),
        "worst_phase": int(samples.phase[worst]),
        "worst_normed_thrust": float(samples.normed_thrust[worst]),
        "worst_required": float(c_req[worst]),
        "min_margin_torqued": float(margin[wt]),
        "worst_torqued_t_s": float(samples.t[wt]),
        "worst_torqued_phase": int(samples.phase[wt]),
        "worst_torqued_normed_thrust": float(samples.normed_thrust[wt]),
        "worst_torqued_required": float(c_req[wt]),
        "zero_authority_frac": float(np.mean(samples.normed_thrust <= 1e-12)),
        "note": (
            "min_margin includes the coast, where zero thrust demands zero torque and the margin "
            "is exactly 0 — feasible only degenerately, since the airframe has NO rate authority "
            "there. Read min_margin_torqued for 'can it fly this'. zero_authority_frac is how "
            "much of the reference is spent with the motors fully off."
        ),
    }


def dynamics_residual_series(samples: Samples, model: RefModel) -> dict[str, np.ndarray]:
    """Per-frame residual magnitudes ``|ṗ − v|``, ``|v̇ − a|``, ``|q̇ − ½q⊗ω|`` (SI).

    The aggregate in :func:`dynamics_residual` says *how big*; this says **where**, which is what
    makes the chart worth looking at — the spikes land exactly on the two intentional acceleration
    steps and nowhere else, and that is the claim rather than a hope.
    """
    t = samples.t
    z_B = samples.R[:, :, 2]
    acc_model = (
        samples.normed_thrust[:, None] * model.g * z_B
        - model.g * _E_Z
        - model.drag_per_mass * samples.vel
    )
    return {
        "t": t,
        "pos": np.linalg.norm(_nonuniform_derivative(t, samples.pos) - samples.vel, axis=-1),
        "vel": np.linalg.norm(_nonuniform_derivative(t, samples.vel) - acc_model, axis=-1),
        "quat": np.linalg.norm(
            _nonuniform_derivative(t, samples.quat)
            - fl.quat_derivative(samples.quat, samples.omega), axis=-1),
    }


def dynamics_residual(samples: Samples, model: RefModel, *, mask: list[int] | None = None) -> dict:
    """Do the emitted arrays satisfy DiffAero's own ODE? (``quadrotor.py:111-142``)

    Three residuals: ``ṗ − v``, ``v̇ − a(q, T, v)`` and ``q̇ − ½q⊗[ω,0]``.

    The mask applies to all three. It is tempting to exempt position (``v`` is continuous) and the
    quaternion (``ω`` is continuous), and that was the first attempt — but a central difference is
    second-order accurate only while the *next* derivative is smooth. Across the 37 m/s²
    acceleration step the position difference collapses to first order (~``h·Δa/2``, ~9 mm/s at
    1 kHz), and across the 186 rad/s² ``ω̇`` step the quaternion difference does the same (~2e-2).
    Both are artifacts of differencing an authored discontinuity, not defects — but they have to be
    excluded honestly and reported, which is what ``*_at_breaks`` is for.
    """
    t = samples.t
    R = samples.R
    z_B = R[:, :, 2]
    acc_model = (
        samples.normed_thrust[:, None] * model.g * z_B
        - model.g * _E_Z
        - model.drag_per_mass * samples.vel
    )
    res_pos = np.linalg.norm(_nonuniform_derivative(t, samples.pos) - samples.vel, axis=-1)
    res_vel = np.linalg.norm(_nonuniform_derivative(t, samples.vel) - acc_model, axis=-1)
    qdot = fl.quat_derivative(samples.quat, samples.omega)
    res_quat = np.linalg.norm(_nonuniform_derivative(t, samples.quat) - qdot, axis=-1)

    keep = np.ones(len(t), dtype=bool)
    keep[[0, -1]] = False              # one-sided endpoints are first order, not second
    smooth = keep.copy()
    if mask:
        smooth[list(mask)] = False
    at_breaks = ~smooth & keep
    out = {
        "pos_max": float(np.max(res_pos[smooth])),
        "pos_rms": float(np.sqrt(np.mean(res_pos[smooth] ** 2))),
        "vel_max": float(np.max(res_vel[smooth])),
        "vel_rms": float(np.sqrt(np.mean(res_vel[smooth] ** 2))),
        "quat_max": float(np.max(res_quat[smooth])),
        "quat_rms": float(np.sqrt(np.mean(res_quat[smooth] ** 2))),
        "n_samples": int(len(t)),
        "n_masked": int(len(mask or [])),
        "masked_frac": float(len(mask or []) / max(len(t), 1)),
        "masked_indices": [int(i) for i in (mask or [])],
        "mask_note": (
            "masked frames straddle an authored command step (thrust and/or rate). A central "
            "difference is second-order only while the NEXT derivative is smooth, so all three "
            "residuals degrade there. Values at those frames are reported as *_at_breaks."
        ),
        "acc_model_max": float(np.max(np.linalg.norm(acc_model, axis=-1))),
    }
    for name, res in (("pos", res_pos), ("vel", res_vel), ("quat", res_quat)):
        out[f"{name}_max_at_breaks"] = float(np.max(res[at_breaks])) if np.any(at_breaks) else 0.0
    return out


def verify_reference(
    fine: Samples,
    replay: Samples,
    model: RefModel,
    spec: FlipSpec,
    *,
    min_thrust_normed: float = 0.0,
) -> dict:
    """Run every check on both sampling rates and assemble ``verify.json``."""
    from neural_whoop.reference.maneuvers import assert_planar

    mask_fine = c2_break_indices(fine)
    mask_replay = c2_break_indices(replay)
    res_fine = dynamics_residual(fine, model, mask=mask_fine)
    res_replay = dynamics_residual(replay, model, mask=mask_replay)
    dt_fine = float(np.median(np.diff(fine.t)))
    dt_replay = float(np.median(np.diff(replay.t)))
    ratio = (dt_replay / dt_fine) ** 2
    got = res_replay["vel_rms"] / max(res_fine["vel_rms"], 1e-300)
    return {
        "planarity": assert_planar(fine, spec),
        "quaternion": check_quaternion(fine, spec),
        "seams": classify_breaks(fine),
        "limits": check_limits(fine, min_thrust_normed=min_thrust_normed),
        "allocation": check_allocation(fine, model),
        "dynamics_residual_fine": res_fine,
        "dynamics_residual_replay": res_replay,
        "second_order_convergence": {
            "dt_fine_s": dt_fine,
            "dt_replay_s": dt_replay,
            "expected_ratio": float(ratio),
            "observed_vel_rms_ratio": float(got),
            "note": (
                "A second-order central difference should degrade as dt^2 between the two rates. "
                "If the observed ratio is far below the expected one, the residual is dominated "
                "by a modeling error in the flatness map rather than by sampling — which is the "
                "whole reason this is measured at two rates."
            ),
        },
    }
