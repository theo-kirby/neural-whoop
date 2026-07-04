"""MSP v1 (MultiWii Serial Protocol) codec + client for Betaflight bench work.

Frame layout (v1): ``$M<`` (to FC) / ``$M>`` (from FC) / ``$M!`` (error), then
``size u8, cmd u8, payload[size], checksum u8`` where checksum = XOR of size, cmd and payload.

Scope is the Stage-0 bench ladder (docs/SIM2REAL.md): identify the board, stream telemetry,
inject RC via ``MSP_SET_RAW_RC`` (the offboard-control seam), spin motors props-off. MSP v2
(needed later for the flow-deck sensor messages) is a documented follow-up, not implemented.

The codec half of this module is pure stdlib and unit-tested without hardware; only
:class:`MspClient` touches pyserial (the ``bench`` extra), imported lazily.

Channel order note: Betaflight's ``rcData`` (what ``MSP_SET_RAW_RC`` writes and ``MSP_RC``
reads) is ``ROLL, PITCH, YAW, THROTTLE, AUX1..`` — MultiWii legacy, NOT the AETR wire order of
serial receivers. Verify on the bench with the Configurator receiver tab before trusting it;
that loopback check is exactly what ``scripts/bench.py rc-test`` is for.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

# --- command ids (Betaflight src/main/msp/msp_protocol.h) ---------------------------------
MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_STATUS = 101
MSP_RAW_IMU = 102
MSP_MOTOR = 104
MSP_RC = 105
MSP_ATTITUDE = 108
MSP_ANALOG = 110
MSP_SET_RAW_RC = 200
MSP_SET_MOTOR = 214

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

    Scale factors are gyro/acc-config dependent (acc ≈ 1/512 g, gyro ≈ deg/s on modern BF, but
    do not trust these unverified) — the bench workflow records raw ints and calibrates against
    Configurator readings; see docs/SIM2REAL.md Stage 0.
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


def decode_fc_version(payload: bytes) -> str:
    major, minor, patch = struct.unpack("<BBB", payload[:3])
    return f"{major}.{minor}.{patch}"


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


class MspClient:
    """Blocking request/response MSP client over a serial port (pyserial, lazy import)."""

    def __init__(self, port: str, baud: int = 115200, timeout_s: float = 0.5) -> None:
        import serial  # the `bench` extra; deferred so the codec imports without it

        self._ser = serial.Serial(port, baudrate=baud, timeout=0.02)
        self._parser = MspParser()
        self._pending: list[MspFrame] = []
        self.timeout_s = timeout_s

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "MspClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send(self, cmd: int, payload: bytes = b"") -> None:
        """Fire-and-forget write (the SET_RAW_RC streaming path)."""
        self._ser.write(encode_msp_v1(cmd, payload))

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
        waiting = self._ser.in_waiting
        data = self._ser.read(waiting if waiting else 1)
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

    def set_motor(self, values: list[int]) -> None:
        if len(values) != 8:
            raise ValueError("MSP_SET_MOTOR wants exactly 8 u16 values (1000=stop)")
        self.send(MSP_SET_MOTOR, struct.pack("<8H", *[int(v) for v in values]))
