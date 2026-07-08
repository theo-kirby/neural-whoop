"""The always-on FlightManager + /ws/flight endpoint — driven by the self-driving fake bridge.

No hardware, no torch: a :class:`~neural_whoop.studio.flight.FakeFlightBridge` (armed/override
scriptable) stands in for the XIAO link, so the whole dashboard backend runs on the bench. Asserts
the safety interlock over the websocket (Start rejected until the radio reports ARMED + override,
then the phase enum walks and frames carry live metrics), abort, a "no bridge configured" rejection,
a link-down status stream, and — crucially — that the GPU-sim ``ROLLOUT_LOCK`` is never taken by the
flight path (the MSP link is a different resource).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from neural_whoop.pilot import FlightParams
from neural_whoop.studio.flight import FakeFlightBridge, FlightManager
from neural_whoop.studio.flight_report import run_flight_report
from neural_whoop.studio.server import ROLLOUT_LOCK, create_app


def _synth_weights(tmp_path):
    """A tiny deterministic 5->4 linear policy JSON (matches the fake bridge's 5-dim obs)."""
    W = [[0.1, 0.0, 0.0, 0.0, 0.0], [0.0, 0.1, 0.0, 0.0, 0.0],
         [0.0, 0.0, 0.1, 0.0, 0.0], [0.0, 0.0, 0.0, 0.1, 0.0]]
    data = {"meta": {"obs_dim": 5, "act_dim": 4, "base_obs_dim": 5, "obs_stack": 1,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / "w.json"
    p.write_text(json.dumps(data))
    return p


def _app_with(tmp_path, mgr):
    return create_app(repo_root=tmp_path, runs_dir=tmp_path / "runs",
                      courses_dir=tmp_path / "courses", device="cpu", flight_manager=mgr)


def _read_until(ws, pred, max_reads=500):
    last = None
    for _ in range(max_reads):
        last = ws.receive_json()
        if pred(last):
            return last
    return last


def test_no_bridge_configured_is_rejected(tmp_path):
    app = create_app(repo_root=tmp_path, runs_dir=tmp_path / "runs",
                     courses_dir=tmp_path / "courses", device="cpu")  # no bridge, no fake
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            msg = ws.receive_json()
    assert msg["type"] == "error" and "no bridge" in msg["detail"]
    assert app.state.flight is None
    assert not ROLLOUT_LOCK.locked()


def test_link_down_status_stream(tmp_path):
    def boom(*_a, **_k):
        raise ConnectionError("bridge unreachable")

    mgr = FlightManager("1.2.3.4", weights=_synth_weights(tmp_path),
                        runs_dir=tmp_path / "pilot", client_factory=boom)
    app = _app_with(tmp_path, mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            f = _read_until(ws, lambda m: m.get("link_state") == "down")
    assert f["link_state"] == "down"
    assert f["status"]["link_ok"] is False
    assert not ROLLOUT_LOCK.locked()


def test_fake_flight_gating_phase_walk_and_abort(tmp_path):
    fake = FakeFlightBridge(armed=False, override=False)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path),
        params=FlightParams(launch=True, hold_seconds=0.1, seconds=5.0, ramp_s=0.1),
        runs_dir=tmp_path / "pilot", client_factory=lambda *_a, **_k: fake)
    app = _app_with(tmp_path, mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            # Link comes up idle; the radio reports NOT armed -> a Start is rejected (stays WAITING).
            _read_until(ws, lambda m: m.get("status", {}).get("armed") is False
                        and m.get("phase") == "waiting")
            ws.send_json({"type": "start"})
            still = _read_until(ws, lambda m: m.get("seq", 0) > 0, max_reads=8)
            assert still["phase"] == "waiting"        # start had no effect (not armed)

            # Arm + engage override on the radio, then Start walks the phase enum.
            fake.set_armed(True)
            fake.set_override(True)
            _read_until(ws, lambda m: m.get("status", {}).get("armed")
                        and m["status"]["override_on"])
            ws.send_json({"type": "start"})
            flying = _read_until(ws, lambda m: m.get("phase") not in (None, "waiting"))
            assert flying["phase"] in ("countdown", "rise", "hover", "land")
            met = flying["metrics"]
            assert met["tilt_deg"] is not None and "vz_est" in met and "battery_v" in met
            assert flying["link_state"] in ("flying", "live")

            # Abort from the browser -> ABORTED (radio still owns the real kill).
            ws.send_json({"type": "abort"})
            aborted = _read_until(ws, lambda m: m.get("phase") == "aborted")
            assert aborted["phase"] == "aborted"
    assert not ROLLOUT_LOCK.locked()


def test_flight_report_emitted_on_landing(tmp_path):
    """A completed (RELEASED) fake flight fires the auto flight-report and emits {type: report}."""
    runs = tmp_path / "runs"
    fake = FakeFlightBridge(armed=True, override=True)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path),
        params=FlightParams(launch=True, hold_seconds=0.15, seconds=0.5, ramp_s=0.1),
        runs_dir=runs / "pilot", client_factory=lambda *_a, **_k: fake)
    # Wire the manager's own auto-report at itself (the server does this via runs_dir in production).
    mgr._on_flight_done = lambda csv, released: run_flight_report(csv, released, mgr, runs_root=runs)

    app = create_app(repo_root=tmp_path, runs_dir=runs, courses_dir=tmp_path / "courses",
                     device="cpu", flight_manager=mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            _read_until(ws, lambda m: m.get("status", {}).get("armed")
                        and m["status"]["override_on"])
            ws.send_json({"type": "start"})
            report = _read_until(ws, lambda m: m.get("type") == "report", max_reads=3000)
    assert report is not None and report["type"] == "report"
    assert set(("median_tilt_deg", "vz_rail_frames", "link_p99_ms", "battery_sag_v")) \
        <= set(report["metrics"])
    assert list((runs / "pilot").glob("*_report/flight_summary.json")), "no report pack written"
    assert not ROLLOUT_LOCK.locked()


def test_create_app_builds_manager_for_fake_bridge(tmp_path):
    w = _synth_weights(tmp_path)
    app = create_app(repo_root=tmp_path, runs_dir=tmp_path / "runs",
                     courses_dir=tmp_path / "courses", device="cpu",
                     bridge="fake", flight_weights="w.json")
    with TestClient(app) as client:
        assert app.state.flight is not None
        with client.websocket_connect("/ws/flight") as ws:
            f = _read_until(ws, lambda m: m.get("type") == "frame")
        assert f["type"] == "frame"
    assert not ROLLOUT_LOCK.locked()
