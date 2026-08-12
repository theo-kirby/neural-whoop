"""Pilot hover_flow (obs-8) family: task-keyed detection, the flow channel, and its abort.

The hover_flow deploy contract extends hover_tof's: channels 0-5 are byte-identical and channels
6/7 are the PMW3901's body-frame horizontal velocity,
``v = (counts/dt - gyro) * rad_per_count * measured_height``, held at the last valid reading and
then faded to zero. What is new — and what this file pins — is that **the dim is no longer a
usable family key**: base_obs_dim 8 is ALSO the acro-flip obs, so every gate has to branch on
``meta["task"]``, and a mistake there feeds a flying drone a channel that means something else.

Reuses the scriptable FakeMsp from test_flight_controller with an MSP_BRIDGE_FLOW answer bolted
on beside the ToF one.
"""

from __future__ import annotations

import json
import math
import struct

import pytest

from neural_whoop.analysis.flight_log import LOG_COLUMNS
from neural_whoop.bench.msp import MSP_BRIDGE_FLOW
from neural_whoop.pilot import (
    FlightController,
    FlightParams,
    Phase,
    Policy,
    check_policy_family,
    flow_to_velocity,
)
from neural_whoop.pilot.config import GYRO_RAW_TO_DPS
from neural_whoop.pilot.controller import FlightSetupError

from test_flight_controller import Clock, _run_until
from test_pilot_tof import TofFakeMsp, _start

RPC = 0.023891  # bench.py's documented geometry placeholder; a real one comes off the slide test


