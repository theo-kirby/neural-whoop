"""FlightController state-machine tests — a canned-MSP fake bridge, no hardware, no torch.

A :class:`FakeMsp` (subclassing the real ``_MspEndpoint``) answers MSP queries from a *scriptable*
timeline (armed / override / attitude / rpm) built with the real ``encode_msp_v1`` codec, so the
controller runs its exact request/drain plumbing against it. The tests drive :meth:`step` through the
phase enum and assert the safety interlock: no RC while WAITING with override off, idle RC once the
override engages, ``request_start`` rejected until ARMED + override, ``abort`` on override-off and on
a sustained >110 deg roll, and a golden RC-output regression (a level-still frame maps to the same
AETR ``us`` the pure ``action_to_us`` formula produces).
"""

from __future__ import annotations

import json
import struct

import pytest

from neural_whoop.bench.msp import (
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_MODE_RANGES,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    _MspEndpoint,
    decode_u16s,
    encode_msp_v1,
)
from neural_whoop.pilot import (
    FlightController,
    FlightParams,
    Phase,
    Policy,
    action_to_us,
    stack_frames,
)


class _DummySock:
    def settimeout(self, *_):  # Telemetry sets the socket non-blocking on construction
        pass


class FakeMsp(_MspEndpoint):
    """A scriptable in-process MSP endpoint: every query gets an immediate canned response, and
    ``MSP_SET_RAW_RC`` writes are captured in :attr:`sent_rc`. Mutate the public fields to script a
    timeline between :meth:`FlightController.step` calls."""

    def __init__(self) -> None:
        super().__init__()
        self._sock = _DummySock()
        self._out = bytearray()
        self.sent_rc: list[tuple[int, ...]] = []
        # Scriptable telemetry state.
        self.roll_deg = 0.0
        self.pitch_deg = 0.0
        self.yaw_deg = 0.0
        self.gyro_raw = (0, 0, 0)
        self.acc_raw = (0, 0, 2048)
        self.vbat = 4.0
        # rcData read-back order: roll, pitch, yaw, throttle, aux1..aux4.
        self.rc = [1500, 1500, 1500, 1000, 1000, 1000, 1000, 1000]
        self.motor_rpm: list[int] | None = [26000, 26000, 26000, 26000]
        # ARM (perm 0) on aux1, MSP OVERRIDE (perm 50) on aux3; steps 32-48 -> 1700-2100 us.
        self.mode_ranges = bytes([0, 0, 32, 48, 50, 2, 32, 48])

    # -- scripting helpers --
    def set_armed(self, on: bool) -> None:
        self.rc[4] = 2000 if on else 1000    # aux1

    def set_override(self, on: bool) -> None:
        self.rc[6] = 2000 if on else 1000    # aux3

    # -- endpoint plumbing --
    def _resp(self, cmd: int, payload: bytes) -> None:
        self._out += encode_msp_v1(cmd, payload, header=b"$M>")

    def _write(self, raw: bytes) -> None:
        cmd = raw[4]
        if cmd == MSP_MODE_RANGES:
            self._resp(cmd, self.mode_ranges)
        elif cmd == MSP_ATTITUDE:
            self._resp(cmd, struct.pack("<hhh", int(self.roll_deg * 10),
                                        int(self.pitch_deg * 10), int(self.yaw_deg)))
        elif cmd == MSP_RAW_IMU:
            self._resp(cmd, struct.pack("<9h", *self.acc_raw, *self.gyro_raw, 0, 0, 0))
        elif cmd == MSP_ANALOG:
            self._resp(cmd, struct.pack("<BHHh", int(self.vbat * 10), 0, 0, 0)
                       + struct.pack("<H", int(self.vbat * 100)))
        elif cmd == MSP_RC:
            self._resp(cmd, struct.pack(f"<{len(self.rc)}H", *self.rc))
        elif cmd == MSP_MOTOR_TELEMETRY and self.motor_rpm:
            p = bytes([len(self.motor_rpm)])
            for rpm in self.motor_rpm:
                p += struct.pack("<IHBHHH", rpm, 0, 20, 370, 100, 50)
            self._resp(cmd, p)
        elif cmd == MSP_SET_RAW_RC:
            size = raw[3]
            self.sent_rc.append(decode_u16s(raw[5:5 + size]))

    def _read(self) -> bytes:
        d = bytes(self._out)
        self._out.clear()
        return d


