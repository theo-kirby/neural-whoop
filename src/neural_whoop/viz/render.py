"""Replay -> Flywheel-native artifacts: trajectory plots, synthetic FPV, curves, comparisons.

This is the lazy, **viz-extra** half of the visual contract. It consumes the portable replay
documents written by :mod:`neural_whoop.viz.replay` (no simulator, no torch) and turns them
into the PNG/CSV artifacts the autonomous loop attaches to every empirical node. Heavy deps
(matplotlib, Pillow, tbparse) are imported **lazily inside each function** and matplotlib is
forced onto the headless ``Agg`` backend, so importing this module is cheap and core training
deps never grow — install with ``pip install -e '.[viz]'``.

Functions
---------
- :func:`project_points` — pure-NumPy pinhole projection (ported from the lab's ``overlay.py``;
  the lab's Three.js viewer / Unity rigs reuse the same math). Always importable.
- :func:`plot_trajectory` — top-down + side flown path(s) with gates and the gate-loop
  reference ("optimal path through gates") overlay.
- :func:`render_fpv` — analytic synthetic onboard view (numpy + PIL): gate reticles + HUD.
- :func:`plot_training_curves` — TensorBoard event file -> learning curves PNG.
- :func:`plot_time_trial_comparison` — N-policy lap-time bars + trajectory overlay + a
  leaderboard table (CSV).
- :func:`plot_swarm_snapshot` — top-down scatter of all drones at a timestep.
- :func:`render_depth` — documented **stub** for the future DiffAero Taichi depth renderer.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from neural_whoop.viz.replay import load_run

# --- gate-state palette (RGB), shared by the matplotlib plots and the PIL FPV overlay -------
_NEXT_COLOR = (255, 150, 30)      # bright orange — the gate to fly through now
_UPCOMING_COLOR = (120, 130, 150)  # faint blue-grey — gates still ahead
_PASSED_COLOR = (60, 200, 90)     # dimmed green — already cleared
_HUD_COLOR = (235, 235, 235)
_HUD_SHADOW = (0, 0, 0)
_ORACLE_COLOR = "#d62728"         # reference / oracle path
_PATH_COLOR = "#1f77b4"           # flown path


def _hex(rgb: tuple[int, int, int]) -> str:
    """0-255 RGB tuple -> '#rrggbb' (matplotlib wants 0-1 / hex, not 0-255 ints)."""
    return "#%02x%02x%02x" % rgb


_NEXT_HEX = _hex(_NEXT_COLOR)
_UPCOMING_HEX = _hex(_UPCOMING_COLOR)
_PASSED_HEX = _hex(_PASSED_COLOR)


# =============================================================================================
# Pure projection math (ported from neural-whoop-lab/viz/overlay.py — always importable)
# =============================================================================================
def project_points(
    view: list[float] | np.ndarray,
    proj: list[float] | np.ndarray,
    pts: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Project world points to pixel coords using column-major 4x4 view/proj matrices.

    Matrices are **column-major** 16-float tuples (OpenGL / PyBullet convention), so we
    reshape ``(4, 4)`` and transpose to row-major ``V`` and ``P``. For each world point
    ``[x, y, z, 1]`` the clip coord is ``P @ V @ p``; NDC is ``clip / clip.w``; pixels are
    ``px = (ndc.x*0.5 + 0.5)*W`` and ``py = (1 - (ndc.y*0.5 + 0.5))*H`` (image y points down).

    Args:
        view: View matrix (16 floats, column-major).
        proj: Projection matrix (16 floats, column-major).
        pts: World points, shape ``(N, 3)``.
        width: Frame width in pixels.
        height: Frame height in pixels.

    Returns:
        ``(px, visible)`` where ``px`` is ``(N, 2)`` float pixel coords and ``visible`` is an
        ``(N,)`` bool — False for points behind the camera (``clip.w <= 0``) or outside the
        frustum (any NDC component outside ``[-1, 1]``).
    """
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    v = np.asarray(view, dtype=np.float64).reshape(4, 4).T
    pr = np.asarray(proj, dtype=np.float64).reshape(4, 4).T
    homog = np.concatenate([pts, np.ones((pts.shape[0], 1))], axis=1)  # (N, 4)
    clip = homog @ (pr @ v).T  # (N, 4)
    w = clip[:, 3]
    in_front = w > 1e-9
    safe_w = np.where(in_front, w, 1.0)
    ndc = clip[:, :3] / safe_w[:, None]
    px = (ndc[:, 0] * 0.5 + 0.5) * width
    py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height
    pixels = np.stack([px, py], axis=1)
    inside = np.all(np.abs(ndc) <= 1.0, axis=1)
    visible = in_front & inside
    return pixels, visible


