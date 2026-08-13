"""MSP v1 (MultiWii Serial Protocol) codec + client for Betaflight bench work.

Frame layout (v1): ``$M<`` (to FC) / ``$M>`` (from FC) / ``$M!`` (error), then
``size u8, cmd u8, payload[size], checksum u8`` where checksum = XOR of size, cmd and payload.

Scope is the Stage-0 bench ladder (docs/SIM2REAL.md): identify the board, stream telemetry,
inject RC via ``MSP_SET_RAW_RC`` (the offboard-control seam), spin motors props-off. MSP v2
(needed later for the flow-deck sensor messages) is a documented follow-up, not implemented.

The codec half of this module is pure stdlib and unit-tested without hardware; only
:class:`MspClient` touches pyserial (the ``bench`` extra), imported lazily.

Channel order note (bench-verified 2026-07-05 on the Air65 II): the two directions DIFFER.
``MSP_SET_RAW_RC`` payloads are in WIRE order and the FC applies its channel map — AETR here,
so send ``[roll, pitch, THROTTLE, yaw, aux..]``. ``MSP_RC`` reads back ``rcData`` in
``ROLL, PITCH, YAW, THROTTLE, AUX1..`` (MultiWii legacy). ``scripts/bench.py rc-test`` is the
loopback that proves the mapping on any new board/config — rerun it if ``map`` changes.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

# --- command ids (Betaflight src/main/msp/msp_protocol.h) ---------------------------------
MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_MODE_RANGES = 34
MSP_STATUS = 101
MSP_RAW_IMU = 102
MSP_MOTOR = 104
MSP_RC = 105
MSP_ATTITUDE = 108
MSP_ALTITUDE = 109
MSP_ANALOG = 110
MSP_MOTOR_TELEMETRY = 139
MSP_SET_RAW_RC = 200
MSP_SET_MOTOR = 214

#: Bridge-local command (NOT a Betaflight id): the xiao_bridge answers it itself with the
#: latest reading from its downward VL53L1X ToF and never forwards it to the FC. Mirrored in
#: ``firmware/xiao_bridge/src/main.cpp`` (``kMspBridgeTof``) — change both together. Over USB
#: (no bridge in the path) the FC replies with an MSP error frame; treat that as "no ToF".
MSP_BRIDGE_TOF = 192

#: Bridge-local command: the xiao_bridge's PMW3901 optical-flow counts. Same interception rule
#: as MSP_BRIDGE_TOF (answered locally, never forwarded, MSP error over USB = no bridge).
#: Mirrored in ``firmware/xiao_bridge/src/main.cpp`` (``kMspBridgeFlow``).
MSP_BRIDGE_FLOW = 193

#: Bridge-local command: open the bridge's over-the-air reflash window (docs/ESPNOW.md "OTA").
#: The request payload must be :data:`OTA_MAGIC` — the command drops the flight link on the
#: ESP-NOW build, so a bare id must never be enough. Reply: u8 accepted, u8 will_reboot.
#: Mirrored in ``firmware/xiao_bridge/src/main.cpp`` (``kMspBridgeOta``).
MSP_BRIDGE_OTA = 194
OTA_MAGIC = b"NWOT"

#: Betaflight rcData index order (see module docstring — verify on bench).
RC_CHANNEL_ORDER = ("roll", "pitch", "yaw", "throttle", "aux1", "aux2", "aux3", "aux4")

_HDR_REQUEST = b"$M<"
_HDR_RESPONSE = b"$M>"
_HDR_ERROR = b"$M!"


class MspError(Exception):
    """FC replied with an MSP error frame, or a frame failed checksum."""


class MspTimeout(TimeoutError):
    """No matching MSP response within the deadline."""


def _xor(size: int, cmd: int, payload: bytes) -> int:
    ck = size ^ cmd
    for b in payload:
        ck ^= b
    return ck & 0xFF


def encode_msp_v1(cmd: int, payload: bytes = b"", *, header: bytes = _HDR_REQUEST) -> bytes:
    if not 0 <= cmd <= 0xFF:
        raise ValueError(f"MSP v1 cmd out of range: {cmd}")
    if len(payload) > 0xFF:
        raise ValueError(f"MSP v1 payload too long: {len(payload)}")
    return header + bytes([len(payload), cmd]) + payload + bytes([_xor(len(payload), cmd, payload)])


@dataclass(frozen=True)
class MspFrame:
    cmd: int
    payload: bytes
    is_error: bool


class MspParser:
    """Incremental MSP v1 frame parser: feed bytes in any chunking, collect frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[MspFrame]:
        self._buf.extend(data)
        frames: list[MspFrame] = []
        while True:
            start = self._buf.find(b"$M")
            if start < 0:
                # keep a possible trailing '$'
                del self._buf[: max(0, len(self._buf) - 1)]
                return frames
            if start:
                del self._buf[:start]
            if len(self._buf) < 5:  # header(3) + size + cmd
                return frames
            direction = self._buf[2]
            if direction not in (ord(">"), ord("<"), ord("!")):
                del self._buf[:2]
                continue
            size = self._buf[3]
            end = 5 + size + 1
            if len(self._buf) < end:
                return frames
            cmd = self._buf[4]
            payload = bytes(self._buf[5 : 5 + size])
            ok = self._buf[end - 1] == _xor(size, cmd, payload)
            del self._buf[:end]
            if not ok:
                continue  # corrupt frame: drop silently, stream self-heals on next header
            frames.append(MspFrame(cmd=cmd, payload=payload, is_error=direction == ord("!")))


