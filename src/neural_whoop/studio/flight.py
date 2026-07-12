"""Always-on real-drone flight manager — the bridge between the browser and the Air65 II.

A :class:`FlightManager` owns one background thread that connects to the XIAO WiFi bridge (retrying
if it's down), runs a :class:`~neural_whoop.pilot.controller.FlightController` at ``params.hz``, and
publishes each frame under a lock with an incrementing ``seq``. The Studio's ``/ws/flight`` endpoint
polls :meth:`latest` and forwards browser commands through :meth:`command`. The manager is the
single-flight guard for the *sequence* — it is deliberately **not** wrapped in the Studio's
``ROLLOUT_LOCK`` (that guards the GPU sim; the MSP link is a different resource, and several viewers
may watch the same telemetry at once).

Imports only :mod:`neural_whoop.pilot` + :mod:`neural_whoop.bench.msp` — **zero torch/numpy**, so
the real-flight path stays pure-stdlib. The parallel CPU-torch sim rides the separate ``/ws/live``.

Safety is inherited wholesale from the controller: the radio owns arm + override (enable) and
drop/disarm (kill -> instant abort via the ~300 ms MSP-freshness handback); software only ever sets
a clock (``request_start``), and only when telemetry already shows ARMED + override. The manager has
no code path that writes aux/arm.
"""

from __future__ import annotations

import csv
import math
import os
import queue
import struct
import threading
import time
from pathlib import Path

from neural_whoop.bench.msp import (
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_MODE_RANGES,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    MspUdpClient,
    _MspEndpoint,
    decode_u16s,
    encode_msp_v1,
)
from neural_whoop.pilot import FlightController, FlightParams, FlightSetupError, Policy
from neural_whoop.pilot.config import BF_MAX_RATE_RP, GYRO_RAW_TO_DPS

#: The 24-col pilot CSV schema (kept in sync with analysis/flight_log.py::LOG_COLUMNS; duplicated
#: here so this module — like the pilot engine — imports without numpy).
LOG_COLUMNS = [
    "t", "obs_age_ms", "roll", "pitch", "p", "q", "r",
    "a_thr", "a_wx", "a_wy", "a_wz", "us_roll", "us_pitch", "us_thr", "us_yaw",
    "vbat", "hover_eff", "vz_est", "trim", "acc_x", "acc_y", "acc_z",
    "rpm_rms", "us_corr",
]

#: Fields a browser ``params`` message may override on the WAITING controller.
_PARAM_FIELDS = ("seconds", "hz", "hover_us", "min_us", "max_us", "hold_seconds", "vz_gain",
                 "trim_roll_deg", "trim_pitch_deg", "trim_thrust", "yaw")


def _parse_bridge(bridge: str) -> tuple[str, int]:
    host, _, port = str(bridge).partition(":")
    return host, int(port or 14550)


def params_from_message(msg: dict, base: FlightParams) -> FlightParams:
    """Build a fresh :class:`FlightParams` from a browser ``params`` message over a base params.

    ``mode`` (``"takeoff"`` | ``"launch"``) maps to the staged-takeoff / hand-launch flags; every
    other key in :data:`_PARAM_FIELDS` overrides the matching field. Unknown keys are ignored.
    """
    kw = {f: getattr(base, f) for f in _PARAM_FIELDS}
    kw["takeoff"] = base.takeoff
    kw["launch"] = base.launch
    kw["max_obs_age"] = base.max_obs_age
    kw["aux"] = base.aux
    for f in _PARAM_FIELDS:
        if f in msg and msg[f] is not None:
            cur = getattr(base, f)
            kw[f] = type(cur)(msg[f]) if isinstance(cur, (int, float)) and not isinstance(cur, bool) else msg[f]
    mode = msg.get("mode")
    if mode == "takeoff":
        kw["takeoff"], kw["launch"] = True, False
    elif mode == "launch":
        kw["takeoff"], kw["launch"] = False, True
    elif mode == "none":
        kw["takeoff"], kw["launch"] = False, False
    return FlightParams(**kw)