class Clock:
    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def weights(tmp_path):
    """A tiny deterministic 5->4 linear policy (obs_stack 1) — a self-contained deploy JSON."""
    W = [[0.1, 0.0, 0.0, 0.0, 0.0],
         [0.0, 0.1, 0.0, 0.0, 0.0],
         [0.0, 0.0, 0.1, 0.0, 0.0],
         [0.0, 0.0, 0.0, 0.1, 0.0]]
    data = {"meta": {"obs_dim": 5, "act_dim": 4, "base_obs_dim": 5, "obs_stack": 1,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / "policy_weights.json"
    p.write_text(json.dumps(data))
    return p


def _make(weights, fake, clk, **params_kw):
    pol = Policy(str(weights))
    params = FlightParams(**params_kw)
    ctrl = FlightController(fake, pol, params, start_mode="software",
                            clock=clk, sleep=lambda _s: None)
    ctrl.setup()
    return pol, ctrl


def _run_until(ctrl, clk, pred, *, dt=0.02, max_steps=800):
    for _ in range(max_steps):
        if pred(ctrl):
            return True
        clk.t += dt
        ctrl.step()
    return pred(ctrl)


def _arm_and_start(ctrl, clk, fake):
    """Arm + engage override on the radio, then accept the software Start (into free flight)."""
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):  # let an MSP_RC poll land so armed/override register
        clk.t += 0.02
        ctrl.step()
    assert ctrl.request_start() is True


def test_waiting_no_rc_until_override_then_idle_and_start_gating(weights):
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, launch=True, hold_seconds=0.1, seconds=0.1, ramp_s=0.1)

    # WAITING, override off, disarmed: request_start rejected and NOTHING is streamed to the FC.
    for _ in range(6):  # >5 ticks so an MSP_RC poll actually lands
        clk.t += 0.02
        ctrl.step()
    assert ctrl.phase is Phase.WAITING
    assert ctrl.request_start() is False
    assert fake.sent_rc == []               # override off -> no RC on the wire

    # Arm + engage the override on the radio: still WAITING (software mode never auto-starts), but
    # now idle RC streams and request_start is permitted.
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.phase is Phase.WAITING
    assert ctrl.status()["armed"] and ctrl.status()["override_on"]
    assert fake.sent_rc[-1][:4] == (1500, 1500, ctrl.params.min_us, 1500)  # idle throttle
    assert ctrl.request_start() is True

    # COUNTDOWN -> RISE -> HOVER -> LAND -> RELEASED, deterministically (launch ramps on a clock).
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.COUNTDOWN)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    f = ctrl.step()
    assert f["metrics"]["tilt_deg"] is not None and "vz_est" in f["metrics"]
    assert f["metrics"]["battery_v"] == pytest.approx(4.0)
    assert _run_until(ctrl, clk, lambda c: c.done)
    assert ctrl.phase is Phase.RELEASED


def test_golden_rc_output_regression(weights):
    """A level-still frame in free HOVER maps to exactly the pure ``action_to_us`` formula's us."""
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False, seconds=5.0,
                      hover_us=1410, min_us=1000, max_us=1600)
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.request_start() is True
    clk.t += 0.02
    ctrl.step()                              # first free-flight (HOVER) tick, level-still obs
    assert ctrl.phase is Phase.HOVER

    # Pre-refactor formula: policy on the level-still stacked frame -> action_to_us, yaw centered.
    from collections import deque
    act = pol(stack_frames(deque(maxlen=1), [0.0, 0.0, 0.0, 0.0, 0.0], 1))
    exp = action_to_us(act, 1410, 1000, 1600, 0.0)
    exp[3] = 1500
    assert list(fake.sent_rc[-1][:4]) == exp


def test_abort_on_override_dropped(weights):
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False, seconds=5.0)
    _arm_and_start(ctrl, clk, fake)
    _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    fake.set_override(False)                 # radio takeover
    assert _run_until(ctrl, clk, lambda c: c.done)
    assert ctrl.phase is Phase.ABORTED
    assert ctrl.abort_reason == "override_off"
    # Once aborted, stepping streams NO further RC — stopping the stream IS the safe action, and
    # Betaflight's ~300 ms freshness window hands control back to the radio.
    n = len(fake.sent_rc)
    clk.t += 0.02
    ctrl.step()
    assert len(fake.sent_rc) == n


def test_abort_on_sustained_extreme_roll(weights):
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False, seconds=5.0)
    _arm_and_start(ctrl, clk, fake)
    _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    fake.roll_deg = 120.0                    # > 110 deg: hopeless attitude
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=60)
    assert ctrl.phase is Phase.ABORTED
    assert ctrl.abort_reason == "crash"


def test_request_start_rejected_when_not_armed(weights):
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False)
    fake.set_override(True)                   # override on but NOT armed
    for _ in range(6):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.status()["override_on"] and not ctrl.status()["armed"]
    assert ctrl.request_start() is False
