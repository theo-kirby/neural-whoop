"""Non-blocking MSP telemetry poller + the RC-stream helper — moved verbatim from ``pilot.py``.

:class:`Telemetry` sits on top of any ``_MspEndpoint`` — :class:`MspUdpClient` (the WiFi bridge)
or :class:`MspClient` (the ESP-NOW USB dongle): each :meth:`Telemetry.poll` fires the
attitude/IMU/(optional analog/rc/rpm/bridge-ToF) queries and drains every waiting reply, so the
control loop never blocks. :func:`stream_rc` packs one AETR RC frame.

This module imports only the codec (``neural_whoop.bench.msp``) and this package's policy layer,
so it is stdlib-only; the *serial* transport it can be handed pulls pyserial in lazily
(``docs/ESPNOW.md``), which is the one place the flight path leaves the stdlib.
"""

from __future__ import annotations

import math

from neural_whoop.bench.msp import (
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_BRIDGE_FLOW,
    MSP_BRIDGE_TOF,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    _MspEndpoint,
    decode_analog,
    decode_attitude,
    decode_bridge_flow,
    decode_bridge_tof,
    decode_motor_telemetry,
    decode_raw_imu,
    decode_u16s,
    pack_rc_channels,
    wrap_delta,
)

from .policy import obs_from_msp


