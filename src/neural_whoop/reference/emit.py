"""Turn a sampled reference into the two artifacts — and be explicit about which is which.

- **``replay.json.gz``** (50 Hz) is the **video** artifact: the Studio/capture-playable document,
  built with the same :class:`~neural_whoop.viz.replay.RunRecorder` a policy rollout uses, so
  ``--preset hero`` renders it with no changes to the capturer.
- **``reference.json``** (1 kHz) is the **data** artifact: the fine stream, the model verbatim, the
  shooting record with its final residuals, and the derived headline metrics.

Two files rather than one because **50 Hz aliases this maneuver**. The rate brake is under two
control steps and the thrust cut is exactly one; any consumer that finite-differences the 50 Hz
replay sees a ~250 rad/s² event as a single-frame spike. The replay is for looking at; the fine
stream is for measuring against.

The metrics deliberately carry **the same names ``acro_flip`` computes**
(``max_lateral_drift``, ``peak_climb``, ``altitude_loss``, ``settle_pos_error``), so "this is the
one we want" becomes a literal number the RL is graded against rather than a paragraph of prose.
Those four are computed here for **every** maneuver, over the window the spec declares; anything
only one maneuver has (``swing_half_width_m``, ``axis_pointing_error_deg``, …) comes from that
spec's :meth:`~neural_whoop.reference.maneuvers.ManeuverSpec.extra_metrics`.

Everything in this module takes a :class:`~neural_whoop.reference.maneuvers.ManeuverSpec` rather
than a ``FlipSpec``, and ``solution`` is optional — a maneuver that needed no boundary-value solve
passes ``None``, which is a result rather than an omission.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from neural_whoop.reference.imu import IMU_INFO
from neural_whoop.reference.limits import (
    HOVER_THRUST_NORMED,
    MAX_BODY_RATE_RP_RPS,
    MAX_BODY_RATE_YAW_RPS,
    MAX_THRUST_NORMED,
    act_v2_from_diffaero,
)
from neural_whoop.reference.maneuvers import ManeuverSpec
from neural_whoop.reference.model import RefModel, drag_sensitivity_models
from neural_whoop.reference.segments import Samples, Trajectory
from neural_whoop.viz.replay import (
    ACTION_LAYOUT,
    COORDINATE_FRAME,
    STATE_LAYOUT,
    UNITY_HINT,
    RunRecorder,
)

REFERENCE_FORMAT = "neural-whoop-reference"
REFERENCE_VERSION = 2


def decimate_indices(fine: Samples, dt_replay: float) -> np.ndarray:
    """Fine-stream indices nearest a ~``dt_replay`` grid, endpoints included."""
    idx = np.unique(np.searchsorted(fine.t, np.arange(fine.t[0], fine.t[-1] + 1e-12, dt_replay)))
    idx = np.clip(idx, 0, len(fine) - 1)
    if idx[-1] != len(fine) - 1:
        idx = np.append(idx, len(fine) - 1)
    return idx


def decimate(fine: Samples, dt_replay: float) -> Samples:
    """Nearest-sample decimation of the fine stream onto a ~``dt_replay`` grid.

    Nearest rather than interpolated: interpolating a quaternion sequence would put frames on the
    chord instead of the arc, and interpolating across the thrust cut would invent a state that
    never existed. The cost is up to half a fine step (~0.5 ms) of timing jitter, which is 2.5% of
    a control step and is why the verification differentiates on the actual ``t``.
    """
    idx = decimate_indices(fine, dt_replay)
    return Samples(**{k: getattr(fine, k)[idx] for k in Samples.__dataclass_fields__})


def step_hold_commands(fine: Samples, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The **impulse-matched** zero-order-hold command for each replay step.

    A replay frame's ``action`` is not a decoration — it is what a consumer would actually send,
    and DiffAero (like the real flight controller) *holds* it for the whole control step. The
    reference is a continuous command profile, so the honest discretization is the **mean over the
    step**, not the value at its left edge.

    This is not a rounding-level nicety. Measured by replaying the emitted stream open-loop
    through ``WhoopDynamics``:

    ========================== ============ ============ ============
    command sampled as         50 Hz        100 Hz       400 Hz
    ========================== ============ ============ ============
    instantaneous at ``t_k``   108 cm       12 cm        9 cm
    instantaneous at midpoint  84 cm        60 cm        5 cm
    **step mean (this)**       **2.1 cm**   **2.3 cm**   **2.6 cm**
    ========================== ============ ============ ============

    The left-edge hold is first-order and blows up exactly where the maneuver lives — the thrust
    cut is one control step wide, so holding the pre-cut value for an extra 20 ms injects a large
    velocity error that never comes back. The step mean is rate-independent, which is the signature
    of having removed the discretization error rather than merely shrinking it.

    Returns:
        ``(normed_thrust, rate_cmd)`` arrays aligned with ``idx``; the final frame has no following
        step, so it carries its instantaneous value.
    """
    n = len(idx)
    thrust = np.empty(n)
    rate = np.empty((n, 3))
    for k in range(n):
        a = int(idx[k])
        b = int(idx[k + 1]) if k + 1 < n else a + 1
        b = max(b, a + 1)
        thrust[k] = fine.normed_thrust[a:b].mean()
        rate[k] = fine.rate_cmd[a:b].mean(axis=0)
    return thrust, rate


