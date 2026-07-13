#!/usr/bin/env python3
"""Offboard pilot: fly a trained hover_blind policy over the WiFi MSP bridge — pure stdlib.

The deployment end of sim2real branch B (docs/SIM2REAL.md Stage 0.5): observations come from
MSP_ATTITUDE + MSP_RAW_IMU over the xiao_bridge, the TinyPolicy actor runs right here in pure
Python (weights from ``policy_weights.json``), and act-v2 commands stream back as MSP_SET_RAW_RC in
**AETR wire order** at ``--hz``.

Deliberately dependency-free (like bench.py's UDP path): runs on a macOS laptop with no venv.

This file is now a thin CLI shim: the flight engine (the policy forward, the MSP telemetry poller,
and the ``fly`` state machine) lives in the importable, torch-free :mod:`neural_whoop.pilot` package,
so the same control code drives both this CLI and the always-on web dashboard
(:mod:`neural_whoop.studio.flight`). The moved public surface is re-exported below so importers
(``scripts/sim_vs_real.py``, ``tests/test_pilot_vz_damper.py``) keep working unchanged.

Subcommands:
  selftest   Pure-math parity check of the Python forward pass against the deploy-exact
             reference outputs saved next to the weights (run after any weights change).
  check      PROPS OFF, powered drone: stream live obs + the policy's commanded channels.
             Hand-tilt the drone and verify every correction points the right way BEFORE
             the first flight (the printed hints say what to expect).
  fly        The real thing. Streams the policy at --hz for --seconds, then ramps thrust
             down and releases the link (Betaflight's MSP freshness window hands control
             back to the radio). Arming and the override switch STAY ON THE POCKET.

Safety model: this script never touches aux channels, never arms, and stops streaming on ANY
fault (stale observations, socket error, Ctrl+C, timer end) — stopping is the safe action,
because Betaflight reverts to the live Pocket RC within its 300 ms MSP freshness window.

Frame/sign conventions (bench-verified 2026-07-05, see docs/SIM2REAL.md):
  sim body frame is x fwd / y LEFT / z UP; Betaflight is roll-right/pitch-up/yaw-right +.
  -> roll matches, pitch and yaw FLIP, both for observations and commanded rates.
  MSP_SET_RAW_RC wire order is AETR: [roll, pitch, THROTTLE, yaw, aux1..4].
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neural_whoop.bench.msp import (  # noqa: E402
    MSP_ALTITUDE,
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_MODE_RANGES,
    MSP_MOTOR_TELEMETRY,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    MSP_STATUS,
    MspError,
    MspTimeout,
    MspUdpClient,
    decode_altitude,
    decode_analog,
    decode_attitude,
    decode_mode_ranges,
    decode_motor_telemetry,
    decode_raw_imu,
    decode_status_sensors,
    decode_u16s,
    pack_rc_channels,
)

# The flight engine now lives in the pure-stdlib package. Re-export its full public surface (and
# every tuning constant) so ``import pilot`` still resolves ``pilot.Policy`` / ``pilot.stack_frames``
# / ``pilot.rpm_climb_rate`` / ``pilot.VZ_AERO_TAU`` … for the two in-repo importers.
from neural_whoop.pilot import (  # noqa: E402,F401
    DEFAULT_WEIGHTS,
    FlightController,
    FlightParams,
    FlightSetupError,
    Phase,
    Policy,
    Telemetry,
    action_to_us,
    check_policy_family,
    check_policy_family_acro,
    obs_from_msp,
    obs_from_msp_acro,
    rpm_climb_rate,
    rpm_damper_trim,
    stack_frames,
    stream_rc,
)
from neural_whoop.pilot.config import *  # noqa: E402,F401,F403 - re-export the constants (VZ_*, SEEK_*, …)

# The pilot CSV schema (matches analysis/flight_log.py::LOG_COLUMNS) — kept inline so this shim
# stays pure-stdlib (flight_log.py imports numpy, which the bench Mac deliberately lacks).
LOG_COLUMNS = [
    "t", "obs_age_ms", "roll", "pitch", "p", "q", "r",
    "a_thr", "a_wx", "a_wy", "a_wz", "us_roll", "us_pitch", "us_thr", "us_yaw",
    "vbat", "hover_eff", "vz_est", "trim", "acc_x", "acc_y", "acc_z",
    "rpm_rms", "us_corr", "tof_m", "h_err",
]


# --- subcommands ----------------------------------------------------------------------------


def cmd_selftest(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    check_policy_family(pol)
    ref_path = Path(args.weights).parent / "policy_ref_outputs.json"
    import json

    with open(ref_path) as f:
        ref = json.load(f)
    worst = 0.0
    for name, frame in ref["inputs"].items():
        # Ref inputs are single BASE frames (old 5-dim files: stack 1 -> identity); tiling the
        # frame across the stack is the reset semantics both env and exporter use.
        got = pol(list(frame) * pol.obs_stack)
        want = ref["outputs"][name]
        err = max(abs(g - w) for g, w in zip(got, want))
        worst = max(worst, err)
        print(f"  {name:26s} max|err| {err:.2e}  act {[round(v, 4) for v in got]}")
    ok = worst < 1e-4
    print(f"parity vs {ref_path}: worst {worst:.2e} -> {'OK' if ok else 'FAIL'}")
    if ok:
        def probe(idx: int | None = None, val: float = 0.0) -> list[float]:
            base = [0.0] * pol.base_obs_dim
            if idx is not None:
                base[idx] = val
            return base * pol.obs_stack

        us = action_to_us(pol(probe()), args.hover_us, args.min_us, args.max_us)
        print(f"level-still command @ hover_us={args.hover_us}: AETR {us} "
              f"(throttle should be ~{args.hover_us})")
        # Closed-loop direction sanity through the FULL conversion chain (empirical signs):
        nose_down = action_to_us(pol(probe(1, 0.2)), args.hover_us, args.min_us, args.max_us)
        tilt_right = action_to_us(pol(probe(0, 0.2)), args.hover_us, args.min_us, args.max_us)
        dir_ok = nose_down[1] < 1500 and tilt_right[0] < 1500
        print(f"nose-down obs -> pitch_us {nose_down[1]} (<1500 = nose-up correction); "
              f"tilt-right obs -> roll_us {tilt_right[0]} (<1500 = roll-left correction) "
              f"-> {'OK' if dir_ok else 'FAIL'}")
        ok = ok and dir_ok
        if pol.uses_vz:  # informational: a healthy v2 policy raises thrust against a sink
            sink = action_to_us(pol(probe(5, -0.5)), args.hover_us, args.min_us, args.max_us)
            print(f"sinking obs (vz_est -0.5 m/s) -> throttle {sink[2]} us vs level {us[2]} us "
                  "(expect higher)")
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    check_policy_family(pol)
    print("PROPS OFF check: hand-move the drone and verify (signs per the 2026-07-05 calibration):")
    print("  tilt RIGHT              -> roll(sim) positive,  roll_us  < 1500 (roll-left correction)")
    print("  tilt NOSE DOWN          -> pitch(sim) POSITIVE, pitch_us < 1500 (nose-up correction)")
    print("  spin CLOCKWISE (top)    -> 3rd gyro number NEGATIVE  (verifies the yaw sign; report it!)")
    print("  level & still           -> throttle ~ hover_us, roll/pitch/yaw ~ 1500")
    if pol.uses_vz:
        print("  lift/lower STEADILY     -> vz_est +/- (leaky, decays back); throttle counters it")
    print("Ctrl+C to stop. Nothing is streamed to the FC in this mode.\n")
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        tel = Telemetry(fc)
        hist: deque = deque(maxlen=pol.obs_stack)
        # Same vz estimator the fly loop runs (full projection, leak, clamp, tilt-freeze) so a
        # v2 policy's 6th channel — and its thrust response — can be sanity-checked by hand.
        az_cal: list[int] = []
        az_ref = None
        vz = 0.0
        t_last = None
        try:
            while True:
                now = time.monotonic()
                tel.poll(now, want_analog=True)
                if tel.obs_age(now) < 0.5:
                    o = tel.obs()
                    acc = tel.imu["acc_raw"]
                    if az_ref is None:
                        az_cal.append(acc[2])
                        if len(az_cal) >= 20:
                            tail = az_cal[len(az_cal) // 4:]
                            ref = sum(tail) / len(tail)
                            if abs(ref) > 100:
                                az_ref = ref
                                print(f"  acc 1g = {az_ref:.0f} raw (hold-still cal) — vz estimate live\n")
                    else:
                        dt = min(0.5, now - t_last) if t_last is not None else 0.0
                        f_up = (-acc[0] * math.sin(o[1])
                                + acc[1] * math.cos(o[1]) * math.sin(o[0])
                                + acc[2] * math.cos(o[1]) * math.cos(o[0]))
                        if abs(o[0]) < VZ_TILT_LIMIT and abs(o[1]) < VZ_TILT_LIMIT:
                            vz = (vz + (f_up / az_ref - 1.0) * 9.81 * dt) * math.exp(-dt / VZ_LEAK_TAU)
                            vz = max(-VZ_CLAMP, min(VZ_CLAMP, vz))
                        else:
                            vz *= math.exp(-dt / VZ_LEAK_TAU)
                    t_last = now
                    frame = o + [vz] if pol.uses_vz else o
                    us = action_to_us(pol(stack_frames(hist, frame, pol.obs_stack)),
                                      args.hover_us, args.min_us, args.max_us, args.trim_thrust)
                    print(f"\r roll {math.degrees(o[0]):+6.1f}  pitch(sim) {math.degrees(o[1]):+6.1f} deg"
                          f" | gyro {math.degrees(o[2]):+7.1f} {math.degrees(o[3]):+7.1f}"
                          f" {math.degrees(o[4]):+7.1f} deg/s"
                          + (f" | vz_est {vz:+5.2f} m/s" if pol.uses_vz else "")
                          + f" | cmd RPTY(us) {us}"
                          f" | vbat {tel.vbat or 0:.2f}V   ", end="")
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Discover better vertical-state sensors than acc integration: a barometer (Betaflight
    fuses altitude+vario for us) and bidirectional-DShot RPM telemetry (hover RPM is a true
    thrust anchor, immune to pack freshness/sag). Battery in; props off is fine."""
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        sensors = decode_status_sensors(fc.request(MSP_STATUS))
        print("sensors:", " ".join(f"{k}={'YES' if v else 'no'}" for k, v in sensors.items()))
        try:
            alt = decode_altitude(fc.request(MSP_ALTITUDE))
            print(f"MSP_ALTITUDE: alt {alt['alt_m']:+.2f} m  vario {alt['vario_ms']:+.2f} m/s"
                  + ("" if sensors["baro"] else "  (no baro: expect zeros)"))
        except (MspError, MspTimeout) as e:
            print(f"MSP_ALTITUDE: unavailable ({e})")
        try:
            mt = decode_motor_telemetry(fc.request(MSP_MOTOR_TELEMETRY))
            print("MSP_MOTOR_TELEMETRY:",
                  " ".join(f"m{i}={m['rpm']}rpm({m['invalid_pct']:.0f}%inv)" for i, m in enumerate(mt))
                  or "empty")
            print("  (rpm needs bidirectional DShot; re-run while armed at idle to see nonzero)")
        except (MspError, MspTimeout) as e:
            print(f"MSP_MOTOR_TELEMETRY: unavailable ({e})")
    return 0