def quat_to_matrix(quat_xyzw: np.ndarray) -> np.ndarray:
    """Body->world rotation matrix ``(3, 3)`` from a real-last ``[qx, qy, qz, qw]`` quaternion.

    Matches DiffAero / the contract (xyzw). Columns are the body axes expressed in world.
    """
    q = np.asarray(quat_xyzw, dtype=np.float64).reshape(4)
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([
        [1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
        [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
        [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)],
    ])


def look_at_proj(
    eye: np.ndarray,
    forward: np.ndarray,
    up: np.ndarray,
    fov_deg: float,
    width: int,
    height: int,
    near: float = 0.05,
    far: float = 100.0,
) -> tuple[list[float], list[float]]:
    """Build column-major ``(view, proj)`` matrices for a pinhole camera (OpenGL convention).

    The output matches :func:`project_points`'s expected layout (column-major flat tuples), so
    a synthetic onboard camera reuses the exact same projection path the lab's viewer uses.

    Args:
        eye: Camera position in world, ``(3,)``.
        forward: Camera look direction in world, ``(3,)`` (need not be unit).
        up: Camera up hint in world, ``(3,)``.
        fov_deg: Vertical field of view (full angle, degrees).
        width: Frame width (px); the horizontal FOV follows from the aspect ratio.
        height: Frame height (px).
        near: Near clip plane (m).
        far: Far clip plane (m).
    """
    eye = np.asarray(eye, dtype=np.float64).reshape(3)
    f = np.asarray(forward, dtype=np.float64).reshape(3)
    f = f / (np.linalg.norm(f) + 1e-12)
    up = np.asarray(up, dtype=np.float64).reshape(3)
    s = np.cross(f, up)
    s = s / (np.linalg.norm(s) + 1e-12)
    u = np.cross(s, f)
    R = np.stack([s, u, -f])  # rows: camera basis (OpenGL: camera looks down -z)
    V = np.eye(4)
    V[:3, :3] = R
    V[:3, 3] = -R @ eye
    aspect = width / max(1, height)
    fy = 1.0 / np.tan(np.radians(fov_deg) / 2.0)
    P = np.zeros((4, 4))
    P[0, 0] = fy / aspect
    P[1, 1] = fy
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = (2 * far * near) / (near - far)
    P[3, 2] = -1.0
    return list(V.T.flatten()), list(P.T.flatten())


# =============================================================================================
# Replay helpers
# =============================================================================================
def _as_doc(replay: str | Path | dict) -> dict:
    """Accept a replay dict or a path to one; return the loaded document."""
    if isinstance(replay, dict):
        return replay
    return load_run(replay)


def _best_episode(doc: dict) -> dict:
    """Pick the most interesting recorded episode: most laps, then most gates, then longest."""
    eps = [e for e in doc.get("episodes", []) if e.get("frames")]
    if not eps:
        raise ValueError("replay has no non-empty episodes to plot")

    def key(e: dict) -> tuple:
        s = e.get("summary", {})
        return (s.get("laps", 0), s.get("gates_passed", 0), len(e["frames"]))

    return max(eps, key=key)


def _gate_loop(ep: dict) -> np.ndarray:
    """Closed-loop reference path through the gate centers: g0->g1->...->g_{n-1}->g0.

    This is the geometric "optimal path through gates" reference the speed oracle times — a
    straight-line racing skeleton the flown path is compared against.
    """
    gates = np.array([g["pos"] for g in ep.get("gates", [])], dtype=np.float64)
    if gates.shape[0] == 0:
        return gates
    return np.concatenate([gates, gates[:1]], axis=0)


def _frames_xyz(ep: dict) -> np.ndarray:
    """``(T, 3)`` world positions of an episode's frames."""
    return np.array([f["pos"] for f in ep["frames"]], dtype=np.float64)


# =============================================================================================
# Plots (matplotlib, Agg)
# =============================================================================================
def _mpl():
    """Import matplotlib forced onto the headless Agg backend; return the pyplot module."""
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    return plt


def plot_trajectory(
    replay: str | Path | dict,
    out_path: str | Path,
    episode: dict | None = None,
    title: str | None = None,
) -> Path:
    """Render a top-down + side view of a hero's flown path with gates and the oracle line.

    Args:
        replay: A replay document or a path to one.
        out_path: PNG output path.
        episode: A specific episode to plot (default: the best recorded one).
        title: Optional figure title.

    Returns:
        The output path.
    """
    plt = _mpl()
    doc = _as_doc(replay)
    ep = episode if episode is not None else _best_episode(doc)
    meta = doc.get("meta", {})
    xyz = _frames_xyz(ep)
    loop = _gate_loop(ep)
    gates = np.array([g["pos"] for g in ep.get("gates", [])], dtype=np.float64).reshape(-1, 3)
    radii = np.array([g["radius"] for g in ep.get("gates", [])], dtype=np.float64).reshape(-1)

    fig, (ax_top, ax_side) = plt.subplots(1, 2, figsize=(13, 6))

    def _draw(ax, ix, iy, xlabel, ylabel, with_circles):
        if loop.shape[0]:
            ax.plot(loop[:, ix], loop[:, iy], "--", color=_ORACLE_COLOR, lw=1.6,
                    label="gate-loop reference", zorder=2)
        ax.plot(xyz[:, ix], xyz[:, iy], "-", color=_PATH_COLOR, lw=1.8, label="flown path", zorder=3)
        ax.scatter([xyz[0, ix]], [xyz[0, iy]], c="k", s=40, marker="o", label="start", zorder=4)
        for k, g in enumerate(gates):
            if with_circles:
                ax.add_patch(plt.Circle((g[ix], g[iy]), float(radii[k]), color=_UPCOMING_HEX,
                                        fill=False, lw=1.2, alpha=0.8))
            ax.annotate(str(k), (g[ix], g[iy]), color="#444", fontsize=8,
                        ha="center", va="center")
        # Lap markers: frames where a lap counter increments.
        laps = np.array([f.get("laps", 0) for f in ep["frames"]])
        bumps = np.where(np.diff(laps, prepend=laps[:1]) > 0)[0]
        if bumps.size:
            ax.scatter(xyz[bumps, ix], xyz[bumps, iy], facecolors="none", edgecolors=_PASSED_HEX,
                       s=90, lw=1.6, label="lap", zorder=5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, alpha=0.25)

    _draw(ax_top, 0, 1, "x (m)", "y (m)", with_circles=True)
    ax_top.set_title("top-down (x-y)")
    ax_top.legend(loc="best", fontsize=8)
    _draw(ax_side, 0, 2, "x (m)", "z (m)", with_circles=False)
    ax_side.set_title("side (x-z)")

    s = ep.get("summary", {})
    sub = (f"{meta.get('config', 'run')} · {meta.get('policy', '')} · "
           f"laps={s.get('laps', 0)} best_lap={_fmt(s.get('best_lap'))}s "
           f"oracle={_fmt(ep.get('oracle_lap'))}s ended={s.get('ended', '?')}")
    fig.suptitle(title or sub, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save(fig, out_path)


def render_fpv(
    replay: str | Path | dict,
    out_path: str | Path,
    frame_idx: int | None = None,
    episode: dict | None = None,
    width: int = 480,
    height: int = 360,
    fov_deg: float = 90.0,
) -> Path:
    """Render one analytic synthetic onboard (FPV) view: gate reticles + a telemetry HUD.

    Builds a pinhole camera from the drone pose (``pos`` + quaternion -> body axes: +x
    forward is the camera axis, +z up) and projects each gate center with
    :func:`project_points`, drawing a circle reticle whose screen radius comes from projecting
    a point offset by the gate radius along the camera-up axis. No pixels are rendered from the
    sim — this is a data-driven overlay on a synthetic sky/ground gradient.

    Args:
        replay: A replay document or a path to one.
        out_path: PNG output path.
        frame_idx: Frame to render (default: the frame nearest the last gate pass / midpoint).
        episode: Episode to use (default: the best recorded one).
        width: Frame width (px).
        height: Frame height (px).
        fov_deg: Vertical field of view (deg).

    Returns:
        The output path.
    """
    from PIL import Image

    doc = _as_doc(replay)
    ep = episode if episode is not None else _best_episode(doc)
    frames = ep["frames"]
    if frame_idx is None:
        frame_idx = _default_fpv_frame(ep)
    frame_idx = int(max(0, min(len(frames) - 1, frame_idx)))
    f = frames[frame_idx]

    R = quat_to_matrix(np.array(f["quat"]))
    eye = np.array(f["pos"], dtype=np.float64)
    forward = R @ np.array([1.0, 0.0, 0.0])   # body +x (camera axis)
    up = R @ np.array([0.0, 0.0, 1.0])        # body +z
    view, proj = look_at_proj(eye, forward, up, fov_deg, width, height)

    frame = _sky_ground(width, height, R)

    gates = ep.get("gates", [])
    next_gate = int(f.get("gate_idx", 0))
    cam_up = np.asarray(view, dtype=np.float64).reshape(4, 4).T[1, :3]
    gates_px: list[tuple[np.ndarray, float, bool, str]] = []
    for k, g in enumerate(gates):
        center = np.array(g["pos"], dtype=np.float64)
        edge = center + cam_up * float(g["radius"])
        px, vis = project_points(view, proj, np.stack([center, edge]), width, height)
        radius_px = float(np.linalg.norm(px[1] - px[0]))
        state = "passed" if k < next_gate else ("next" if k == next_gate else "upcoming")
        gates_px.append((px[0], radius_px, bool(vis[0]), state))
    frame = draw_targets(frame, gates_px)

    speed = float(np.linalg.norm(f.get("vel", [0, 0, 0])))
    stats = {
        "step": f.get("step", frame_idx + 1),
        "gate_idx": next_gate,
        "num_gates": len(gates),
        "speed": speed,
        "reward": f.get("cum_reward", 0.0),
        "laps": f.get("laps", 0),
    }
    frame = draw_hud(frame, stats, lines=[
        f"t {f.get('t', 0.0):.2f}s  step {stats['step']}",
        f"gate {next_gate}/{len(gates)}  lap {stats['laps']}",
        f"speed {speed:.2f} m/s",
        f"cum_reward {stats['reward']:.1f}",
    ])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame, "RGB").save(out_path)
    return out_path


def render_fpv_keyframes(
    replay: str | Path | dict,
    out_dir: str | Path,
    prefix: str = "fpv",
    episode: dict | None = None,
    max_frames: int = 6,
    gif: bool = False,
    **fpv_kwargs,
) -> list[Path]:
    """Render a handful of FPV keyframes (start, each gate pass, last) and optionally a GIF.

    Args:
        replay: Replay doc or path.
        out_dir: Directory for the ``{prefix}_NN.png`` files (and ``{prefix}.gif``).
        prefix: Filename prefix.
        episode: Episode to use (default: best).
        max_frames: Cap on the number of keyframes.
        gif: Also stitch a GIF (needs the ``imageio`` part of the viz extra).
        **fpv_kwargs: Forwarded to :func:`render_fpv` (width/height/fov_deg).

    Returns:
        The list of written PNG paths.
    """
    doc = _as_doc(replay)
    ep = episode if episode is not None else _best_episode(doc)
    frames = ep["frames"]
    idxs = [0]
    idxs += [i for i, f in enumerate(frames) if f.get("passed")]
    idxs.append(len(frames) - 1)
    # De-dup, keep order, cap.
    seen: set[int] = set()
    keys: list[int] = []
    for i in idxs:
        i = int(max(0, min(len(frames) - 1, i)))
        if i not in seen:
            seen.add(i)
            keys.append(i)
    if len(keys) > max_frames:
        sel = np.linspace(0, len(keys) - 1, max_frames).round().astype(int)
        keys = [keys[j] for j in sorted(set(sel.tolist()))]

    out_dir = Path(out_dir)
    paths: list[Path] = []
    for n, i in enumerate(keys):
        p = out_dir / f"{prefix}_{n:02d}.png"
        render_fpv(doc, p, frame_idx=i, episode=ep, **fpv_kwargs)
        paths.append(p)

    if gif and paths:
        try:
            import imageio.v2 as imageio
            imgs = [imageio.imread(p) for p in paths]
            imageio.mimsave(out_dir / f"{prefix}.gif", imgs, duration=0.6)
        except Exception:
            pass  # imageio optional; PNGs are the durable artifact
    return paths


def plot_training_curves(run_dir: str | Path, out_path: str | Path) -> Path | None:
    """Read a TensorBoard event file under ``run_dir`` and plot the key learning curves.

    Plots ``charts/episodic_return``, ``metrics/best_lap_time``,
    ``metrics/lap_completion_rate``, and ``losses/approx_kl`` (whichever are present). Returns
    ``None`` if no event file / no usable tags are found (so a pack build degrades gracefully).

    Args:
        run_dir: Run directory containing ``events.out.tfevents.*``.
        out_path: PNG output path.
    """
    run_dir = Path(run_dir)
    if not any(run_dir.glob("events.out.tfevents.*")):
        return None
    try:
        from tbparse import SummaryReader
    except ImportError:
        return None

    df = SummaryReader(str(run_dir), pivot=False).scalars
    if df is None or len(df) == 0:
        return None

    wanted = [
        ("charts/episodic_return", "episodic return"),
        ("metrics/best_lap_time", "best lap time (s)"),
        ("metrics/lap_completion_rate", "lap completion rate"),
        ("losses/approx_kl", "approx KL"),
    ]
    present = [(t, lbl) for t, lbl in wanted if (df["tag"] == t).any()]
    if not present:
        return None

    plt = _mpl()
    n = len(present)
    ncol = 2 if n > 1 else 1
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(6.5 * ncol, 3.4 * nrow), squeeze=False)
    for ax, (tag, lbl) in zip(axes.flat, present):
        sub = df[df["tag"] == tag].sort_values("step")
        ax.plot(sub["step"], sub["value"], color=_PATH_COLOR, lw=1.5)
        ax.set_title(lbl, fontsize=10)
        ax.set_xlabel("env step")
        ax.grid(True, alpha=0.25)
    for ax in axes.flat[n:]:
        ax.axis("off")
    fig.suptitle(f"training curves · {run_dir.name}", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save(fig, out_path)


def _flight_phase_bands(ax, metrics: dict) -> None:
    """Shade the airborne + stable-hover phases and mark the first vz_est rail on a time axis.

    Shared by every panel of :func:`plot_hover_telemetry` so the phase context reads across the
    stack. No-op for keys that are missing/NaN (a flight that never lifted degrades to bare traces).
    """
    air = metrics.get("phases", {}).get("airborne", {})
    hov = metrics.get("stable_hover", {})
    t0, t1 = air.get("t_start"), air.get("t_end")
    if t0 is not None and t1 is not None and np.isfinite(t0) and np.isfinite(t1):
        ax.axvspan(t0, t1, color="#9aa4b2", alpha=0.08, lw=0)  # airborne
    h0, h1 = hov.get("t_start"), hov.get("t_end")
    if h0 is not None and h1 is not None and np.isfinite(h0) and np.isfinite(h1):
        ax.axvspan(h0, h1, color=_PASSED_HEX, alpha=0.14, lw=0)  # stable hover (green)
    rail_t = metrics.get("vertical", {}).get("vz_first_rail_t")
    if rail_t is not None and np.isfinite(rail_t):
        ax.axvline(rail_t, color=_ORACLE_COLOR, lw=1.1, ls="--", alpha=0.8)


def plot_hover_telemetry(log: Any, metrics: dict, out_path: str | Path) -> Path:
    """Stacked scalar-telemetry panels for a real hover flight (the flight-report headline plot).

    Panels (shared time axis): roll/pitch, body rates (p,q,r), ``us_thr`` vs the policy's ``a_thr``
    (twin axis — the thrust-divergence view), ``vz_est`` with the ±clamp rail marked, and
    ``obs_age``. The airborne and longest stable-hover windows are shaded (green = stable hover) and
    the first ``vz_est`` rail is drawn as a red dashed line — so the ceiling-hit signature (throttle
    climbing while ``a_thr`` is flat, right as ``vz_est`` rails) is legible at a glance.

    Args:
        log: A :class:`neural_whoop.analysis.flight_log.FlightLog` (duck-typed: needs ``t``, ``roll``,
            ``pitch``, ``us_thr``, ``a_thr``, ``vz_est``, ``obs_age_ms`` and ``.data``/``.col``).
        metrics: The :func:`neural_whoop.analysis.flight_log.flight_metrics` dict (phase bands + rail).
        out_path: PNG output path.
    """
    plt = _mpl()
    t = np.asarray(log.t, dtype=np.float64)
    fig, axes = plt.subplots(5, 1, figsize=(11, 11), sharex=True)

    # 1) attitude (deg)
    ax = axes[0]
    ax.plot(t, np.degrees(log.roll), color=_PATH_COLOR, lw=1.1, label="roll")
    ax.plot(t, np.degrees(log.pitch), color=_NEXT_HEX, lw=1.1, label="pitch")
    ax.set_ylabel("attitude (deg)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    # 2) body rates (deg/s) — the gyro signal
    ax = axes[1]
    for name, color in (("p", _PATH_COLOR), ("q", _NEXT_HEX), ("r", _PASSED_HEX)):
        ax.plot(t, np.degrees(log.col(name)), color=color, lw=0.9, label=name)
    ax.set_ylabel("body rate (deg/s)")
    ax.legend(loc="upper left", fontsize=8, ncol=3)

    # 3) commanded throttle (us) vs the policy's thrust action (twin axis) — the divergence view
    ax = axes[2]
    ax.plot(t, log.us_thr, color=_PATH_COLOR, lw=1.2, label="us_thr (µs)")
    ax.set_ylabel("us_thr (µs)", color=_PATH_COLOR)
    ax.tick_params(axis="y", labelcolor=_PATH_COLOR)
    axr = ax.twinx()
    axr.plot(t, log.a_thr, color=_ORACLE_COLOR, lw=1.2, label="a_thr")
    axr.set_ylabel("a_thr [-1,1]", color=_ORACLE_COLOR)
    axr.tick_params(axis="y", labelcolor=_ORACLE_COLOR)
    div = metrics.get("vertical", {}).get("thrust_divergence", {})
    if div.get("detected"):
        ax.set_title(
            f"thrust divergence: us_thr +{div.get('us_thr_rise', float('nan')):.0f} µs while "
            f"a_thr IQR {div.get('a_thr_iqr', float('nan')):.3f} (policy steady — pilot damper drove it)",
            fontsize=9, color=_ORACLE_COLOR,
        )

    # 4) vz_est with the ±clamp rail
    ax = axes[3]
    ax.plot(t, log.vz_est, color=_PATH_COLOR, lw=1.1)
    clamp = metrics.get("vertical", {}).get("vz_clamp")
    if clamp:
        ax.axhline(-clamp, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.9)
        ax.axhline(clamp, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.9)
        ax.text(t[0] if len(t) else 0.0, -clamp, f" vz rail −{clamp:g} m/s",
                color=_ORACLE_COLOR, fontsize=8, va="bottom")
    ax.set_ylabel("vz_est (m/s)")

    # 5) link latency
    ax = axes[4]
    ax.plot(t, log.obs_age_ms, color=_UPCOMING_HEX, lw=0.8)
    ax.axhline(40.0, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.8)
    ax.set_ylabel("obs_age (ms)")
    ax.set_xlabel("flight time (s)")

    for ax in axes:
        ax.grid(True, alpha=0.2)
        _flight_phase_bands(ax, metrics)

    hov = metrics.get("stable_hover", {})
    fig.suptitle(
        f"hover telemetry · {Path(log.path).name} · stable-hover "
        f"{_fmt(hov.get('duration_s'))} s @ {_fmt(hov.get('median_tilt_deg'))}° median tilt",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return _save(fig, out_path)


# =============================================================================================
# Reference-maneuver charts (neural_whoop.reference — the hand-authored "one we want")
# =============================================================================================
#: Muted band colours per phase code, indexed like ``meta.scene_info.phase_labels``. The powered
#: beats are warm, the coast is cold — so the shape of the maneuver reads off the background
#: before you look at a single trace.
_PHASE_BAND_COLORS = {
    "CLIMB": "#9aa4b2", "HOVER": "#c9d1d9", "POP": "#f0a35e", "ROLL-IN": "#e8734a",
    "COAST": "#6fa8dc", "CATCH": "#e8734a", "RECOVER": "#8fd19e", "LAND": "#9aa4b2",
    # the swing / orbit beats
    "SWING": "#e8734a", "SETTLE": "#8fd19e",
    "WIND-UP": "#f0a35e", "ORBIT": "#e8734a", "WIND-DOWN": "#f0a35e",
}


def _replay_phases(doc: dict, ep: dict) -> tuple[np.ndarray, list[str]]:
    """``(per-frame phase code, labels)`` from a replay's ``scene.phase`` channel."""
    labels = list((doc.get("meta", {}).get("scene_info", {}) or {}).get("phase_labels", []))
    codes = np.array(
        [int(round((f.get("scene") or {}).get("phase", -1))) for f in ep["frames"]], dtype=int
    )
    return codes, labels


def _replay_phase_bands(ax, doc: dict, ep: dict, *, annotate: bool = False) -> None:
    """Shade a time axis by ``scene.phase`` run-lengths — the replay-fed ``_flight_phase_bands``.

    Where the flight version reads phase windows out of a metrics dict, this one derives them from
    the per-frame channel the scripted sequences already carry, so it works on any replay that
    sets ``scene.phase`` (this generator and ``hero_takeoff_flip_land.py``). No-op otherwise.
    """
    codes, labels = _replay_phases(doc, ep)
    if not labels or np.all(codes < 0):
        return
    t = np.array([f["t"] for f in ep["frames"]], dtype=np.float64)
    edges = np.flatnonzero(np.diff(codes)) + 1
    starts = np.concatenate([[0], edges])
    stops = np.concatenate([edges, [len(codes)]])
    for a, b in zip(starts, stops):
        c = codes[a]
        if c < 0 or c >= len(labels):
            continue
        name = labels[c]
        ax.axvspan(t[a], t[min(b, len(t) - 1)], color=_PHASE_BAND_COLORS.get(name, "#9aa4b2"),
                   alpha=0.16, lw=0)
        if annotate and (t[min(b, len(t) - 1)] - t[a]) > 0.12:
            ax.annotate(name, xy=(0.5 * (t[a] + t[min(b, len(t) - 1)]), 1.0),
                        xycoords=("data", "axes fraction"), xytext=(0, 2),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=7, color="#444")


def _replay_rotation_turns(ep: dict, axis: int) -> np.ndarray:
    """Unwrapped rotation about body ``axis``, in **turns**, from the quaternion.

    Charts must never compute on ``rpy``: ``quaternion_to_euler`` (``utils/math.py:190``) is ZYX
    with pitch clamped to ±90°, so a full 360° roll renders there as a 180° wobble. The replay
    still *carries* ``rpy`` because the schema requires it; everything downstream uses this.
    Unwrap the HALF angle then double — doubling first makes the flip a 4π jump, which
    ``np.unwrap`` reads as no jump at all and silently flattens.
    """
    q = np.array([f["quat"] for f in ep["frames"]], dtype=np.float64)
    return 2.0 * np.unwrap(np.arctan2(q[:, axis], q[:, 3])) / (2.0 * np.pi)


def _replay_heading_turns(ep: dict) -> np.ndarray:
    """Unwrapped azimuth of body **+x**, in turns — how far the *nose* wound.

    The right rotation readout for a maneuver that yaws rather than rolling. The orbit sits at 70°
    of bank for most of its run, where ZYX yaw is largely an artifact of the ±90° pitch clamp and
    the single-axis half-angle formula measures a quantity that does not exist.
    """
    q = np.array([f["quat"] for f in ep["frames"]], dtype=np.float64)
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    xb_x = 1 - 2 * (y * y + z * z)
    xb_y = 2 * (x * y + z * w)
    return np.unwrap(np.arctan2(xb_y, xb_x)) / (2.0 * np.pi)


def _replay_body_z(ep: dict) -> np.ndarray:
    """Body **+z** (the thrust axis) in world, ``(N, 3)``, straight from the quaternion."""
    q = np.array([f["quat"] for f in ep["frames"]], dtype=np.float64)
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)], axis=-1)


