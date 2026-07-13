"""Pilot ToF-obs family tests: task-keyed policy detection + the FlightController height path.

The hover_tof deploy contract: the 6th obs channel is ``target_height_m − h`` with
``h = tof_range · cos(roll) · cos(pitch)`` held at the last valid reading; the external climb
damper is OFF (the policy owns altitude); a ToF policy refuses to fly without the sensor
(setup gate) and aborts if it goes silent for >1 s in flight. Reuses the scriptable FakeMsp
from test_flight_controller with an MSP_BRIDGE_TOF answer bolted on.
"""

from __future__ import annotations

import json
import math
import struct

import pytest

from neural_whoop.bench.msp import MSP_BRIDGE_TOF
from neural_whoop.pilot import FlightController, FlightParams, Phase, Policy
from neural_whoop.pilot.controller import FlightSetupError

from test_flight_controller import Clock, FakeMsp, _run_until


class TofFakeMsp(FakeMsp):
    """FakeMsp + a scriptable MSP_BRIDGE_TOF answer (range_mm/status/answer switch)."""

    def __init__(self) -> None:
        super().__init__()
        self.tof_mm = 500
        self.tof_status = 0
        self.tof_answer = True

    def _write(self, raw: bytes) -> None:
        if raw[4] == MSP_BRIDGE_TOF:
            if self.tof_answer:
                self._resp(MSP_BRIDGE_TOF,
                           struct.pack("<HBHB", self.tof_mm, self.tof_status, 10, 1))
        else:
            super()._write(raw)


def _weights(tmp_path, task: str, base_dim: int = 6, stack: int = 1):
    """A tiny zero policy JSON with an explicit meta task (the family key)."""
    W = [[0.0] * (base_dim * stack) for _ in range(4)]
    data = {"meta": {"task": task, "obs_dim": base_dim * stack, "act_dim": 4,
                     "base_obs_dim": base_dim, "obs_stack": stack,
                     "log_std": [-1.0, -1.0, -1.0, -1.0]},
            "layers": [{"W": W, "b": [0.0, 0.0, 0.0, 0.0]}]}
    p = tmp_path / f"policy_{task}.json"
    p.write_text(json.dumps(data))
    return p


# --- family detection (the base-6 ambiguity is task-keyed) -------------------------------------

def test_family_flags(tmp_path):
    tof = Policy(str(_weights(tmp_path, "hover_tof")))
    assert tof.uses_tof and not tof.uses_vz and tof.owns_altitude
    v2 = Policy(str(_weights(tmp_path, "hover_blind_v2")))
    assert v2.uses_vz and not v2.uses_tof and v2.owns_altitude
    blind = Policy(str(_weights(tmp_path, "hover_blind", base_dim=5)))
    assert not blind.uses_vz and not blind.uses_tof and not blind.owns_altitude


def test_pre_task_meta_stays_vz(tmp_path):
    # Hand-extracted / pre-tof exports carry no task field: 6-dim must stay the vz family.
    p = _weights(tmp_path, "hover_blind_v2")
    data = json.loads(p.read_text())
    del data["meta"]["task"]
    p.write_text(json.dumps(data))
    pol = Policy(str(p))
    assert pol.uses_vz and not pol.uses_tof


# --- FlightController height path ---------------------------------------------------------------

def _make_tof(tmp_path, fake, clk, **params_kw):
    pol = Policy(str(_weights(tmp_path, "hover_tof")))
    params = FlightParams(**params_kw)
    ctrl = FlightController(fake, pol, params, start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s))
    ctrl.setup()
    return pol, ctrl


def _start(ctrl, clk, fake):
    fake.set_armed(True)
    fake.set_override(True)
    for _ in range(6):  # let an MSP_RC poll land so armed/override register
        clk.t += 0.02
        ctrl.step()
    assert ctrl.request_start() is True


def test_setup_refuses_without_tof(tmp_path):
    fake = FakeMsp()  # never answers MSP_BRIDGE_TOF
    clk = Clock()
    pol = Policy(str(_weights(tmp_path, "hover_tof")))
    ctrl = FlightController(fake, pol, FlightParams(), start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s))
    with pytest.raises(FlightSetupError, match="ToF|tof"):
        ctrl.setup()


def test_height_estimate_is_tilt_corrected_and_held(tmp_path):
    fake = TofFakeMsp()
    clk = Clock()
    fake.roll_deg, fake.pitch_deg = 20.0, 10.0
    fake.tof_mm = 800
    pol, ctrl = _make_tof(tmp_path, fake, clk, launch=True, hold_seconds=0.1, seconds=5.0)
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    expect = 0.8 * math.cos(math.radians(20.0)) * math.cos(math.radians(10.0))
    assert ctrl.h_est == pytest.approx(expect, rel=1e-3)
    # Sensor goes invalid (status != 0): the estimate HOLDS at the last valid value.
    fake.tof_status = 4
    for _ in range(5):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.h_est == pytest.approx(expect, rel=1e-3)


def test_logged_h_err_matches_the_fed_channel(tmp_path):
    rows: list[list] = []
    fake = TofFakeMsp()
    clk = Clock()
    fake.tof_mm = 550
    pol = Policy(str(_weights(tmp_path, "hover_tof")))
    params = FlightParams(launch=True, hold_seconds=0.1, seconds=5.0, target_height_m=0.7)
    ctrl = FlightController(fake, pol, params, start_mode="software", clock=clk,
                            sleep=lambda s: setattr(clk, "t", clk.t + s),
                            on_log=rows.append)
    ctrl.setup()
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    h_err = float(rows[-1][-1])
    assert h_err == pytest.approx(0.7 - ctrl.h_est, abs=1e-3)
    assert len(rows[-1]) == 26


def test_tof_policy_disables_external_damper(tmp_path):
    fake = TofFakeMsp()
    clk = Clock()
    fake.motor_rpm = [30000] * 4  # well above any hover anchor: a blind policy would get trimmed
    pol, ctrl = _make_tof(tmp_path, fake, clk, launch=True, hold_seconds=0.1, seconds=5.0,
                          vz_gain=0.5)
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    for _ in range(10):
        clk.t += 0.02
        ctrl.step()
    assert ctrl.thr_trim == 0.0


def test_abort_when_tof_lost_in_flight(tmp_path):
    fake = TofFakeMsp()
    clk = Clock()
    pol, ctrl = _make_tof(tmp_path, fake, clk, launch=True, hold_seconds=0.1, seconds=30.0)
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.HOVER)
    fake.tof_answer = False
    assert _run_until(ctrl, clk, lambda c: c.done, max_steps=120)  # > 1 s of silence
    assert ctrl.abort_reason == "tof_lost"


def test_blind_policy_flies_without_tof(tmp_path):
    # Regression: the ToF plumbing must not gate the proven 5-dim family.
    fake = FakeMsp()  # no ToF at all
    clk = Clock()
    pol = Policy(str(_weights(tmp_path, "hover_blind", base_dim=5)))
    ctrl = FlightController(fake, pol, FlightParams(launch=True, hold_seconds=0.1, seconds=0.2,
                                                    ramp_s=0.1),
                            start_mode="software", clock=clk, sleep=lambda _s: None)
    ctrl.setup()
    _start(ctrl, clk, fake)
    assert _run_until(ctrl, clk, lambda c: c.phase is Phase.RELEASED)