class FlightManager:
    """Own the MSP link + a :class:`FlightController` on a background thread; publish frames.

    Args:
        bridge: ``host[:port]`` of the XIAO bridge (or ``"fake"`` / ``NW_FLIGHT_FAKE=1`` for the
            self-driving in-process bridge — no hardware).
        weights: path to the deploy ``policy_weights.json``.
        params: base :class:`FlightParams` (defaults to the recommended ground-takeoff flow).
        runs_dir: where per-flight CSVs are written (``runs/pilot``).
        client_factory: ``(host, port) -> _MspEndpoint`` (injectable for tests).
        controller_factory: ``(fc, policy, params, **kw) -> FlightController`` (injectable).
        on_flight_done: optional ``(csv_path, released) -> None`` hook fired when a flight ends
            (Phase 5 wires the auto flight-report here).
    """

    def __init__(self, bridge: str, *, weights: str | Path,
                 acro_weights: str | Path | None = None,
                 params: FlightParams | None = None,
                 runs_dir: str | Path = "runs/pilot",
                 client_factory=None, controller_factory=FlightController,
                 on_flight_done=None) -> None:
        self._bridge = bridge
        self._host, self._port = _parse_bridge(bridge)
        self._policy = Policy(str(weights))
        self._weights = str(weights)
        # Optional acro-flip policy: enables the {type:"flip"} command (a bounded FLIP window at
        # HOVER). None = the Flip button is inert (the base take-off/land/hover flow is unchanged).
        self._acro_policy = Policy(str(acro_weights)) if acro_weights else None
        self._params = params or FlightParams(takeoff=True)
        self._runs_dir = Path(runs_dir)
        self._use_fake = str(bridge).lower() == "fake" or _truthy(os.environ.get("NW_FLIGHT_FAKE"))
        self._client_factory = client_factory or (
            (lambda *_a, **_k: FakeFlightBridge()) if self._use_fake
            else (lambda host, port: MspUdpClient(host, port)))
        self._controller_factory = controller_factory
        self._on_flight_done = on_flight_done

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cmds: queue.Queue = queue.Queue()
        self._latest: dict | None = None
        self._msgs: list[dict] = []          # out-of-band messages (e.g. flight-report ready)
        self._seq = 0
        self._link_state = "down"
        self._ctrl: FlightController | None = None
        # Per-flight CSV (opened lazily on the first in-flight row).
        self._csv_file = None
        self._csv_writer = None
        self._csv_path: Path | None = None
        self._logbuf: list[str] = []

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Spawn the poll thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="flight-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Abort + join + release the link (safe: stopping the stream hands back to the radio)."""
        self._stop.set()
        ctrl = self._ctrl
        if ctrl is not None:
            try:
                ctrl.abort("shutdown")
            except Exception:  # noqa: BLE001 - best-effort
                pass
        t = self._thread
        if t is not None:
            t.join(timeout=3.0)
        self._thread = None

    @property
    def link_state(self) -> str:
        return self._link_state

    # ------------------------------------------------------------------ public API (websocket side)
    def command(self, msg: dict) -> None:
        """Enqueue a browser command (``{type: start|abort|params}``) for the flight thread."""
        self._cmds.put(msg)

    def latest(self) -> dict | None:
        """A thread-safe copy of the most recent published frame (carries ``seq``/``link_state``)."""
        with self._lock:
            return dict(self._latest) if self._latest is not None else None

    def emit(self, msg: dict) -> None:
        """Queue an out-of-band message (e.g. a flight-report-ready notice) for the websocket."""
        with self._lock:
            self._msgs.append(dict(msg))

    def drain_messages(self) -> list[dict]:
        """Pop all queued out-of-band messages (the websocket sends these alongside frames)."""
        with self._lock:
            if not self._msgs:
                return []
            out, self._msgs = self._msgs, []
            return out

    # ------------------------------------------------------------------ background thread
    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            fc = None
            try:
                self._set_link("connecting")
                fc = self._client_factory(self._host, self._port)
                ctrl = self._new_controller(fc)
                ctrl.setup()
                backoff = 0.5
                self._fly_loop(fc, ctrl)
            except FlightSetupError as e:
                self._publish_status("down", f"setup: {e}")
            except Exception as e:  # noqa: BLE001 - any link/socket error: back off and retry
                self._publish_status("down", f"link error: {e}")
            finally:
                self._ctrl = None
                self._close_csv(released=False)
                if fc is not None:
                    try:
                        fc.close()
                    except Exception:  # noqa: BLE001
                        pass
            if self._stop.is_set():
                break
            self._set_link("down")
            self._stop.wait(backoff)
            backoff = min(4.0, backoff * 1.5)
        self._set_link("down")

    def _fly_loop(self, fc, ctrl: FlightController) -> None:
        self._ctrl = ctrl
        period = 1.0 / max(1.0, ctrl.params.hz)
        while not self._stop.is_set():
            t0 = time.monotonic()
            ctrl = self._apply_commands(fc, ctrl)
            frame = ctrl.step()
            self._link_state = self._derive_link(ctrl, frame)
            self._publish(frame)
            if ctrl.done:
                self._close_csv(released=ctrl._released)
                # Rebuild a fresh WAITING controller so the dashboard is instantly ready again.
                ctrl = self._new_controller(fc)
                ctrl.setup()
                self._ctrl = ctrl
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    # ------------------------------------------------------------------ helpers
    def _new_controller(self, fc) -> FlightController:
        self._logbuf = []
        return self._controller_factory(
            fc, self._policy, self._params, acro_policy=self._acro_policy, start_mode="software",
            on_log=self._log_row, log=self._logbuf.append)

    def _apply_commands(self, fc, ctrl: FlightController) -> FlightController:
        while True:
            try:
                msg = self._cmds.get_nowait()
            except queue.Empty:
                break
            t = msg.get("type")
            if t == "start":
                ctrl.request_start()
            elif t == "flip":
                # In HOVER: gated to fresh link + near-level. While WAITING: doubles as a software
                # Start (same ARMED+override gate) with the flip auto-firing once free hover settles.
                ctrl.request_flip()
            elif t == "abort":
                ctrl.abort("user")
            elif t == "params" and ctrl.t_start is None and not ctrl.done:
                self._params = params_from_message(msg, self._params)
                prev = ctrl
                ctrl = self._new_controller(fc)
                ctrl.setup()
                # A fresh controller hasn't stepped yet, so armed_seen/override_on are False.
                # Carry over what the previous (live) controller just observed from the radio, so
                # a `start` queued in the SAME drain isn't spuriously rejected by request_start.
                # The next step() re-reads RC and re-verifies; the radio still owns enable + kill.
                ctrl.armed_seen = prev.armed_seen
                ctrl.override_on = prev.override_on
                self._ctrl = ctrl
        return ctrl

    def _derive_link(self, ctrl: FlightController, frame: dict) -> str:
        if ctrl.t_start is not None and not ctrl.done:
            return "flying"
        return "live" if frame["status"]["link_ok"] else "connecting"

    def _publish(self, frame: dict) -> None:
        with self._lock:
            self._seq += 1
            out = dict(frame)
            out["seq"] = self._seq
            out["link_state"] = self._link_state
            if self._logbuf:
                out["events"] = list(self._logbuf)
                self._logbuf = []
            self._latest = out

    def _publish_status(self, link_state: str, detail: str = "") -> None:
        """Publish a telemetry-free status frame (link down / setup failed)."""
        self._link_state = link_state
        with self._lock:
            self._seq += 1
            self._latest = {
                "type": "status", "phase": "waiting", "seq": self._seq,
                "link_state": link_state, "detail": detail,
                "status": {"armed": False, "override_on": False, "link_ok": False},
            }

    def _set_link(self, state: str) -> None:
        self._link_state = state

    # --- per-flight CSV (only rows once a flight is actually running) ---
    def _log_row(self, row: list) -> None:
        ctrl = self._ctrl
        if ctrl is None or ctrl.t_start is None:
            return  # only log a real flight (skip the idle WAITING rows of an always-on session)
        if self._csv_writer is None:
            self._open_csv()
        self._csv_writer.writerow(row)

    def _open_csv(self) -> None:
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = self._runs_dir / f"flight_{int(time.time())}.csv"
        self._csv_file = self._csv_path.open("w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(LOG_COLUMNS)

    def _close_csv(self, *, released: bool) -> None:
        if self._csv_file is None:
            return
        path = self._csv_path
        try:
            self._csv_file.close()
        finally:
            self._csv_file = self._csv_writer = self._csv_path = None
        if path is not None and self._on_flight_done is not None:
            try:
                self._on_flight_done(path, released)
            except Exception:  # noqa: BLE001 - a report failure never touches the flight loop
                pass


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on") if v is not None else False


class _DummySock:
    def settimeout(self, *_):  # Telemetry sets the socket non-blocking on construction
        pass


class FakeFlightBridge(_MspEndpoint):
    """A self-driving in-process MSP endpoint so the whole dashboard runs with no hardware.

    Reports ARMED + override engaged (so the browser's Start lights immediately), a gentle attitude
    wobble, and an acc-z / RPM response to the commanded throttle so a ``takeoff`` flight actually
    seeks liftoff, hovers, and lands out. Physically crude — just enough to exercise the pipeline
    end-to-end (``--bridge fake`` / ``NW_FLIGHT_FAKE=1``).
    """

    def __init__(self, *_a, armed: bool = True, override: bool = True, **_k) -> None:
        super().__init__()
        self._sock = _DummySock()
        self._out = bytearray()
        self._thr = 1000
        self._gyro = (0, 0, 0)     # echoed from the commanded roll/pitch rate (crude flip model)
        self._roll = 0.0           # attitude integrated from the commanded rate (deg): a real flip
        self._pitch = 0.0
        self._i = 0
        self._vbat = 4.05
        self._armed = armed
        self._override = override

    @staticmethod
    def _wrap180(a: float) -> float:
        return (a + 180.0) % 360.0 - 180.0

    def set_armed(self, on: bool) -> None:
        self._armed = on

    def set_override(self, on: bool) -> None:
        self._override = on

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def _resp(self, cmd: int, payload: bytes) -> None:
        self._out += encode_msp_v1(cmd, payload, header=b"$M>")

    def _write(self, raw: bytes) -> None:
        cmd = raw[4]
        if cmd == MSP_MODE_RANGES:
            self._resp(cmd, bytes([0, 0, 32, 48, 50, 2, 32, 48]))  # ARM aux1, OVERRIDE aux3
        elif cmd == MSP_ATTITUDE:
            self._i += 1
            # Integrated attitude (a commanded flip really rolls the airframe over) + a gentle idle
            # wobble so a plain hover still looks alive.
            roll = self._wrap180(self._roll + 2.5 * math.sin(self._i * 0.05))
            pitch = self._wrap180(self._pitch + 2.0 * math.cos(self._i * 0.037))
            self._resp(cmd, struct.pack("<hhh", int(roll * 10), int(pitch * 10), 0))
        elif cmd == MSP_RAW_IMU:
            az = 2048 + max(0, (self._thr - 1300)) * 3   # acc-z rises with throttle -> liftoff
            gx, gy, _gz = self._gyro                       # echoed commanded rate -> the flip spins
            self._resp(cmd, struct.pack("<9h", 0, 0, int(az), int(gx), int(gy), 0, 0, 0, 0))
        elif cmd == MSP_ANALOG:
            self._vbat = max(3.4, self._vbat - 0.0002)   # gentle sag
            self._resp(cmd, struct.pack("<BHHh", int(self._vbat * 10), 0, 0, 0)
                       + struct.pack("<H", int(self._vbat * 100)))
        elif cmd == MSP_RC:
            aux1 = 2000 if self._armed else 1000    # ARM
            aux3 = 2000 if self._override else 1000  # MSP OVERRIDE
            self._resp(cmd, struct.pack("<8H", 1500, 1500, 1500, 1000, aux1, 1000, aux3, 1000))
        elif cmd == MSP_MOTOR_TELEMETRY:
            rpm = max(600, int((self._thr - 1000) * 45))
            p = bytes([4])
            for _ in range(4):
                p += struct.pack("<IHBHHH", rpm, 0, 22, 370, 100, 50)
            self._resp(cmd, p)
        elif cmd == MSP_SET_RAW_RC:
            ch = decode_u16s(raw[5:5 + raw[3]])
            if len(ch) >= 3:
                self._thr = ch[2]
            if len(ch) >= 2:
                # Echo the commanded roll/pitch rate (AETR us -> deg/s) into both the gyro (raw LSB,
                # so obs_from_msp_acro reads it back) and an integrated attitude at the ~50 Hz tick,
                # so a FLIP actually rolls the airframe through Φ and the policy re-levels out of it.
                dps_per_us = BF_MAX_RATE_RP * 180.0 / math.pi / 500.0   # us above 1500 -> deg/s
                roll_dps = (ch[0] - 1500) * dps_per_us
                pitch_dps = (ch[1] - 1500) * dps_per_us
                self._gyro = (int(roll_dps / GYRO_RAW_TO_DPS), int(pitch_dps / GYRO_RAW_TO_DPS), 0)
                self._roll = self._wrap180(self._roll + roll_dps * 0.02)   # fixed 50 Hz control tick
                self._pitch = self._wrap180(self._pitch + pitch_dps * 0.02)

    def _read(self) -> bytes:
        d = bytes(self._out)
        self._out.clear()
        return d