def maneuver_mask(samples: Samples, spec: ManeuverSpec) -> np.ndarray:
    """Boolean mask selecting the spec's own metric window — the maneuver, not the stagecraft."""
    lo, hi = spec.metric_window
    return (samples.phase >= lo) & (samples.phase <= hi)


def reference_metrics(samples: Samples, spec: ManeuverSpec, model: RefModel) -> dict[str, float]:
    """The headline numbers, using ``acro_flip``'s own metric names where they correspond.

    The first four names are computed identically for every maneuver, over that spec's own
    ``metric_window``, so a swing and a flip are directly comparable on "did it come back?".
    ``max_lateral_drift`` is measured against the spec's **station**, which is the origin for the
    flip and the swing but ``(−R, 0, z)`` for the orbit — measuring it against the world origin
    instead would report the orbit's radius as drift.
    """
    m = maneuver_mask(samples, spec)
    station = np.asarray(spec.station, dtype=np.float64)
    pos = samples.pos[m]
    lat = np.linalg.norm(pos[:, :2] - station[:2], axis=-1)
    alt_err = pos[:, 2] - spec.z_entry
    settle = np.flatnonzero(samples.phase == spec.settle_phase)
    settle_i = int(settle[-1]) if settle.size else int(np.flatnonzero(m)[-1])
    imu = samples.imu(model)
    out = {
        # --- the four that acro_flip computes, by the same names ---
        "max_lateral_drift": float(np.max(lat)),
        "peak_climb": float(np.max(np.clip(alt_err, 0.0, None))),
        "altitude_loss": float(np.max(np.clip(-alt_err, 0.0, None))),
        "settle_pos_error": float(np.linalg.norm(samples.pos[settle_i] - station)),
        # --- the envelope, for every maneuver ---
        "peak_normed_thrust": float(np.max(samples.normed_thrust)),
        "min_normed_thrust": float(np.min(samples.normed_thrust)),
        "peak_body_rate_rps": float(np.max(np.abs(samples.omega))),
        "peak_rate_cmd_rps": float(np.max(np.abs(samples.rate_cmd))),
        "vz_min_mps": float(np.min(samples.vel[m, 2])),
        "vz_max_mps": float(np.max(samples.vel[m, 2])),
        "peak_speed_mps": float(np.max(np.linalg.norm(samples.vel[m], axis=-1))),
        "apex_altitude_m": float(np.max(pos[:, 2])),
        "total_duration_s": float(samples.t[-1] - samples.t[0]),
        "imu_peak_g": float(np.max(np.linalg.norm(imu, axis=-1)) / model.g),
    }
    out.update(spec.extra_metrics(samples, model))
    return out


