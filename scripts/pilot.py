#!/usr/bin/env python3
"""Offboard pilot: fly a trained hover_blind policy over the WiFi MSP bridge — pure stdlib.

The deployment end of sim2real branch B (docs/SIM2REAL.md Stage 0.5): observations come from
MSP_ATTITUDE + MSP_RAW_IMU over the xiao_bridge, the TinyPolicy actor runs right here in pure
Python (weights from ``policy_weights.json`` — see the extraction note below), and act-v2
commands stream back as MSP_SET_RAW_RC in **AETR wire order** at ``--hz``.

Deliberately dependency-free (like bench.py's UDP path): runs on a macOS laptop with no venv.
A [64,64] MLP forward is ~5k MACs — microseconds in CPython, nothing to optimize.

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

Weights: produced from a checkpoint by the extraction snippet in the runs/ dir (torch needed
once, anywhere): actor Linear layers + log_std to JSON. Deploy convention since 5c735cd is the
clipped-Gaussian effective mean E[clip(N(mu, sigma))] — implemented here with math.erf.

Thrust mapping: act[0] -> normed thrust t in [0, 4] hover-units (contract.py), then
us = 1000 + (hover_us - 1000) * sqrt(t)  (prop thrust ~ quadratic in throttle; sqrt inverts),
clamped to [--min-us, --max-us]. --hover-us anchors on the bench-measured hover throttle;
--trim-thrust nudges act[0] if the bench check shows residual bias (SIM2REAL: mandatory step).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neural_whoop.bench.msp import (  # noqa: E402
    MSP_ANALOG,
    MSP_ATTITUDE,
    MSP_MODE_RANGES,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_RAW_RC,
    MspError,
    MspTimeout,
    MspUdpClient,
    decode_analog,
    decode_attitude,
    decode_mode_ranges,
    decode_raw_imu,
    decode_u16s,
    pack_rc_channels,
)

DEFAULT_WEIGHTS = "runs/hover_blind_air65_long/policy_weights.json"

# Sim action limits (contract.py ActionLimits) and the Betaflight ACTUAL-rates the drone must
# be configured with (rates_type=ACTUAL, expo 0, roll/pitch 690 deg/s, yaw 345 deg/s).
MAX_THRUST_NORMED = 4.0
SIM_MAX_RATE_RP = 12.0    # rad/s
SIM_MAX_RATE_YAW = 6.0
BF_MAX_RATE_RP = math.radians(690.0)
BF_MAX_RATE_YAW = math.radians(345.0)

# Betaflight permanent box ids (msp_box.c) — stable across versions, keyed by MSP_MODE_RANGES.
BOX_ARM = 0
BOX_MSP_OVERRIDE = 50

# Acc-z climb damper. Open-loop thrust-from-voltage failed honestly: a fresh pack and a tired
# pack both read ~3.65-3.7 V UNDER LOAD yet the same 1410 us climbs to the ceiling on one and
# sinks to the floor on the other (flights 1783278136 vs 1783276185). So close the loop with
# the accelerometer instead: acc-z at rest during the countdown IS 1 g (self-calibrating, no
# scale lore), vertical specific force integrates to a leak-filtered climb-rate estimate, and
# a proportional thrust trim damps it. The leak (tau below) bounds acc-bias drift; this is a
# DAMPER, not an altitude hold — it turns the blind policy's altitude random walk into a
# strongly damped one, and also arrests the leftover takeoff-boost climb after handoff.
VZ_LEAK_TAU = 4.0    # s; climb-rate estimate forgets (bounds acc-bias drift)
VZ_TRIM_CAP = 0.15   # act[0] units (0.15 -> +-0.3 g of P authority)
VZ_TRIM_KI = 0.15    # integral gain: absorbs the pack's constant thrust bias (P alone is
VZ_ITRIM_CAP = 0.20  # DC-blind past the leak). Sim: +15% pack bias peaks 1.1 m and holds.
VZ_CLAMP = 3.0       # m/s; a whoop indoors doesn't do more — beyond this the estimate is lying
VZ_TILT_LIMIT = math.radians(45.0)  # beyond this the cos-tilt correction + collision accels
#                     poison the estimate (flights 1783280676/65: ceiling strike -> pitch -73,
#                     vz "-10 m/s", trim pinned +, throttle 1600 while sideways). Freeze there.

# Ground-takeoff profile (--takeoff): spool fast through the on-ground sub-hover zone (a
# skittering half-throttle whoop tips over), hold a boost above hover to actually climb —
# exactly 1.0x hover just sits light on its wheels (flights 1783273972/92 proved it: 5 s
# parked at a perfect 1410 us) — then settle onto the policy's command.
TAKEOFF_SPOOL_S = 0.3
TAKEOFF_SETTLE_S = 0.5

# MSP_RAW_IMU gyro scale. Betaflight's gyroRateDps() (sensors/gyro_init.c) returns
# gyroADCf / rawSensorDev->scale — i.e. the FILTERED rate converted back to raw LSB units,
# 16.384 LSB per deg/s on a +-2000 dps gyro. Confirmed empirically from flight_1783271742:
# the crash-tumble railed at |31527| raw = 1924 dps ~= the sensor's 2000 dps full scale.
# (First two flights fed the policy rates 16.4x real -> constant overreaction -> climb.)
GYRO_RAW_TO_DPS = 2000.0 / 32768.0

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


# --- policy ---------------------------------------------------------------------------------


class Policy:
    """TinyPolicy actor (tanh MLP) + clipped-Gaussian effective-mean output, pure Python."""

    def __init__(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        self.meta = data["meta"]
        self.layers = [(l["W"], l["b"]) for l in data["layers"]]
        self.sigma = [math.exp(v) for v in self.meta["log_std"]]
        self.obs_dim = self.meta["obs_dim"]
        self.act_dim = self.meta["act_dim"]

    @staticmethod
    def _clipped_gaussian_mean(mu: float, sd: float, lo: float = -1.0, hi: float = 1.0) -> float:
        # E[clip(N(mu, sd))] — mirrors training/ppo.py::clipped_gaussian_mean exactly.
        a = (lo - mu) / sd
        b = (hi - mu) / sd
        cdf_a = 0.5 * (1.0 + math.erf(a / _SQRT2))
        cdf_b = 0.5 * (1.0 + math.erf(b / _SQRT2))
        pdf_a = math.exp(-0.5 * a * a) / _SQRT2PI
        pdf_b = math.exp(-0.5 * b * b) / _SQRT2PI
        return lo * cdf_a + hi * (1.0 - cdf_b) + mu * (cdf_b - cdf_a) - sd * (pdf_b - pdf_a)

    def __call__(self, obs: list[float]) -> list[float]:
        x = obs
        last = len(self.layers) - 1
        for i, (W, b) in enumerate(self.layers):
            y = [sum(wr[j] * x[j] for j in range(len(x))) + b[k] for k, wr in enumerate(W)]
            x = [math.tanh(v) for v in y] if i < last else y
        return [self._clipped_gaussian_mean(x[k], self.sigma[k]) for k in range(self.act_dim)]


# --- conversions ----------------------------------------------------------------------------


def obs_from_msp(att: dict, imu: dict) -> list[float]:
    """[roll, pitch, p, q, r] in sim convention from MSP attitude (deg) + gyro (raw LSB).

    Signs are EMPIRICAL for this Air65 II stack (2026-07-05: hand-pose check + manual-flight
    command/attitude correlation, 87:1 roll / 57:3 pitch): this board reports nose-down as
    POSITIVE on both attitude pitch and gyro y — same as the sim convention — so pitch takes
    no flip (the textbook BF nose-up+ convention does NOT hold here). Yaw (r = -gz) is the
    one remaining doc-derived sign: verify via the clockwise-spin check before trusting
    policy yaw (fly defaults to --yaw center for exactly this reason).
    """
    roll = math.radians(att["roll_deg"])           # + = roll right (matches sim)
    pitch = math.radians(att["pitch_deg"])         # + = nose down on this board (matches sim)
    gx, gy, gz = (v * GYRO_RAW_TO_DPS for v in imu["gyro_raw"])  # raw LSB -> deg/s
    p = math.radians(gx)                           # + = roll-right rate (check-verified)
    q = math.radians(gy)                           # + = nose-down rate (event-verified)
    r = -math.radians(gz)                          # assumed gz+ = yaw right; UNVERIFIED
    return [roll, pitch, p, q, r]


def action_to_us(act: list[float], hover_us: int, min_us: int, max_us: int,
                 trim_thrust: float = 0.0) -> list[int]:
    """act-v2 -> AETR channel microseconds [roll, pitch, throttle, yaw]."""
    a0 = max(-1.0, min(1.0, act[0] + trim_thrust))
    t = (a0 + 1.0) * 0.5 * MAX_THRUST_NORMED               # hover-units, 1.0 == hover
    thr = 1000.0 + (hover_us - 1000.0) * math.sqrt(max(0.0, t))
    thr_us = int(max(min_us, min(max_us, thr)))

    wx = act[1] * SIM_MAX_RATE_RP                          # sim rad/s
    wy = act[2] * SIM_MAX_RATE_RP
    wz = act[3] * SIM_MAX_RATE_YAW
    # Command signs: EMPIRICAL from the manual-flight rcData/attitude correlation (see
    # obs_from_msp) — on this setup channel-high = roll right AND nose DOWN (pitch takes no
    # flip, mirroring the telemetry convention). Yaw is doc-derived and unverified; fly
    # streams 1500 there unless --yaw policy.
    roll_us = 1500.0 + 500.0 * max(-1.0, min(1.0, wx / BF_MAX_RATE_RP))    # + = roll right
    pitch_us = 1500.0 + 500.0 * max(-1.0, min(1.0, wy / BF_MAX_RATE_RP))   # + = nose down
    yaw_us = 1500.0 + 500.0 * max(-1.0, min(1.0, -wz / BF_MAX_RATE_YAW))   # sim nose-left+ -> BF nose-right+
    return [int(roll_us), int(pitch_us), thr_us, int(yaw_us)]


# --- MSP plumbing (non-blocking polling on top of MspUdpClient) -----------------------------


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
        self.t_att = 0.0
        self.t_imu = 0.0
        self.t_rc = 0.0

    def poll(self, now: float, want_analog: bool = False, want_rc: bool = False) -> None:
        self.fc.send(MSP_ATTITUDE)
        self.fc.send(MSP_RAW_IMU)
        if want_analog:
            self.fc.send(MSP_ANALOG)
        if want_rc:
            self.fc.send(MSP_RC)
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

    def obs_age(self, now: float) -> float:
        if self.att is None or self.imu is None:
            return float("inf")
        return now - min(self.t_att, self.t_imu)

    def obs(self) -> list[float]:
        return obs_from_msp(self.att, self.imu)


def stream_rc(fc: MspUdpClient, us4: list[int]) -> None:
    # AETR + aux low. Aux is not overridden (mask) — values here are ignored by the FC.
    fc.send(MSP_SET_RAW_RC, pack_rc_channels(us4 + [1000, 1000, 1000, 1000]))


# --- subcommands ----------------------------------------------------------------------------


def cmd_selftest(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    ref_path = Path(args.weights).parent / "policy_ref_outputs.json"
    with open(ref_path) as f:
        ref = json.load(f)
    worst = 0.0
    for name, obs in ref["inputs"].items():
        got = pol(obs)
        want = ref["outputs"][name]
        err = max(abs(g - w) for g, w in zip(got, want))
        worst = max(worst, err)
        print(f"  {name:26s} max|err| {err:.2e}  act {[round(v, 4) for v in got]}")
    ok = worst < 1e-4
    print(f"parity vs {ref_path}: worst {worst:.2e} -> {'OK' if ok else 'FAIL'}")
    if ok:
        us = action_to_us(pol([0.0] * pol.obs_dim), args.hover_us, args.min_us, args.max_us)
        print(f"level-still command @ hover_us={args.hover_us}: AETR {us} "
              f"(throttle should be ~{args.hover_us})")
        # Closed-loop direction sanity through the FULL conversion chain (empirical signs):
        nose_down = action_to_us(pol([0.0, 0.2, 0, 0, 0]), args.hover_us, args.min_us, args.max_us)
        tilt_right = action_to_us(pol([0.2, 0, 0, 0, 0]), args.hover_us, args.min_us, args.max_us)
        dir_ok = nose_down[1] < 1500 and tilt_right[0] < 1500
        print(f"nose-down obs -> pitch_us {nose_down[1]} (<1500 = nose-up correction); "
              f"tilt-right obs -> roll_us {tilt_right[0]} (<1500 = roll-left correction) "
              f"-> {'OK' if dir_ok else 'FAIL'}")
        ok = ok and dir_ok
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    pol = Policy(args.weights)
    print("PROPS OFF check: hand-move the drone and verify (signs per the 2026-07-05 calibration):")
    print("  tilt RIGHT              -> roll(sim) positive,  roll_us  < 1500 (roll-left correction)")
    print("  tilt NOSE DOWN          -> pitch(sim) POSITIVE, pitch_us < 1500 (nose-up correction)")
    print("  spin CLOCKWISE (top)    -> 3rd gyro number NEGATIVE  (verifies the yaw sign; report it!)")
    print("  level & still           -> throttle ~ hover_us, roll/pitch/yaw ~ 1500")
    print("Ctrl+C to stop. Nothing is streamed to the FC in this mode.\n")
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        tel = Telemetry(fc)
        try:
            while True:
                now = time.monotonic()
                tel.poll(now, want_analog=True)
                if tel.obs_age(now) < 0.5:
                    o = tel.obs()
                    us = action_to_us(pol(o), args.hover_us, args.min_us, args.max_us,
                                      args.trim_thrust)
                    print(f"\r roll {math.degrees(o[0]):+6.1f}  pitch(sim) {math.degrees(o[1]):+6.1f} deg"
                          f" | gyro {math.degrees(o[2]):+7.1f} {math.degrees(o[3]):+7.1f}"
                          f" {math.degrees(o[4]):+7.1f} deg/s | cmd RPTY(us) {us}"
                          f" | vbat {tel.vbat or 0:.2f}V   ", end="")
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


def cmd_fly(args: argparse.Namespace) -> int:
    if not args.ack_props_on:
        sys.exit("refusing: fly streams live flight commands. Re-run with --ack-props-on once\n"
                 "the drone is tethered, the area is clear, and YOUR thumb is on the override\n"
                 "switch + arm/kill on the Pocket.")
    pol = Policy(args.weights)
    log_path = Path(args.log or f"runs/pilot/flight_{int(time.time())}.csv")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fout = open(log_path, "w", newline="")
    writer = csv.writer(fout)
    writer.writerow(["t", "obs_age_ms", "roll", "pitch", "p", "q", "r",
                     "a_thr", "a_wx", "a_wy", "a_wz", "us_roll", "us_pitch", "us_thr", "us_yaw",
                     "vbat", "hover_eff", "vz_est", "trim"])

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))

    period = 1.0 / args.hz
    ramp_s = 1.5  # end-of-flight thrust ramp-down
    with MspUdpClient(args.udp_host, args.udp_port) as fc:
        # WHICH aux channel is the override switch? Ask the FC — MSP_MODE_RANGES lists every
        # Modes-tab assignment by permanent box id. (Watching for "any aux that rises" grabbed
        # the ARM flip first: arm and override are both just aux channels on the Pocket.)
        override_rng = arm_rng = ranges = None
        for attempt in range(16):  # ~8 s of patience: single UDP losses must not abort a flight
            try:
                ranges = decode_mode_ranges(fc.request(MSP_MODE_RANGES, retries=0))
                break
            except MspTimeout:
                print("waiting for the FC link" if attempt == 0 else ".",
                      end="", flush=True)
            except MspError as e:
                sys.exit(f"FC rejected MSP_MODE_RANGES: {e}")
        if attempt:
            print()
        if ranges is None and args.aux is None:
            sys.exit("no reply to MSP_MODE_RANGES in ~8 s — bridge/FC link down? Check the bridge "
                     "LED, then: python3 scripts/bench.py --udp <host> info")
        for r in ranges or []:
            if r["perm_id"] == BOX_MSP_OVERRIDE and override_rng is None:
                override_rng = r
            elif r["perm_id"] == BOX_ARM and arm_rng is None:
                arm_rng = r
        if args.aux is not None:
            override_rng = {"aux_idx": args.aux - 1, "lo_us": 1700, "hi_us": 2115}
        if override_rng is None:
            sys.exit("the FC reports no MSP OVERRIDE mode range — assign it to a switch in the\n"
                     "Modes tab (and `save`), or pass --aux N to name the aux channel manually.")
        ov_ch = 4 + override_rng["aux_idx"]  # rcData index
        print(f"override switch = AUX{override_rng['aux_idx'] + 1} "
              f"[{override_rng['lo_us']}-{override_rng['hi_us']} us]"
              + (f"; arm = AUX{arm_rng['aux_idx'] + 1} (ignored)" if arm_rng else ""))

        tel = Telemetry(fc)
        print("acquiring telemetry...")
        t0 = time.monotonic()
        while tel.obs_age(time.monotonic()) > 0.1:
            tel.poll(time.monotonic(), want_analog=True)
            time.sleep(0.02)
            if time.monotonic() - t0 > 10.0:
                sys.exit("no telemetry from the bridge — is the battery in and the LED blinking?")
        print(f"telemetry live (vbat {tel.vbat or 0:.2f} V). hover_us={args.hover_us} "
              f"trim={args.trim_thrust:+.4f} yaw={args.yaw}. Ctrl+C = instant release.")

        # Watch rcData[ov_ch] (straight from the radio — the mask never overrides aux) for an
        # OFF -> IN-RANGE transition of the override switch: that starts the flight clock.
        # The same channel leaving the range mid-flight = manual takeover.
        seen_off = False
        warned_already_on = False
        armed_seen = False
        t_start = None
        if args.takeoff and args.launch:
            sys.exit("pick one of --takeoff / --launch")
        staged = args.launch or args.takeoff
        hold_s = args.hold_seconds if staged else 0.0
        ramp_in_s = (args.boost_s + TAKEOFF_SETTLE_S) if args.takeoff else (0.5 if args.launch else 0.0)
        boost_us = int(1000 + (args.hover_us - 1000) * math.sqrt(args.boost))
        if args.takeoff:
            print(f"GROUND-TAKEOFF mode: set the drone LEVEL on the floor, stand clear, ARM on "
                  f"the Pocket, flip the OVERRIDE switch — {hold_s:.0f}s idle countdown, then it "
                  f"spools to {args.boost:.2f}x hover ({boost_us} us) for {args.boost_s:.1f}s and "
                  f"hands to the policy. After the flight it ramps down and lands: DISARM then.")
        elif args.launch:
            print(f"HAND-LAUNCH mode: hold the drone (grip the duct, fingers clear), ARM on the "
                  f"Pocket, flip the OVERRIDE SWITCH — {hold_s:.0f}s idle countdown, then the "
                  f"throttle ramps up WHILE YOU KEEP HOLDING; release only at 'GO'. After the "
                  f"flight it ramps down and settles: DISARM then.")
        else:
            print(f"streaming... FLIP THE OVERRIDE SWITCH to start the {args.seconds}s flight window "
                  "(keep your throttle stick at hover for the handback!)")

        n_sent = n_stale = 0
        worst_age = 0.0
        tick = 0
        last_countdown = -1
        bad_att_since = None  # crash detector: sustained extreme attitude -> cut + release
        vfilt = None          # slow-EMA vbat for the sag-compensated hover anchor
        last_wait_print = 0.0
        az_cal: list[int] = []   # countdown acc-z samples (drone at rest -> 1 g reference)
        az_ref = None
        vz = 0.0                 # leak-filtered climb-rate estimate (m/s, + = up)
        thr_trim = 0.0
        i_trim = 0.0             # integral trim: absorbs the pack's constant thrust bias
        t_last_fresh = None
        try:
            while not stop["flag"]:
                now = time.monotonic()
                tick += 1
                tel.poll(now, want_analog=(tick % int(args.hz) == 0), want_rc=(tick % 5 == 0))
                if tel.vbat:
                    vfilt = tel.vbat if vfilt is None else 0.98 * vfilt + 0.02 * tel.vbat

                if t_start is None and staged and now - last_wait_print > 3.0:
                    last_wait_print = now
                    sw = tel.rc[ov_ch] if tel.rc is not None and len(tel.rc) > ov_ch else None
                    print(f"waiting (idle throttle): override aux{override_rng['aux_idx'] + 1} = "
                          f"{sw if sw is not None else 'no RC data yet'}")

                if tel.rc is not None and len(tel.rc) > ov_ch:
                    ov_on = override_rng["lo_us"] <= tel.rc[ov_ch] <= override_rng["hi_us"]
                    if (arm_rng and not armed_seen and len(tel.rc) > 4 + arm_rng["aux_idx"]
                            and arm_rng["lo_us"] <= tel.rc[4 + arm_rng["aux_idx"]] <= arm_rng["hi_us"]):
                        armed_seen = True
                        print(f"\narm switch ON (aux{arm_rng['aux_idx'] + 1}) — now flip the "
                              f"OVERRIDE switch (aux{override_rng['aux_idx'] + 1}) to start")
                    if t_start is None:
                        if not ov_on:
                            seen_off = True
                        elif seen_off:
                            t_start = now
                            print(f"\noverride ON (aux{override_rng['aux_idx'] + 1}) -> policy flying")
                        elif not warned_already_on:
                            warned_already_on = True
                            print("override switch is already ON — flip it OFF, then ON to start")
                    elif not ov_on:
                        print("\noverride switch OFF -> manual takeover, releasing")
                        break

                t_fl = (now - t_start) if t_start is not None else 0.0
                t_air = t_fl - hold_s - ramp_in_s  # airborne time (launch phases excluded)
                if t_start is not None and t_air >= args.seconds + ramp_s:
                    break
                age = tel.obs_age(now)
                worst_age = max(worst_age, min(age, 9.9))
                if age > args.max_obs_age:
                    n_stale += 1
                    if age > 0.5 and t_start is not None:
                        print(f"\nobs stale {age * 1e3:.0f} ms -> releasing to Pocket")
                        break  # stop streaming: Betaflight freshness window hands back RC
                    # brief staleness: skip this tick (FC holds last values up to 300 ms).
                    # While still WAITING for the switch, stales are harmless (idle stream,
                    # drone on the ground) — never exit, just keep polling.
                else:
                    o = tel.obs()
                    # Crash detector (flight_1783273010: it lay INVERTED for 2 s with motors
                    # grinding at 1467 us — the blind policy can't know it's on its back).
                    # Sustained-only, so mid-tumble sign flips through +-180 don't cut a
                    # recovery attempt; a settled upside-down/pinned drone trips it fast.
                    hopeless = abs(o[0]) > math.radians(110) or abs(o[1]) > math.radians(80)
                    if t_start is not None and hopeless:
                        if bad_att_since is None:
                            bad_att_since = now
                        elif now - bad_att_since > 0.3:
                            print(f"\ncrashed (|roll| {math.degrees(abs(o[0])):.0f} deg for 0.3 s)"
                                  " -> releasing, DISARM on the Pocket")
                            break
                    else:
                        bad_att_since = None
                    # Acc-z climb damper (see VZ_* constants). Calibrate the 1 g reference while
                    # the drone rests through the countdown; integrate from spool start so the
                    # takeoff boost's climb rate is known — and damped — at handoff.
                    acc_z = tel.imu["acc_raw"][2]
                    if t_start is not None and staged and t_fl < hold_s:
                        if t_fl > 0.5:
                            az_cal.append(acc_z)
                    elif az_ref is None and len(az_cal) >= 20:
                        tail = az_cal[len(az_cal) // 4:]
                        ref = sum(tail) / len(tail)
                        if abs(ref) > 100:
                            az_ref = ref
                            print(f"  acc 1g = {az_ref:.0f} raw ({len(az_cal)} rest samples) "
                                  f"— climb damper armed (gain {args.vz_gain})")
                    if (az_ref is not None and args.vz_gain > 0
                            and t_start is not None and t_fl >= hold_s):
                        dt = min(0.1, now - t_last_fresh) if t_last_fresh is not None else 0.0
                        if abs(o[0]) < VZ_TILT_LIMIT and abs(o[1]) < VZ_TILT_LIMIT:
                            a_vert = (acc_z / az_ref * math.cos(o[0]) * math.cos(o[1]) - 1.0) * 9.81
                            vz = (vz + a_vert * dt) * math.exp(-dt / VZ_LEAK_TAU)
                            vz = max(-VZ_CLAMP, min(VZ_CLAMP, vz))
                            # I only in the hover window: not during boost (keeps the takeoff
                            # punch) and not during ramp-down (intentional descent).
                            if 0.0 < t_air <= args.seconds:
                                i_trim = max(-VZ_ITRIM_CAP,
                                             min(VZ_ITRIM_CAP, i_trim - VZ_TRIM_KI * vz * dt))
                        else:
                            vz *= math.exp(-dt / VZ_LEAK_TAU)  # tilted: no new evidence, decay
                        thr_trim = max(-VZ_TRIM_CAP, min(VZ_TRIM_CAP, -args.vz_gain * vz)) + i_trim
                    t_last_fresh = now

                    act = pol(o)
                    if t_air > args.seconds:  # ramp down: ease thrust action toward floor
                        k = (t_air - args.seconds) / ramp_s
                        act = [act[0] * (1 - k) + (-1.0) * k, act[1], act[2], act[3]]
                    # Sag-compensated hover anchor: hover_us was measured at --vbat-ref; required
                    # duty scales ~1/V, so re-anchor on the (filtered) live voltage. At 3.45 V the
                    # calibrated 1410 is BELOW true hover — flight_1783276185 sank and bounced off
                    # the floor on exactly this.
                    comp = 1.0
                    if args.vbat_ref > 0 and vfilt:
                        comp = max(0.9, min(1.2, args.vbat_ref / vfilt))
                    hover_eff = int(1000 + (args.hover_us - 1000) * comp)
                    boost_us = int(1000 + (hover_eff - 1000) * math.sqrt(args.boost))
                    us = action_to_us(act, hover_eff, args.min_us, args.max_us,
                                      args.trim_thrust + thr_trim)
                    if args.yaw == "center":
                        us[3] = 1500  # zero-rate setpoint: the FC damps yaw itself (sign unverified)
                    if staged and t_start is None:
                        # Waiting for the switch: stream IDLE, never the policy's hover throttle.
                        # (Streaming ~1410 us while waiting meant an early/undetected override
                        # flip sent the drone STRAIGHT UP — observed, ceiling included.)
                        us = [1500, 1500, args.min_us, 1500]
                    elif t_start is not None and staged and t_fl < hold_s:
                        # Countdown: props at idle (in hand for --launch, on the floor for --takeoff).
                        us = [1500, 1500, args.min_us, 1500]
                        remaining = int(hold_s - t_fl) + 1
                        if remaining != last_countdown:
                            last_countdown = remaining
                            print(f"  {'liftoff' if args.takeoff else 'throttle'} in {remaining}...")
                    elif t_start is not None and staged and t_fl < hold_s + ramp_in_s:
                        if last_countdown != 0:
                            last_countdown = 0
                            print("  LIFTOFF" if args.takeoff else "  throttle ramping — KEEP HOLDING")
                        tp = t_fl - hold_s
                        if args.takeoff:
                            if tp < TAKEOFF_SPOOL_S:      # spool: idle -> boost, fast
                                us[2] = int(args.min_us + (boost_us - args.min_us) * (tp / TAKEOFF_SPOOL_S))
                            elif tp < args.boost_s:       # climb-out above hover
                                us[2] = boost_us
                            else:                         # settle: boost -> policy command
                                k = (tp - args.boost_s) / TAKEOFF_SETTLE_S
                                us[2] = int(boost_us + (us[2] - boost_us) * k)
                        else:                             # --launch: idle -> policy while still held
                            us[2] = int(args.min_us + (us[2] - args.min_us) * (tp / ramp_in_s))
                    elif t_start is not None and args.launch and last_countdown != -2:
                        last_countdown = -2  # throttle is fully up now — only NOW let go
                        print("  GO — release!")
                    stream_rc(fc, us)
                    n_sent += 1
                    writer.writerow([f"{t_fl:.3f}", f"{age * 1e3:.0f}",
                                     *[f"{v:.4f}" for v in o], *[f"{v:.4f}" for v in act],
                                     *us, tel.vbat or "", hover_eff,
                                     f"{vz:.3f}", f"{thr_trim:+.4f}"])
                time.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            fout.close()
        print(f"\nreleased. {n_sent} frames streamed, {n_stale} stale ticks, "
              f"worst obs age {worst_age * 1e3:.0f} ms. Log: {log_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--udp", required=True, metavar="HOST[:PORT]", help="bridge address")
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
                     help="takeoff thrust in hover-units; 1.0 just sits on the ground")
    fly.add_argument("--boost-s", type=float, default=0.6,
                     help="seconds of boost before settling onto the policy")
    fly.add_argument("--launch", action="store_true",
                     help="hand-launch flow: after the override switch, idle countdown, throttle "
                          "ramps WHILE HELD, release only at GO")
    fly.add_argument("--hold-seconds", type=float, default=3.0)
    fly.add_argument("--vz-gain", type=float, default=0.15,
                     help="acc-z climb damper gain (act[0] per m/s of estimated climb); "
                          "0 disables")
    fly.add_argument("--aux", type=int, default=None, metavar="N",
                     help="override-switch aux channel number (1-4); normally auto-detected "
                          "from the FC's MSP OVERRIDE mode range")
    fly.add_argument("--log", default=None)
    fly.add_argument("--ack-props-on", action="store_true")
    args = ap.parse_args()

    host, _, port = args.udp.partition(":")
    args.udp_host, args.udp_port = host, int(port or 14550)
    return {"selftest": cmd_selftest, "check": cmd_check, "fly": cmd_fly}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