class Telemetry:
    """Fire-and-forget MSP pollers + latest-known state. Never blocks the control loop."""

    def __init__(self, fc: _MspEndpoint) -> None:
        self.fc = fc
        # Non-blocking reads: poll() must drain EVERY waiting reply each tick (we send 2-3
        # queries per tick; one blocking read per tick would back-log replies -> stale obs).
        # Transport-dispatched, NOT `fc._sock.settimeout(0)` — that was UDP-only, and over the
        # ESP-NOW dongle's serial port a blocking read costs up to 20 ms of a 22 ms tick.
        self.fc.set_nonblocking()
        self.att: dict | None = None
        self.imu: dict | None = None
        self.vbat: float | None = None
        self.rc: tuple[int, ...] | None = None
        self.mt: list[dict] | None = None
        self.tof: dict | None = None
        self.flow: dict | None = None
        self.t_att = 0.0
        self.t_imu = 0.0
        self.t_rc = 0.0
        self.t_mt = 0.0
        self.t_tof = 0.0         # arrival time of the newest ToF frame
        self.t_tof_sample = 0.0  # when that RANGE was taken (arrival - the bridge's own age stamp)
        self.t_flow = 0.0        # arrival time of the newest flow frame
        # Previous flow counters, for differencing the CUMULATIVE sums the bridge reports. Held
        # here rather than recomputed by callers so there is exactly ONE consumer of the deltas:
        # two independent differencers would each see half the motion.
        self._flow_prev: dict | None = None

    def poll(self, now: float, want_analog: bool = False, want_rc: bool = False,
             want_rpm: bool = False, want_tof: bool = False, want_flow: bool = False) -> None:
        self.fc.send(MSP_ATTITUDE)
        self.fc.send(MSP_RAW_IMU)
        if want_rpm:
            self.fc.send(MSP_MOTOR_TELEMETRY)
        if want_analog:
            self.fc.send(MSP_ANALOG)
        if want_rc:
            self.fc.send(MSP_RC)
        if want_tof:  # bridge-answered (never reaches the FC); errors harmlessly over USB
            self.fc.send(MSP_BRIDGE_TOF)
        if want_flow:  # likewise bridge-answered
            self.fc.send(MSP_BRIDGE_FLOW)
        frames = []
        for _ in range(32):  # drain the socket dry (non-blocking)
            got = self.fc._drain()
            if not got:
                break
            frames.extend(got)
        for frame in frames:
            if frame.is_error:
                continue
            if frame.cmd == MSP_ATTITUDE and len(frame.payload) >= 6:
                self.att, self.t_att = decode_attitude(frame.payload), now
            elif frame.cmd == MSP_RAW_IMU and len(frame.payload) >= 18:
                self.imu, self.t_imu = decode_raw_imu(frame.payload), now
            elif frame.cmd == MSP_ANALOG and len(frame.payload) >= 7:
                self.vbat = decode_analog(frame.payload)["vbat_v"]
            elif frame.cmd == MSP_RC and len(frame.payload) >= 16:
                self.rc, self.t_rc = decode_u16s(frame.payload), now
            elif frame.cmd == MSP_MOTOR_TELEMETRY and len(frame.payload) >= 14:
                self.mt, self.t_mt = decode_motor_telemetry(frame.payload), now
            elif frame.cmd == MSP_BRIDGE_TOF and len(frame.payload) >= 6:
                tof = decode_bridge_tof(frame.payload)
                self.tof, self.t_tof = tof, now
                # The bridge stamps every range with its own age, so we can recover WHEN the
                # sensor ranged rather than when the reply happened to arrive. Consecutive polls
                # re-serve the same sample with a growing age -> the same stamp, which is how
                # height_sample() tells a NEW range from a re-served one.
                if tof["range_m"] is not None:
                    self.t_tof_sample = now - tof["age_ms"] / 1000.0
            elif frame.cmd == MSP_BRIDGE_FLOW and len(frame.payload) >= 19:
                self.flow, self.t_flow = decode_bridge_flow(frame.payload), now

    def flow_delta(self, now: float) -> tuple[int, int, float, int] | None:
        """Motion since the previous call: ``(dx_counts, dy_counts, dt_s, squal)``.

        **Stateful and destructive by contract** — each call consumes the interval, so exactly
        one caller may use it per tick (the underlying MSP reply is non-destructive, so a
        ``bench.py flow`` window running alongside a flight is still harmless; two callers
        *inside* the pilot would not be).

        ``dt_s`` comes from the BRIDGE's own sample stamps, not from host arrival times: the
        counts were accumulated over that interval and dividing them by a host-jittered dt is
        what would turn a clean flow signal into a noisy velocity. Returns ``None`` until a
        second valid frame has arrived, and whenever the sensor is absent/stale — never a zero,
        which a caller would read as "not moving" rather than "no data".

        Counts are NOT velocity: ``v = dx/dt * rad_per_count * height``, where
        ``rad_per_count`` is a MEASURED constant (firmware/xiao_bridge/README.md's slide test)
        and ``height`` is the ToF's. Deliberately not done here — this layer reports what the
        sensor said.
        """
        if self.flow is None or not self.flow["valid"] or now - self.t_flow > 0.2:
            return None
        cur = self.flow
        prev, self._flow_prev = self._flow_prev, cur
        if prev is None or prev["t_ms"] == cur["t_ms"]:
            return None  # first frame, or the same sample re-served: no new interval
        dt_ms = wrap_delta(cur["t_ms"], prev["t_ms"], 32)
        if dt_ms <= 0:
            return None  # bridge rebooted (its clock restarted); resync on the next frame
        return (
            wrap_delta(cur["sum_dx"], prev["sum_dx"], 32),
            wrap_delta(cur["sum_dy"], prev["sum_dy"], 32),
            dt_ms / 1000.0,
            cur["squal"],
        )

    def height_sample(self, now: float) -> tuple[float, float] | None:
        """Newest valid ToF range as ``(range_m, sample_time)``; None if absent/invalid/stale.

        ``sample_time`` is when the sensor actually ranged, NOT when the frame arrived. Callers
        that tilt-correct the range MUST pair it with the attitude from that instant: the range
        and the attitude ride different MSP replies at different rates, and projecting a held
        range through a fresh attitude manufactures height steps that never happened (a 0.45 m
        phantom step showed up in flight_1785399097, 180 ms before the tumble).
        """
        if self.tof is None or self.tof["range_m"] is None:
            return None
        if now - self.t_tof > 0.2 or now - self.t_tof_sample > 0.2:
            return None
        return self.tof["range_m"], self.t_tof_sample

    def height_m(self, now: float) -> float | None:
        """Measured height (bridge VL53L1X, m); None if absent, invalid, or stale (>0.2 s)."""
        sample = self.height_sample(now)
        return None if sample is None else sample[0]

    def bridge_loop_max_ms(self) -> int | None:
        """The bridge's worst ``loop()`` duration in its current 5 s window (ms).

        Deliberately NOT staleness-gated: this is a 5 s-window maximum, so the last value the
        bridge sent is the right answer even if the reply is a moment old — and if the bridge
        has gone silent entirely there is no newer number to have. ``None`` on pre-2026-07-30
        firmware, which sends a 6-byte ToF reply with no such field.
        """
        return None if self.tof is None else self.tof.get("loop_max_ms")

    def rpm_rms(self, now: float) -> float | None:
        """RMS motor RPM (thrust ~ sum(rpm^2)); None if stale, missing, or bidir-DShot off."""
        if self.mt is None or now - self.t_mt > 0.2:
            return None
        vals = [m["rpm"] for m in self.mt]
        if len(vals) < 4 or any(v < 500 for v in vals):
            return None
        return math.sqrt(sum(v * v for v in vals) / len(vals))

    def obs_age(self, now: float) -> float:
        if self.att is None or self.imu is None:
            return float("inf")
        return now - min(self.t_att, self.t_imu)

    def obs(self) -> list[float]:
        return obs_from_msp(self.att, self.imu)


def stream_rc(fc: _MspEndpoint, us4: list[int]) -> None:
    # AETR + aux low. Aux is not overridden (mask) — values here are ignored by the FC.
    fc.send(MSP_SET_RAW_RC, pack_rc_channels(us4 + [1000, 1000, 1000, 1000]))
