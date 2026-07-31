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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from neural_whoop.reference import flatness as fl
from neural_whoop.reference.imu import IMU_INFO
from neural_whoop.reference.limits import (
    HOVER_THRUST_NORMED,
    MAX_BODY_RATE_RP_RPS,
    MAX_BODY_RATE_YAW_RPS,
    MAX_THRUST_NORMED,
    act_v2_from_diffaero,
)
from neural_whoop.reference.maneuvers import PHASE, PHASE_LABELS, FlipSolution, FlipSpec
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
REFERENCE_VERSION = 1

#: The phases that constitute "the maneuver" for metric purposes. ``acro_flip`` scores an episode
#: that begins at a level hover at ``z0`` and ends after the recover, which is exactly this window
#: — the climb and the landing are stagecraft, not part of what the policy is graded on.
MANEUVER_PHASES = (PHASE["POP"], PHASE["RECOVER"])


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


def maneuver_mask(samples: Samples) -> np.ndarray:
    """Boolean mask selecting POP..RECOVER — the window the metrics are computed over."""
    lo, hi = MANEUVER_PHASES
    return (samples.phase >= lo) & (samples.phase <= hi)


def reference_metrics(samples: Samples, spec: FlipSpec, model: RefModel) -> dict[str, float]:
    """The headline numbers, using ``acro_flip``'s own metric names where they correspond."""
    m = maneuver_mask(samples)
    station = np.array([0.0, 0.0, spec.z_entry])
    pos = samples.pos[m]
    lat = np.linalg.norm(pos[:, :2] - station[:2], axis=-1)
    alt_err = pos[:, 2] - spec.z_entry
    # settle: where the RECOVER phase ends, i.e. the last frame before LAND.
    rec = np.flatnonzero(samples.phase == PHASE["RECOVER"])
    settle_i = int(rec[-1]) if rec.size else int(np.flatnonzero(m)[-1])
    phi = fl.rotation_angle_about(samples.quat, spec.axis_idx)
    flip = np.flatnonzero(
        (samples.phase >= PHASE["POP"]) & (samples.phase <= PHASE["CATCH"])
    )
    imu = samples.imu(model)
    coast = samples.phase == PHASE["COAST"]
    return {
        # --- the four that acro_flip computes, by the same names ---
        "max_lateral_drift": float(np.max(lat)),
        "peak_climb": float(np.max(np.clip(alt_err, 0.0, None))),
        "altitude_loss": float(np.max(np.clip(-alt_err, 0.0, None))),
        "settle_pos_error": float(np.linalg.norm(samples.pos[settle_i] - station)),
        # --- the maneuver's own shape ---
        "flip_duration_s": float(samples.t[flip[-1]] - samples.t[flip[0]]),
        "rotation_turns": float(phi[-1] / (2.0 * np.pi)),
        "peak_normed_thrust": float(np.max(samples.normed_thrust)),
        "peak_body_rate_rps": float(np.max(np.abs(samples.omega))),
        "peak_rate_cmd_rps": float(np.max(np.abs(samples.rate_cmd))),
        "vz_min_mps": float(np.min(samples.vel[m, 2])),
        "vz_max_mps": float(np.max(samples.vel[m, 2])),
        "apex_altitude_m": float(np.max(pos[:, 2])),
        "total_duration_s": float(samples.t[-1] - samples.t[0]),
        # --- the accelerometer, because the coast is the surprising part ---
        "imu_coast_min_g": float(np.min(np.linalg.norm(imu[coast], axis=-1)) / model.g),
        "imu_coast_max_g": float(np.max(np.linalg.norm(imu[coast], axis=-1)) / model.g),
        "imu_peak_g": float(np.max(np.linalg.norm(imu, axis=-1)) / model.g),
    }


def drag_sensitivity(
    traj: Trajectory, spec: FlipSpec, base: RefModel, dt: float
) -> dict[str, dict[str, float]]:
    """Re-fly the **identical authored command stream** under other drag models.

    The sim's drag is the dominant modeling error and the reference bakes it in, so this is shipped
    as a column rather than a footnote. Note what does and does not change: the *commands* are
    fixed, so rotation is untouched (there is no aerodynamic torque in this model at all) while
    coast duration, apex and return speed move a lot. The flatness-authored segments are re-derived
    under each model, so their thrust changes too — that is the honest comparison, since a path is
    only a path once you say what airframe flies it.
    """
    out: dict[str, dict[str, float]] = {}
    for label, model in drag_sensitivity_models(base).items():
        try:
            s = traj.sample(model, dt)
        except Exception as exc:                      # a drag model can make a segment singular
            out[label] = {"error": str(exc)[:200],
                          "terminal_velocity_mps": model.terminal_velocity_mps}
            continue
        m = maneuver_mask(s)
        alt = s.pos[m, 2] - spec.z_entry
        lat = np.linalg.norm(s.pos[m, :2], axis=-1)
        out[label] = {
            "D": model.D_xy,
            "terminal_velocity_mps": model.terminal_velocity_mps,
            "peak_climb_m": float(np.max(np.clip(alt, 0.0, None))),
            "altitude_loss_m": float(np.max(np.clip(-alt, 0.0, None))),
            "max_lateral_drift_m": float(np.max(lat)),
            "vz_min_mps": float(np.min(s.vel[m, 2])),
            "vz_max_mps": float(np.max(s.vel[m, 2])),
            "end_z_error_m": float(s.pos[-1, 2] - spec.z_rest),
        }
    return out


