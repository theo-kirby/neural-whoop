"""Pilot optical-flow telemetry: differencing the bridge's CUMULATIVE PMW3901 counters.

The bridge reports running sums plus its own sample clock, deliberately (a "counts since you
last asked" reply is destructive: one dropped packet eats real motion and a second client steals
it). Everything that can go wrong with that lives in ``Telemetry.flow_delta``, so it is pinned
here: no phantom first interval, no double-counting a re-served sample, dt from the BRIDGE
clock, and None-rather-than-zero whenever there is no data.

Reuses the scriptable FakeMsp from test_flight_controller with an MSP_BRIDGE_FLOW answer.
"""

from __future__ import annotations

import struct

from neural_whoop.bench.msp import MSP_BRIDGE_FLOW
from neural_whoop.pilot.telemetry import Telemetry

from test_flight_controller import FakeMsp


class FlowFakeMsp(FakeMsp):
    """FakeMsp + a scriptable MSP_BRIDGE_FLOW answer."""

    def __init__(self) -> None:
        super().__init__()
        self.sum_dx = 0
        self.sum_dy = 0
        self.t_ms = 1000
        self.n_frames = 0
        self.squal = 80
        self.sensor_ok = 1
        self.age_ms = 10
        self.answer = True

    def move(self, dx: int, dy: int, dt_ms: int, frames: int = 1) -> None:
        """Advance the sensor as the bridge would: sums accumulate, its clock moves on."""
        self.sum_dx += dx
        self.sum_dy += dy
        self.t_ms += dt_ms
        self.n_frames += frames

    def _write(self, raw: bytes) -> None:
        if raw[4] == MSP_BRIDGE_FLOW:
            if self.answer:
                self._resp(MSP_BRIDGE_FLOW, struct.pack(
                    "<iiIHBBBH", self.sum_dx, self.sum_dy, self.t_ms, self.n_frames,
                    self.squal, 1, self.sensor_ok, self.age_ms))
        else:
            super()._write(raw)


def _tel(fc):
    t = Telemetry(fc)
    return t


def test_first_frame_yields_no_interval():
    """One cumulative reading is a snapshot, not motion. Returning (0, 0) here would tell the
    caller "not moving" on the very first tick of every flight."""
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    assert tel.flow is not None and tel.flow["valid"]
    assert tel.flow_delta(0.0) is None


def test_counts_and_dt_come_from_differences():
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    assert tel.flow_delta(0.0) is None  # establishes the baseline

    fc.move(dx=120, dy=-45, dt_ms=20)
    tel.poll(0.02, want_flow=True)
    got = tel.flow_delta(0.02)
    assert got is not None
    dx, dy, dt_s, squal = got
    assert (dx, dy) == (120, -45)
    assert abs(dt_s - 0.020) < 1e-9  # the BRIDGE's interval, not the host's poll spacing
    assert squal == 80

    # The next interval is measured from the previous one, not from the start.
    fc.move(dx=10, dy=10, dt_ms=20)
    tel.poll(0.04, want_flow=True)
    dx2, dy2, dt2, _ = tel.flow_delta(0.04)
    assert (dx2, dy2) == (10, 10) and abs(dt2 - 0.020) < 1e-9


def test_dt_ignores_host_poll_jitter():
    """A late host poll must not stretch dt: the counts were accumulated over the bridge's
    interval, and dividing them by a jittered host interval is how a clean flow signal becomes a
    noisy velocity."""
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    tel.flow_delta(0.0)
    fc.move(dx=100, dy=0, dt_ms=20)
    tel.poll(0.15, want_flow=True)  # host was 130 ms late
    _, _, dt_s, _ = tel.flow_delta(0.15)
    assert abs(dt_s - 0.020) < 1e-9


def test_reserved_sample_is_not_counted_twice():
    """A stalled bridge re-serves the same sample with a growing age. Differencing it against
    itself must yield None, not a zero-dt interval (which divides by zero downstream)."""
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    tel.flow_delta(0.0)
    fc.move(dx=60, dy=0, dt_ms=20)
    tel.poll(0.02, want_flow=True)
    assert tel.flow_delta(0.02)[0] == 60

    fc.age_ms = 60  # same t_ms, older stamp: the bridge has not sampled since
    tel.poll(0.04, want_flow=True)
    assert tel.flow_delta(0.04) is None


def test_absent_or_stale_sensor_returns_none_not_zero():
    fc = FlowFakeMsp()
    fc.sensor_ok = 0
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    assert tel.flow_delta(0.0) is None

    fc.sensor_ok = 1
    fc.age_ms = 900  # bridge has the sensor but the sample is ancient
    tel.poll(0.02, want_flow=True)
    assert tel.flow_delta(0.02) is None


def test_bridge_reboot_resyncs_instead_of_reporting_a_huge_interval():
    """The bridge's clock restarts at 0 on reboot. A naive difference would be hugely negative;
    a wrap-corrected one would be a ~49-day positive. Neither is motion — resync instead."""
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0, want_flow=True)
    tel.flow_delta(0.0)
    fc.move(dx=50, dy=0, dt_ms=20)
    tel.poll(0.02, want_flow=True)
    assert tel.flow_delta(0.02) is not None

    fc.t_ms = 5  # rebooted
    fc.sum_dx = 0
    tel.poll(0.04, want_flow=True)
    assert tel.flow_delta(0.04) is None
    # ... and the next real interval works normally again.
    fc.move(dx=30, dy=0, dt_ms=20)
    tel.poll(0.06, want_flow=True)
    assert tel.flow_delta(0.06)[0] == 30


def test_flow_is_not_polled_unless_asked():
    """want_flow gates the extra MSP query: it costs a round trip on every control tick, and the
    hover_tof/hover_blind families have no use for it."""
    fc = FlowFakeMsp()
    tel = _tel(fc)
    tel.poll(0.0)  # no want_flow
    assert tel.flow is None