class FlowFakeMsp(TofFakeMsp):
    """TofFakeMsp + a scriptable MSP_BRIDGE_FLOW answer.

    The counts are CUMULATIVE and the clock is the bridge's own, exactly like the firmware — a
    fake that returned per-read deltas would exercise the wrong contract entirely (the host
    differences two replies). The sensor FREE-RUNS: each poll advances the counters by
    ``dx_per_tick``/``dy_per_tick`` over ``dt_ms``, because the real PMW3901 keeps sampling
    whether or not the host asks.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sum_dx = 0
        self.sum_dy = 0
        self.t_ms = 1000
        self.n_frames = 0
        self.squal = 72
        self.flow_answer = True
        self.sensor_ok = True
        self.dx_per_tick = 0
        self.dy_per_tick = 0
        self.dt_ms = 20

    def _write(self, raw: bytes) -> None:
        if raw[4] == MSP_BRIDGE_FLOW:
            self.sum_dx += self.dx_per_tick
            self.sum_dy += self.dy_per_tick
            self.t_ms += self.dt_ms
            self.n_frames += 1
            if self.flow_answer:
                self._resp(MSP_BRIDGE_FLOW, struct.pack(
                    "<iiIHBBBH", self.sum_dx, self.sum_dy, self.t_ms, self.n_frames,
                    self.squal, 1, int(self.sensor_ok), 8))
        else:
            super()._write(raw)


def _weights(tmp_path, task: str = "hover_flow", base_dim: int = 8, stack: int = 1):
    W = [[0.0] * (base_dim * stack) for _ in range(4)]
    data = {"meta": {"task": task, "obs_dim": base_dim * stack, "act_dim": 4,
                     "base_obs_dim": base_dim, "obs_stack": stack,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / f"policy_{task}_{base_dim}x{stack}.json"
    p.write_text(json.dumps(data))
    return p


def _make(tmp_path, fake, clk, **kw):
    kw.setdefault("rad_per_count", RPC)
    pol = Policy(str(_weights(tmp_path)))
    ctrl = FlightController(fake, pol, FlightParams(**kw), start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s))
    ctrl.setup()
    return pol, ctrl


# --- family detection: the dim is not the key ---------------------------------------------------

def test_flow_family_flags(tmp_path):
    pol = Policy(str(_weights(tmp_path)))
    assert pol.uses_flow
    assert pol.uses_tof, "channel 5 is still the ToF height error — the height path must run"
    assert not pol.uses_vz, "an 8-dim flow file must not fall through the vz fallback"
    assert pol.owns_altitude


def test_an_8_dim_acro_file_is_rejected_by_the_hover_gate(tmp_path):
    """Both directions of the obs-8 collision, since either one flies a real drone.

    ``check_policy_family_acro``'s half lives in test_pilot_acro_obs.py.
    """
    acro = Policy(str(_weights(tmp_path, task="acro_flip_v2", base_dim=8)))
    assert not acro.uses_flow and not acro.uses_tof
    with pytest.raises(SystemExit, match="acro"):
        check_policy_family(acro)
    check_policy_family(Policy(str(_weights(tmp_path))))            # the flow file is accepted
    with pytest.raises(SystemExit, match="hover_flow"):             # ...at 8 channels only
        check_policy_family(Policy(str(_weights(tmp_path, base_dim=6))))


# --- setup refusals -----------------------------------------------------------------------------

def test_setup_refuses_without_rad_per_count(tmp_path):
    """The refusal that is not about hardware: an unmeasured scale is a zeroed channel.

    rad_per_count 0 makes every velocity exactly 0.0 — the faded-channel state the knockout probe
    measured as WORSE than never having the channel (16.8% vs 25.6% survival).
    """
    fake, clk = FlowFakeMsp(), Clock()
    pol = Policy(str(_weights(tmp_path)))
    ctrl = FlightController(fake, pol, FlightParams(), start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s))
    with pytest.raises(FlightSetupError, match="rad_per_count"):
        ctrl.setup()


def test_setup_warns_about_a_poor_surface_but_does_not_refuse(tmp_path):
    """Setup gates the SENSOR, not the surface — and that distinction is load-bearing.

    Setup runs with the drone on the floor, ~3 cm up, BELOW the PMW3901's 80 mm working range,
    where a collapsed squal is the expected reading rather than a diagnosis. A squal refusal here
    made a hover_flow policy unable to take off AT ALL (caught on the fake bridge, which models
    the blind floor honestly). The textureless-floor case is caught by ``flow_lost`` one second
    into free flight, where the reading means something.
    """
    logs: list[str] = []
    fake, clk = FlowFakeMsp(), Clock()
    fake.squal = 3
    pol = Policy(str(_weights(tmp_path)))
    ctrl = FlightController(fake, pol, FlightParams(rad_per_count=RPC), start_mode="software",
                            clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s),
                            log=logs.append)
    ctrl.setup()                                    # no refusal
    assert any("squal 3" in m and "flow_lost" in m for m in logs), logs


def test_setup_refuses_without_the_sensor(tmp_path):
    """A missing sensor IS a refusal: the channel is load-bearing, so flying blind is not a mode."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.flow_answer = False
    pol = Policy(str(_weights(tmp_path)))
    ctrl = FlightController(fake, pol, FlightParams(rad_per_count=RPC), start_mode="software",
                            clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s))
    with pytest.raises(FlightSetupError, match="optical flow"):
        ctrl.setup()

    fake.flow_answer, fake.sensor_ok = True, False  # bridge answers, no PMW3901 behind it
    ctrl = FlightController(fake, pol, FlightParams(rad_per_count=RPC), start_mode="software",
                            clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s))
    with pytest.raises(FlightSetupError, match="no PMW3901 found"):
        ctrl.setup()


