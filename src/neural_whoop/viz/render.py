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