def _reference_rotation(ep: dict, ref: dict) -> tuple[np.ndarray, float, str]:
    """``(turns, target_turns, label)`` — the rotation readout **this** maneuver actually has.

    Driven by ``meta.reference.rotation``, which the spec writes, so one chart captions a roll
    flip, a swing that returns to level, and a three-revolution orbit without knowing about any of
    them. Falls back to the pre-generalization behaviour (axis from ``reference.axis``) so the
    already-shipped 1.2 m flip artifacts still render.
    """
    rot = ref.get("rotation") or {}
    if rot.get("kind") == "heading":
        return (_replay_heading_turns(ep), float(rot.get("target_turns") or 0.0),
                str(rot.get("label", "heading (turns)")))
    axis = int(rot.get("axis", 1 if ref.get("axis") == "pitch" else 0))
    target = rot.get("target_turns")
    if target is None:
        target = float(ref.get("n_rotations", 1.0) or 1.0)
    return (_replay_rotation_turns(ep, axis), float(target),
            str(rot.get("label", "rotation (turns)")))


def _reference_title(ref: dict) -> str:
    """One line naming the maneuver and the two or three knobs that actually set its shape."""
    kind = ref.get("maneuver") or ("flip" if "omega_peak_rps" in ref else "reference")
    variant = ref.get("variant", "")
    if kind == "flip":
        return (f"{ref.get('axis', '?')}-flip Ω={ref.get('omega_peak_rps', float('nan')):g} rad/s"
                f" · {variant}")
    if kind == "swing":
        return (f"roll U-swing L={ref.get('arc_length_m', float('nan')):g} m "
                f"Θ={ref.get('amplitude_deg', float('nan')):g}° "
                f"{ref.get('freq_scale', float('nan')):g}× resonance, "
                f"{ref.get('n_swings', float('nan')):g} swings · {variant}")
    if kind == "orbit":
        return (f"banked orbit R={ref.get('radius_m', float('nan')):g} m "
                f"Ω={ref.get('omega_orbit_rps', float('nan')):g} rad/s, "
                f"{ref.get('n_revs', float('nan')):g} revs, nose {ref.get('nose', '?')} · {variant}")
    return f"{kind} · {variant}"


