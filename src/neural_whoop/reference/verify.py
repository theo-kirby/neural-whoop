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
- :func:`check_rate_loop_stability` — would DiffAero's rate loop, as it stood **before
  2026-08-01**, have tracked this? A separate question from every check above, and the only one
  that is about the substrate rather than about the reference. The frame bug it describes is now
  **fixed** in the fork; the check runs on every maneuver so the answer stays a number in every
  artifact, and so pre-fix artifacts can still be read for what they were flown on.
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
from neural_whoop.reference.maneuvers import ManeuverSpec
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


def classify_breaks(samples: Samples, spec: ManeuverSpec) -> list[dict]:
    """Per-seam report: what actually steps at each segment boundary, measured not assumed.

    Worth running even on a maneuver that declares no C² breaks at all — "nothing steps anywhere"
    is a claim, and this is what turns it into a measurement. The swing and the orbit both make it.
    """
    labels = list(spec.phase_labels)
    breaks = tuple(spec.c2_break_phases)
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
            "from_phase": labels[p0] if p0 < len(labels) else str(p0),
            "to_phase": labels[p1] if p1 < len(labels) else str(p1),
            "d_normed_thrust": d_thrust,
            "d_acc_mps2": d_acc,
            "d_rate_cmd_rps": d_cmd,
            "d_omega_rps": d_omega,
            "is_c2_break": bool((p0, p1) in breaks),
        })
    return out


def check_quaternion(samples: Samples, spec: ManeuverSpec) -> dict:
    """Quaternion hygiene, plus whatever "went round correctly" means for *this* maneuver.

    Unit norm and sign continuity are universal — a slerp across a sign flip spins the drone
    backwards for a frame, and no other check would notice. What varies is the rotation claim:

    - **Planar** maneuvers (flip, swing) get the single-axis test: the unwrapped rotation about the
      declared body axis is monotone through the maneuver window and crosses its target exactly
      once. That test is only meaningful *because* the maneuver is a pure rotation about that axis;
      running it on the orbit would be measuring a quantity that does not exist.
    - The **orbit** gets the heading test instead: how many turns the nose actually wound, measured
      as the unwrapped azimuth of body +x. Not euler yaw — at 70° of bank the ZYX yaw is largely a
      gimbal artifact of the ±90° pitch clamp.
    """
    q = samples.quat
    norms = np.linalg.norm(q, axis=-1)
    dots = np.einsum("ij,ij->i", q[1:], q[:-1])
    base = {
        "max_norm_error": float(np.max(np.abs(norms - 1.0))),
        "sign_flips": int(np.count_nonzero(dots < 0.0)),
        "max_attitude_from_identity_deg": float(
            np.degrees(np.max(fl.attitude_angle_from_identity(q)))
        ),
    }
    if spec.is_planar:
        return {**base, "kind": "single-axis", **_planar_rotation(samples, spec)}
    return {**base, "kind": "heading", **_heading_rotation(samples, spec)}


def _heading_rotation(samples: Samples, spec: ManeuverSpec) -> dict:
    """How far the nose wound, from the quaternion, gimbal-free."""
    az = fl.heading_azimuth(samples.quat)
    target = float((spec.reference_meta(None).get("rotation") or {}).get("target_turns") or 0.0)
    turns = float((az[-1] - az[0]) / (2.0 * np.pi))
    return {
        "heading_turns": turns,
        "heading_target_turns": target,
        "heading_turns_error": turns - target,
        "monotone_heading": bool(np.all(np.diff(az) >= -1e-12)),
        "min_dpsi": float(np.min(np.diff(az))) if len(az) > 1 else 0.0,
        "heading_note": (
            "measured as the unwrapped azimuth of body +x, NOT euler yaw: at 70 deg of bank the "
            "ZYX yaw is largely an artifact of the +-90 deg pitch clamp. Monotonicity is expected "
            "here because phi-dot is authored non-negative throughout."
        ),
    }


