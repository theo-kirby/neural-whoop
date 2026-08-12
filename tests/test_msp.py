"""MSP v1 codec + transport tests — the bench seam's unit layer.

Mostly pure stdlib and hardware-free. The one exception is the non-blocking-read contract at the
bottom, which opens a pty as a real serial port to exercise pyserial itself (skipped when the
``bench``/``studio`` extra is absent).
"""

import struct
import time

import pytest

from neural_whoop.bench.msp import (
    MSP_ATTITUDE,
    MSP_RC,
    MSP_SET_RAW_RC,
    MspParser,
    decode_analog,
    decode_attitude,
    decode_mode_ranges,
    decode_raw_imu,
    decode_u16s,
    encode_msp_v1,
    pack_rc_channels,
)


def _response(cmd: int, payload: bytes) -> bytes:
    return encode_msp_v1(cmd, payload, header=b"$M>")


def test_encode_known_frame():
    # MSP_ATTITUDE request: $M< size=0 cmd=108 ck=0^108=108
    assert encode_msp_v1(MSP_ATTITUDE) == b"$M<" + bytes([0, 108, 108])


def test_encode_checksum_covers_payload():
    frame = encode_msp_v1(MSP_SET_RAW_RC, b"\x01\x02")
    size, cmd, p0, p1, ck = frame[3], frame[4], frame[5], frame[6], frame[7]
    assert ck == size ^ cmd ^ p0 ^ p1


def test_parser_roundtrip_and_chunking():
    payload = struct.pack("<hhh", -123, 45, 270)
    raw = _response(MSP_ATTITUDE, payload)
    parser = MspParser()
    frames = []
    for i in range(len(raw)):  # worst case: one byte at a time
        frames.extend(parser.feed(raw[i : i + 1]))
    assert len(frames) == 1
    assert frames[0].cmd == MSP_ATTITUDE
    assert not frames[0].is_error
    assert decode_attitude(frames[0].payload) == {
        "roll_deg": -12.3,
        "pitch_deg": 4.5,
        "yaw_deg": 270.0,
    }


def test_parser_resyncs_after_garbage_and_bad_checksum():
    good = _response(MSP_RC, struct.pack("<8H", *range(1000, 1008)))
    corrupt = bytearray(good)
    corrupt[-1] ^= 0xFF  # break the checksum
    stream = b"\x00noise$M" + bytes(corrupt) + good
    frames = MspParser().feed(stream)
    assert len(frames) == 1  # corrupt frame dropped, good frame recovered
    assert decode_u16s(frames[0].payload) == tuple(range(1000, 1008))


def test_parser_error_frame_flag():
    frames = MspParser().feed(encode_msp_v1(200, header=b"$M!"))
    assert len(frames) == 1 and frames[0].is_error


def test_pack_rc_channels_clamps_and_orders():
    payload = pack_rc_channels([1500, 1500, 2500, 100])
    assert decode_u16s(payload) == (1500, 1500, 2115, 885)
    with pytest.raises(ValueError):
        pack_rc_channels([1500])  # too few


def test_decode_analog_prefers_high_res_voltage():
    legacy = struct.pack("<BHHh", 41, 120, 99, 250)
    assert decode_analog(legacy)["vbat_v"] == pytest.approx(4.1)
    modern = legacy + struct.pack("<H", 412)
    out = decode_analog(modern)
    assert out["vbat_v"] == pytest.approx(4.12)
    assert out["amps"] == pytest.approx(2.5)


def test_udp_client_roundtrip_against_fake_bridge():
    # The xiao_bridge is a transparent proxy, so a UDP socket that answers MSP requests IS a
    # faithful stand-in: this exercises MspUdpClient end-to-end without hardware.
    import socket
    import threading

    from neural_whoop.bench.msp import MspParser, MspUdpClient

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(2.0)
    port = srv.getsockname()[1]

    def fake_fc():
        parser = MspParser()
        data, addr = srv.recvfrom(2048)
        for frame in parser.feed(data):
            if frame.cmd == MSP_ATTITUDE:
                srv.sendto(_response(MSP_ATTITUDE, struct.pack("<hhh", 150, -30, 90)), addr)

    t = threading.Thread(target=fake_fc, daemon=True)
    t.start()
    with MspUdpClient("127.0.0.1", port=port) as fc:
        att = fc.attitude()
    t.join(2.0)
    srv.close()
    assert att == {"roll_deg": 15.0, "pitch_deg": -3.0, "yaw_deg": 90.0}