def _reference_window(codes: np.ndarray, ref: dict, key: str, n: int) -> np.ndarray:
    """Frame indices inside a phase-code window the spec declared, with a whole-flight fallback."""
    win = ref.get(key)
    if win and len(win) == 2:
        idx = np.flatnonzero((codes >= int(win[0])) & (codes <= int(win[1])))
        if idx.size:
            return idx
    return np.arange(n)


def plot_reference_telemetry(
    replay: str | Path | dict,
    checks: dict,
    out_path: str | Path,
    *,
    metrics: dict | None = None,
    residual_series: dict | None = None,
) -> Path:
    """Six stacked shared-x panels: everything the reference asserts about itself, as traces.

    Modeled on :func:`plot_hover_telemetry`, but fed by a replay rather than a flight log. The
    panels are ordered so the maneuver reads top-down as a story — where it went, how fast, how
    far round, what the motors were asked for, what the IMU would have felt, and whether any of it
    is actually true:

    1. altitude + lateral offset, with the entry-altitude rail
    2. vertical / lateral velocity
    3. unwrapped rotation (turns) + body rate, with the 12 rad/s rail
    4. normed thrust, with the 4.0 ceiling and (when set) the throttle-floor rail
    5. **IMU body specific force** — three components + magnitude, with the +1 g rail. This is the
       panel that surprises people. The coast reads as a **V**, not a null and not a constant: the
       magnitude starts near 1 g (the drone is still moving fast, and this simulator's oversized
       drag is the only force acting), collapses to ~0.09 g at the apex where the velocity
       genuinely passes through zero, then climbs back to ~0.7 g on the way down. Anyone expecting
       a flat free-fall null across the whole coast will think the generator is broken.
    6. per-frame verification residuals on a log axis, with the masked C²-break frames marked

    Args:
        replay: The reference replay document or a path to one.
        checks: The ``verify.json`` dict from
            :func:`neural_whoop.reference.verify.verify_reference`.
        out_path: PNG output path.
        metrics: Optional headline metrics for the figure title.
        residual_series: Optional per-frame residuals from
            :func:`neural_whoop.reference.verify.dynamics_residual_series` (at the replay rate).

    Returns:
        The output path.
    """
    plt = _mpl()
    doc = _as_doc(replay)
    ep = _best_episode(doc)
    meta = doc.get("meta", {})
    ref = meta.get("reference", {})
    axis = int((ref.get("rotation") or {}).get("axis", 1 if ref.get("axis") == "pitch" else 0))
    lat_axis = int(ref.get("lateral_axis", 0 if axis == 1 else 1))
    z_entry = float(ref.get("z_entry_m", 0.0))
    station = np.asarray(ref.get("station") or [0.0, 0.0, z_entry], dtype=np.float64)

    fr = ep["frames"]
    t = np.array([f["t"] for f in fr], dtype=np.float64)
    pos = np.array([f["pos"] for f in fr], dtype=np.float64)
    vel = np.array([f["vel"] for f in fr], dtype=np.float64)
    angvel = np.array([f["angvel"] for f in fr], dtype=np.float64)
    act = np.array([f["action_diffaero"] for f in fr], dtype=np.float64)
    has_imu = "imu" in fr[0]
    imu = np.array([f.get("imu", [np.nan] * 3) for f in fr], dtype=np.float64)
    turns, n_turns, rot_label = _reference_rotation(ep, ref)
    lat_name = "xy"[lat_axis]
    # Lateral offset FROM THE STATION, not from the world origin: the orbit's station is
    # (-R, 0, z), so plotting raw x there would read the orbit's own radius as an excursion.
    lat_offset = pos[:, lat_axis] - station[lat_axis]

    fig, axes = plt.subplots(6, 1, figsize=(12, 15), sharex=True)

    # 1) altitude + lateral offset
    ax = axes[0]
    ax.plot(t, pos[:, 2], color=_PATH_COLOR, lw=1.4, label="altitude z")
    ax.plot(t, lat_offset, color=_NEXT_HEX, lw=1.2, label=f"lateral {lat_name} (from station)")
    if z_entry:
        ax.axhline(z_entry, color=_ORACLE_COLOR, lw=1.0, ls="--", alpha=0.85)
        ax.text(t[0], z_entry, f" entry {z_entry:g} m", color=_ORACLE_COLOR, fontsize=8,
                va="bottom")
    ax.set_ylabel("position (m)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    # 2) velocities
    ax = axes[1]
    ax.plot(t, vel[:, 2], color=_PATH_COLOR, lw=1.2, label="vz")
    ax.plot(t, vel[:, lat_axis], color=_NEXT_HEX, lw=1.2, label=f"v{lat_name}")
    ax.axhline(0.0, color="#888", lw=0.7)
    ax.set_ylabel("velocity (m/s)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    # 3) rotation + body rate. Which rotation is the spec's business (see _reference_rotation):
    #    a roll flip counts turns about body x, the orbit counts how far the nose wound.
    ax = axes[2]
    ax.plot(t, turns, color=_PATH_COLOR, lw=1.8, label=rot_label)
    ax.axhline(n_turns, color=_PATH_COLOR, lw=1.0, ls="--", alpha=0.6)
    ax.text(t[-1], n_turns, f"target {n_turns:g} turn ", color=_PATH_COLOR, fontsize=8,
            ha="right", va="bottom")
    ax.set_ylabel(rot_label, color=_PATH_COLOR)
    ax.tick_params(axis="y", labelcolor=_PATH_COLOR)
    lo, hi = float(np.min(turns)), max(float(np.max(turns)), n_turns)
    pad = max(0.08, 0.12 * (hi - lo))
    ax.set_ylim(lo - pad, hi + pad)
    axr = ax.twinx()
    rate_lim = float(meta.get("action_limits", {}).get("max_body_rate_rp_rps", 12.0))
    axr.plot(t, angvel[:, axis], color=_NEXT_HEX, lw=1.2, label="body rate ω")
    axr.plot(t, act[:, 1 + axis], color="#6b7280", lw=1.0, ls=":",
             label="rate command u = ω + ω̇/K")
    if not ref.get("is_planar", True):
        # A 3D maneuver has meaningful rate on every axis; showing only the lean axis would hide
        # the yaw that is the whole reason it breaks psi == 0.
        axr.plot(t, angvel[:, 2], color="#7a3b8f", lw=1.0, alpha=0.8, label="body rate ω_z")
    for sign in (1, -1):
        axr.axhline(sign * rate_lim, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.75)
    axr.text(t[0], rate_lim, f" act-v2 rate limit ±{rate_lim:g}", color=_ORACLE_COLOR,
             fontsize=8, va="top")
    axr.set_ylim(-rate_lim * 1.14, rate_lim * 1.14)
    axr.set_ylabel("body rate (rad/s)", color=_NEXT_HEX)
    axr.tick_params(axis="y", labelcolor=_NEXT_HEX)
    axr.legend(loc="lower right", fontsize=7, ncol=2)

    # 4) collective, with the ceiling and (if any) the throttle floor
    ax = axes[3]
    lim = meta.get("action_limits", {})
    ceil = float(lim.get("max_thrust_normed", 4.0))
    floor = float(lim.get("min_thrust_normed", 0.0) or 0.0)
    ax.plot(t, act[:, 0], color=_PATH_COLOR, lw=1.3)
    ax.axhline(ceil, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.85)
    ax.text(t[0], ceil, f" ceiling {ceil:g}", color=_ORACLE_COLOR, fontsize=8, va="top")
    ax.axhline(1.0, color="#888", lw=0.8, ls="--")
    ax.text(t[0], 1.0, " hover", color="#666", fontsize=8, va="bottom")
    if floor > 0:
        ax.axhline(floor, color=_PASSED_HEX, lw=1.2, ls=":")
        ax.text(t[0], floor, f" deploy floor {floor:g}", color=_PASSED_HEX, fontsize=8,
                va="bottom")
    ax.set_ylabel("normed thrust")

    # 5) IMU specific force
    ax = axes[4]
    if has_imu and np.isfinite(imu).any():
        g = 9.81
        for k, (name, color) in enumerate(
            (("ax", _PATH_COLOR), ("ay", _NEXT_HEX), ("az", _PASSED_HEX))
        ):
            ax.plot(t, imu[:, k], color=color, lw=1.0, label=name)
        ax.plot(t, np.linalg.norm(imu, axis=-1), color="#333", lw=1.3, ls="--", label="|f|")
        ax.axhline(g, color=_ORACLE_COLOR, lw=1.0, ls=":", alpha=0.85)
        ax.text(t[0], g, " +1 g (rest)", color=_ORACLE_COLOR, fontsize=8, va="bottom")
        ax.axhline(0.0, color="#888", lw=0.7)
        ax.legend(loc="upper left", fontsize=7, ncol=4)
    else:
        ax.text(0.5, 0.5, "no imu channel in this replay", transform=ax.transAxes,
                ha="center", va="center", color="#888", fontsize=9)
    ax.set_ylabel("IMU specific force\n(body, m/s²)")

    # 6) verification residuals, per frame. Time series rather than summary bars: the aggregate
    #    says how big, this says WHERE — and "the spikes land on the two intentional acceleration
    #    steps and nowhere else" is the actual claim being made.
    ax = axes[5]
    rf = checks.get("dynamics_residual_fine", {})
    rr = checks.get("dynamics_residual_replay", {})
    conv = checks.get("second_order_convergence", {})
    if residual_series:
        floor = 1e-16
        for name, color in (("pos", _PATH_COLOR), ("vel", _NEXT_HEX), ("quat", _PASSED_HEX)):
            r = np.maximum(np.asarray(residual_series[name], dtype=np.float64), floor)
            ax.plot(residual_series["t"], r, color=color, lw=0.9, label=f"|d{name}/dt − model|")
        for i in rr.get("masked_indices", []):
            if 0 <= i < len(t):
                ax.axvline(t[i], color=_ORACLE_COLOR, lw=0.8, ls=":", alpha=0.6)
        ax.set_yscale("log")
        ax.legend(loc="upper left", fontsize=7, ncol=3)
    else:
        ax.text(0.5, 0.5, "no residual series supplied", transform=ax.transAxes,
                ha="center", va="center", color="#888", fontsize=9)
    ax.set_ylabel("dynamics residual\n(SI, log)")
    # How many seams actually STEP is a per-maneuver fact — the flip has two, the swing and the
    # orbit have none — so the caption counts them rather than asserting "the two C² breaks".
    n_steps = sum(1 for s in checks.get("seams", []) if s.get("is_c2_break"))
    masked = len(rr.get("masked_indices", []))
    ax.set_title(
        f"residual at {conv.get('dt_replay_s', 0.02)*1e3:.0f} ms (shown) vs "
        f"{conv.get('dt_fine_s', 0.001)*1e3:.0f} ms stream: vel rms "
        f"{rr.get('vel_rms', float('nan')):.2e} vs {rf.get('vel_rms', float('nan')):.2e} = "
        f"{conv.get('observed_vel_rms_ratio', float('nan')):.0f}x, expected ~"
        f"{conv.get('expected_ratio', float('nan')):.0f}x for a second-order difference.\n"
        f"Dotted red = the {masked} frames masked at every segment seam" +
        (f"; {n_steps} of those seams are intentional C² breaks (the motor cut and the catch)."
         if n_steps else
         "; this maneuver has NO intentional C² breaks — nothing steps the motor command anywhere,"
         " so the mask is precautionary rather than load-bearing."),
        fontsize=7.5, color="#555", loc="left",
    )

    for ax in axes:
        ax.grid(True, alpha=0.2)
        _replay_phase_bands(ax, doc, ep, annotate=(ax is axes[0]))
    axes[5].set_xlabel("time (s)")

    m = metrics or {}
    head = (f"drift {m.get('max_lateral_drift', float('nan')):.3f} m · "
            f"peak climb {m.get('peak_climb', float('nan')):+.3f} m · "
            f"alt loss {m.get('altitude_loss', float('nan')):.3f} m · "
            f"settle {m.get('settle_pos_error', float('nan')):.3f} m") if m else ""
    loop = checks.get("rate_loop_stability") or {}
    if loop and not loop.get("vendored_loop_stable", True):
        # The maneuver is non-planar past 90°, i.e. it is one the LEGACY rate loop could not track.
        # Post-fix (2026-08-01) that is history, not a blocker — but artifacts generated before the
        # fix carry the same flag and must not be read as if they were flown on the patched fork.
        if loop.get("substrate_rate_loop_fixed"):
            head += (f"\n attitude reaches {loop['max_attitude_from_identity_deg']:.0f}° from "
                     f"identity off ω's fixed axis — untrackable by DiffAero's rate loop before "
                     f"the 2026-08-01 controller fix; flyable on the patched fork")
        else:
            head += (f"\n⚠ attitude reaches {loop['max_attitude_from_identity_deg']:.0f}° from "
                     f"identity — DiffAero's vendored rate loop (controller.py:93) is DIVERGENT "
                     f"past 90°, so this maneuver is a valid reference but is NOT flyable here")
    fig.suptitle(
        f"REFERENCE maneuver — hand-authored, not a rollout\n{_reference_title(ref)}\n{head}",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    return _save(fig, out_path)


def plot_reference_envelope(
    replay: str | Path | dict, out_path: str | Path, *, plane: str | None = None,
    spec: Any = None, every: int = 2,
) -> Path:
    """The "maneuver strip": the maneuver's own plane, with a body-z tick every few frames.

    This is the single most legible picture of a maneuver and costs almost nothing — the tick
    direction *is* the attitude, so the flip's rotation, the swing's lean into travel and the
    orbit's bank are all visible at a glance in one static image, which no time-series panel
    manages.

    Which plane is the *maneuver's* business, not the chart's:

    - ``"yz"`` / ``"xz"`` — a side elevation, for the planar maneuvers. The flip and the swing both
      live in one vertical plane, so this is the whole truth about where they went.
    - ``"xy"`` — a **top-down** view, for the orbit. Its whole shape is horizontal; an elevation
      would render a 1 m circle as a flat line and the ticks would all point the same way.

    On the top-down view the invisible anchor axis is drawn as a cross with the authored circle
    around it, so "the top face points at the axis" and its measured 24° error are things you can
    *see* rather than only read in ``verify.json``. The anchor is deliberately **not** in the
    video — ``web/studio/playback.js`` would draw a 0.16 m marker sphere, twice the size of the
    true-scale airframe, right in the middle of the shot.

    Args:
        replay: The reference replay document or a path to one.
        out_path: PNG output path.
        plane: ``"yz"`` / ``"xz"`` / ``"xy"``; ``None`` reads ``meta.reference.plane`` and falls
            back to the flip's convention so pre-generalization artifacts still render.
        spec: Unused; accepted so old call sites keep working.
        every: Draw an attitude tick every N frames.
    """
    plt = _mpl()
    doc = _as_doc(replay)
    ep = _best_episode(doc)
    meta = doc.get("meta", {})
    ref = meta.get("reference", {})
    plane = plane or ref.get("plane") or ("xz" if ref.get("axis") == "pitch" else "yz")
    if plane not in ("yz", "xz", "xy"):
        raise ValueError(f"plane must be 'yz', 'xz' or 'xy', got {plane!r}")
    h_axis = {"yz": 1, "xz": 0, "xy": 0}[plane]
    v_axis = {"yz": 2, "xz": 2, "xy": 1}[plane]
    h_name, v_name = "xyz"[h_axis], "xyz"[v_axis]
    top_down = plane == "xy"

    fr = ep["frames"]
    pos = np.array([f["pos"] for f in fr], dtype=np.float64)
    zb = _replay_body_z(ep)
    codes, labels = _replay_phases(doc, ep)

    # Zoom to the maneuver, keep the whole flight as faint context. The climb and the landing are
    # stagecraft and, on an equal-aspect axis, a 1.2 m vertical line squashes the maneuver into a
    # corner. The window comes from the spec (meta.reference.metric_window).
    win = _reference_window(codes, ref, "metric_window", len(pos))
    tw = _reference_window(codes, ref, "tick_window", len(pos))

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.plot(pos[:, h_axis], pos[:, v_axis], color="#dfe3ea", lw=1.0, zorder=1)
    for c in np.unique(codes):
        if c < 0 or c >= len(labels):
            continue
        m = codes == c
        ax.plot(pos[m, h_axis], pos[m, v_axis], lw=2.2, zorder=2,
                color=_PHASE_BAND_COLORS.get(labels[c], "#9aa4b2"), label=labels[c])

    # Attitude ticks only through the maneuver proper: outside it the airframe is level by
    # construction, so a hundred identical up-arrows would be noise on the busiest part of the plot.
    tick = 0.05
    sel = (tw if tw.size else win)[:: max(1, every)]
    ax.quiver(pos[sel, h_axis], pos[sel, v_axis], zb[sel, h_axis], zb[sel, v_axis],
              color="#33383f", width=0.0024, scale=1.0 / tick, scale_units="xy",
              angles="xy", zorder=3, alpha=0.8)

    anchor = ref.get("anchor")
    if top_down and anchor:
        a_h, a_v = float(anchor[h_axis]), float(anchor[v_axis])
        ax.plot([a_h], [a_v], marker="+", ms=16, mew=2.0, color=_ORACLE_COLOR, zorder=4,
                label="anchor axis (invisible)")
        r = ref.get("radius_m")
        if r:
            th = np.linspace(0.0, 2.0 * np.pi, 361)
            ax.plot(a_h + float(r) * np.cos(th), a_v + float(r) * np.sin(th),
                    color=_ORACLE_COLOR, lw=1.0, ls="--", alpha=0.55, zorder=1)
    elif not top_down:
        z_entry = float(ref.get("z_entry_m", 0.0))
        if z_entry:
            ax.axhline(z_entry, color=_ORACLE_COLOR, lw=1.0, ls="--", alpha=0.7)
            ax.text(0.995, z_entry, "entry / station ", color=_ORACLE_COLOR, fontsize=8,
                    ha="right", va="bottom", transform=ax.get_yaxis_transform())
        rest_z = float((meta.get("scene_info", {}) or {}).get("rest_z", 0.0))
        ax.axhline(rest_z, color="#555", lw=1.4)

    pad = 0.12
    x0, x1 = pos[win, h_axis].min(), pos[win, h_axis].max()
    y0, y1 = pos[win, v_axis].min(), pos[win, v_axis].max()
    ax.set_xlim(x0 - pad - 0.08, x1 + pad + 0.08)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_xlabel(f"{h_name} (m)" + ("   — top-down" if top_down else "   — the maneuver plane"))
    ax.set_ylabel(f"{v_name} (m)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    view = ("TOP-DOWN. Ticks are body +z projected onto the floor, so their angle to the anchor\n"
            "IS the axis-pointing error" if top_down else
            "Ticks are body +z (the thrust axis)")
    ax.set_title(
        f"reference envelope · {_reference_title(ref)}\n"
        f"{view}, every {every} frames · zoomed to the maneuver, climb/land faint",
        fontsize=9.5,
    )
    del spec
    fig.tight_layout()
    return _save(fig, out_path)


def plot_link_histogram(log: Any, out_path: str | Path, metrics: dict | None = None) -> Path:
    """Histogram of the flight's ``obs_age`` (uplink freshness) with the 40 ms cliff + p99 marked.

    The 40 ms line is the staleness cliff the policy trained against; p99 is the fat tail that the
    pilot's single-poll-per-tick coupling produces. Consumes the raw column, so it works without the
    metrics dict; when ``metrics`` is given the p99/median lines come from it (else recomputed here).

    Args:
        log: A :class:`neural_whoop.analysis.flight_log.FlightLog` (needs ``obs_age_ms``, ``path``).
        out_path: PNG output path.
        metrics: Optional :func:`flight_metrics` dict for the marker lines.
    """
    plt = _mpl()
    age = np.asarray(log.obs_age_ms, dtype=np.float64)
    age = age[np.isfinite(age)]
    link = (metrics or {}).get("link", {})
    p50 = link.get("median_ms") if link else (float(np.median(age)) if age.size else float("nan"))
    p99 = link.get("p99_ms") if link else (float(np.percentile(age, 99)) if age.size else float("nan"))
    frac40 = link.get("frac_over_40ms")
    if frac40 is None:
        frac40 = float((age > 40).mean()) if age.size else float("nan")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if age.size:
        ax.hist(age, bins=40, color=_PATH_COLOR, alpha=0.8)
    ax.axvline(40.0, color=_ORACLE_COLOR, lw=1.4, ls="--",
               label=f"40 ms cliff ({frac40 * 100:.0f}% past)")
    if p50 is not None and np.isfinite(p50):
        ax.axvline(p50, color=_PASSED_HEX, lw=1.2, ls=":", label=f"median {p50:.0f} ms")
    if p99 is not None and np.isfinite(p99):
        ax.axvline(p99, color="#7a3b8f", lw=1.2, ls=":", label=f"p99 {p99:.0f} ms")
    ax.set_xlabel("obs_age (ms)")
    ax.set_ylabel("frames")
    ax.set_title(f"uplink freshness · {Path(log.path).name}", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return _save(fig, out_path)


def plot_time_trial_comparison(
    replays: list[str | Path | dict],
    out_path: str | Path,
    labels: list[str] | None = None,
    table_path: str | Path | None = None,
) -> Path:
    """Overlay N policies: a lap-time bar chart + their hero trajectories (top-down).

    Also writes a leaderboard table (CSV) suitable for a Flywheel ``table`` artifact when
    ``table_path`` is given.

    Args:
        replays: Replay docs or paths (one per policy).
        out_path: PNG output path.
        labels: Per-policy labels (default: each replay's ``meta.config``).
        table_path: Optional CSV path for the leaderboard.

    Returns:
        The PNG output path.
    """
    plt = _mpl()
    docs = [_as_doc(r) for r in replays]
    eps = [_best_episode(d) for d in docs]
    if labels is None:
        labels = [d.get("meta", {}).get("config", f"policy{i}") for i, d in enumerate(docs)]

    rows = []
    for d, ep, lbl in zip(docs, eps, labels):
        s = ep.get("summary", {})
        rows.append({
            "policy": lbl,
            "best_lap": s.get("best_lap"),
            "oracle_lap": ep.get("oracle_lap"),
            "laps": s.get("laps", 0),
            "gates_passed": s.get("gates_passed", 0),
            "ended": s.get("ended", "?"),
        })

    fig, (ax_bar, ax_traj) = plt.subplots(1, 2, figsize=(13, 6))

    # Lap-time bars (best lap; oracle as a reference marker). Missing laps -> 0 bar.
    xs = np.arange(len(rows))
    best = [r["best_lap"] if r["best_lap"] is not None else 0.0 for r in rows]
    ax_bar.bar(xs, best, color=_PATH_COLOR, alpha=0.85, label="best lap")
    for i, r in enumerate(rows):
        if r["oracle_lap"]:
            ax_bar.hlines(r["oracle_lap"], i - 0.4, i + 0.4, color=_ORACLE_COLOR, lw=2)
    ax_bar.set_xticks(xs)
    ax_bar.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax_bar.set_ylabel("lap time (s)")
    ax_bar.set_title("best lap time (— = oracle)")
    ax_bar.grid(True, axis="y", alpha=0.25)

    # Trajectory overlay (top-down). Each policy's hero path; gate loop of the first.
    cmap = plt.get_cmap("tab10")
    loop = _gate_loop(eps[0])
    if loop.shape[0]:
        ax_traj.plot(loop[:, 0], loop[:, 1], "--", color="#888", lw=1.2, label="gate loop (ref)")
    for i, (ep, lbl) in enumerate(zip(eps, labels)):
        xyz = _frames_xyz(ep)
        ax_traj.plot(xyz[:, 0], xyz[:, 1], "-", color=cmap(i % 10), lw=1.6, label=lbl)
    ax_traj.set_xlabel("x (m)")
    ax_traj.set_ylabel("y (m)")
    ax_traj.set_aspect("equal", adjustable="datalim")
    ax_traj.set_title("hero trajectories (top-down)")
    ax_traj.legend(loc="best", fontsize=8)
    ax_traj.grid(True, alpha=0.25)

    fig.suptitle("time-trial comparison", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    if table_path is not None:
        write_leaderboard(rows, table_path)
    return _save(fig, out_path)


def write_leaderboard(rows: list[dict[str, Any]], table_path: str | Path) -> Path:
    """Write a leaderboard CSV (Flywheel ``table`` artifact) sorted by best lap (ascending)."""
    table_path = Path(table_path)
    table_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["policy", "best_lap", "oracle_lap", "laps", "gates_passed", "ended"]
    ordered = sorted(
        rows, key=lambda r: (r["best_lap"] is None, r["best_lap"] if r["best_lap"] is not None else 0.0)
    )
    with open(table_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r.get(k) for k in fields})
    return table_path


def plot_swarm_snapshot(
    replay: str | Path | dict,
    out_path: str | Path,
    t: float | None = None,
    step: int | None = None,
) -> Path:
    """Top-down scatter of every recorded drone at a single timestep.

    Works trivially at ``n_agents=1`` (one dot per hero); built for future swarm tasks where
    many drones share a course. Selects each episode's frame nearest ``t`` (or index ``step``).

    Args:
        replay: Replay doc or path.
        out_path: PNG output path.
        t: Sim time (s) to snapshot (default: midpoint of the longest episode).
        step: Frame index to snapshot (overrides ``t`` when given).
    """
    plt = _mpl()
    doc = _as_doc(replay)
    eps = [e for e in doc.get("episodes", []) if e.get("frames")]
    if not eps:
        raise ValueError("replay has no non-empty episodes to plot")

    if step is None and t is None:
        longest = max(eps, key=lambda e: len(e["frames"]))
        t = float(longest["frames"][len(longest["frames"]) // 2].get("t", 0.0))

    fig, ax = plt.subplots(figsize=(7, 7))
    loop = _gate_loop(eps[0])
    if loop.shape[0]:
        ax.plot(loop[:, 0], loop[:, 1], "--", color="#888", lw=1.0, label="gate loop")
        g = np.array([gg["pos"] for gg in eps[0]["gates"]])
        ax.scatter(g[:, 0], g[:, 1], c=_UPCOMING_HEX, marker="s", s=40, label="gates")

    xs, ys = [], []
    for e in eps:
        frames = e["frames"]
        if step is not None:
            i = int(max(0, min(len(frames) - 1, step)))
        else:
            times = np.array([fr.get("t", 0.0) for fr in frames])
            i = int(np.argmin(np.abs(times - t)))
        p = frames[i]["pos"]
        xs.append(p[0])
        ys.append(p[1])
    ax.scatter(xs, ys, c=_PATH_COLOR, s=60, edgecolors="k", zorder=5, label="drones")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(f"swarm snapshot · {len(eps)} drones · "
                 f"{'step ' + str(step) if step is not None else 't=' + f'{t:.2f}s'}")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return _save(fig, out_path)


def render_depth(*args, **kwargs):
    """**Stub / seam** for the future DiffAero Taichi depth (and RGB) renderer — not built now.

    The honest camera-only path (rendering real depth from the DiffAero scene on Blackwell)
    is deferred (locked decision #1/#2: the tiled-camera path is Blackwell-broken today). When
    it lands, this becomes the bridge from a replay (or a live env) to per-frame depth/RGB
    tensors that feed the camera tasks' obs and a true FPV video — replacing the analytic
    :func:`render_fpv` overlay with rendered pixels. Until then it raises so callers don't
    silently get a fake render.
    """
    raise NotImplementedError(
        "render_depth is a documented seam for the future DiffAero Taichi renderer "
        "(deferred — Blackwell-broken camera path). Use render_fpv for the analytic FPV view."
    )


# =============================================================================================
# PIL drawing primitives (ported from neural-whoop-lab/viz/overlay.py)
# =============================================================================================
def draw_targets(
    frame: np.ndarray,
    gates_px: list[tuple[np.ndarray, float, bool, str]],
) -> np.ndarray:
    """Draw gate-target circle reticles on a frame.

    Args:
        frame: ``(H, W, 3)`` uint8 RGB frame.
        gates_px: per-gate ``(center_px, radius_px, visible, state)`` where ``state`` is one of
            ``"next"``, ``"upcoming"``, ``"passed"``; invisible gates are skipped.

    Returns:
        A new ``(H, W, 3)`` uint8 frame with the overlays drawn.
    """
    from PIL import Image, ImageDraw

    img = Image.fromarray(np.ascontiguousarray(frame[:, :, :3].astype(np.uint8)), "RGB")
    draw = ImageDraw.Draw(img)
    color_for = {"next": _NEXT_COLOR, "upcoming": _UPCOMING_COLOR, "passed": _PASSED_COLOR}
    for center_px, radius_px, visible, state in gates_px:
        if not bool(visible):
            continue
        color = color_for.get(state, _UPCOMING_COLOR)
        width = 4 if state == "next" else 2
        cx, cy = float(center_px[0]), float(center_px[1])
        rad = max(2.0, float(radius_px))
        draw.ellipse([(cx - rad, cy - rad), (cx + rad, cy + rad)], outline=color, width=width)
        r = 6 if state == "next" else 4
        draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)
        draw.line([(cx, cy - r), (cx, cy + r)], fill=color, width=width)
        if state == "next":
            draw.text((cx + rad + 6, cy - 16), "NEXT", fill=color)
    return np.asarray(img, dtype=np.uint8)


def draw_hud(frame: np.ndarray, stats: dict, lines: list[str] | None = None) -> np.ndarray:
    """Draw a top-left HUD text block on a frame.

    Args:
        frame: ``(H, W, 3)`` uint8 RGB frame.
        stats: keys ``gate_idx``, ``num_gates``, ``speed``, ``reward``, ``step`` (defaults
            tolerated). Ignored when ``lines`` is given.
        lines: optional explicit HUD lines (overrides the default block).

    Returns:
        A new ``(H, W, 3)`` uint8 frame with the HUD drawn.
    """
    from PIL import Image, ImageDraw

    img = Image.fromarray(np.ascontiguousarray(frame[:, :, :3].astype(np.uint8)), "RGB")
    draw = ImageDraw.Draw(img)
    if lines is None:
        lines = [
            f"step {stats.get('step', 0)}",
            f"gate {stats.get('gate_idx', 0)}/{stats.get('num_gates', 0)}",
            f"speed {stats.get('speed', 0.0):.2f} m/s",
            f"reward {stats.get('reward', 0.0):.1f}",
        ]
    x, y, dy = 10, 8, 14
    for i, line in enumerate(lines):
        ly = y + i * dy
        draw.text((x + 1, ly + 1), line, fill=_HUD_SHADOW)  # drop shadow for legibility
        draw.text((x, ly), line, fill=_HUD_COLOR)
    return np.asarray(img, dtype=np.uint8)


# =============================================================================================
# Internal helpers
# =============================================================================================
def _sky_ground(width: int, height: int, R: np.ndarray) -> np.ndarray:
    """A cheap synthetic backdrop: sky->ground vertical gradient shifted by the drone's tilt.

    The horizon offset follows the camera's roll/pitch (read off the body->world matrix) so
    the analytic FPV reads as an onboard view rather than a flat plate. Purely cosmetic.
    """
    sky = np.array([135, 180, 225], dtype=np.float64)
    ground = np.array([70, 95, 70], dtype=np.float64)
    # Pitch of the camera axis (body +x) gives a horizon shift in [-0.25, 0.25] of the frame.
    fwd_z = float(np.clip((R @ np.array([1.0, 0.0, 0.0]))[2], -1.0, 1.0))
    horizon = int(np.clip(height * (0.5 + 0.25 * fwd_z), 1, height - 1))
    img = np.zeros((height, width, 3), dtype=np.uint8)
    grad_sky = np.linspace(0.7, 1.0, horizon)[:, None]
    img[:horizon] = (sky[None, None, :] * grad_sky[:, None]).astype(np.uint8)
    grad_g = np.linspace(1.0, 0.7, height - horizon)[:, None]
    img[horizon:] = (ground[None, None, :] * grad_g[:, None]).astype(np.uint8)
    return img


def _default_fpv_frame(ep: dict) -> int:
    """Pick a representative FPV frame: the last gate pass, else the episode midpoint."""
    passes = [i for i, f in enumerate(ep["frames"]) if f.get("passed")]
    if passes:
        return passes[-1]
    return len(ep["frames"]) // 2


def _fmt(v: Any) -> str:
    """Format an optional float for a title ('—' when missing/non-finite)."""
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if not np.isfinite(x) else f"{x:.2f}"


def _save(fig, out_path: str | Path) -> Path:
    """Save and close a matplotlib figure; return the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return out_path
