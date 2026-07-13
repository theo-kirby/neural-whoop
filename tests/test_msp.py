"""MSP v1 codec tests — pure stdlib, no serial port needed (the bench seam's unit layer)."""

import struct

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

    # Fresh valid sample: range_m populated.
    p = struct.pack("<HBHB", 743, 0, 24, 1)
    out = decode_bridge_tof(p)
    assert out == {"range_m": 0.743, "range_mm": 743, "status": 0, "age_ms": 24, "sensor_ok": True}

    # Invalid status (VL53L1X wrap/no-return), stale sample, or absent sensor -> range_m None.
    assert decode_bridge_tof(struct.pack("<HBHB", 743, 4, 24, 1))["range_m"] is None
    assert decode_bridge_tof(struct.pack("<HBHB", 743, 0, 900, 1))["range_m"] is None
    never = decode_bridge_tof(struct.pack("<HBHB", 0xFFFF, 0xFF, 0xFFFF, 0))
    assert never["range_m"] is None and never["sensor_ok"] is False