def build_replay(
    replay_samples: Samples,
    spec: FlipSpec,
    model: RefModel,
    solution: FlipSolution,
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
    opt-out on the capture page. The station point belongs in the charts, not in the video.
    """
    variant = ("motors-off" if spec.coast_thrust <= 0.0
               else f"deployable (coast {spec.coast_thrust:g})")
    meta: dict[str, Any] = {
        "config": f"reference_flip_{spec.axis}",
        "policy": (
            f"HAND-AUTHORED REFERENCE — not a policy rollout. {spec.axis}-flip, "
            f"Ω={spec.omega_peak:g} rad/s, {variant}; attitude/thrust/rates derived by "
            f"differential flatness, flip closed by a damped-Newton shoot (stage {solution.stage})."
        ),
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
            "command_label": f"{spec.axis}-flip reference",
            "phase_labels": list(PHASE_LABELS),
            "rest_z": float(spec.z_rest),
        },
        "source": "reference-generator",
        "reference": {
            "axis": spec.axis, "omega_peak_rps": spec.omega_peak,
            "coast_thrust": spec.coast_thrust, "variant": variant,
            "z_entry_m": spec.z_entry, "stage": solution.stage,
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
        "sequence": "climb->hover->pop->rollin->coast->catch->recover->land",
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
    spec: FlipSpec,
    model: RefModel,
    solution: FlipSolution,
    checks: dict,
    *,
    metrics: dict[str, float],
    sensitivity: dict[str, dict[str, float]],
    dt_fine: float,
) -> dict[str, Any]:
    """Assemble ``reference.json`` — the 1 kHz stream plus everything needed to interpret it."""
    imu = fine.imu(model)
    return {
        "format": REFERENCE_FORMAT,
        "version": REFERENCE_VERSION,
        "what_this_is": (
            "A hand-authored reference maneuver: the trajectory we WANT, not one a policy flew. "
            "Attitude, body rates and collective thrust are DERIVED (differential flatness for the "
            "powered path segments, forward integration of authored commands through the flip), "
            "and the flip's boundary conditions are closed by a damped-Newton shoot. Nothing here "
            "was trained. replay.json.gz is the video artifact; THIS is the data artifact."
        ),
        "caveats": [
            "The sim's drag is the dominant modeling error and this reference bakes it in: "
            f"D = {model.D_xy:g} N/(m/s) on {model.mass:g} kg gives a "
            f"{model.terminal_velocity_mps:.2f} m/s terminal velocity, where a real 65 mm whoop is "
            "8-12 m/s — roughly 8x too much drag at the flip's speeds, and linear where reality is "
            "quadratic. Coast duration, apex height, return speed and the entire coast IMU trace "
            "are artifacts of THIS simulator. See drag_sensitivity for the bracket.",
            "Body rate is exactly constant through the coast because DiffAero applies drag only to "
            "linear velocity and both gyroscopic terms vanish on a symmetric-inertia axis with "
            "w_z = 0. A real whoop would shed 5-15% of its roll rate to blade flapping over a "
            "0.6 s coast. That is NOT modeled here.",
            "The coast IMU is a V, not a flat free-fall null: drag scales with speed, which is "
            "large at both ends of a ballistic arc and zero at the apex. See metrics."
            "imu_coast_min_g / imu_coast_max_g for the measured spread. The body-z component goes "
            "strongly negative at coast entry because the drone is climbing fast along its own "
            "+z and drag pushes back along -z — that is what the accelerometer reads, not a sign "
            "error.",
            "psi == 0 is load-bearing in three places (RateController frame bug is a no-op, the "
            "coast rate stays exactly constant, the heading construction stays non-degenerate). "
            "A yaw sweep breaks all three and only the first fails loudly.",
            "Control allocation: the catch itself is comfortably feasible here (see "
            "checks.allocation.min_margin_torqued) because the rate brake is authored as a "
            "smoothstep rather than a step command, so the torque it asks for is modest. The "
            "binding problem is elsewhere and is structural: through the motors-off coast the "
            "margin is exactly 0 — zero thrust demanding zero torque — which means the airframe "
            "has NO rate authority for that whole stretch and could not correct a disturbance if "
            "it had one. That is the AIRMODE flip-stall failure of docs/SIM2REAL.md in miniature. "
            "If this reference is used as an RL target or a scoring reference, use the "
            "--deployable variant, whose 0.25 floor keeps authority alive throughout.",
        ],
        "spec": {k: (v if not isinstance(v, np.generic) else float(v))
                 for k, v in vars(spec).items()},
        "model": model.to_dict(),
        "solution": solution.to_dict(),
        "metrics": {k: float(v) for k, v in metrics.items()},
        "metrics_note": (
            "max_lateral_drift / peak_climb / altitude_loss / settle_pos_error carry the SAME "
            "names AcroFlipTask.metrics() computes, measured over the same window (a level hover "
            "at z_entry through the end of the recover), so they can be compared directly."
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
            "phase_labels": list(PHASE_LABELS),
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
