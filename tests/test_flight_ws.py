"""The always-on FlightManager + /ws/flight endpoint — driven by the self-driving fake bridge.

No hardware, no torch: a :class:`~neural_whoop.studio.flight.FakeFlightBridge` (armed/override
scriptable) stands in for the XIAO link, so the whole dashboard backend runs on the bench. Asserts
the safety interlock over the websocket (Start rejected until the radio reports ARMED + override,
then the phase enum walks and frames carry live metrics), abort, a "no bridge configured" rejection,
a link-down status stream, and — crucially — that the GPU-sim ``ROLLOUT_LOCK`` is never taken by the
flight path (the MSP link is a different resource).
"""

from __future__ import annotations

import csv
import json
import time

from fastapi.testclient import TestClient

from neural_whoop.analysis.flight_log import LOG_COLUMNS as ANALYSIS_LOG_COLUMNS
from neural_whoop.analysis.flight_log import load_flight
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


def _synth_acro_weights(tmp_path):
    """A tiny deterministic 7->4 linear acro policy JSON (obs-7 [gravity_body(3),p,q,r,rot_rem])."""
    W = [[0.05] * 7, [0.05] * 7, [0.05] * 7, [0.05] * 7]
    data = {"meta": {"obs_dim": 7, "act_dim": 4, "base_obs_dim": 7, "obs_stack": 1,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / "acro.json"
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


def test_params_then_start_same_batch_flies(tmp_path):
    """Regression: bench.js fires {params} then {start} back-to-back on one Start click. The params
    message rebuilds a fresh WAITING controller; a fresh controller hasn't polled RC yet, so unless
    the manager carries over the radio-observed armed/override state, request_start rejects the start
    queued in the same drain and the drone silently never leaves WAITING."""
    fake = FakeFlightBridge(armed=True, override=True)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path),
        params=FlightParams(launch=True, hold_seconds=0.1, seconds=5.0, ramp_s=0.1),
        runs_dir=tmp_path / "pilot", client_factory=lambda *_a, **_k: fake)
    app = _app_with(tmp_path, mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            _read_until(ws, lambda m: m.get("status", {}).get("armed")
                        and m["status"]["override_on"])
            # Exactly what the Start button sends: params immediately followed by start
            # (incl. the level-trim fields the Bench UI exposes).
            ws.send_json({"type": "params", "seconds": 5, "hz": 50, "hover_us": 1410,
                          "trim_roll_deg": 0.5, "trim_pitch_deg": -2.5,
                          "mode": "ground-takeoff"})
            ws.send_json({"type": "start"})
            flying = _read_until(ws, lambda m: m.get("phase") not in (None, "waiting"))
            assert flying["phase"] in ("countdown", "seek", "rise", "hover", "land")
    assert mgr._params.trim_pitch_deg == -2.5 and mgr._params.trim_roll_deg == 0.5
    assert not ROLLOUT_LOCK.locked()


def test_params_hz_change_retimes_the_loop(tmp_path):
    """Regression: the fly loop must recompute its sleep period from the CURRENT controller.

    `period` used to be hoisted above the loop, so it was fixed to whatever the first controller was
    built with. A `params` message swaps in a new controller (and `ctrl.params.hz` did change), but
    the loop kept sleeping at the original rate -- so the Calibrate view's request for a faster poll,
    and the panel's own hz field, were silently ignored. Asserts the live controller carries the new
    rate and that frames actually speed up.
    """
    fake = FakeFlightBridge(armed=True, override=True)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path), params=FlightParams(hz=20.0),
        runs_dir=tmp_path / "pilot", client_factory=lambda *_a, **_k: fake)
    app = _app_with(tmp_path, mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            _read_until(ws, lambda m: m.get("step"))
            assert mgr._ctrl.params.hz == 20.0
            # What setCal(true) sends on opening the calibration view: hz only, no other field.
            ws.send_json({"type": "params", "hz": 100})
            # Let the swap land, then time how long N ticks actually take. Asserting on step counts
            # alone does NOT catch the bug -- the reader just waits longer -- and neither does
            # ctrl.params.hz, which changed even when the loop ignored it. Only wall-clock per tick
            # measures the thing that was broken.
            base = _read_until(ws, lambda m: m.get("step"))
            t0 = time.monotonic()
            ticks = 20
            later = _read_until(ws, lambda m: (m.get("step") or 0) >= (base["step"] + ticks))
            elapsed = time.monotonic() - t0
            hz_after = mgr._ctrl.params.hz  # inside the context: stop() clears _ctrl
    assert hz_after == 100.0
    assert (later.get("step") or 0) >= base["step"] + ticks
    # 20 ticks take ~0.2 s at 100 Hz but ~1.0 s at the stale 20 Hz. 0.5 s splits them with room
    # for scheduler noise on a loaded machine.
    assert elapsed < 0.5, f"{ticks} ticks took {elapsed:.2f}s — loop still paced by the old hz"


def test_flip_command_as_starter_takes_off_flips_then_hovers(tmp_path):
    """{type:"flip"} while WAITING doubles as the starter (same ARMED+override gate as start): the
    flight takes off, the FLIP window auto-opens once free hover settles — no further command — and
    the flight returns to HOVER and keeps flying."""
    fake = FakeFlightBridge(armed=True, override=True)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path), acro_weights=_synth_acro_weights(tmp_path),
        params=FlightParams(launch=True, hold_seconds=0.1, seconds=8.0, ramp_s=0.1,
                            acro_flip_max_s=1.0),
        runs_dir=tmp_path / "pilot", client_factory=lambda *_a, **_k: fake)
    app = _app_with(tmp_path, mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            _read_until(ws, lambda m: m.get("status", {}).get("armed")
                        and m["status"]["override_on"])
            ws.send_json({"type": "flip"})            # the one press, from WAITING
            flying = _read_until(ws, lambda m: m.get("phase") not in ("waiting",), max_reads=100)
            assert flying["phase"] in ("countdown", "rise", "hover")

            # The FLIP auto-fires after the settle window, with no further command.
            flip = _read_until(ws, lambda m: m.get("phase") == "flip")
            assert flip is not None and flip["phase"] == "flip"
            assert flip["metrics"]["flipping"] is True
            assert flip["metrics"]["rotation_remaining"] is not None

            # ... and hands back to the hover policy (the flight keeps flying).
            after = _read_until(ws, lambda m: m.get("phase") == "hover")
            assert after["phase"] == "hover"
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


def test_dashboard_csv_matches_the_analysis_schema(tmp_path):
    """A dashboard flight must write a CSV that ``load_flight`` accepts, header AND row width.

    studio/flight.py duplicates LOG_COLUMNS (it imports without numpy), and the row itself comes
    from FlightController._on_log — three places that can drift apart silently. They did not when
    ``bridge_loop_max_ms`` was appended, but only because this test now says so: the dashboard is
    the path the real flights actually use.
    """
    runs = tmp_path / "runs"
    fake = FakeFlightBridge(armed=True, override=True)
    mgr = FlightManager(
        "fake", weights=_synth_weights(tmp_path),
        params=FlightParams(launch=True, hold_seconds=0.15, seconds=0.5, ramp_s=0.1),
        runs_dir=runs / "pilot", client_factory=lambda *_a, **_k: fake)
    app = create_app(repo_root=tmp_path, runs_dir=runs, courses_dir=tmp_path / "courses",
                     device="cpu", flight_manager=mgr)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/flight") as ws:
            _read_until(ws, lambda m: m.get("status", {}).get("armed")
                        and m["status"]["override_on"])
            ws.send_json({"type": "start"})
            _read_until(ws, lambda m: m.get("status", {}).get("phase") == "released",
                        max_reads=3000)

    csvs = list((runs / "pilot").glob("flight_*.csv"))
    assert csvs, "dashboard flight wrote no CSV"
    with csvs[0].open(newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ANALYSIS_LOG_COLUMNS, "dashboard header drifted from the analysis schema"
    assert all(len(r) == len(ANALYSIS_LOG_COLUMNS) for r in rows[1:]), "row width != header width"
    load_flight(csvs[0])  # the real contract: flight_report.py must be able to read it


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