def test_decode_mode_ranges_skips_empty_slots_and_scales_steps():
    # ARM (perm 0) on aux1 steps 32-48, MSP OVERRIDE (perm 50) on aux3, one unused slot.
    payload = bytes([0, 0, 32, 48, 50, 2, 32, 48, 0, 0, 0, 0])
    ranges = decode_mode_ranges(payload)
    assert ranges == [
        {"perm_id": 0, "aux_idx": 0, "lo_us": 1700, "hi_us": 2100},
        {"perm_id": 50, "aux_idx": 2, "lo_us": 1700, "hi_us": 2100},
    ]


def test_decode_raw_imu_keeps_raw_units():
    payload = struct.pack("<9h", 1, -2, 512, 10, -20, 30, 0, 0, 0)
    out = decode_raw_imu(payload)
    assert out["acc_raw"] == (1, -2, 512)
    assert out["gyro_raw"] == (10, -20, 30)


def test_decode_bridge_tof_gates_range_m():
    from neural_whoop.bench.msp import decode_bridge_tof

    # Fresh valid sample: range_m populated. Pre-2026-07-30 firmware sends 6 bytes and carries
    # no loop_max_ms; the decoder must still accept it (the bridge is flashed independently of
    # the host, so both generations are live at once).
    p = struct.pack("<HBHB", 743, 0, 24, 1)
    out = decode_bridge_tof(p)
    assert out == {"range_m": 0.743, "range_mm": 743, "status": 0, "age_ms": 24,
                   "sensor_ok": True, "loop_max_ms": None}

    # Current firmware appends u16 loop_max_ms (worst loop() stall in the last 5 s window).
    out8 = decode_bridge_tof(struct.pack("<HBHBH", 743, 0, 24, 1, 97))
    assert out8["range_m"] == 0.743 and out8["loop_max_ms"] == 97

    # Invalid status (VL53L1X wrap/no-return), stale sample, or absent sensor -> range_m None.
    assert decode_bridge_tof(struct.pack("<HBHB", 743, 4, 24, 1))["range_m"] is None
    assert decode_bridge_tof(struct.pack("<HBHB", 743, 0, 900, 1))["range_m"] is None
    never = decode_bridge_tof(struct.pack("<HBHB", 0xFFFF, 0xFF, 0xFFFF, 0))
    assert never["range_m"] is None and never["sensor_ok"] is False


def test_decode_bridge_flow_is_cumulative_and_gated():
    from neural_whoop.bench.msp import decode_bridge_flow

    # i32 sum_dx, i32 sum_dy, u32 t_ms, u16 n_frames, u8 squal, u8 motion, u8 ok, u16 age_ms
    p = struct.pack("<iiIHBBBH", 1200, -350, 90_000, 4500, 78, 1, 1, 12)
    out = decode_bridge_flow(p)
    assert out["sum_dx"] == 1200 and out["sum_dy"] == -350  # SIGNED: backwards motion is real
    assert out["t_ms"] == 90_000 and out["squal"] == 78
    assert out["motion"] is True and out["sensor_ok"] is True and out["valid"] is True

    # Absent sensor, never-sampled, and stale all fail `valid` — but the counters still decode,
    # so a caller can log them without branching.
    assert decode_bridge_flow(struct.pack("<iiIHBBBH", 0, 0, 0, 0, 0, 0, 0, 0xFFFF))["valid"] is False
    assert decode_bridge_flow(struct.pack("<iiIHBBBH", 5, 5, 0, 1, 60, 0, 1, 3))["valid"] is False
    assert decode_bridge_flow(struct.pack("<iiIHBBBH", 5, 5, 900, 1, 60, 0, 1, 400))["valid"] is False

    # A blind sensor over a featureless floor is FRESH and VALID with zero counts and low squal:
    # freshness cannot detect it, which is why squal is decoded rather than folded into `valid`.
    blind = decode_bridge_flow(struct.pack("<iiIHBBBH", 0, 0, 90_000, 4500, 2, 0, 1, 10))
    assert blind["valid"] is True and blind["squal"] == 2