def drag_sensitivity(
    traj: Trajectory, spec: ManeuverSpec, base: RefModel, dt: float
) -> dict[str, dict[str, float]]:
    """Re-fly the **identical authored command stream** under other drag models.

    The sim's drag is the dominant modeling error and the reference bakes it in, so this is shipped
    as a column rather than a footnote. Note what does and does not change. For the **flip** the
    *commands* are fixed, so rotation is untouched (there is no aerodynamic torque in this model at
    all) while coast duration, apex and return speed move a lot. For the **swing and the orbit**
    the *path* is fixed instead and the attitude/thrust are re-derived, so the geometry is
    identical under every model and what moves is what the airframe has to do to fly it — which is
    exactly the right comparison for the orbit's axis-pointing error, whose whole claim is that it
    is a drag artifact. ``peak_bank_deg`` / ``axis_pointing_error_deg`` therefore appear in this
    column and are the numbers to read there.
    """
    out: dict[str, dict[str, float]] = {}
    for label, model in drag_sensitivity_models(base).items():
        try:
            s = traj.sample(model, dt)
        except Exception as exc:                      # a drag model can make a segment singular
            out[label] = {"error": str(exc)[:200],
                          "terminal_velocity_mps": model.terminal_velocity_mps}
            continue
        m = maneuver_mask(s, spec)
        station = np.asarray(spec.station, dtype=np.float64)
        alt = s.pos[m, 2] - spec.z_entry
        lat = np.linalg.norm(s.pos[m, :2] - station[:2], axis=-1)
        row = {
            "D": model.D_xy,
            "terminal_velocity_mps": model.terminal_velocity_mps,
            "peak_climb_m": float(np.max(np.clip(alt, 0.0, None))),
            "altitude_loss_m": float(np.max(np.clip(-alt, 0.0, None))),
            "max_lateral_drift_m": float(np.max(lat)),
            "vz_min_mps": float(np.min(s.vel[m, 2])),
            "vz_max_mps": float(np.max(s.vel[m, 2])),
            "peak_normed_thrust": float(np.max(s.normed_thrust)),
            "peak_rate_cmd_rps": float(np.max(np.abs(s.rate_cmd))),
            "end_z_error_m": float(s.pos[-1, 2] - spec.z_rest),
        }
        extra = spec.extra_metrics(s, model)
        for key in ("peak_bank_deg", "axis_pointing_error_deg", "swing_half_width_m"):
            if key in extra:
                row[key] = float(extra[key])
        out[label] = row
    return out