def test_the_flow_abort_does_not_fire_before_free_flight(tmp_path):
    """The countdown, the liftoff seek and the climb-out all happen under 80 mm — blind by
    construction. A t_start-gated abort killed every take-off; the clock starts at free flight."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 30                                 # on the floor: the flow sensor cannot see
    fake.squal = 2
    pol, ctrl = _make(tmp_path, fake, clk, takeoff=True, hold_seconds=2.0, seconds=5.0)
    _start(ctrl, clk, fake)
    for _ in range(120):                             # 2.4 s of countdown/seek, all of it blind
        clk.t += 0.02
        ctrl.step()
        if ctrl.done:
            break
    assert not ctrl.done, f"aborted on the ground: {ctrl.abort_reason}"
    assert ctrl.phase in (Phase.COUNTDOWN, Phase.SEEK, Phase.RISE)


# --- the channel itself -------------------------------------------------------------------------

def _fly_to_hover(tmp_path, fake, clk, **kw):
    pol, ctrl = _make(tmp_path, fake, clk, launch=True, hold_seconds=0.1, seconds=30.0, **kw)
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    return pol, ctrl


def _tick(ctrl, clk, fake, dx=0, dy=0, n=1):
    fake.dx_per_tick, fake.dy_per_tick = dx, dy
    for _ in range(n):
        clk.t += 0.02
        ctrl.step()


def test_velocity_is_gyro_compensated_and_height_scaled(tmp_path):
    """The conversion, end to end and against the shared pure function.

    A pitching drone sweeps the ground past the lens with no translation at all, so without the
    gyro term the channel is a mixture rather than a velocity — and the sim models only the
    RESIDUAL of that compensation, i.e. it presumes it happens here.
    """
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400                       # h_est 0.400 m, level
    _, ctrl = _fly_to_hover(tmp_path, fake, clk)
    _tick(ctrl, clk, fake, dx=60, dy=-25)
    expect = flow_to_velocity(60, -25, 0.020, RPC, ctrl.h_est, ctrl.p, ctrl.q)
    assert ctrl.vx_obs == pytest.approx(expect[0], rel=1e-6)
    assert ctrl.vy_obs == pytest.approx(expect[1], rel=1e-6)
    assert abs(ctrl.vx_obs) > 0.01, "test setup produced no motion to check"

    # Same counts at twice the height read twice the velocity — the error the 0.15 m setpoint
    # was chosen against (the uncalibrated +23.9 mm ToF offset is 16% of it).
    fake.tof_mm = 800
    _tick(ctrl, clk, fake, dx=60, dy=-25, n=3)
    assert ctrl.h_est == pytest.approx(0.8, rel=1e-3)
    assert ctrl.vx_obs == pytest.approx(2.0 * expect[0], rel=1e-3)


def test_a_pure_rotation_reports_no_velocity(tmp_path):
    """The gyro term's whole job, isolated: rotating in place must read ~zero velocity."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk)
    # A pure pitch rate q sweeps the lens at exactly q rad/s along body x, and nothing else.
    # Pick the COUNTS first and derive q from them: counts are integers, so choosing q first
    # leaves a rounding residual that swamps the thing under test (0.8 rad/s is 0.67 of a count
    # per 20 ms, i.e. a 50% quantization error, and the test then measures arithmetic).
    counts = 5
    q = counts / 0.020 * RPC                       # 5.97 rad/s nose-down = 342 deg/s
    fake.gyro_raw = (0, int(round(math.degrees(q) / GYRO_RAW_TO_DPS)), 0)
    _tick(ctrl, clk, fake, dx=counts, n=3)
    assert ctrl.q == pytest.approx(q, rel=1e-3)
    uncompensated = q * ctrl.h_est                 # what the raw counts alone would claim
    assert uncompensated > 2.0, "the test would pass on a channel that reports nothing"
    assert abs(ctrl.vx_obs) < 0.02, f"rotation leaked into the velocity channel: {ctrl.vx_obs}"


@pytest.mark.parametrize("why,setup", [
    ("below the 80 mm working range", lambda f: setattr(f, "tof_mm", 50)),
    ("no texture", lambda f: setattr(f, "squal", 2)),
    ("past the tilt limit", lambda f: setattr(f, "pitch_deg", 45.0)),
])
def test_validity_gates_mirror_the_task(tmp_path, why, setup):
    """Each gate is HoverFlowConfig's, and a deploy gate that differs hands the policy a channel
    it never trained against. Rejected readings must HOLD, never silently pass through."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk, flow_blind_grace_s=1e9)  # hold, don't fade
    _tick(ctrl, clk, fake, dx=60)
    assert abs(ctrl.vx_obs) > 0.01, "the channel was not live before the gate closed"
    setup(fake)
    # Two quiet ticks so the gate is fully closed before the bad data starts. The height gate in
    # particular closes one tick LATE by design: flow is computed before the ToF advance (the
    # sim's own order), so the tick a range changes on still uses the previous height.
    _tick(ctrl, clk, fake, dx=0, n=2)
    held = ctrl.vx_obs
    _tick(ctrl, clk, fake, dx=900, n=5)          # a big, WRONG reading arrives every tick
    assert ctrl.vx_obs == pytest.approx(held, abs=1e-9), f"{why}: a gated reading got through"


def test_blind_flow_fades_to_zero(tmp_path):
    """Grace, then fade to an HONEST neutral. For a velocity, zero means 'I don't know that I'm
    moving' — unlike a faded height error, which claims 'at target'."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk, flow_blind_grace_s=0.2, flow_blind_fade_s=0.3)
    _tick(ctrl, clk, fake, dx=60)
    fresh = ctrl.vx_obs
    assert abs(fresh) > 0.01

    fake.squal = 1                                # the mat lifts; frames keep arriving
    _tick(ctrl, clk, fake, dx=60, n=5)            # 0.10 s: inside grace
    assert ctrl.vx_obs == pytest.approx(fresh, rel=1e-3)
    _tick(ctrl, clk, fake, dx=60, n=13)           # ~0.36 s: mid-fade
    assert 0.0 < abs(ctrl.vx_obs) < abs(fresh)
    _tick(ctrl, clk, fake, dx=60, n=10)           # past grace + fade
    assert ctrl.vx_obs == 0.0


