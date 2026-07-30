#!/usr/bin/env python
"""Stage-0 bench CLI: talk to the real Air65 II over USB (docs/SIM2REAL.md).

Subcommands (all read-only unless stated; writing ones require --ack-props-off):

  info        FC identity + battery sanity check (plug in over USB, run this first).
  monitor     Stream attitude / raw IMU / RC / battery at --hz; optional --csv.
  latency     MSP round-trip timing stats (the USB floor of the control-loop budget).
  rc-test     [writes] Stream safe MSP_SET_RAW_RC (sticks centered, throttle low, aux low)
              and echo back MSP_RC — the loopback proof that the MSP-override seam works and
              that the channel order is what we think. Needs `set msp_override_channels_mask`
              + the MSPRCOVERRIDE mode configured to see values land (see docs/SIM2REAL.md).
  tof         Live range from the bridge's downward VL53L1X (CJMCU-531) — bridge-answered
              (MSP_BRIDGE_TOF), so it needs the bridge in the path: --udp over WiFi, or
              --port <dongle> through the ESP-NOW dongle. The desk bring-up check after wiring.
  motor-test  [writes] Spin ONE motor briefly at a capped value. PROPS OFF. Value hard-capped.

Safety: nothing here ever raises an arm channel; arming stays with the human on the Pocket.

Examples:
  uv run python scripts/bench.py info --port /dev/ttyACM0
  uv run python scripts/bench.py monitor --hz 20 --csv runs/bench/monitor.csv
  uv run python scripts/bench.py rc-test --seconds 10 --ack-props-off
  uv run python scripts/bench.py motor-test --motor 0 --value 1050 --seconds 2 --ack-props-off
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neural_whoop.bench import (  # noqa: E402
    MSP_ATTITUDE,
    MSP_RAW_IMU,
    MspClient,
    MspError,
    MspTimeout,
    MspUdpClient,
)
from neural_whoop.bench.msp import MSP_BRIDGE_TOF  # noqa: E402

MOTOR_VALUE_HARD_CAP = 1200  # 1000=stop; keep bench spins gentle, no override flag offered
# MSP_SET_RAW_RC frames are in WIRE order and the FC applies its channel map (AETR on our
# Air65 II): [roll, pitch, THROTTLE, yaw, aux...]. Verified on the bench 2026-07-05 — sending
# RPYT here landed throttle=1500/yaw=1000 in rcData. rcData reads back as R,P,Y,T (msp.py).
NEUTRAL_RC = [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000]  # AETR: R,P centered; T low; Y centered


def _client(args: argparse.Namespace):
    if args.udp:
        host, _, port = args.udp.partition(":")
        return MspUdpClient(host, port=int(port) if port else 14550)
    return MspClient(args.port, baud=args.baud)


def _link_hint(args: argparse.Namespace, exc: Exception) -> str:
    if args.udp:
        return (
            f"{exc}\n\n"
            "UDP link check:\n"
            f"  1. Run: python3 scripts/bench.py --udp {args.udp} tof\n"
            "     - if this also times out: wrong bridge IP/port, bridge firmware not running, "
            "or laptop and bridge are not on the same WiFi.\n"
            "     - if this works: WiFi is alive, but the bridge is not getting FC MSP replies.\n"
            "  2. Is the flight battery plugged in? The bridge runs off USB or the FC BEC, so it "
            "answers 'tof' with the FC dark -- but no FC power means no MSP replies, ever.\n"
            "  3. For FC replies, check Betaflight Ports: UART1 Configuration/MSP at 115200, "
            "then verify XIAO TX/RX wiring is crossed to the FC RX/TX and shares ground.\n"
            "  4. The bridge USB monitor should show 'commands flowing' when this command runs."
        )
    return (
        f"{exc}\n\n"
        "Serial link check: verify the port path, that Betaflight is not already held open by "
        "Configurator, and that the selected port speaks MSP at the requested baud.\n"
        "If this is the ESP-NOW dongle: check both boards are flashed with matching MACs and the "
        "same ESPNOW_CHANNEL, and that the drone bridge has power (docs/ESPNOW.md)."
    )


def _route_hint(args: argparse.Namespace, exc: OSError) -> str:
    """A socket-layer failure: the frame never left this machine, so no MSP advice applies."""
    if args.udp:
        return (
            f"{exc}\n\n"
            f"No route to the bridge at {args.udp} -- this is a socket/ARP failure, not an MSP\n"
            "timeout, so the bridge is absent rather than unresponsive. Running 'tof' will fail\n"
            "the same way; don't read anything into it.\n"
            "  1. Power the bridge: USB, or the flight battery via the FC BEC. With no power the\n"
            "     XIAO is simply not on the network.\n"
            "  2. Confirm the address. A stale ARP/mDNS cache keeps a dead address 'resolving'\n"
            "     for minutes after the board goes away, and DHCP may hand out a new lease on\n"
            "     the next boot -- 'pio device monitor' prints the real IP at boot, or use the\n"
            "     mDNS name: --udp whoop-bridge.local\n"
            "  3. Confirm this machine is on the same WiFi/subnet as the bridge."
        )
    return f"{exc}\n\nCould not open the serial port; check the device path and that nothing else holds it."


def cmd_info(args: argparse.Namespace) -> int:
    with _client(args) as fc:
        info = fc.fc_info()
        analog = fc.analog()
        att = fc.attitude()
    print(f"FC: {info['variant']} {info['version']} (MSP API {info['api']})")
    print(f"Battery: {analog['vbat_v']:.2f} V   drawn: {analog['mah_drawn']} mAh")
    print(f"Attitude: roll {att['roll_deg']:+.1f}  pitch {att['pitch_deg']:+.1f}  yaw {att['yaw_deg']:.0f}")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    writer = None
    fout = None
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        fout = open(args.csv, "w", newline="")
        writer = csv.writer(fout)
        writer.writerow(
            ["t", "roll_deg", "pitch_deg", "yaw_deg", "gx_raw", "gy_raw", "gz_raw",
             "ax_raw", "ay_raw", "az_raw", "vbat_v"] + [f"rc{i}" for i in range(8)]
        )
    period = 1.0 / args.hz
    t0 = time.monotonic()
    try:
        with _client(args) as fc:
            while True:
                t = time.monotonic() - t0
                att, imu, an, rc = fc.attitude(), fc.raw_imu(), fc.analog(), fc.rc()
                line = (
                    f"t={t:7.2f}  rpy=({att['roll_deg']:+6.1f},{att['pitch_deg']:+6.1f},"
                    f"{att['yaw_deg']:5.0f})  gyro={imu['gyro_raw']}  vbat={an['vbat_v']:.2f}V"
                    f"  rc={list(rc[:8])}"
                )
                print(line)
                if writer:
                    writer.writerow(
                        [f"{t:.4f}", att["roll_deg"], att["pitch_deg"], att["yaw_deg"],
                         *imu["gyro_raw"], *imu["acc_raw"], an["vbat_v"], *rc[:8]]
                    )
                time.sleep(max(0.0, period - ((time.monotonic() - t0) - t)))
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        if fout:
            fout.close()
            print(f"wrote {args.csv}")
    return 0


def _rtt_samples(fc, cmds: tuple, n: int) -> list[float]:
    """``n`` round-trip times (ms), cycling ``cmds`` so a late/duplicate reply can't match.

    MSP has no sequence ids and UDP duplicates are real on this LAN, so a stale reply to request
    N would otherwise satisfy request N+1 and report a fake sub-ms round trip.
    """
    out: list[float] = []
    fc.request(cmds[0])  # warm up
    for i in range(n):
        t0 = time.perf_counter()
        fc.request(cmds[i % len(cmds)])
        out.append((time.perf_counter() - t0) * 1e3)
    return out


def _rtt_line(label: str, times_ms: list[float]) -> None:
    s = sorted(times_ms)
    p = lambda q: s[min(len(s) - 1, int(q * len(s)))]  # noqa: E731
    print(f"  {label:<28} median {statistics.median(s):6.2f} ms  p90 {p(0.90):6.2f}  "
          f"p99 {p(0.99):6.2f}  max {s[-1]:6.2f}")


def cmd_latency(args: argparse.Namespace) -> int:
    bridge_ms = None
    with _client(args) as fc:
        fc_ms = _rtt_samples(fc, (MSP_ATTITUDE, MSP_RAW_IMU), args.n)
        # The isolation split: MSP_BRIDGE_TOF is answered by the BRIDGE and never reaches the FC,
        # so its round trip is the pure host<->bridge air path. Anything the FC path has on top
        # of it is UART + Betaflight MSP scheduling, not the radio. Attempted on BOTH transports:
        # over ESP-NOW the bridge is behind a serial port (the USB dongle), so --port carries the
        # same split. Only a direct USB cable to the FC has no bridge — there the FC rejects the
        # id and we say so instead of pretending.
        # Probe once, no retries, before committing to n samples. A bridge-less path normally
        # fails fast (Betaflight answers an unknown id with an error frame), but if the id merely
        # went UNANSWERED, request()'s 3 x 0.5 s retries would turn 500 samples into 12 minutes
        # of timeouts.
        try:
            fc.request(MSP_BRIDGE_TOF, retries=0)
            bridge_ms = _rtt_samples(fc, (MSP_BRIDGE_TOF,), args.n)
        except (MspError, MspTimeout):
            bridge_ms = None

    print(f"MSP round-trip over {args.n} requests:")
    _rtt_line("host->bridge->FC (ATT/IMU)", fc_ms)
    if bridge_ms is not None:
        _rtt_line("host->bridge only (ToF)", bridge_ms)
        air_p99 = sorted(bridge_ms)[min(len(bridge_ms) - 1, int(0.99 * len(bridge_ms)))]
        fc_p99 = sorted(fc_ms)[min(len(fc_ms) - 1, int(0.99 * len(fc_ms)))]
        print("\nWhere the tail lives: ", end="")
        if air_p99 > 0.5 * fc_p99:
            print(f"the AIR. The bridge-answered path alone carries p99 {air_p99:.0f} ms — the FC\n"
                  "  is not involved. Look at the radio: a dedicated AP/channel rather than a mesh\n"
                  "  repeater, or the ESP-NOW dongle (docs/ESPNOW.md).")
        else:
            print(f"the FC PATH. The air is clean (p99 {air_p99:.0f} ms) but the full trip is\n"
                  f"  p99 {fc_p99:.0f} ms — that delta is UART + Betaflight MSP task scheduling.\n"
                  "  Look at the FC's UART baud and Betaflight's MSP task rate, not the network.")
        # The ESP-NOW acceptance gate (docs/ESPNOW.md §0): air p50 < 5 ms, air p99 < 20 ms.
        air = sorted(bridge_ms)
        air_p50 = statistics.median(air)
        gate = air_p50 < 5.0 and air_p99 < 20.0
        print(f"\nAir-path gate (p50 < 5 ms, p99 < 20 ms): p50 {air_p50:.2f}, p99 {air_p99:.2f} "
              f"-> {'PASS' if gate else 'FAIL'}")
    else:
        print("\n(no air/FC split: nothing bridge-answered MSP_BRIDGE_TOF. Either there is no\n"
              " xiao_bridge in this path — a direct USB cable to the flight controller — or the\n"
              " bridge firmware predates the ToF interception.)")
    if args.udp:
        print("(measured through the WiFi bridge: this IS the real offboard link budget)")
    elif bridge_ms is not None:
        print("(measured through the ESP-NOW dongle: this IS the real offboard link budget)")
    else:
        print("(this is the USB serial floor; the radio/WiFi bridge adds its own budget on top)")
    return 0


def _require_ack(args: argparse.Namespace) -> None:
    if not args.ack_props_off:
        sys.exit("refusing: this subcommand sends commands to the FC. Re-run with "
                 "--ack-props-off after physically removing all four props.")


def cmd_rc_test(args: argparse.Namespace) -> int:
    _require_ack(args)
    print(f"streaming neutral MSP_SET_RAW_RC at {args.hz} Hz for {args.seconds}s: {NEUTRAL_RC}")
    print("watch the Configurator receiver tab / the echo below; channels move => override seam live")
    period = 1.0 / args.hz
    sent = 0
    with _client(args) as fc:
        t_end = time.monotonic() + args.seconds
        next_echo = 0.0
        while time.monotonic() < t_end:
            fc.set_raw_rc(NEUTRAL_RC)
            sent += 1
            if time.monotonic() >= next_echo:
                try:
                    print(f"  FC rcData: {list(fc.rc()[:8])}")
                except Exception as e:  # echo is best-effort; the stream is the test
                    print(f"  (echo failed: {e})")
                next_echo = time.monotonic() + 1.0
            time.sleep(period)
    expected_rcdata = [NEUTRAL_RC[0], NEUTRAL_RC[1], NEUTRAL_RC[3], NEUTRAL_RC[2]]  # AETR wire -> RPYT rcData
    print(f"sent {sent} frames. If rcData held {expected_rcdata} on the overridden channels, "
          "the seam works; if it showed your Pocket/failsafe values, check msp_override config.")
    return 0


def cmd_checkup(args: argparse.Namespace) -> int:
    """Walk the whole host -> bridge -> FC chain once and say which layer is broken.

    Built because the drone's battery comes out between tests (it overheats sitting on the
    bench), so every powered window is scarce -- and half the failures in a bring-up session
    are really "that test was invalid because something wasn't powered". This runs the entire
    ladder in one window, in dependency order, and never reports a lower layer's failure as an
    upper layer's fault.
    """
    print("bench checkup -- battery IN, props OFF\n")
    rows: list[tuple[str, bool, str]] = []

    # Layer 1: the bridge answers its own MSP id. Proves board + link + our transport, and needs
    # no FC power at all. Tried on BOTH transports — over ESP-NOW the bridge sits behind the USB
    # dongle's serial port, so "serial" no longer implies "no bridge". Only a direct USB cable to
    # the FC has none, which shows up as an MspError (Betaflight rejecting the id).
    bridge_ok, tof_note = False, ""
    direct_usb = False
    try:
        with _client(args) as fc:
            r = fc.bridge_tof()
        bridge_ok = True
        if not r["sensor_ok"]:
            tof_note = "bridge up, but no VL53L1X on the I2C bus"
        elif r["range_m"] is not None:
            tof_note = f"range {r['range_m']*100:.1f} cm, age {r['age_ms']} ms"
        else:
            tof_note = f"sensor up, sample invalid (status {r['status']}) -- aim it at a surface"
    except MspError:
        # The FC answered, with a rejection: no bridge in the path at all. Not a failure.
        direct_usb, bridge_ok = True, True  # not in the chain; don't let it mask the FC result
        tof_note = "skipped: direct USB to the FC, no bridge in the path"
    # MspTimeout subclasses TimeoutError, hence OSError -- so it must be caught FIRST or the
    # socket-layer branch below swallows it and mislabels a timeout as "no route".
    except MspTimeout as e:
        tof_note = f"no reply ({e}) -- unpowered, firmware not running, or wrong address/port"
    except OSError as e:
        tof_note = f"no route to the bridge ({e}) -- absent, or wrong address"
    rows.append(("bridge (MSP_BRIDGE_TOF)", bridge_ok and not direct_usb, tof_note))

    # Layer 2: the FC answers. Needs FC power AND both UART directions.
    fc_ok, fc_note = False, ""
    if bridge_ok:
        try:
            with _client(args) as fc:
                info = fc.fc_info()
            fc_ok = True
            fc_note = f"{info.get('fc_variant', '?')} api {info.get('api_version', '?')}"
            vbat = info.get("vbat_v")
            if vbat is not None:
                fc_note += f", vbat {vbat:.2f} V"
        except (MspTimeout, MspError) as e:
            fc_note = f"no reply ({e})"
        except OSError as e:
            fc_note = f"socket error ({e})"
    else:
        fc_note = "not tested: the bridge itself did not answer, so this says nothing"
    rows.append(("FC over the UART (MSP_API_VERSION)", fc_ok, fc_note))

    # Layer 3: the number that actually matters for offboard control.
    link_ok, link_note = False, "not tested: needs a talking FC"
    if fc_ok:
        try:
            times_ms = []
            cmds = (MSP_ATTITUDE, MSP_RAW_IMU)
            with _client(args) as fc:
                fc.request(MSP_ATTITUDE)
                for i in range(args.n):
                    t0 = time.perf_counter()
                    fc.request(cmds[i % 2])
                    times_ms.append((time.perf_counter() - t0) * 1e3)
            times_ms.sort()
            p99 = times_ms[min(len(times_ms) - 1, int(0.99 * len(times_ms)))]
            med = statistics.median(times_ms)
            link_ok = p99 < 300.0  # Betaflight's MSP-RC freshness window
            link_note = f"median {med:.2f} ms, p99 {p99:.2f} ms over {args.n} requests"
            if not link_ok:
                link_note += "  -- p99 is past Betaflight's 300 ms MSP-RC window!"
        except (MspTimeout, MspError, OSError) as e:
            link_note = f"failed mid-measurement ({e}) -- intermittent link"
    rows.append(("link budget", link_ok, link_note))

    width = max(len(name) for name, _, _ in rows)
    print("  layer" + " " * (width - 3) + "status  detail")
    for name, ok, note in rows:
        print(f"  {name.ljust(width)}  {'PASS' if ok else 'FAIL'}    {note}")

    # One next action, chosen from the lowest layer that failed.
    print()
    if not bridge_ok:
        print("next: the bridge is the broken layer. Power it (USB, or the battery via the FC "
              "BEC),\n      check the antenna is seated, and confirm the address -- a stale ARP/mDNS "
              "cache\n      keeps a dead address resolving. 'pio device monitor' prints the real IP.")
    elif not fc_ok:
        print("next: bridge fine, FC silent. Is the battery IN? If it is, this is the UART:\n"
              "      check Betaflight 'serial' shows the MSP UART at 115200, then run\n"
              "      'pio run -e uart_scan -t upload' (battery in) to find which pins it is on.")
    elif not link_ok:
        print("next: the chain works but the link is too slow for offboard control. Check WiFi\n"
              "      RSSI at the bridge and contention on the LAN.")
    else:
        print("all layers pass -- clear for the Studio Real tab.")
    return 0 if (bridge_ok and fc_ok and link_ok) else 1


def cmd_tof(args: argparse.Namespace) -> int:
    """Live-print the bridge's VL53L1X range — the CJMCU-531 desk bring-up check.

    Bridge-answered (MSP_BRIDGE_TOF), so it needs the bridge in the path: ``--udp <bridge-ip>``
    over WiFi, or ``--port <dongle>`` through the ESP-NOW USB dongle. A direct USB cable to the
    FC has no bridge, and Betaflight rejects the id — caught below and reported as such.
    """
    period = 1.0 / args.hz
    print("bridge ToF (ctrl-C to stop) — wave a hand over the sensor, range should track it")
    try:
        with _client(args) as fc:
            while True:
                t0 = time.monotonic()
                r = fc.bridge_tof()
                if not r["sensor_ok"]:
                    print("  sensor_ok=0 — bridge up but no VL53L1X found (check D4/SDA D5/SCL + 3V3)")
                # loop_max_ms: the bridge's own worst loop() stall this 5 s window. Anything
                # over ~20 ms is a blind window in the MSP proxy and will show up as an
                # obs_age spike in flight; the old 100 ms I2C timeout used to park it at ~100.
                lmax = r.get("loop_max_ms")
                stall = "" if lmax is None else f"  loop_max {lmax:3d} ms"
                if r["range_m"] is not None:
                    bar = "#" * min(60, int(r["range_m"] * 40))
                    print(f"  {r['range_m']*100:6.1f} cm  age {r['age_ms']:3d} ms{stall}  {bar}")
                else:
                    print(f"  -- invalid (status {r['status']}, age {r['age_ms']} ms){stall} — "
                          "out of range / no return")
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        print("\nstopped.")
    except MspError:
        sys.exit("the FC rejected MSP_BRIDGE_TOF: there is no xiao_bridge in this path.\n"
                 "Run through the bridge — '--udp <bridge-ip>' over WiFi, or '--port <dongle>'\n"
                 "through the ESP-NOW USB dongle (docs/ESPNOW.md).")
    return 0


def cmd_motor_test(args: argparse.Namespace) -> int:
    _require_ack(args)
    value = min(int(args.value), MOTOR_VALUE_HARD_CAP)
    if value != int(args.value):
        print(f"value capped to {MOTOR_VALUE_HARD_CAP}")
    if not 0 <= args.motor <= 3:
        sys.exit("--motor must be 0-3")
    values = [1000] * 8
    values[args.motor] = value
    print(f"spinning motor {args.motor} at {value} for {args.seconds}s (1000=stop) — PROPS OFF")
    with _client(args) as fc:
        try:
            t_end = time.monotonic() + args.seconds
            while time.monotonic() < t_end:
                fc.set_motor(values)  # refreshed faster than the FC's MSP-motor timeout
                time.sleep(0.05)
        finally:
            for _ in range(5):
                fc.set_motor([1000] * 8)
                time.sleep(0.02)
            print("motors stopped.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyACM0", help="FC serial port (default /dev/ttyACM0)")
    ap.add_argument("--baud", type=int, default=115200, help="baud (USB VCP ignores it)")
    ap.add_argument("--udp", default=None, metavar="HOST[:PORT]",
                    help="talk through the xiao_bridge WiFi proxy instead of serial "
                         "(firmware/xiao_bridge/, default port 14550)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="FC identity + battery")

    p = sub.add_parser("checkup", help="one-shot host->bridge->FC ladder + verdict (battery in)")
    p.add_argument("--n", type=int, default=100, help="latency samples (default 100)")

    p = sub.add_parser("monitor", help="stream telemetry")
    p.add_argument("--hz", type=float, default=20.0)
    p.add_argument("--csv", default=None, help="also append rows to this CSV")

    p = sub.add_parser("latency", help="MSP round-trip timing")
    p.add_argument("--n", type=int, default=500)

    p = sub.add_parser("rc-test", help="MSP_SET_RAW_RC loopback smoke test (props off)")
    p.add_argument("--hz", type=float, default=50.0)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--ack-props-off", action="store_true")

    p = sub.add_parser("tof", help="live bridge VL53L1X range (needs the bridge in the path; "
                                   "desk bring-up)")
    p.add_argument("--hz", type=float, default=10.0)

    p = sub.add_parser("motor-test", help="spin one motor, capped + props off")
    p.add_argument("--motor", type=int, required=True, help="motor index 0-3")
    p.add_argument("--value", type=int, default=1050, help=f"1000=stop, hard cap {MOTOR_VALUE_HARD_CAP}")
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--ack-props-off", action="store_true")

    args = ap.parse_args()
    try:
        return {"info": cmd_info, "monitor": cmd_monitor, "latency": cmd_latency,
                "rc-test": cmd_rc_test, "tof": cmd_tof, "motor-test": cmd_motor_test,
                "checkup": cmd_checkup}[args.cmd](args)
    except MspTimeout as e:
        sys.exit(_link_hint(args, e))
    except MspError as e:
        sys.exit(f"{e}\n\nThe FC answered with an MSP error frame; the link is up, but that command "
                 "is unsupported or disabled in the current FC/bridge configuration.")
    except OSError as e:
        # EHOSTDOWN/EHOSTUNREACH/ENETUNREACH: ARP or routing failed and the datagram never went
        # out. Distinct from MspTimeout (frames sent, nothing came back) and worth saying so --
        # the timeout advice above would send you chasing the FC when the bridge is just off.
        sys.exit(_route_hint(args, e))


if __name__ == "__main__":
    raise SystemExit(main())
