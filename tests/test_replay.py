"""Round-trip + schema tests for the pure replay exporter (no simulator / torch required).

Mirrors neural-whoop-lab's ``test_replay.py``: proves the document is valid JSON with no
leaked numpy/torch types, the self-describing ``format``/``version``/``meta`` are present and
complete, and gzip is transparent. Pure stdlib + numpy, so it runs without the viz extra.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from neural_whoop.viz.replay import (
    ACTION_LAYOUT,
    COORDINATE_FRAME,
    REPLAY_FORMAT,
    REPLAY_VERSION,
    STATE_LAYOUT,
    RunRecorder,
    load_run,
)

_META = {
    "config": "gate_race",
    "policy": "TinyPolicy (5,380 params) · ckpt_final.pt",
    "task": "gate_race",
    "obs_version": "obs-v4",
    "action_version": "act-v2",
    "substrate": "diffaero",
    "control_hz": 50,
    "sim_hz": 100,
    "dt": 0.02,
    "coordinate_frame": COORDINATE_FRAME,
    "state_layout": STATE_LAYOUT,
    "action_layout": ACTION_LAYOUT,
    "action_limits": {
        "max_thrust_normed": 4.0, "hover_thrust_normed": 1.0,
        "max_body_rate_rp_rps": 12.0, "max_body_rate_yaw_rps": 6.0,
    },
    "unity_hint": "see docs",
}


def _make_recorder() -> RunRecorder:
    rec = RunRecorder(_META)
    # gates as an (N, 4) [x,y,z,radius] array (mirrors gate_pos/gate_rad concat).
    gates = np.array([[1.5, 0.0, 1.0, 0.35], [3.0, 1.0, 1.2, 0.45]], dtype=np.float32)
    rec.begin_episode(1, gates, drone=7, dr=None, oracle_lap=np.float64(3.47))
    for step in range(3):
        # Pass numpy arrays/scalars to prove coercion -> plain JSON floats/ints/bools.
        rec.add_frame(
            t=np.float64((step + 1) / 50.0),
            step=step + 1,
            pos=np.array([0.1 * step, 0.0, 1.0]),
            quat=np.array([0.0, 0.0, 0.0, 1.0]),
            rpy=np.array([0.0, 0.0, 0.0]),
            vel=np.array([1.0, 0.0, 0.0]),
            angvel=np.array([0.0, 0.0, 0.0]),
            action=np.array([0.5, 0.0, 0.0, 0.0], dtype=np.float32),
            action_diffaero=np.array([3.0, 0.0, 0.0, 0.0], dtype=np.float32),
            reward=np.float32(0.5),
            cum_reward=0.5 * (step + 1),
            gate_idx=np.int64(0),
            dist_to_gate=np.float32(1.23),
            laps=np.int64(0),
            passed=np.bool_(step == 1),
            crashed=False,
            obs=np.arange(14, dtype=np.float32),
        )
    rec.end_episode({
        "steps": 3, "total_reward": 1.5, "laps": 0, "best_lap": None,
        "gates_passed": 1, "num_gates": 2, "ended": "max_steps",
    })
    return rec


def test_round_trip_json(tmp_path):
    rec = _make_recorder()
    path = tmp_path / "run.json"
    rec.save(path)

    raw = json.loads(path.read_text())
    assert raw["format"] == REPLAY_FORMAT
    assert raw["version"] == REPLAY_VERSION

    doc = load_run(path)
    assert doc["meta"]["config"] == "gate_race"
    assert doc["meta"]["obs_version"] == "obs-v4"
    assert doc["meta"]["action_version"] == "act-v2"
    assert doc["meta"]["substrate"] == "diffaero"
    assert len(doc["episodes"]) == 1

    ep = doc["episodes"][0]
    assert ep["index"] == 1
    assert ep["drone"] == 7
    assert ep["dr"] is None
    assert ep["oracle_lap"] == 3.47
    assert len(ep["gates"]) == 2

    gate = ep["gates"][0]
    assert gate["pos"] == [1.5, 0.0, 1.0]
    assert gate["radius"] == pytest.approx(0.35)

    assert len(ep["frames"]) == 3
    frame = ep["frames"][1]
    assert frame["step"] == 2
    assert frame["action"] == [0.5, 0.0, 0.0, 0.0]
    assert frame["action_diffaero"] == [3.0, 0.0, 0.0, 0.0]
    assert frame["passed"] is True
    assert frame["crashed"] is False
    assert len(frame["obs"]) == 14
    assert ep["summary"]["num_gates"] == 2


def test_no_leaked_numpy_types(tmp_path):
    """Every scalar in the document must be a JSON-native python type (json.dumps proves it)."""
    rec = _make_recorder()
    doc = rec.to_dict()
    # json.dumps with no default= raises TypeError on any numpy/torch scalar that leaked.
    json.dumps(doc)
    frame = doc["episodes"][0]["frames"][0]
    assert all(isinstance(v, float) for v in frame["pos"])
    assert isinstance(frame["step"], int)
    assert isinstance(frame["gate_idx"], int)
    assert isinstance(frame["laps"], int)
    assert isinstance(frame["passed"], bool)
    assert isinstance(frame["dist_to_gate"], float)


def test_meta_completeness():
    """The self-describing meta block carries the full contract — a consumer needs no doc."""
    rec = _make_recorder()
    meta = rec.to_dict()["meta"]
    for key in (
        "config", "policy", "task", "obs_version", "action_version", "substrate",
        "control_hz", "sim_hz", "dt", "coordinate_frame", "state_layout",
        "action_layout", "action_limits", "unity_hint",
    ):
        assert key in meta, f"meta missing {key!r}"
    for key in (
        "max_thrust_normed", "hover_thrust_normed", "max_body_rate_rp_rps", "max_body_rate_yaw_rps",
    ):
        assert key in meta["action_limits"]


def test_round_trip_gzip(tmp_path):
    rec = _make_recorder()
    path = tmp_path / "run.json.gz"
    rec.save(path)
    assert path.exists() and path.stat().st_size > 0
    # It really is gzip (magic bytes) and decodes to the same document.
    with open(path, "rb") as fh:
        assert fh.read(2) == b"\x1f\x8b"

    doc = load_run(path)
    assert doc["format"] == REPLAY_FORMAT
    assert len(doc["episodes"][0]["frames"]) == 3
    assert doc["episodes"][0]["gates"][1]["radius"] == pytest.approx(0.45)


def test_dr_dict_round_trips(tmp_path):
    rec = RunRecorder({"config": "dr_on"})
    dr = {"wind_vec": [0.5, -0.2, 0.0], "rate_gain_scale": 1.07, "latency_steps": 1}
    rec.begin_episode(1, [], dr=dr, oracle_lap=None)
    rec.add_frame(
        t=0.02, step=1, pos=[0, 0, 1], quat=[0, 0, 0, 1], rpy=[0, 0, 0],
        vel=[0, 0, 0], angvel=[0, 0, 0], action=[0, 0, 0, 0], action_diffaero=[2, 0, 0, 0],
        reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=1.0, laps=0,
    )
    rec.end_episode({"steps": 1})
    doc = load_run(rec.save(tmp_path / "dr.json"))
    ep = doc["episodes"][0]
    assert ep["dr"]["latency_steps"] == 1
    assert ep["oracle_lap"] is None
    # obs omitted when not provided.
    assert "obs" not in ep["frames"][0]


