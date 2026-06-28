"""Tests for the pure Studio course validator + authored-course persistence (no torch/sim).

Mirrors ``neural-whoop-lab``'s validator tests, adapted to the plain ``[{pos, radius}]`` gate-list
API and the ``_web`` save round-trip the editor relies on.
"""

from __future__ import annotations

from neural_whoop.course import ArenaSpec
from neural_whoop.studio import courses as courses_mod
from neural_whoop.studio.course_validate import validate_gates


def _codes(report, level=None):
    return {i["code"] for i in report["issues"] if level is None or i["level"] == level}


def test_no_gates_is_error():
    report = validate_gates([])
    assert not report["ok"]
    assert _codes(report) == {"no_gates"}


def test_non_positive_radius_is_error():
    report = validate_gates([{"pos": [2.0, 0.0, 1.0], "radius": 0.0}])
    assert not report["ok"]
    assert any(i["code"] == "non_positive_radius" and i["gate_index"] == 0
               for i in report["issues"])


def test_gate_outside_arena_is_error():
    report = validate_gates([{"pos": [20.0, 0.0, 1.0], "radius": 0.35}])
    assert not report["ok"]
    assert "gate_outside_arena" in _codes(report, "error")


def test_gate_height_out_of_band_is_error():
    report = validate_gates([{"pos": [2.0, 0.0, 0.1], "radius": 0.35}])
    assert not report["ok"]
    assert "gate_height_out_of_band" in _codes(report, "error")


def test_spacing_is_warning_and_keeps_ok():
    # Hops well below step_min -> spacing warning, but warnings don't flip ok.
    report = validate_gates([
        {"pos": [2.0, 0.0, 1.0], "radius": 0.35},
        {"pos": [2.2, 0.0, 1.0], "radius": 0.35},
        {"pos": [2.2, 0.4, 1.0], "radius": 0.35},
    ])
    assert report["ok"]
    assert "spacing_out_of_range" in _codes(report, "warning")
    assert "sharp_turn" not in _codes(report)


def test_arena_bounds_widen_with_preset():
    # A gate at 7 m is outside tight (r=4.5) but inside the spread preset (r=8.0).
    from neural_whoop.course import ARENA_PRESETS

    gate = [{"pos": [7.0, 0.0, 1.0], "radius": 0.35}]
    assert not validate_gates(gate, ArenaSpec())["ok"]
    assert validate_gates(gate, ARENA_PRESETS["spread"])["ok"]


def test_save_course_roundtrip_under_web(tmp_path):
    cdir = tmp_path / "courses"
    gates = [{"pos": [2.0, 0.0, 1.0], "radius": 0.4},
             {"pos": [3.6, 0.6, 1.2], "radius": 0.35}]
    res = courses_mod.save_course(cdir, "My Test Course", gates)
    assert res["num_gates"] == 2
    saved = cdir / "_web" / "my-test-course.yaml"
    assert saved.is_file()
    # Listed as a 'web' course, resolvable by stem, flyable as tensors.
    listed = courses_mod.list_courses(cdir)
    assert any(c["name"] == "my-test-course" and c["kind"] == "web" for c in listed)
    pos, rad, label = courses_mod.resolve_course("my-test-course", cdir, device="cpu")
    assert pos.shape == (2, 3) and rad.shape == (2,)
    loaded = courses_mod.load_course_named(cdir, "my-test-course")
    assert loaded["name"] == "My Test Course" and len(loaded["gates"]) == 2


def test_save_course_rejects_unflyable(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        courses_mod.save_course(tmp_path / "courses", "bad", [{"pos": [99.0, 0.0, 1.0], "radius": 0.0}])
    assert not (tmp_path / "courses" / "_web").exists() or \
        not list((tmp_path / "courses" / "_web").glob("*.yaml"))


def test_course_routes_validate_save_get(tmp_path):
    from fastapi.testclient import TestClient

    from neural_whoop.studio.server import create_app

    courses_dir = tmp_path / "repo" / "assets" / "courses"
    courses_dir.mkdir(parents=True)
    app = create_app(repo_root=tmp_path / "repo", runs_dir=tmp_path / "repo" / "runs",
                     courses_dir=courses_dir, device="cpu")
    client = TestClient(app)

    good = {"name": "web-loop", "gates": [
        {"pos": [2.0, 0.0, 1.0], "radius": 0.4}, {"pos": [3.8, 0.6, 1.2], "radius": 0.35}]}

    # validate: a 7 m gate is invalid against tight, valid against spread.
    far = {"name": "far", "gates": [{"pos": [7.0, 0.0, 1.0], "radius": 0.35}]}
    assert client.post("/api/courses/validate", json=far).json()["ok"] is False
    assert client.post("/api/courses/validate?preset=spread", json=far).json()["ok"] is True

    # save: persists under _web, appears in the listing, and is loadable for editing.
    res = client.post("/api/courses", json=good)
    assert res.status_code == 200 and res.json()["num_gates"] == 2
    assert (courses_dir / "_web" / "web-loop.yaml").is_file()
    assert any(c["name"] == "web-loop" and c["kind"] == "web"
               for c in client.get("/api/courses").json()["courses"])
    got = client.get("/api/courses/web-loop").json()
    assert got["name"] == "web-loop" and len(got["gates"]) == 2

    # save rejects an unflyable course with 422.
    assert client.post("/api/courses", json={"name": "x", "gates": [
        {"pos": [0, 0, 1], "radius": -1}]}).status_code == 422


def test_export_missing_run_is_404(tmp_path):
    from fastapi.testclient import TestClient

    from neural_whoop.studio.server import create_app

    app = create_app(repo_root=tmp_path / "repo", runs_dir=tmp_path / "repo" / "runs",
                     courses_dir=tmp_path / "repo" / "courses", device="cpu")
    client = TestClient(app)
    assert client.post("/api/export", json={"run_path": "studio/nope.json.gz"}).status_code == 404