def _planar_rotation(samples: Samples, spec: ManeuverSpec) -> dict:
    """Rotation about the **declared** body axis — see :func:`check_quaternion`.

    Two claims, and only one of them is universal.

    *Always*: the maneuver ends on its target rotation. For the flip that is 2π; for the swing it
    is exactly 0, since a pendulum returns to level. Both are checked the same way.

    *Only when the spec declares a ``rotation_window``*: that the rotation is monotone through it
    and crosses the target exactly once, i.e. no two-turn root and no over-rotate-and-come-back.
    The flip declares POP..CATCH; the swing declares **none**, and that is correct rather than
    lenient — a swing rolls both ways by construction, so demanding monotonicity would be demanding
    it not be a swing.

    Note the window is the *flip*, not the whole flight: through the recover the airframe
    deliberately leans to fly the residual lateral offset back to the station, so φ wobbles a couple
    of degrees either side of 2π. That is reported (``max_post_window_wobble_rad``), not forbidden.

    The target crossing is counted against ``target − tol`` for the same reason a float comparison
    against an exactly-achieved value is a trap: φ lands on 2π to machine precision, so a bare
    ``phi >= 2π`` toggles on rounding noise and reports dozens of "crossings".
    """
    phi = fl.rotation_angle_about(samples.quat, spec.axis_idx)
    target = float(getattr(spec, "target_phi", 0.0))
    out = {
        "axis": int(spec.axis_idx),
        "phi_end_rad": float(phi[-1]),
        "phi_end_error_rad": float(phi[-1] - target),
        "phi_end_turns": float(phi[-1] / (2.0 * np.pi)),
        "max_abs_phi_rad": float(np.max(np.abs(phi))),
        "target_phi_rad": target,
    }
    window = getattr(spec, "rotation_window", None)
    if window is None:
        out["monotonicity_note"] = (
            "this maneuver declares no rotation window: it rotates both ways by construction, so "
            "monotonicity is not a property it should have."
        )
        return out
    lo, hi = window
    idx = np.flatnonzero((samples.phase >= lo) & (samples.phase <= hi))
    dphi = np.diff(phi[idx]) if idx.size > 1 else np.zeros(1)
    tol = 1e-6
    crossings = int(np.count_nonzero(
        np.diff((phi[idx] >= target - tol).astype(np.int8))
    )) if idx.size > 1 else 0
    post = phi[int(idx[-1]):] if idx.size else phi
    out.update({
        "min_dphi_in_window": float(np.min(dphi)),
        "monotone_in_window": bool(np.all(dphi >= -1e-12)),
        "crossings_of_target": crossings,
        "max_post_window_wobble_rad": float(np.max(np.abs(post - target))),
        "wobble_note": (
            "post-window wobble is the recover phase leaning to fly the residual lateral offset "
            "back to the station — expected, not a defect."
        ),
    })
    return out


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


