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


@pytest.fixture
def acro_weights(tmp_path):
    """A tiny deterministic 7->4 linear acro policy (obs-7 [gravity_body(3),p,q,r,rot_rem])."""
    W = [[0.05] * 7, [0.05] * 7, [0.05] * 7, [0.05] * 7]
    data = {"meta": {"obs_dim": 7, "act_dim": 4, "base_obs_dim": 7, "obs_stack": 1,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / "acro_weights.json"
    p.write_text(json.dumps(data))
    return p


# ~12 rad/s (688 deg/s) roll rate in raw gyro LSB: enough to sweep Φ=2π in ~0.5 s at dt=0.02.
_ROLL_RATE_RAW = int(688.0 / (2000.0 / 32768.0))


def test_acro_flip_sequence_and_crash_detector_suspended(weights, acro_weights):
    """A flip_at_s-triggered FLIP: reaches FLIP, sweeps rotation_remaining 1->0, does NOT crash-abort
    through the inverted attitude, then returns to HOVER and lands out to RELEASED."""
    fake = FakeMsp()
    clk = Clock()
    hover = Policy(str(weights))
    acro = Policy(str(acro_weights))
    params = FlightParams(takeoff=False, launch=False, seconds=5.0, ramp_s=0.2,
                          flip_at_s=0.1, acro_axis="roll", acro_flip_max_s=1.5)
    ctrl = FlightController(fake, hover, params, acro_policy=acro, start_mode="software",
                            clock=clk, sleep=lambda _s: None)
    ctrl.setup()
    _arm_and_start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)

    fake.gyro_raw = (_ROLL_RATE_RAW, 0, 0)     # spin about roll while the acro policy "flies"
    seen_flip = False
    rot_trace = []
    for _ in range(400):
        if ctrl.flipping:
            # Drive the airframe inverted (|roll| 120° > the 110° crash threshold) until the
            # rotation is nearly complete, then re-level so the clean completed+level exit fires.
            fake.roll_deg = 120.0 if ctrl.rot_rem > 0.05 else 0.0
        clk.t += 0.02
        f = ctrl.step()
        if f["phase"] == "flip":
            seen_flip = True
            rot_trace.append(f["metrics"]["rotation_remaining"])
            assert f["metrics"]["flipping"] is True
        if seen_flip and not ctrl.flipping:
            break

    assert seen_flip, "the FLIP window never opened"
    assert not ctrl.done and ctrl.abort_reason is None  # crash detector stayed suspended mid-flip
    assert rot_trace[0] > 0.9 and rot_trace[-1] < 0.1   # rotation_remaining swept 1 -> 0
    assert ctrl.phase is Phase.HOVER                     # re-leveled -> back to the hover policy

    # The crash detector re-armed: a sustained inverted attitude now DOES abort.
    fake.roll_deg = 120.0
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=60)
    assert ctrl.phase is Phase.ABORTED and ctrl.abort_reason == "crash"


def test_acro_flip_bounded_window_exits_even_if_never_relevels(weights, acro_weights):
    """Safety backstop: if the airframe never re-levels, FLIP still exits at acro_flip_max_s and the
    crash detector re-arms (a real tumble after a failed flip must still cut)."""
    fake = FakeMsp()
    clk = Clock()
    params = FlightParams(takeoff=False, launch=False, seconds=10.0, flip_at_s=0.1,
                          acro_axis="roll", acro_flip_max_s=0.5)
    ctrl = FlightController(fake, Policy(str(weights)), params,
                            acro_policy=Policy(str(acro_weights)), start_mode="software",
                            clock=clk, sleep=lambda _s: None)
    ctrl.setup()
    _arm_and_start(ctrl, clk, fake)
    _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    fake.gyro_raw = (_ROLL_RATE_RAW, 0, 0)
    # Trigger fires from level (gated on near-level); it then never re-levels (a "failed" flip).
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.FLIP, max_steps=20)
    fake.roll_deg = 120.0                       # stays inverted the whole time
    t_flip = clk.t
    assert _run_until(ctrl, clk, lambda c: not c.flipping, max_steps=100)
    # Exited within ~acro_flip_max_s of opening (the bounded window, not the rotation-complete path).
    assert clk.t - t_flip <= params.acro_flip_max_s + 0.1
    # Detector re-armed instantly -> the still-inverted airframe aborts as a crash.
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=60)
    assert ctrl.abort_reason == "crash"