def build_replay(
    replay_samples: Samples,
    spec: ManeuverSpec,
    model: RefModel,
    solution: Any = None,
    *,
    dt_replay: float,
    min_thrust_normed: float = 0.0,
    label: str = "reference",
    hold_commands: tuple[np.ndarray, np.ndarray] | None = None,
) -> RunRecorder:
    """Assemble the 50 Hz replay document (the video artifact).

    ``gates`` is empty and ``scene`` carries **only** ``phase``. That is deliberate:
    ``web/studio/playback.js`` builds a 0.16 m marker sphere for any ``target``/``anchor``/``slot``
    key, which would be twice the size of the true-scale 82 mm airframe in the hero shot and has no
    opt-out on the capture page. **This applies to the orbit's anchor too** — it is an *invisible*
    axis by design, and putting a marker on it would put a beach ball in the middle of the shot.
    The station and the anchor belong in the charts, not in the video.

    ``meta.scene_info.phase_labels`` comes from the spec, which is what gives each maneuver its own
    on-screen captions with no renderer change (``web/capture/capture.js``).
    """
    meta: dict[str, Any] = {
        "config": f"reference_{spec.name}",
        "policy": spec.describe(solution),
        "task": "acro_flip",
        "obs_version": "obs-v4",
        "action_version": "act-v2",
        "substrate": "reference-generator",
        "control_hz": int(round(1.0 / dt_replay)),
        "sim_hz": int(round(1.0 / dt_replay)),
        "dt": float(dt_replay),
        "coordinate_frame": COORDINATE_FRAME,
        "state_layout": STATE_LAYOUT + "  [REFERENCE: authored, not simulated]",
        "action_layout": ACTION_LAYOUT + (
            "  [REFERENCE: the action on frame k is the IMPULSE-MATCHED zero-order hold — the mean "
            "of the continuous authored command over [t_k, t_k+dt) — because that is what a "
            "consumer actually sends and holds for the step. Sampling the instantaneous value at "
            "t_k instead drifts ~1 m over this sequence, since the thrust cut is one control step "
            "wide. The instantaneous profile is in reference.json's 1 kHz stream.]"
        ),
        "action_limits": {
            "max_thrust_normed": MAX_THRUST_NORMED,
            "hover_thrust_normed": HOVER_THRUST_NORMED,
            "max_body_rate_rp_rps": MAX_BODY_RATE_RP_RPS,
            "max_body_rate_yaw_rps": MAX_BODY_RATE_YAW_RPS,
            "min_thrust_normed": float(min_thrust_normed),
        },
        "unity_hint": UNITY_HINT,
        "imu_info": dict(IMU_INFO),
        "scene_info": {
            "command_label": f"{spec.name} reference",
            "phase_labels": list(spec.phase_labels),
            "rest_z": float(spec.z_rest),
        },
        "source": "reference-generator",
        # The spec's own knobs, plus the three windows every chart needs. Adding them here rather
        # than in each spec keeps the replay self-describing without three copies of the same
        # boilerplate — the charts read the replay, never a spec object.
        "reference": {
            **spec.reference_meta(solution),
            "phase_labels": list(spec.phase_labels),
            "metric_window": list(spec.metric_window),
            "tick_window": list(getattr(spec, "rotation_window", None) or spec.metric_window),
            "is_planar": bool(spec.is_planar),
            "z_rest_m": float(spec.z_rest),
        },
    }
    rec = RunRecorder(meta)
    rec.begin_episode(1, gates=[], drone=0)
    imu = replay_samples.imu(model)
    rpy_all = _rpy_from_quat(replay_samples.quat)
    hold_thrust, hold_rate = hold_commands if hold_commands is not None else (
        replay_samples.normed_thrust, replay_samples.rate_cmd)
    for i in range(len(replay_samples)):
        ctbr = [float(hold_thrust[i]), *[float(v) for v in hold_rate[i]]]
        rec.add_frame(
            t=float(replay_samples.t[i]),
            step=i + 1,
            pos=replay_samples.pos[i],
            quat=replay_samples.quat[i],
            rpy=rpy_all[i],
            vel=replay_samples.vel[i],
            angvel=replay_samples.omega[i],
            action=act_v2_from_diffaero(ctbr[0], tuple(ctbr[1:]),
                                        min_thrust_normed=min_thrust_normed),
            action_diffaero=ctbr,
            reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=0.0, laps=0,
            imu=imu[i],
            scene={"phase": float(replay_samples.phase[i])},
        )
    rec.end_episode({
        "steps": len(replay_samples),
        "ended": "landed",
        "sequence": "->".join(s.lower() for s in spec.phase_labels),
        "kind": label,
    })
    return rec


def _rpy_from_quat(q: np.ndarray) -> np.ndarray:
    """ZYX euler from xyzw, matching ``diffaero.utils.math.quaternion_to_euler``.

    Carried because the replay schema requires an ``rpy`` field — **not** because anything should
    compute on it. Pitch is clamped to ±90°, so a full 360° roll renders here as a 180° wobble.
    Every chart in this package derives the rotation angle from the quaternion instead.
    """
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - x * z), -1.0, 1.0))
    yaw = np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return np.stack([roll, pitch, yaw], axis=-1)