# --- payload decoders (return plain dicts; raw fields kept raw where scaling is board-lore) ---


def decode_attitude(payload: bytes) -> dict:
    """MSP_ATTITUDE: roll/pitch in 0.1 deg, yaw (heading) in deg."""
    roll, pitch, yaw = struct.unpack("<hhh", payload[:6])
    return {"roll_deg": roll / 10.0, "pitch_deg": pitch / 10.0, "yaw_deg": float(yaw)}


def decode_raw_imu(payload: bytes) -> dict:
    """MSP_RAW_IMU: 9 int16 — acc[3], gyro[3], mag[3], in RAW device units.

    Gyro scale VERIFIED (source + flight data, 2026-07-05): Betaflight's gyroRateDps()
    returns gyroADCf / rawSensorDev->scale — the filtered rate in raw LSB units, 16.384
    LSB per deg/s on a +-2000 dps gyro (deg/s = raw * 2000/32768). It is NOT deg/s.
    Acc stays config-dependent lore; see docs/SIM2REAL.md Stage 0.
    """
    v = struct.unpack("<9h", payload[:18])
    return {"acc_raw": v[0:3], "gyro_raw": v[3:6], "mag_raw": v[6:9]}


def decode_analog(payload: bytes) -> dict:
    """MSP_ANALOG: legacy u8 vbat (0.1 V), u16 mAh, u16 rssi, i16 amps (0.01 A) [+ u16 vbat cV]."""
    vbat_dv, mah, rssi, amps = struct.unpack("<BHHh", payload[:7])
    out = {"vbat_v": vbat_dv / 10.0, "mah_drawn": mah, "rssi": rssi, "amps": amps / 100.0}
    if len(payload) >= 9:  # BF appends a higher-resolution voltage field
        out["vbat_v"] = struct.unpack("<H", payload[7:9])[0] / 100.0
    return out


#: MSP_STATUS sensor-present bitmask (Betaflight msp.c sensorFlags)
SENSOR_BITS = {"acc": 1, "baro": 2, "mag": 4, "gps": 8, "rangefinder": 16, "gyro": 32}


def decode_status_sensors(payload: bytes) -> dict:
    """MSP_STATUS: cycleTime u16, i2cErrors u16, then the sensor-present u16 bitmask."""
    sensors = struct.unpack_from("<H", payload, 4)[0]
    return {name: bool(sensors & bit) for name, bit in SENSOR_BITS.items()}


def decode_altitude(payload: bytes) -> dict:
    """MSP_ALTITUDE: i32 estimated altitude (cm), i16 vario (cm/s). Zeros without a source."""
    alt_cm, vario = struct.unpack("<ih", payload[:6])
    return {"alt_m": alt_cm / 100.0, "vario_ms": vario / 100.0}


def decode_motor_telemetry(payload: bytes) -> list[dict]:
    """MSP_MOTOR_TELEMETRY: u8 count, then per motor rpm u32, invalid%% u16 (1/100),
    escTemp u8, escVoltage u16, escCurrent u16, escConsumption u16 (13 bytes/motor).
    RPM requires bidirectional DShot; otherwise rpm reads 0."""
    if not payload:
        return []
    out = []
    off = 1
    for _ in range(payload[0]):
        if off + 13 > len(payload):
            break
        rpm, invalid, temp, volt, curr, cons = struct.unpack_from("<IHBHHH", payload, off)
        out.append({"rpm": rpm, "invalid_pct": invalid / 100.0, "esc_temp_c": temp})
        off += 13
    return out