def test_wrap_delta_survives_counter_rollover():
    from neural_whoop.bench.msp import wrap_delta

    assert wrap_delta(105, 100, 32) == 5
    assert wrap_delta(95, 100, 32) == -5
    # u32 millisecond clock rolling over (49.7 days of bridge uptime): the delta must stay small,
    # not become ~4.3e9 — which downstream is a velocity divided by a 49-day interval.
    assert wrap_delta(3, (1 << 32) - 2, 32) == 5
    # i32 count sums wrapping at the positive rail.
    assert wrap_delta(-(1 << 31) + 2, (1 << 31) - 3, 32) == 5
    # u16 frame counter.
    assert wrap_delta(2, 65534, 16) == 4


# --- non-blocking reads: the flight-loop contract -------------------------------------------
# `Telemetry` fires 3-5 queries per control tick and then drains until dry, against a 22 ms
# budget at 45 Hz. A transport whose `_read()` waits for the NEXT byte burns most of that tick
# doing nothing. This used to be handled by `fc._sock.settimeout(0)` in Telemetry — UDP-only,
# and silently wrong the moment the ESP-NOW dongle put a serial port on the flight path
# (docs/ESPNOW.md). These pin the per-transport behaviour instead.


def test_set_nonblocking_zeroes_the_udp_socket_timeout():
    from neural_whoop.bench.msp import MspUdpClient

    with MspUdpClient("127.0.0.1", port=59999) as fc:
        assert fc._sock.gettimeout() == 0.02  # blocking-ish by default (bench request/response)
        fc.set_nonblocking()
        assert fc._sock.gettimeout() == 0.0
        assert fc._read() == b""  # nothing waiting -> returns immediately, no exception


def test_set_nonblocking_base_default_is_a_noop():
    # Transports that never block (the in-process fakes) inherit a no-op rather than needing a
    # dummy socket to satisfy the caller.
    from neural_whoop.bench.msp import _MspEndpoint

    class Fake(_MspEndpoint):
        def _write(self, raw: bytes) -> None:
            pass

        def _read(self) -> bytes:
            return b""

    Fake().set_nonblocking()  # must not raise


def test_serial_read_blocks_until_set_nonblocking():
    """The regression that would otherwise only show up as a sluggish flight loop.

    With the stock 20 ms port timeout, `_read()` on an idle port falls back to `read(1)` and
    waits — measured ~30 ms here, i.e. MORE than a whole control tick, every tick. Uses a pty as
    a real serial port so this exercises pyserial itself, not a stand-in.
    """
    import os

    pytest.importorskip("serial")
    from neural_whoop.bench.msp import MspClient

    master, slave = os.openpty()
    fc = MspClient(os.ttyname(slave), baud=115200)
    try:
        t0 = time.perf_counter()
        assert fc._read() == b""
        blocking_ms = (time.perf_counter() - t0) * 1e3
        assert blocking_ms > 15.0, f"expected the port timeout to bite, took {blocking_ms:.1f} ms"

        fc.set_nonblocking()
        assert fc._ser.timeout == 0
        t0 = time.perf_counter()
        assert fc._read() == b""
        idle_ms = (time.perf_counter() - t0) * 1e3
        assert idle_ms < 10.0, f"non-blocking read still waited {idle_ms:.1f} ms"

        # ...and it still returns everything that HAS arrived (the drain path must not go quiet).
        os.write(master, encode_msp_v1(MSP_ATTITUDE, struct.pack("<hhh", 150, -30, 90),
                                       header=b"$M>"))
        deadline = time.monotonic() + 2.0
        frames: list = []
        while time.monotonic() < deadline and not frames:
            frames.extend(fc._drain())
        assert len(frames) == 1
        assert decode_attitude(frames[0].payload)["roll_deg"] == 15.0
    finally:
        fc.close()
        os.close(master)


def test_telemetry_makes_its_transport_nonblocking():
    """Telemetry must go through the transport seam, not reach into a UDP socket attribute."""
    from neural_whoop.bench.msp import _MspEndpoint
    from neural_whoop.pilot import Telemetry

    class Fake(_MspEndpoint):
        def __init__(self) -> None:
            super().__init__()
            self.nonblocking = False

        def set_nonblocking(self) -> None:
            self.nonblocking = True

        def _write(self, raw: bytes) -> None:
            pass

        def _read(self) -> bytes:
            return b""

    fc = Fake()
    Telemetry(fc)
    assert fc.nonblocking