def test_flip_not_triggered_without_acro_policy(weights):
    """flip_at_s is inert when no acro policy is loaded — the base hover flight is untouched."""
    fake = FakeMsp()
    clk = Clock()
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False, seconds=5.0, flip_at_s=0.1)
    _arm_and_start(ctrl, clk, fake)
    _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    for _ in range(40):
        clk.t += 0.02
        ctrl.step()
        assert not ctrl.flipping and ctrl.phase is not Phase.FLIP


def test_flip_as_starter_gating(weights, acro_weights):
    """request_flip while WAITING is a starter: rejected under the exact request_start gate (ARMED +
    override on the radio; no acro policy = inert), accepted = the flight clock starts + a flip is
    armed pending free hover."""
    fake = FakeMsp()
    clk = Clock()
    # No acro policy: request_flip must NOT double as a bare Start.
    pol, ctrl = _make(weights, fake, clk, takeoff=False, launch=False, seconds=5.0)
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.request_flip() is False and ctrl.t_start is None

    # With an acro policy but not armed: rejected, still WAITING.
    fake2 = FakeMsp()
    clk2 = Clock()
    ctrl2 = FlightController(fake2, Policy(str(weights)), FlightParams(seconds=5.0),
                             acro_policy=Policy(str(acro_weights)), start_mode="software",
                             clock=clk2, sleep=lambda _s: None)
    ctrl2.setup()
    fake2.set_override(True)                  # override on but NOT armed
    for _ in range(6):
        clk2.t += 0.02
        ctrl2.step()
    assert ctrl2.request_flip() is False and ctrl2.t_start is None

    # Armed + override: accepted -> flight clock set + the flip pending.
    fake2.set_armed(True)
    for _ in range(6):
        clk2.t += 0.02
        ctrl2.step()
    assert ctrl2.request_flip() is True
    assert ctrl2.t_start is not None and ctrl2.flip_pending


def test_flip_as_starter_takes_off_flips_then_keeps_hovering(weights, acro_weights):
    """One press from WAITING: the flight starts, the flip auto-fires only after ACRO_START_SETTLE_S
    of free hover, and the flight returns to HOVER and keeps flying (no early land/abort)."""
    from neural_whoop.pilot.config import ACRO_START_SETTLE_S

    fake = FakeMsp()
    clk = Clock()
    params = FlightParams(takeoff=False, launch=False, seconds=8.0, ramp_s=0.2,
                          acro_axis="roll", acro_flip_max_s=1.5)   # no flip_at_s: pending only
    ctrl = FlightController(fake, Policy(str(weights)), params,
                            acro_policy=Policy(str(acro_weights)), start_mode="software",
                            clock=clk, sleep=lambda _s: None)
    ctrl.setup()
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.request_flip() is True        # the one press

    # Free hover but before the settle window: pending, NOT flipping yet.
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    assert ctrl.flip_pending and not ctrl.flipping

    fake.gyro_raw = (_ROLL_RATE_RAW, 0, 0)     # spin about roll while the acro policy "flies"
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.FLIP, max_steps=100)
    assert ctrl._t_air >= ACRO_START_SETTLE_S  # fired only once free hover settled
    assert not ctrl.flip_pending

    # Ride the flip out (inverted mid-maneuver, re-level near the end) -> back to HOVER, still flying.
    for _ in range(200):
        if not ctrl.flipping:
            break
        fake.roll_deg = 120.0 if ctrl.rot_rem > 0.05 else 0.0
        clk.t += 0.02
        ctrl.step()
    assert not ctrl.flipping and ctrl.phase is Phase.HOVER
    assert not ctrl.done and ctrl.abort_reason is None
    # It keeps hovering — a second flip is NOT re-armed by the starter press.
    for _ in range(40):
        clk.t += 0.02
        ctrl.step()
        assert not ctrl.flipping and ctrl.phase is Phase.HOVER