def decode_bridge_tof(payload: bytes) -> dict:
    """MSP_BRIDGE_TOF: u16 range_mm, u8 VL53L1X range_status (0 = valid), u16 age_ms
    (65535 = never sampled), u8 sensor_ok, and (firmware >= 2026-07-30) u16 loop_max_ms.

    ``range_m`` is ``None`` unless the sensor is present, the sample is valid (status 0) and
    fresh (age < 200 ms) — one field the callers can trust without re-deriving the gating.

    ``loop_max_ms`` is the bridge's worst ``loop()`` duration in the current 5 s window, i.e.
    how long it went without servicing UDP. It is the direct measure of the host-side
    ``obs_age_ms`` spikes; ``None`` on pre-2026-07-30 firmware, which sends only 6 bytes.
    """
    range_mm, status, age_ms, ok = struct.unpack("<HBHB", payload[:6])
    valid = bool(ok) and status == 0 and age_ms < 200
    return {
        "range_m": range_mm / 1000.0 if valid else None,
        "range_mm": range_mm,
        "status": status,
        "age_ms": age_ms,
        "sensor_ok": bool(ok),
        "loop_max_ms": struct.unpack("<H", payload[6:8])[0] if len(payload) >= 8 else None,
    }


def wrap_delta(new: int, old: int, bits: int) -> int:
    """Difference two counters that wrap at ``bits``, returning the signed short-way delta.

    The bridge's cumulative flow sums are int32 and its timestamp is a u32 millisecond clock;
    both wrap (the clock every 49.7 days, the sums after ~60 hours of continuous motion). A
    plain subtraction across a wrap yields a ~4e9 jump, which downstream becomes an absurd
    velocity — cheap to get right here, impossible to notice later.
    """
    span = 1 << bits
    return (new - old + span // 2) % span - span // 2


def decode_bridge_flow(payload: bytes) -> dict:
    """MSP_BRIDGE_FLOW: i32 sum_dx, i32 sum_dy, u32 t_ms, u16 n_frames, u8 squal, u8 motion,
    u8 sensor_ok, u16 age_ms (65535 = never sampled).

    The sums are **cumulative counts since the bridge booted**, not counts since the last read:
    callers difference two replies to get ``(dx, dy, dt)``. See the firmware header for why —
    a destructive read loses motion on any dropped packet and cannot tolerate a second client.

    ``t_ms`` is the *bridge's* millisecond stamp of the newest sample, so a differenced ``dt``
    is measured in the bridge's own clock and carries none of the host's polling jitter. That
    matters: the count sum divided by a jittery dt is exactly how a clean flow signal becomes a
    noisy velocity.

    ``valid`` gates the way ``decode_bridge_tof`` does — sensor present, ever sampled, and the
    sample fresh (age < 200 ms). It says nothing about whether the counts are *meaningful*:
    that is ``squal`` (surface quality), which collapses over a featureless floor while the
    frames keep arriving on time.
    """
    sum_dx, sum_dy, t_ms, n_frames, squal, motion, ok, age_ms = struct.unpack(
        "<iiIHBBBH", payload[:19]
    )
    return {
        "sum_dx": sum_dx,
        "sum_dy": sum_dy,
        "t_ms": t_ms,
        "n_frames": n_frames,
        "squal": squal,
        "motion": bool(motion),
        "sensor_ok": bool(ok),
        "age_ms": age_ms,
        "valid": bool(ok) and t_ms != 0 and age_ms < 200,
    }


def decode_fc_version(payload: bytes) -> str:
    major, minor, patch = struct.unpack("<BBB", payload[:3])
    return f"{major}.{minor}.{patch}"


def decode_mode_ranges(payload: bytes) -> list[dict]:
    """MSP_MODE_RANGES: 4 bytes per slot — box permanentId, aux index, start/end step.

    Steps map to microseconds as ``900 + 25 * step``; a slot with start >= end is unused.
    Permanent ids are Betaflight's stable box ids (msp_box.c): ARM=0, MSP OVERRIDE=50, ...
    This is how a host discovers WHICH aux channel a Modes-tab switch lives on, instead of
    guessing from rcData edges (the arm switch is also just an aux channel).
    """
    out = []
    for i in range(0, len(payload) - 3, 4):
        perm_id, aux_idx, lo, hi = payload[i : i + 4]
        if lo >= hi:
            continue
        out.append({"perm_id": perm_id, "aux_idx": aux_idx,
                    "lo_us": 900 + 25 * lo, "hi_us": 900 + 25 * hi})
    return out


def decode_u16s(payload: bytes) -> tuple[int, ...]:
    """Generic n×u16 decoder (MSP_RC channels, MSP_MOTOR outputs)."""
    n = len(payload) // 2
    return struct.unpack(f"<{n}H", payload[: 2 * n])


def pack_rc_channels(channels: list[int] | tuple[int, ...]) -> bytes:
    """Pack MSP_SET_RAW_RC payload; values clamped to the 885-2115 us Betaflight-valid band."""
    if not 4 <= len(channels) <= 18:
        raise ValueError(f"expected 4-18 RC channels, got {len(channels)}")
    clamped = [min(2115, max(885, int(c))) for c in channels]
    return struct.pack(f"<{len(clamped)}H", *clamped)


class _MspEndpoint:
    """Blocking request/response MSP logic, transport-agnostic.

    Subclasses provide ``_write(raw)`` and ``_read() -> bytes`` (may return ``b""``); this
    base owns framing, matching, retries and the typed convenience getters. The same host
    code therefore drives the FC over USB serial (:class:`MspClient`) or through the
    xiao_bridge WiFi proxy (:class:`MspUdpClient`) — see ``firmware/xiao_bridge/``.
    """

    timeout_s: float = 0.5

    def __init__(self) -> None:
        self._parser = MspParser()
        self._pending: list[MspFrame] = []

    def _write(self, raw: bytes) -> None:
        raise NotImplementedError

    def _read(self) -> bytes:
        raise NotImplementedError

    def set_nonblocking(self) -> None:
        """Make :meth:`_read` return immediately with whatever has already arrived.

        The control loop (``neural_whoop.pilot.Telemetry``) fires 3-5 queries per tick and then
        drains until dry; a transport that blocks waiting for the *next* byte spends the whole
        tick budget in ``_read``. Each transport implements this its own way (UDP: a zero socket
        timeout; serial: ``timeout = 0`` plus reading only ``in_waiting``) — the base is a no-op
        for transports that never block, like the in-process fake bridge.
        """

    def close(self) -> None:  # pragma: no cover - transport-specific
        pass

    def __enter__(self) -> "_MspEndpoint":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send(self, cmd: int, payload: bytes = b"") -> None:
        """Fire-and-forget write (the SET_RAW_RC streaming path)."""
        self._write(encode_msp_v1(cmd, payload))

    def request(self, cmd: int, payload: bytes = b"", *, retries: int = 2) -> bytes:
        """Send and wait for the matching response frame; returns its payload."""
        for attempt in range(retries + 1):
            self.send(cmd, payload)
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                for frame in self._drain():
                    if frame.cmd != cmd:
                        continue  # unsolicited/stale frame from an earlier stream: skip
                    if frame.is_error:
                        raise MspError(f"FC rejected MSP cmd {cmd}")
                    return frame.payload
        raise MspTimeout(f"no response to MSP cmd {cmd} after {retries + 1} attempts")

    def _drain(self) -> list[MspFrame]:
        frames = self._pending
        self._pending = []
        data = self._read()
        if data:
            frames.extend(self._parser.feed(data))
        return frames

    # --- convenience wrappers -------------------------------------------------------------
    def fc_info(self) -> dict:
        api = self.request(MSP_API_VERSION)
        return {
            "api": f"{api[1]}.{api[2]}" if len(api) >= 3 else "?",
            "variant": self.request(MSP_FC_VARIANT).decode("ascii", "replace"),
            "version": decode_fc_version(self.request(MSP_FC_VERSION)),
        }

    def attitude(self) -> dict:
        return decode_attitude(self.request(MSP_ATTITUDE))

    def raw_imu(self) -> dict:
        return decode_raw_imu(self.request(MSP_RAW_IMU))

    def analog(self) -> dict:
        return decode_analog(self.request(MSP_ANALOG))

    def rc(self) -> tuple[int, ...]:
        return decode_u16s(self.request(MSP_RC))

    def motor(self) -> tuple[int, ...]:
        return decode_u16s(self.request(MSP_MOTOR))

    def set_raw_rc(self, channels: list[int] | tuple[int, ...]) -> None:
        self.send(MSP_SET_RAW_RC, pack_rc_channels(channels))

    def bridge_tof(self) -> dict:
        """Latest bridge ToF reading (see :func:`decode_bridge_tof`). Bridge-answered — over
        USB the FC errors this id, which surfaces as :class:`MspError`."""
        return decode_bridge_tof(self.request(MSP_BRIDGE_TOF))

    def bridge_flow(self) -> dict:
        """Latest bridge optical-flow counters (see :func:`decode_bridge_flow`). Cumulative —
        one call is a snapshot, motion needs two. Bridge-answered, like :meth:`bridge_tof`."""
        return decode_bridge_flow(self.request(MSP_BRIDGE_FLOW))

    def bridge_ota(self) -> dict:
        """Ask the bridge to open its OTA reflash window (see :data:`MSP_BRIDGE_OTA`).

        Returns ``{"accepted": bool, "will_reboot": bool}``. ``will_reboot`` means the ESP-NOW
        build acked and is now LEAVING the link to serve ArduinoOTA — expect it to be
        unreachable here until the window closes. On the WiFi/UDP build OTA runs full-time, so
        ``will_reboot`` is False and the link stays up. ``retries=0``: a retried magic packet
        could land after the ack and be lost anyway, and the first send either worked or the
        link is down."""
        p = self.request(MSP_BRIDGE_OTA, OTA_MAGIC, retries=0)
        return {"accepted": bool(p[0]) if len(p) >= 1 else False,
                "will_reboot": bool(p[1]) if len(p) >= 2 else False}

    def set_motor(self, values: list[int]) -> None:
        if len(values) != 8:
            raise ValueError("MSP_SET_MOTOR wants exactly 8 u16 values (1000=stop)")
        self.send(MSP_SET_MOTOR, struct.pack("<8H", *[int(v) for v in values]))


class MspClient(_MspEndpoint):
    """MSP over a USB serial port (pyserial — the ``bench`` extra, imported lazily).

    Two things are on the other end of this port: the flight controller itself (plugged in over
    USB, the Stage-0 bench setup) or the **ESP-NOW dongle** (``firmware/xiao_bridge/`` env
    ``espnow_dongle``), which relays raw MSP frames to the drone's bridge over the air. The
    protocol is identical either way, which is why the ESP-NOW link needed no new client — see
    ``docs/ESPNOW.md``.
    """

    def __init__(self, port: str, baud: int = 115200, timeout_s: float = 0.5) -> None:
        import serial  # deferred so the codec imports without the bench extra

        super().__init__()
        self._ser = serial.Serial(port, baudrate=baud, timeout=0.02)
        self.timeout_s = timeout_s
        self._nonblocking = False

    def close(self) -> None:
        self._ser.close()

    def set_nonblocking(self) -> None:
        # Both halves matter. `timeout = 0` alone still lets `read(1)` below wait for a byte on
        # some backends, and `read(1)` alone would block for the port's 20 ms timeout — either
        # way the flight loop stalls most of its 22 ms budget in here, every tick.
        self._ser.timeout = 0
        self._nonblocking = True

    def _write(self, raw: bytes) -> None:
        self._ser.write(raw)

    def _read(self) -> bytes:
        waiting = self._ser.in_waiting
        if self._nonblocking:
            return self._ser.read(waiting) if waiting else b""
        return self._ser.read(waiting if waiting else 1)


class MspUdpClient(_MspEndpoint):
    """MSP through the xiao_bridge WiFi proxy (raw MSP frames in UDP datagrams).

    Stdlib-only. The bridge replies to whichever host:port last commanded it, so a single
    socket per session both sends and receives. Default port matches the firmware's 14550.
    """

    def __init__(self, host: str, port: int = 14550, timeout_s: float = 0.5) -> None:
        import socket

        super().__init__()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.02)
        self._addr = (host, port)
        self.timeout_s = timeout_s

    def close(self) -> None:
        self._sock.close()

    def set_nonblocking(self) -> None:
        self._sock.settimeout(0.0)

    def _write(self, raw: bytes) -> None:
        self._sock.sendto(raw, self._addr)

    def _read(self) -> bytes:
        import socket

        try:
            data, _ = self._sock.recvfrom(2048)
            return data
        except (TimeoutError, socket.timeout, BlockingIOError):
            return b""