def check_rate_loop_stability(samples: Samples, model: RefModel) -> dict:
    """**Would DiffAero's rate loop, as it was before 2026-08-01, have tracked this maneuver?**

    A different question from every other check here, and the only one that is about the
    *substrate* rather than about the reference. It runs on every maneuver so the answer ships as a
    number in every artifact instead of living in one commit message.

    **This finding is RESOLVED — the fork is patched.** Until 2026-08-01,
    ``third_party/diffaero/dynamics/controller.py`` computed the measured body rate as
    ``R_i2b @ w`` while ``w`` was already body-frame (``quadrotor.py`` uses ``q̇ = ½q⊗[w,0]`` and
    ``M = τ − w×Jw``, both body-frame), making the closed loop::

        ω̇ = K(u − R·ω)          instead of      ω̇ = K(u − ω)

    ``R`` is a rotation, so its eigenvalues are ``1`` and ``e^{±iθ}`` with ``θ`` the attitude's
    rotation angle from identity. The loop's eigenvalues were therefore ``−K`` and ``−K·e^{±iθ}``,
    whose **real part is ``−K·cos θ``** — negative (stable) below 90° of attitude, *positive*
    (divergent) above it. That line now reads ``actual_angvel_b = w`` and the loop is ``K(u − ω)``
    at every attitude, so **nothing here blocks a maneuver any more**.

    The check is kept because it explains *why the bug hid*, and because it is the right lens for
    reading any artifact generated before the fix. **The 90° threshold alone was never the answer,
    and the flip is the proof.** A roll flip spends ~6% of its frames past 90° of attitude and
    tracked to 2.15 cm even under the bug. The reason is the third eigenvalue: ``R``'s eigenvector
    for eigenvalue ``1`` is its own **rotation axis**, and there the loop eigenvalue stays ``−K``
    no matter what θ is. A planar maneuver's ω lies exactly on that axis, so it never excited the
    two ``−K·e^{±iθ}`` modes at all — which is why every maneuver this repo flew was fine and only
    the genuinely 3D orbit exposed the fault.

    So the check measures **both**: how far the attitude goes, *and* whether ω stays on ``R``'s
    fixed axis. That pairing is what made "ψ ≡ 0 is load-bearing" a mechanism rather than a
    superstition. Measured on the orbit over its 3.85 s: **17.6 m** of position error under the
    legacy loop (DiffAero's own state clamps bound the blow-up rather than letting it reach NaN,
    which is if anything more misleading — it looked like a finite trajectory) versus **1.8 cm /
    0.65°** through the corrected loop, now confirmed in the patched fork. The onset matched the
    predicted 90° crossing and did not improve as ``dt → 1 ms``, so it was instability and not
    discretization.

    Returns:
        The attitude excursion, the worst eigenvalue real part of the off-axis modes, the measured
        ω-to-fixed-axis alignment, and the verdict that combines them — all with respect to the
        **legacy** loop. ``substrate_rate_loop_fixed`` records that the fork no longer has the bug;
        ``vendored_loop_stable`` is retained as a back-compat alias of ``legacy_loop_stable`` so
        pre-fix artifacts stay readable against the same key.
    """
    q = np.asarray(samples.quat, dtype=np.float64)
    theta = fl.attitude_angle_from_identity(q)
    K = model.K_angvel_rp
    above = theta > 0.5 * np.pi
    first = np.flatnonzero(above)

    # R's fixed axis is the quaternion's own rotation axis; both are undefined at identity, and
    # the alignment question is vacuous where there is no rate to misalign.
    axis = q[:, :3]
    n_axis = np.linalg.norm(axis, axis=-1)
    w = np.asarray(samples.omega, dtype=np.float64)
    n_w = np.linalg.norm(w, axis=-1)
    live = (n_axis > 1e-6) & (n_w > 1e-6)
    if np.any(live):
        align = np.abs(np.sum(axis[live] * w[live], axis=-1) / (n_axis[live] * n_w[live]))
        min_align = float(np.min(align))
    else:
        min_align = 1.0
    on_fixed_axis = min_align > 1.0 - 1e-9
    legacy_stable = bool(on_fixed_axis or not np.any(above))
    return {
        "max_attitude_from_identity_deg": float(np.degrees(np.max(theta))),
        "frac_above_90deg": float(np.mean(above)),
        "worst_offaxis_eigenvalue_real_part_per_s": float(np.max(-K * np.cos(theta))),
        "K_angvel_rp": float(K),
        "first_crossing_t_s": float(samples.t[int(first[0])]) if first.size else None,
        "min_omega_fixed_axis_alignment": min_align,
        "omega_on_fixed_axis": bool(on_fixed_axis),
        # The substrate is FIXED as of 2026-08-01; the verdicts below are about the LEGACY loop and
        # exist to explain why the bug hid and to date-stamp older artifacts.
        "substrate_rate_loop_fixed": True,
        "flyable_in_diffaero": True,
        "legacy_loop_stable": legacy_stable,
        "vendored_loop_stable": legacy_stable,   # back-compat alias; same value
        "stability_reason": (
            "omega lies on R's fixed axis (alignment "
            f"{min_align:.6f}), so only the eigenvalue that stays -K is ever excited — the "
            "attitude excursion is irrelevant, and this maneuver would have tracked even under "
            "the legacy loop" if on_fixed_axis else
            ("attitude never exceeds 90 deg, so every eigenvalue has negative real part even "
             "under the legacy loop"
             if not np.any(above) else
             "omega leaves R's fixed axis (alignment "
             f"{min_align:.3f}) AND the attitude passes 90 deg, so under the LEGACY loop the "
             "-K*cos(theta) modes were excited with a POSITIVE real part and it diverged. The "
             "fork is now patched, so it tracks in DiffAero as vendored today")
        ),
        "note": (
            "RESOLVED 2026-08-01. DiffAero's RateController USED TO compute the measured body rate "
            "as R_i2b @ w while w is already body-frame, so the closed loop was wdot = K(u - R w). "
            "R's eigenvalues are 1 and exp(+-i*theta), so the loop's were -K and -K*exp(+-i*theta) "
            "— real part -K*cos(theta), which goes POSITIVE past 90 deg of attitude. The "
            "eigenvalue that stays -K belongs to R's rotation axis, which is why a planar maneuver "
            "(omega ON that axis) survived 180 deg of inversion and a 3D one did not — and why the "
            "bug went unnoticed until the orbit. controller.py now reads actual_angvel_b = w; the "
            "orbit tracks to 1.8 cm where it previously diverged 17.6 m, and both arms of that "
            "control experiment are pinned in tests/test_reference_sim.py. Nothing here blocks "
            "using a maneuver as an RL target any more."
        ),
    }


def verify_reference(
    fine: Samples,
    replay: Samples,
    model: RefModel,
    spec: ManeuverSpec,
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
        "maneuver": spec.name,
        # Planarity is a claim only a planar maneuver makes. Running assert_planar on the orbit
        # would fail by design and say nothing — the orbit's non-planarity is the point of it.
        "planarity": (assert_planar(fine, spec) if spec.is_planar else {
            "is_planar": False,
            "max_abs_omega_z_rps": float(np.max(np.abs(fine.omega[:, 2]))),
            "note": ("this maneuver is 3D by design (psi winds), so there is no planarity claim to "
                     "assert. See rate_loop_stability for what that costs in this simulator."),
        }),
        "quaternion": check_quaternion(fine, spec),
        "seams": classify_breaks(fine, spec),
        "limits": check_limits(fine, min_thrust_normed=min_thrust_normed),
        "allocation": check_allocation(fine, model),
        "rate_loop_stability": check_rate_loop_stability(fine, model),
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
