"""Non-blocking MSP telemetry poller + the RC-stream helper — moved verbatim from ``pilot.py``.

:class:`Telemetry` sits on top of an :class:`MspUdpClient` (or any ``_MspEndpoint``): each
:meth:`Telemetry.poll` fires the attitude/IMU/(optional analog/rc/rpm/bridge-ToF) queries and drains every
waiting datagram, so the control loop never blocks. :func:`stream_rc` packs one AETR RC frame.
Pure stdlib — imports only the codec (``neural_whoop.bench.msp``) and this package's policy layer.
"""

from __future__ import annotations

import math

from neural_whoop.bench.msp import (
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_BRIDGE_TOF,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    MspUdpClient,
    decode_analog,
    decode_attitude,
    decode_bridge_tof,
    decode_motor_telemetry,
    decode_raw_imu,
    decode_u16s,
    pack_rc_channels,
)

from .policy import obs_from_msp


class Telemetry:
    """Fire-and-forget MSP pollers + latest-known state. Never blocks the control loop."""

    def __init__(self, fc: MspUdpClient) -> None:
        self.fc = fc
        # Non-blocking reads: poll() must drain EVERY waiting datagram each tick (we send 2-3
        # queries per tick; one blocking read per tick would back-log replies -> stale obs).
        self.fc._sock.settimeout(0.0)
        self.att: dict | None = None
        self.imu: dict | None = None
        self.vbat: float | None = None
        self.rc: tuple[int, ...] | None = None
        self.mt: list[dict] | None = None
        self.tof: dict | None = None
        self.t_att = 0.0
        self.t_imu = 0.0
        self.t_rc = 0.0
        self.t_mt = 0.0
        self.t_tof = 0.0

    def poll(self, now: float, want_analog: bool = False, want_rc: bool = False,
             want_rpm: bool = False, want_tof: bool = False) -> None:
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
                self.tof, self.t_tof = decode_bridge_tof(frame.payload), now

    def height_m(self, now: float) -> float | None:
        """Measured height (bridge VL53L1X, m); None if absent, invalid, or stale (>0.2 s)."""
        if self.tof is None or now - self.t_tof > 0.2:
            return None
        return self.tof["range_m"]

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


def stream_rc(fc: MspUdpClient, us4: list[int]) -> None:
    # AETR + aux low. Aux is not overridden (mask) — values here are ignored by the FC.
    fc.send(MSP_SET_RAW_RC, pack_rc_channels(us4 + [1000, 1000, 1000, 1000]))