def cmd_fly(args: argparse.Namespace) -> int:
    fake = getattr(args, "fake", False)
    if not args.ack_props_on and not fake:
        sys.exit("refusing: fly streams live flight commands. Re-run with --ack-props-on once\n"
                 "the drone is tethered, the area is clear, and YOUR thumb is on the override\n"
                 "switch + arm/kill on the Pocket.")
    if args.takeoff and args.launch:
        sys.exit("pick one of --takeoff / --launch")
    pol = Policy(args.weights)
    check_policy_family(pol)
    acro_pol = None
    if args.acro_weights:
        acro_pol = Policy(args.acro_weights)
        check_policy_family_acro(acro_pol)
        print(f"acro policy loaded ({args.acro_weights}): FLIP window enabled "
              f"(axis={args.axis}, {args.n_rotations}x"
              + (f", auto @ {args.flip_at}s" if args.flip_at is not None else ", manual") + ")")
    log_path = Path(args.log or f"runs/pilot/flight_{int(time.time())}.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Never silently clobber a prior flight: if --log names an existing file, wedge a timestamp
    # before the suffix. Each flight's data is irreplaceable, so a fixed --log stem rolls over.
    if log_path.exists():
        log_path = log_path.with_name(f"{log_path.stem}_{int(time.time())}{log_path.suffix}")
    print(f"logging flight to {log_path}")
    fout = open(log_path, "w", newline="")
    writer = csv.writer(fout)
    writer.writerow(LOG_COLUMNS)

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))

    params = FlightParams(
        seconds=args.seconds, hz=args.hz, max_obs_age=args.max_obs_age, yaw=args.yaw,
        takeoff=args.takeoff, launch=args.launch, hold_seconds=args.hold_seconds,
        vz_gain=args.vz_gain, trim_roll_deg=args.trim_roll_deg, trim_pitch_deg=args.trim_pitch_deg,
        aux=args.aux, hover_us=args.hover_us, vbat_ref=args.vbat_ref, trim_thrust=args.trim_thrust,
        min_us=args.min_us, max_us=args.max_us, target_height_m=args.target_height,
        flip_at_s=args.flip_at, acro_axis=args.axis, acro_n_rotations=args.n_rotations,
    )
    period = 1.0 / args.hz
    # The fake in-process bridge (NW_FLIGHT_FAKE=1 / --udp fake) self-reports ARMED + OVERRIDE, so
    # the physical override edge never fires: use software start and auto-accept it each tick.
    if fake:
        from neural_whoop.studio.flight import FakeFlightBridge
        fc, start_mode = FakeFlightBridge(), "software"
    else:
        fc, start_mode = MspUdpClient(args.udp_host, args.udp_port), "switch"
    try:
        # The override edge auto-starts the flight clock (start_mode="switch"); the human log lines
        # and the CSV rows (LOG_COLUMNS order) route through the injected callbacks so console +
        # log are unchanged.
        ctrl = FlightController(fc, pol, params, acro_policy=acro_pol, start_mode=start_mode,
                                on_log=writer.writerow, log=print)
        try:
            ctrl.setup()
        except FlightSetupError as e:
            fout.close()
            sys.exit(str(e))
        print("Ctrl+C = instant release." + (" [FAKE BRIDGE — no hardware]" if fake else ""))
        if args.trim_roll_deg or args.trim_pitch_deg:
            print(f"manual trim: roll {args.trim_roll_deg:+.1f} / pitch {args.trim_pitch_deg:+.1f} deg "
                  "(+ = right / nose-down push)")
        hold_s = ctrl.hold_s
        if args.takeoff:
            print(f"GROUND-TAKEOFF mode: set the drone LEVEL on the floor, stand clear, ARM on "
                  f"the Pocket, flip the OVERRIDE switch — {hold_s:.0f}s idle countdown, then a "
                  f"slow throttle ramp SEEKS the liftoff point (learning this pack's true hover) "
                  f"and hands to the policy. After the flight it ramps down and lands: DISARM then.")
        elif args.launch:
            print(f"HAND-LAUNCH mode: hold the drone (grip the duct, fingers clear), ARM on the "
                  f"Pocket, flip the OVERRIDE SWITCH — {hold_s:.0f}s idle countdown, then the "
                  f"throttle ramps up WHILE YOU KEEP HOLDING; release only at 'GO'. After the "
                  f"flight it ramps down and settles: DISARM then.")
        else:
            print(f"streaming... FLIP THE OVERRIDE SWITCH to start the {args.seconds}s flight window "
                  "(keep your throttle stick at hover for the handback!)")
        try:
            while not stop["flag"] and not ctrl.done:
                now = time.monotonic()
                if fake and ctrl.t_start is None:
                    ctrl.request_start()   # fake bridge is always armed+override: software auto-start
                ctrl.step(now)
                time.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            fout.close()
        print(f"\nreleased. {ctrl.n_sent} frames streamed, {ctrl.n_stale} stale ticks, "
              f"worst obs age {ctrl.worst_age * 1e3:.0f} ms. Log: {log_path}"
              + (f"\nlearned hover anchor this pack: {ctrl.hover_learned} us (breakaway-measured)"
                 if ctrl.hover_learned else ""))
    finally:
        fc.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--udp", default=os.environ.get("NW_BRIDGE"), metavar="HOST[:PORT]",
                    help="bridge address (default: $NW_BRIDGE, so you can set it once per "
                         "bench session with `export NW_BRIDGE=<ip>`)")
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    ap.add_argument("--hover-us", type=int, default=1410, help="bench-measured hover throttle (us)")
    ap.add_argument("--vbat-ref", type=float, default=0.0,
                    help="DEPRECATED voltage re-anchoring of the throttle map (duty ~ 1/V). "
                         "Default 0 = OFF: loaded vbat proved a bad thrust proxy in both "
                         "directions (flights 1783278136/1783280676); the acc-z climb damper "
                         "owns thrust bias now. Set to the calibration voltage to re-enable.")
    ap.add_argument("--trim-thrust", type=float, default=0.0, help="additive act[0] trim (bench-calibrated)")
    ap.add_argument("--min-us", type=int, default=1000)
    ap.add_argument("--max-us", type=int, default=1600, help="hard throttle ceiling for early flights")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    sub.add_parser("check")
    sub.add_parser("probe")
    fly = sub.add_parser("fly")
    fly.add_argument("--seconds", type=float, default=15.0)
    fly.add_argument("--hz", type=float, default=50.0)
    fly.add_argument("--max-obs-age", type=float, default=0.25, help="stale-obs watchdog (s)")
    fly.add_argument("--yaw", choices=["center", "policy"], default="center",
                     help="yaw channel: center (1500, FC damps yaw; default until the yaw sign "
                          "is verified) or policy")
    fly.add_argument("--takeoff", action="store_true",
                     help="ground-takeoff flow (RECOMMENDED): drone level on the floor; after the "
                          "override switch, idle countdown, spool to --boost x hover for --boost-s, "
                          "then hand to the policy")
    fly.add_argument("--boost", type=float, default=1.18,
                     help="DEPRECATED, ignored: --takeoff now auto-seeks the liftoff throttle")
    fly.add_argument("--boost-s", type=float, default=0.6,
                     help="DEPRECATED, ignored: --takeoff now auto-seeks the liftoff throttle")
    fly.add_argument("--launch", action="store_true",
                     help="hand-launch flow: after the override switch, idle countdown, throttle "
                          "ramps WHILE HELD, release only at GO")
    fly.add_argument("--hold-seconds", type=float, default=3.0)
    fly.add_argument("--target-height", type=float, default=1.0, metavar="M",
                     help="hover_tof policies: height to hold (m); the obs channel is "
                          "target - measured (tilt-corrected bridge ToF, last-valid-held)")
    fly.add_argument("--vz-gain", type=float, default=0.15,
                     help="climb damper gain (act[0] per m/s of RPM-anchored climb rate for a "
                          "blind policy; vz-consuming policies own damping and ignore it); "
                          "0 disables")
    fly.add_argument("--trim-roll-deg", type=float, default=0.0,
                     help="manual level trim: + pushes RIGHT (drifts left -> positive)")
    fly.add_argument("--trim-pitch-deg", type=float, default=0.0,
                     help="manual level trim: + pushes FORWARD/nose-down (drifts backwards -> "
                          "positive, start with 1.5)")
    fly.add_argument("--aux", type=int, default=None, metavar="N",
                     help="override-switch aux channel number (1-4); normally auto-detected "
                          "from the FC's MSP OVERRIDE mode range")
    fly.add_argument("--acro-weights", default=None, metavar="PATH",
                     help="deploy weights for a 7-dim acro-flip policy: enables a bounded FLIP "
                          "window at HOVER (the pilot still owns takeoff/land; the acro policy "
                          "owns the flip). System take-off -> flip -> land, flown blind.")
    fly.add_argument("--flip-at", type=float, default=None, metavar="SEC",
                     help="auto-trigger the FLIP this many seconds into free flight (needs "
                          "--acro-weights); omit to trigger only via the dashboard Flip button")
    fly.add_argument("--axis", choices=["roll", "pitch"], default="roll",
                     help="flip axis (matches the acro policy's trained axis)")
    fly.add_argument("--n-rotations", type=float, default=1.0,
                     help="flip rotations Φ = 2π·n (1 = a single barrel roll / loop)")
    fly.add_argument("--log", default=None)
    fly.add_argument("--ack-props-on", action="store_true")
    args = ap.parse_args()

    args.fake = str(os.environ.get("NW_FLIGHT_FAKE", "")).lower() in ("1", "true", "yes", "on") \
        or (args.udp or "").lower() == "fake"
    if not args.udp and not args.fake:
        ap.error("no bridge address: pass --udp HOST[:PORT] or set $NW_BRIDGE "
                 "(e.g. `export NW_BRIDGE=<ip>`), or NW_FLIGHT_FAKE=1 for the in-process bridge")
    host, _, port = (args.udp or "fake").partition(":")
    args.udp_host, args.udp_port = host, int(port or 14550)
    return {"selftest": cmd_selftest, "check": cmd_check, "probe": cmd_probe,
            "fly": cmd_fly}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