def test_flow_lost_aborts_after_a_second(tmp_path):
    """The abort the blackout model exists to make survivable up to this point — and no further:
    a faded-to-zero channel is worse than never having had one (staid-moon-7407)."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk)
    _tick(ctrl, clk, fake, dx=60)
    fake.squal = 1
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=120)
    assert ctrl.abort_reason == "flow_lost"


def test_a_dead_tof_is_reported_as_tof_lost_not_its_flow_symptom(tmp_path):
    """flow_lost SUBSUMES tof_lost by construction (a flow reading needs a valid height), so the
    ToF check runs first and names the cause rather than the downstream symptom."""
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk)
    _tick(ctrl, clk, fake, dx=60)
    fake.tof_answer = False
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=120)
    assert ctrl.abort_reason == "tof_lost"


# --- the log is the replay ----------------------------------------------------------------------

def test_logged_vx_vy_are_the_fed_channels(tmp_path):
    """The h_err discipline, extended: the CSV carries what the POLICY SAW, post-fade.

    The four raw flow columns are pre-fusion — they carry neither the height, nor the gyro, nor
    the fade state — so without these two, sim_vs_real cannot replay a flow flight at all.
    """
    rows: list[list] = []
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    pol = Policy(str(_weights(tmp_path)))
    ctrl = FlightController(fake, pol, FlightParams(launch=True, hold_seconds=0.1, seconds=30.0,
                                                    rad_per_count=RPC),
                            start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s), on_log=rows.append)
    ctrl.setup()
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    _tick(ctrl, clk, fake, dx=60, dy=-25)
    assert len(rows[-1]) == len(LOG_COLUMNS)
    assert float(rows[-1][LOG_COLUMNS.index("vx")]) == pytest.approx(ctrl.vx_obs, abs=1e-4)
    assert float(rows[-1][LOG_COLUMNS.index("vy")]) == pytest.approx(ctrl.vy_obs, abs=1e-4)
    # The raw counts ride alongside, unfused, so the calibration question stays answerable.
    assert int(rows[-1][LOG_COLUMNS.index("flow_dx")]) == 60


def test_flow_delta_is_consumed_exactly_once_per_tick(tmp_path):
    """``Telemetry.flow_delta`` consumes its interval by contract.

    The logging path used to own the only call; the obs path MOVED it rather than adding one,
    because two callers would each see half the motion — and the halves would not even be
    consistent, since which caller wins depends on poll timing.
    """
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    _, ctrl = _fly_to_hover(tmp_path, fake, clk)
    calls = {"n": 0}
    real = ctrl.tel.flow_delta

    def counted(now):
        calls["n"] += 1
        return real(now)

    ctrl.tel.flow_delta = counted
    _tick(ctrl, clk, fake, dx=10, n=7)
    assert calls["n"] == 7, f"flow_delta called {calls['n']} times over 7 ticks"


def test_passive_log_flow_never_reaches_the_obs(tmp_path):
    """``--log-flow`` on a hover_tof policy stays PASSIVE — that split is the calibration flight.

    It must also still consume the interval exactly once, through the same single call site.
    """
    fake, clk = FlowFakeMsp(), Clock()
    fake.tof_mm = 400
    pol = Policy(str(_weights(tmp_path, task="hover_tof", base_dim=6)))
    ctrl = FlightController(fake, pol, FlightParams(launch=True, hold_seconds=0.1, seconds=30.0,
                                                    log_flow=True),
                            start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s))
    ctrl.setup()                       # no rad_per_count needed: nothing consumes the channel
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    _tick(ctrl, clk, fake, dx=60, n=3)
    assert ctrl.vx_obs is None and ctrl.vy_obs is None
    assert not ctrl.done, "a passive flow reader must not arm the flow_lost abort"
