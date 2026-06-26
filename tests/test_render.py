"""Renderer tests: pure-NumPy projection determinism + headless (Agg) plot smoke tests.

``project_points`` / ``quat_to_matrix`` / ``look_at_proj`` are pure NumPy and always run. The
plot/FPV functions need the ``viz`` extra (matplotlib, Pillow), so they ``importorskip`` — the
suite stays green without the extra installed, and actually exercises rendering when it is.
"""

from __future__ import annotations

import numpy as np
import pytest

from neural_whoop.viz.render import look_at_proj, project_points, quat_to_matrix


def _axis_view_proj(width: int, height: int):
    """A column-major (view, proj) looking from -X toward +X at (0,0,1), up=+Z."""
    return look_at_proj(
        eye=np.array([-3.0, 0.0, 1.0]),
        forward=np.array([1.0, 0.0, 0.0]),
        up=np.array([0.0, 0.0, 1.0]),
        fov_deg=60.0, width=width, height=height,
    )


def test_project_points_center_and_behind():
    w, h = 200, 100
    view, proj = _axis_view_proj(w, h)
    # A point on the camera axis (the look-at target) lands near image center.
    px, visible = project_points(view, proj, np.array([[0.0, 0.0, 1.0]]), w, h)
    assert visible[0]
    assert px[0, 0] == pytest.approx(w / 2, abs=1.0)
    assert px[0, 1] == pytest.approx(h / 2, abs=1.0)
    # A point behind the camera is not visible.
    _, vis_behind = project_points(view, proj, np.array([[-10.0, 0.0, 1.0]]), w, h)
    assert not vis_behind[0]


def test_project_points_deterministic():
    w, h = 320, 240
    view, proj = _axis_view_proj(w, h)
    pts = np.array([[0.5, 0.3, 1.2], [1.0, -0.4, 0.8], [2.0, 0.0, 1.0]])
    a, va = project_points(view, proj, pts, w, h)
    b, vb = project_points(view, proj, pts, w, h)
    assert np.array_equal(a, b)
    assert np.array_equal(va, vb)


def test_quat_to_matrix_identity_and_orthonormal():
    R = quat_to_matrix(np.array([0.0, 0.0, 0.0, 1.0]))
    assert np.allclose(R, np.eye(3))
    # A 90° yaw about world +z (xyzw): body +x -> world +y.
    q = np.array([0.0, 0.0, np.sin(np.pi / 4), np.cos(np.pi / 4)])
    R = quat_to_matrix(q)
    assert np.allclose(R @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-6)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-6)


def _synthetic_replay() -> dict:
    """A small but complete two-gate replay with one lap, for the plot smoke tests."""
    gates = [{"pos": [1.5, 0.0, 1.0], "radius": 0.4}, {"pos": [3.0, 1.0, 1.2], "radius": 0.4}]
    frames = []
    for i in range(40):
        x = 0.1 * i
        passed = i in (15, 30)
        frames.append({
            "t": i / 50.0, "step": i + 1,
            "pos": [x, 0.5 * np.sin(0.2 * i), 1.0 + 0.1 * np.cos(0.2 * i)],
            "quat": [0.0, 0.0, 0.0, 1.0], "rpy": [0.0, 0.0, 0.0],
            "vel": [4.0, 0.0, 0.0], "angvel": [0.0, 0.0, 0.0],
            "action": [0.3, 0.0, 0.0, 0.0], "action_diffaero": [2.6, 0.0, 0.0, 0.0],
            "reward": 0.1, "cum_reward": 0.1 * (i + 1),
            "gate_idx": 0 if i < 15 else 1, "dist_to_gate": 1.0,
            "laps": 1 if i >= 30 else 0, "passed": passed, "crashed": False,
        })
    return {
        "format": "neural-whoop-replay", "version": 1,
        "meta": {"config": "gate_race", "policy": "test", "dt": 0.02},
        "episodes": [{
            "index": 1, "drone": 0, "gates": gates, "dr": None, "oracle_lap": 3.4,
            "summary": {"steps": 40, "laps": 1, "best_lap": 0.6, "gates_passed": 2,
                        "num_gates": 2, "ended": "max_steps"},
            "frames": frames,
        }],
    }


def test_plot_trajectory_writes_png(tmp_path):
    pytest.importorskip("matplotlib")
    from neural_whoop.viz.render import plot_trajectory

    out = plot_trajectory(_synthetic_replay(), tmp_path / "traj.png")
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_fpv_writes_png(tmp_path):
    pytest.importorskip("PIL")
    from neural_whoop.viz.render import render_fpv

    out = render_fpv(_synthetic_replay(), tmp_path / "fpv.png", frame_idx=10)
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_fpv_keyframes(tmp_path):
    pytest.importorskip("PIL")
    from neural_whoop.viz.render import render_fpv_keyframes

    paths = render_fpv_keyframes(_synthetic_replay(), tmp_path, prefix="fpv", max_frames=4)
    assert 1 <= len(paths) <= 4
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)


def test_plot_time_trial_comparison_and_table(tmp_path):
    pytest.importorskip("matplotlib")
    from neural_whoop.viz.render import plot_time_trial_comparison

    rep = _synthetic_replay()
    out = plot_time_trial_comparison(
        [rep, rep], tmp_path / "cmp.png", labels=["a", "b"], table_path=tmp_path / "table.csv"
    )
    assert out.exists() and out.stat().st_size > 0
    table = (tmp_path / "table.csv").read_text()
    assert "policy" in table and "best_lap" in table


def test_plot_swarm_snapshot(tmp_path):
    pytest.importorskip("matplotlib")
    from neural_whoop.viz.render import plot_swarm_snapshot

    out = plot_swarm_snapshot(_synthetic_replay(), tmp_path / "swarm.png", step=10)
    assert out.exists() and out.stat().st_size > 0


def test_render_depth_is_a_documented_stub():
    from neural_whoop.viz.render import render_depth

    with pytest.raises(NotImplementedError):
        render_depth()
