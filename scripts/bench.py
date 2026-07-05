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

from neural_whoop.bench import MSP_ATTITUDE, MspClient, MspUdpClient  # noqa: E402

MOTOR_VALUE_HARD_CAP = 1200  # 1000=stop; keep bench spins gentle, no override flag offered
NEUTRAL_RC = [1500, 1500, 1500, 1000, 1000, 1000, 1000, 1000]  # R,P,Y centered; T + aux low


def _client(args: argparse.Namespace):
    if args.udp:
        host, _, port = args.udp.partition(":")
        return MspUdpClient(host, port=int(port) if port else 14550)
    return MspClient(args.port, baud=args.baud)


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


def cmd_latency(args: argparse.Namespace) -> int:
    times_ms: list[float] = []
    with _client(args) as fc:
        fc.request(MSP_ATTITUDE)  # warm up
        for _ in range(args.n):
            t0 = time.perf_counter()
            fc.request(MSP_ATTITUDE)
            times_ms.append((time.perf_counter() - t0) * 1e3)
    times_ms.sort()
    p = lambda q: times_ms[min(len(times_ms) - 1, int(q * len(times_ms)))]  # noqa: E731
    print(
        f"MSP_ATTITUDE round-trip over {args.n} requests: "
        f"median {statistics.median(times_ms):.2f} ms  p90 {p(0.90):.2f}  p99 {p(0.99):.2f}  "
        f"max {times_ms[-1]:.2f}"
    )
    if args.udp:
        print("(measured through the WiFi bridge: this IS the real offboard link budget)")
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
    print(f"sent {sent} frames. If rcData held {NEUTRAL_RC[:4]} on the overridden channels, "
          "the seam works; if it showed your Pocket/failsafe values, check msp_override config.")
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

    p = sub.add_parser("monitor", help="stream telemetry")
    p.add_argument("--hz", type=float, default=20.0)
    p.add_argument("--csv", default=None, help="also append rows to this CSV")

    p = sub.add_parser("latency", help="MSP round-trip timing")
    p.add_argument("--n", type=int, default=500)

    p = sub.add_parser("rc-test", help="MSP_SET_RAW_RC loopback smoke test (props off)")
    p.add_argument("--hz", type=float, default=50.0)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--ack-props-off", action="store_true")

    p = sub.add_parser("motor-test", help="spin one motor, capped + props off")
    p.add_argument("--motor", type=int, required=True, help="motor index 0-3")
    p.add_argument("--value", type=int, default=1050, help=f"1000=stop, hard cap {MOTOR_VALUE_HARD_CAP}")
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--ack-props-off", action="store_true")

    args = ap.parse_args()
    return {"info": cmd_info, "monitor": cmd_monitor, "latency": cmd_latency,
            "rc-test": cmd_rc_test, "motor-test": cmd_motor_test}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