def build_reference_doc(
    fine: Samples,
    spec: ManeuverSpec,
    model: RefModel,
    solution: Any,
    checks: dict,
    *,
    metrics: dict[str, float],
    sensitivity: dict[str, dict[str, float]],
    dt_fine: float,
    derived: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Assemble ``reference.json`` — the 1 kHz stream plus everything needed to interpret it."""
    imu = fine.imu(model)
    return {
        "format": REFERENCE_FORMAT,
        "version": REFERENCE_VERSION,
        "maneuver": spec.name,
        "what_this_is": (
            "A hand-authored reference maneuver: the trajectory we WANT, not one a policy flew. "
            "Attitude, body rates and collective thrust are DERIVED — differential flatness turns "
            "an authored path into exactly one attitude/thrust/rate history, so working out the "
            "thrust is algebra rather than a job for RL. Where flatness has no solution (a flip's "
            "inversion would demand negative thrust) the COMMANDS are authored instead and the "
            "path is what physics returns, with the boundary conditions closed by a damped-Newton "
            "shoot. Nothing here was trained. replay.json.gz is the video artifact; THIS is the "
            "data artifact."
        ),
        "caveats": [
            "The sim's drag is the dominant modeling error and this reference bakes it in: "
            f"D = {model.D_xy:g} N/(m/s) on {model.mass:g} kg gives a "
            f"{model.terminal_velocity_mps:.2f} m/s terminal velocity, where a real 65 mm whoop is "
            "8-12 m/s — roughly 8x too much drag at these speeds, and linear where reality is "
            "quadratic. See drag_sensitivity for the bracket.",
            *spec.caveats(model),
        ],
        "spec": {k: (v if not isinstance(v, np.generic) else float(v))
                 for k, v in vars(spec).items()},
        "derived": {k: float(v) for k, v in (derived or {}).items()},
        "model": model.to_dict(),
        "solution": solution.to_dict() if solution is not None else {
            "stage": None,
            "stage_meaning": (
                "no boundary-value solve was needed: this maneuver is authored entirely by "
                "differential flatness and closes on its own start point analytically. That is a "
                "result, not an omission — see the package docs for why the flip cannot be."
            ),
        },
        "metrics": {k: float(v) for k, v in metrics.items()},
        "metrics_note": (
            "max_lateral_drift / peak_climb / altitude_loss / settle_pos_error carry the SAME "
            "names AcroFlipTask.metrics() computes, measured over this maneuver's own window "
            "(a level hover at z_entry through the end of the settle/recover), so they can be "
            "compared directly. max_lateral_drift is measured against spec.station, which is the "
            "origin for the flip and the swing but (-R, 0, z) for the orbit."
        ),
        "drag_sensitivity": sensitivity,
        "checks": checks,
        "stream": {
            "rate_hz": float(round(1.0 / dt_fine)),
            "n": int(len(fine)),
            "fields": {
                "t": "s", "phase": "index into phase_labels", "pos": "world m",
                "vel": "world m/s", "acc": "world m/s^2", "quat": "xyzw",
                "omega": "body rad/s (gyro)", "omega_dot": "body rad/s^2",
                "normed_thrust": "DiffAero units, 1.0 == hover",
                "rate_cmd": "body rate COMMAND rad/s (u = omega + omega_dot/K)",
                "imu": "body specific force m/s^2, +1 g on body +z at rest",
            },
            "phase_labels": list(spec.phase_labels),
            "t": fine.t.tolist(),
            "phase": fine.phase.tolist(),
            "pos": fine.pos.tolist(),
            "vel": fine.vel.tolist(),
            "acc": fine.acc.tolist(),
            "quat": fine.quat.tolist(),
            "omega": fine.omega.tolist(),
            "omega_dot": fine.omega_dot.tolist(),
            "normed_thrust": fine.normed_thrust.tolist(),
            "rate_cmd": fine.rate_cmd.tolist(),
            "imu": imu.tolist(),
        },
    }


def save_reference(doc: dict[str, Any], path: str | Path) -> Path:
    """Write ``reference.json`` (pretty for the header, compact for the stream arrays)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path
