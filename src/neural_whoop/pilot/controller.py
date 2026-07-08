"""The offboard-pilot flight engine — the ``cmd_fly`` state machine as a steppable class.

``scripts/pilot.py``'s ``fly`` loop was a single inline ``while`` triggered by a physical override-
switch edge and printing to a console. :class:`FlightController` is that exact loop, one 50 Hz tick
per :meth:`step`: every former loop local is now an instance attribute, and the phase is *derived
from the same inline predicates* the loop always used (``t_start``, ``staged``, ``t_fl``,
``t_liftoff_tp`` …). The numerics are unchanged, so the CLI (``scripts/pilot.py fly``) and the
always-on web dashboard (:mod:`neural_whoop.studio.flight`) run byte-identical control.

**Start-trigger seam = the safety interlock.** ``start_mode="switch"`` (CLI): the override OFF->ON
edge sets ``t_start``, exactly as today. ``start_mode="software"`` (UI): the edge does *not* auto-
start; :meth:`request_start` sets ``t_start`` and is **rejected unless the drone is already ARMED +
override-engaged** on the radio. In *both* modes, override leaving range / stale obs / a crash still
calls :meth:`abort`. The radio owns enable + kill; software only ever sets a clock, and stopping the
RC stream is the only "stop" (Betaflight's ~300 ms MSP-freshness window hands control back).

Pure stdlib (``math`` + ``time`` + ``enum``): imports zero torch/numpy. Human messages route through
the injected ``log`` callback (the CLI passes ``print``; the web manager captures them); the 24-col
CSV row goes to ``on_log`` (``analysis/flight_log.py::LOG_COLUMNS`` order).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

from neural_whoop.bench.msp import (
    MSP_MODE_RANGES,
    MspError,
    MspTimeout,
    decode_mode_ranges,
)

from .config import (
    BOX_ARM,
    BOX_MSP_OVERRIDE,
    LIFT_LAG_US,
    LIFT_VZ,
    MAX_THRUST_NORMED,
    RAMP_DOWN_S,
    RISE_S,
    RISE_THRUST,
    RPM_CORR_CAP,
    RPM_KI_US,
    SEEK_RATE_US_S,
    SEEK_SPOOL_S,
    SEEK_START_US,
    SEEK_TIMEOUT_S,
    VZ_CLAMP,
    VZ_LEAK_TAU,
    VZ_TILT_LIMIT,
)
from .policy import Policy, action_to_us, rpm_climb_rate, rpm_damper_trim, stack_frames
from .telemetry import Telemetry, stream_rc


class FlightSetupError(RuntimeError):
    """A hard failure during :meth:`FlightController.setup` (no FC link / no override / no telem).

    The CLI turns this into a ``sys.exit`` with the same message; the always-on web manager catches
    it and retries with backoff (the bridge may simply not be up yet).
    """


class Phase(Enum):
    """The flight state machine, derived from the same predicates ``cmd_fly`` computed inline."""

    WAITING = "waiting"      # streaming idle (or nothing) until the override switch engages
    COUNTDOWN = "countdown"  # staged: props idle for hold_seconds (3,2,1)
    SEEK = "seek"            # --takeoff: slow throttle ramp seeking the liftoff point
    RISE = "rise"            # gentle climb-out on the learned hover anchor (or --launch ramp)
    HOVER = "hover"          # the policy is flying
    LAND = "land"            # end-of-flight thrust ramp-down
    RELEASED = "released"    # flight completed, link handed back to the radio
    ABORTED = "aborted"      # override dropped / obs stale / crash / user stop -> released early


@dataclass
class FlightParams:
    """Every ``fly`` knob, defaulting EXACTLY to the ``fly`` subparser + shared-arg defaults."""

    seconds: float = 15.0
    hz: float = 50.0
    max_obs_age: float = 0.25
    yaw: str = "center"           # "center" | "policy"
    takeoff: bool = False
    launch: bool = False
    hold_seconds: float = 3.0
    vz_gain: float = 0.15
    trim_roll_deg: float = 0.0
    trim_pitch_deg: float = 0.0
    aux: int | None = None
    hover_us: int = 1410
    vbat_ref: float = 0.0
    trim_thrust: float = 0.0
    min_us: int = 1000
    max_us: int = 1600
    ramp_s: float = RAMP_DOWN_S   # end-of-flight thrust ramp-down window (s)

    def __post_init__(self) -> None:
        if self.takeoff and self.launch:
            raise ValueError("pick one of takeoff / launch")


class FlightController:
    """One steppable offboard flight: :meth:`setup`, then :meth:`step` at ``params.hz`` until done.

    Args:
        fc: an open :class:`~neural_whoop.bench.msp.MspUdpClient` (or any ``_MspEndpoint``).
        policy: a loaded :class:`~neural_whoop.pilot.policy.Policy`.
        params: a :class:`FlightParams`.
        start_mode: ``"switch"`` (the override edge auto-starts, CLI) or ``"software"`` (the edge
            only *arms* the software Start; :meth:`request_start` sets the clock, gated on armed +
            override).
        clock: monotonic time source (injectable for tests).
        sleep: sleeper used only inside :meth:`setup`'s telemetry-acquire loop (injectable).
        on_log: called with each 24-col CSV row (LOG_COLUMNS order); ``None`` disables logging.
        log: called with each human-readable status line; ``None`` is silent (the CLI passes
            ``print`` to preserve its console output; the web manager captures the lines).
    """

    def __init__(self, fc, policy: Policy, params: FlightParams, *,
                 start_mode: str = "switch", clock=time.monotonic, sleep=time.sleep,
                 on_log=None, log=None) -> None:
        if start_mode not in ("switch", "software"):
            raise ValueError(f"start_mode must be 'switch' or 'software', got {start_mode!r}")
        self.fc = fc
        self.pol = policy
        self.params = params
        self.start_mode = start_mode
        self._clock = clock
        self._sleep = sleep
        self._on_log = on_log or (lambda _row: None)
        self._log = log if log is not None else (lambda *_a, **_k: None)

        self.tel = Telemetry(fc)

        # Staging (mirrors cmd_fly): --takeoff/--launch are "staged"; the ramp-in window differs.
        self.staged = params.launch or params.takeoff
        self.hold_s = params.hold_seconds if self.staged else 0.0
        self.ramp_in_s = (SEEK_TIMEOUT_S + RISE_S) if params.takeoff else (
            0.5 if params.launch else 0.0)
        self.ramp_s = params.ramp_s

        # Setup discovers these.
        self.override_rng: dict | None = None
        self.arm_rng: dict | None = None
        self.ov_ch: int | None = None

        # --- former cmd_fly loop locals, now instance state ---
        self.seen_off = False
        self.warned_already_on = False
        self.armed_seen = False
        self.override_on = False
        self.t_start: float | None = None
        self.n_sent = 0
        self.n_stale = 0
        self.worst_age = 0.0
        self.tick = 0
        self.last_countdown = -1
        self.bad_att_since: float | None = None
        self.vfilt: float | None = None
        self.last_wait_print = 0.0
        self.az_cal: list[int] = []
        self.az_ref: float | None = None
        self.lvl_cal: list[tuple] = []
        self.lvl = (0.0, 0.0)
        self.vz = 0.0
        self.obs_hist: deque = deque(maxlen=policy.obs_stack)
        self.thr_trim = 0.0
        self.t_last_fresh: float | None = None
        self.t_liftoff_tp: float | None = None
        self.hover_learned: int | None = None
        self.v_liftoff: float | None = None
        self.fup_buf: list[tuple] = []
        self.rpm_buf: list[tuple] = []
        self.rpm_hover: float | None = None
        self.us_corr = 0.0
        self.trim_roll_rad = math.radians(params.trim_roll_deg)
        self.trim_pitch_rad = math.radians(params.trim_pitch_deg)

        # Frame-display state (kept between ticks so idle/stale frames still carry last-known).
        self.roll = self.pitch = self.p = self.q = self.r = 0.0
        self.age = float("inf")
        self.us = [1500, 1500, params.min_us, 1500]
        self.hover_eff = params.hover_us
        self._rpm_now: float | None = None
        self._thrust_norm = 0.0
        self._t_fl = 0.0
        self._t_air = 0.0

        self._done = False
        self._aborted = False
        self._released = False
        self._abort_reason: str | None = None

    # ------------------------------------------------------------------ setup
    def setup(self) -> dict:
        """Discover the MSP OVERRIDE / ARM aux channels and acquire fresh telemetry.

        Raises :class:`FlightSetupError` on any hard failure (no FC reply, no override range, no
        telemetry) — the CLI ``sys.exit``s the message, the web manager retries.
        """
        p = self.params
        override_rng = arm_rng = ranges = None
        for attempt in range(16):  # ~8 s of patience: single UDP losses must not abort a flight
            try:
                ranges = decode_mode_ranges(self.fc.request(MSP_MODE_RANGES, retries=0))
                break
            except MspTimeout:
                self._log("waiting for the FC link" if attempt == 0 else ".")
            except MspError as e:
                raise FlightSetupError(f"FC rejected MSP_MODE_RANGES: {e}")
        if ranges is None and p.aux is None:
            raise FlightSetupError(
                "no reply to MSP_MODE_RANGES in ~8 s — bridge/FC link down? Check the bridge "
                "LED, then: python3 scripts/bench.py --udp <host> info")
        for r in ranges or []:
            if r["perm_id"] == BOX_MSP_OVERRIDE and override_rng is None:
                override_rng = r
            elif r["perm_id"] == BOX_ARM and arm_rng is None:
                arm_rng = r
        if p.aux is not None:
            override_rng = {"aux_idx": p.aux - 1, "lo_us": 1700, "hi_us": 2115}
        if override_rng is None:
            raise FlightSetupError(
                "the FC reports no MSP OVERRIDE mode range — assign it to a switch in the "
                "Modes tab (and `save`), or pass --aux N to name the aux channel manually.")
        self.override_rng = override_rng
        self.arm_rng = arm_rng
        self.ov_ch = 4 + override_rng["aux_idx"]  # rcData index
        self._log(f"override switch = AUX{override_rng['aux_idx'] + 1} "
                  f"[{override_rng['lo_us']}-{override_rng['hi_us']} us]"
                  + (f"; arm = AUX{arm_rng['aux_idx'] + 1} (ignored)" if arm_rng else ""))

        self._log("acquiring telemetry...")
        t0 = self._clock()
        while self.tel.obs_age(self._clock()) > 0.1:
            self.tel.poll(self._clock(), want_analog=True)
            self._sleep(0.02)
            if self._clock() - t0 > 10.0:
                raise FlightSetupError(
                    "no telemetry from the bridge — is the battery in and the LED blinking?")
        self._log(f"telemetry live (vbat {self.tel.vbat or 0:.2f} V). hover_us={p.hover_us} "
                  f"trim={p.trim_thrust:+.4f} yaw={p.yaw}.")
        return {
            "override_aux": override_rng["aux_idx"] + 1,
            "arm_aux": (arm_rng["aux_idx"] + 1) if arm_rng else None,
            "override_lo": override_rng["lo_us"], "override_hi": override_rng["hi_us"],
            "vbat": self.tel.vbat,
        }

    # ------------------------------------------------------------------ start / abort
    def request_start(self) -> bool:
        """Software Start (UI). Accepted ONLY if the radio already reports ARMED + override on.

        Sets the flight clock; the radio still owns enable + instant kill. Returns whether accepted.
        """
        if self._done or self.t_start is not None:
            return False
        if self.armed_seen and self.override_on:
            self.t_start = self._clock()
            self._log("software START accepted -> policy flying")
            return True
        return False

    def abort(self, reason: str = "user") -> None:
        """Stop the flight — stopping the RC stream IS the safe action (never touches arm/aux)."""
        if not self._done:
            self._log(f"\naborting ({reason}) -> releasing to Pocket")
            self._aborted = True
            self._done = True
            self._abort_reason = reason

    def _abort(self, reason: str) -> dict:
        if not self._done:
            self._aborted = True
            self._done = True
            self._abort_reason = reason
        return self._make_frame()

    def _release(self) -> dict:
        self._released = True
        self._done = True
        return self._make_frame()

    # ------------------------------------------------------------------ properties
    @property
    def done(self) -> bool:
        return self._done

    @property
    def phase(self) -> Phase:
        return self._derive_phase()

    @property
    def abort_reason(self) -> str | None:
        return self._abort_reason

    def status(self) -> dict:
        """Lightweight status (usable even while idle) — for the dashboard's Start gating."""
        return {
            "armed": self.armed_seen,
            "override_on": self.override_on,
            "link_age_ms": (self.age * 1e3 if math.isfinite(self.age) else None),
            "phase": self._derive_phase().value,
        }

    # ------------------------------------------------------------------ step (one 50 Hz tick)
    def step(self, now: float | None = None) -> dict:
        """Advance one control tick; return a frame dict (see module docstring / the plan schema)."""
        if self._done:
            return self._make_frame()
        p = self.params
        now = self._clock() if now is None else now
        self.tick += 1
        self.tel.poll(now, want_analog=(self.tick % int(p.hz) == 0),
                      want_rc=(self.tick % 5 == 0), want_rpm=True)
        if self.tel.vbat:
            self.vfilt = self.tel.vbat if self.vfilt is None else 0.98 * self.vfilt + 0.02 * self.tel.vbat

        if self.t_start is None and self.staged and now - self.last_wait_print > 3.0:
            self.last_wait_print = now
            sw = self.tel.rc[self.ov_ch] if (self.tel.rc is not None
                                             and len(self.tel.rc) > self.ov_ch) else None
            self._log(f"waiting (idle throttle): override aux{self.override_rng['aux_idx'] + 1} = "
                      f"{sw if sw is not None else 'no RC data yet'}")

        # --- override-switch tracking (the safety interlock) ---
        if self.tel.rc is not None and self.ov_ch is not None and len(self.tel.rc) > self.ov_ch:
            ov_on = self.override_rng["lo_us"] <= self.tel.rc[self.ov_ch] <= self.override_rng["hi_us"]
            self.override_on = ov_on
            arm = self.arm_rng
            if (arm and not self.armed_seen and len(self.tel.rc) > 4 + arm["aux_idx"]
                    and arm["lo_us"] <= self.tel.rc[4 + arm["aux_idx"]] <= arm["hi_us"]):
                self.armed_seen = True
                self._log(f"\narm switch ON (aux{arm['aux_idx'] + 1}) — now flip the "
                          f"OVERRIDE switch (aux{self.override_rng['aux_idx'] + 1}) to start")
            if self.t_start is None:
                if not ov_on:
                    self.seen_off = True
                elif self.seen_off:
                    if self.start_mode == "switch":
                        self.t_start = now
                        self._log(f"\noverride ON (aux{self.override_rng['aux_idx'] + 1}) -> policy flying")
                    # software mode: the edge only ARMS the software Start (request_start gates it).
                elif not self.warned_already_on:
                    self.warned_already_on = True
                    self._log("override switch is already ON — flip it OFF, then ON to start")
            elif not ov_on:
                self._log("\noverride switch OFF -> manual takeover, releasing")
                return self._abort("override_off")

        t_fl = (now - self.t_start) if self.t_start is not None else 0.0
        t_air = t_fl - self.hold_s - self.ramp_in_s  # airborne time (launch phases excluded)
        self._t_fl, self._t_air = t_fl, t_air
        if self.t_start is not None and t_air >= p.seconds + self.ramp_s:
            return self._release()
        age = self.tel.obs_age(now)
        self.worst_age = max(self.worst_age, min(age, 9.9))
        self.age = age
        if age > p.max_obs_age:
            self.n_stale += 1
            if age > 0.5 and self.t_start is not None:
                self._log(f"\nobs stale {age * 1e3:.0f} ms -> releasing to Pocket")
                return self._abort("stale_obs")
            # brief staleness: skip this tick (FC holds last values up to 300 ms). While WAITING
            # for the switch, stales are harmless (idle stream, drone on the ground).
            return self._make_frame()

        # --- fresh obs: the full control tick ---
        o = self.tel.obs()
        self.roll, self.pitch, self.p, self.q, self.r = o[0], o[1], o[2], o[3], o[4]
        # Crash detector: sustained extreme attitude -> cut + release.
        hopeless = abs(o[0]) > math.radians(110) or abs(o[1]) > math.radians(80)
        if self.t_start is not None and hopeless:
            if self.bad_att_since is None:
                self.bad_att_since = now
            elif now - self.bad_att_since > 0.3:
                self._log(f"\ncrashed (|roll| {math.degrees(abs(o[0])):.0f} deg for 0.3 s)"
                          " -> releasing, DISARM on the Pocket")
                return self._abort("crash")
        else:
            self.bad_att_since = None

        acc_z = self.tel.imu["acc_raw"][2]
        rpm_now = self.tel.rpm_rms(now)
        self._rpm_now = rpm_now
        dt_tick = min(0.1, now - self.t_last_fresh) if self.t_last_fresh is not None else 0.0
        if (p.takeoff and self.t_start is not None and self.t_liftoff_tp is None
                and t_fl >= self.hold_s and rpm_now):
            self.rpm_buf.append((t_fl - self.hold_s, rpm_now))
        if self.t_start is not None and self.staged and t_fl < self.hold_s:
            if t_fl > 0.5:
                self.az_cal.append(acc_z)
                if p.takeoff:  # resting on the floor: this attitude IS level
                    self.lvl_cal.append((o[0], o[1]))
        elif self.az_ref is None and len(self.az_cal) >= 20:
            tail = self.az_cal[len(self.az_cal) // 4:]
            ref = sum(tail) / len(tail)
            if abs(ref) > 100:
                self.az_ref = ref
                self._log(f"  acc 1g = {self.az_ref:.0f} raw ({len(self.az_cal)} rest samples) "
                          f"— climb damper armed (gain {p.vz_gain})")
            if self.lvl_cal:
                n = len(self.lvl_cal)
                tail_l = self.lvl_cal[n // 4:]
                self.lvl = (sum(v[0] for v in tail_l) / len(tail_l),
                            sum(v[1] for v in tail_l) / len(tail_l))
                self._log(f"  level reference: roll {math.degrees(self.lvl[0]):+.1f} / "
                          f"pitch {math.degrees(self.lvl[1]):+.1f} deg (floor-rest bias, "
                          "subtracted from the policy's view)")
        if (self.az_ref is not None and (p.vz_gain > 0 or self.pol.uses_vz)
                and self.t_start is not None and t_fl >= self.hold_s):
            dt = dt_tick
            ax, ay = self.tel.imu["acc_raw"][0], self.tel.imu["acc_raw"][1]
            f_up = (-ax * math.sin(o[1])
                    + ay * math.cos(o[1]) * math.sin(o[0])
                    + acc_z * math.cos(o[1]) * math.cos(o[0]))
            if p.takeoff and self.t_liftoff_tp is None:
                self.fup_buf.append((t_fl - self.hold_s, f_up))
            if abs(o[0]) < VZ_TILT_LIMIT and abs(o[1]) < VZ_TILT_LIMIT:
                a_vert = (f_up / self.az_ref - 1.0) * 9.81
                self.vz = (self.vz + a_vert * dt) * math.exp(-dt / VZ_LEAK_TAU)
                self.vz = max(-VZ_CLAMP, min(VZ_CLAMP, self.vz))
            else:
                self.vz *= math.exp(-dt / VZ_LEAK_TAU)  # tilted: no new evidence, decay
            if self.pol.uses_vz:
                self.thr_trim = 0.0
            else:
                self.thr_trim = rpm_damper_trim(rpm_now, self.rpm_hover, p.vz_gain)
                if self.rpm_hover:
                    self.vz = rpm_climb_rate(rpm_now, self.rpm_hover)
        self.t_last_fresh = now
        # Level reference + manual trim, policy's view only (estimator uses raw).
        o = [o[0] - self.lvl[0] - self.trim_roll_rad,
             o[1] - self.lvl[1] - self.trim_pitch_rad, o[2], o[3], o[4]]

        frame = o + [self.vz] if self.pol.uses_vz else o
        act = self.pol(stack_frames(self.obs_hist, frame, self.pol.obs_stack))
        if t_air > p.seconds:  # ramp down: ease thrust action toward floor
            k = (t_air - p.seconds) / self.ramp_s
            act = [act[0] * (1 - k) + (-1.0) * k, act[1], act[2], act[3]]
        self._thrust_norm = (max(-1.0, min(1.0, act[0] + p.trim_thrust + self.thr_trim)) + 1.0) \
            * 0.5 * MAX_THRUST_NORMED
        # Hover anchor: the liftoff-learned value, sag-adjusted relative to the liftoff voltage.
        base_hover = self.hover_learned if self.hover_learned is not None else p.hover_us
        comp = 1.0
        if p.vbat_ref > 0 and self.vfilt:  # legacy absolute mode (opt-in)
            comp = max(0.9, min(1.2, p.vbat_ref / self.vfilt))
        elif self.v_liftoff and self.vfilt:
            comp = max(0.97, min(1.12, self.v_liftoff / self.vfilt))
        hover_eff = int(1000 + (base_hover - 1000) * comp)
        us = action_to_us(act, hover_eff, p.min_us, p.max_us, p.trim_thrust + self.thr_trim)
        if p.yaw == "center":
            us[3] = 1500  # zero-rate setpoint: the FC damps yaw itself (sign unverified)
        if self.staged and self.t_start is None:
            # Waiting for the switch: stream IDLE, never the policy's hover throttle.
            us = [1500, 1500, p.min_us, 1500]
        elif self.t_start is not None and self.staged and t_fl < self.hold_s:
            us = [1500, 1500, p.min_us, 1500]
            remaining = int(self.hold_s - t_fl) + 1
            if remaining != self.last_countdown:
                self.last_countdown = remaining
                self._log(f"  {'liftoff' if p.takeoff else 'throttle'} in {remaining}...")
        elif self.t_start is not None and self.staged and t_fl < self.hold_s + self.ramp_in_s:
            if self.last_countdown != 0:
                self.last_countdown = 0
                self._log("  seeking liftoff (slow ramp)..." if p.takeoff
                          else "  throttle ramping — KEEP HOLDING")
            tp = t_fl - self.hold_s
            if p.takeoff:
                if self.t_liftoff_tp is None:  # seek: slow ramp until acc-z sees liftoff
                    if tp < SEEK_SPOOL_S:
                        us[2] = int(p.min_us + (SEEK_START_US - p.min_us) * (tp / SEEK_SPOOL_S))
                    else:
                        us[2] = int(min(p.max_us,
                                        SEEK_START_US + SEEK_RATE_US_S * (tp - SEEK_SPOOL_S)))
                    if us[2] > 1250 and self.vz > LIFT_VZ:
                        self.t_liftoff_tp = tp
                        self.hover_learned = max(1250, min(1550, us[2] - LIFT_LAG_US))
                        self.ramp_in_s = self.t_liftoff_tp + RISE_S  # flight clock: rise ends it
                        self.v_liftoff = self.vfilt
                        self._log(f"  LIFTOFF at {us[2]} us -> hover anchor learned: "
                                  f"{self.hover_learned} us")
                        cal = [f for (tt, f) in self.fup_buf if tp - 0.7 <= tt <= tp - 0.2]
                        if len(cal) >= 8:
                            new_ref = sum(cal) / len(cal)
                            self._log(f"  1g re-referenced at throttle: {self.az_ref:.0f} -> "
                                      f"{new_ref:.0f} ({(new_ref / self.az_ref - 1) * 100:+.1f}%)")
                            self.az_ref = new_ref
                            self.vz = 0.3  # we know it just lifted at ~this rate
                        rcal = [v for (tt, v) in self.rpm_buf if tp - 0.3 <= tt <= tp - 0.02]
                        if len(rcal) >= 4:
                            self.rpm_hover = sum(rcal) / len(rcal)
                            self._log(f"  hover RPM anchor: {self.rpm_hover:.0f} rms "
                                      "(breakaway = weight) — RPM governor armed")
                    elif tp > SEEK_TIMEOUT_S:
                        self._log("\nno liftoff within the seek window — weak pack or prop "
                                  "drag? releasing, DISARM")
                        return self._abort("no_liftoff")
                else:  # rise: gentle climb-out on the LEARNED anchor
                    us[2] = int(1000 + (self.hover_learned - 1000) * math.sqrt(RISE_THRUST))
            else:  # --launch: idle -> policy while still held
                us[2] = int(p.min_us + (us[2] - p.min_us) * (tp / self.ramp_in_s))
        elif self.t_start is not None and p.launch and self.last_countdown != -2:
            self.last_countdown = -2  # throttle is fully up now — only NOW let go
            self._log("  GO — release!")
        # RPM thrust governor (free flight only): steer throttle so measured thrust tracks command.
        if (self.rpm_hover and rpm_now and self.t_start is not None
                and t_fl >= self.hold_s + self.ramp_in_s):
            a0c = max(-1.0, min(1.0, act[0] + p.trim_thrust + self.thr_trim))
            t_des = (a0c + 1.0) * 0.5 * MAX_THRUST_NORMED
            rpm_err = (rpm_now / self.rpm_hover) ** 2 - t_des
            self.us_corr = max(-RPM_CORR_CAP,
                               min(RPM_CORR_CAP, self.us_corr - RPM_KI_US * rpm_err * dt_tick))
            us[2] = int(max(p.min_us, min(p.max_us, us[2] + self.us_corr)))

        # Stream RC — but while WAITING with override OFF, send NOTHING (the FC ignores MSP RC when
        # override is off anyway; not streaming is strictly safer). Idle RC resumes the moment the
        # override switch is engaged (t_start set, or override_on true in software mode).
        if self.t_start is not None or self.override_on:
            stream_rc(self.fc, us)
            self.n_sent += 1
        self.us = us
        self.hover_eff = hover_eff
        self._on_log([f"{t_fl:.3f}", f"{age * 1e3:.0f}",
                      *[f"{v:.4f}" for v in o], *[f"{v:.4f}" for v in act],
                      *us, self.tel.vbat or "", hover_eff,
                      f"{self.vz:.3f}", f"{self.thr_trim:+.4f}", *self.tel.imu["acc_raw"],
                      f"{rpm_now:.0f}" if rpm_now else "", f"{self.us_corr:+.0f}"])
        return self._make_frame()

    # ------------------------------------------------------------------ frame / phase
    def _derive_phase(self) -> Phase:
        if self._aborted:
            return Phase.ABORTED
        if self._released:
            return Phase.RELEASED
        if self.t_start is None:
            return Phase.WAITING
        t_fl, t_air = self._t_fl, self._t_air
        if self.staged and t_fl < self.hold_s:
            return Phase.COUNTDOWN
        if self.staged and t_fl < self.hold_s + self.ramp_in_s:
            if self.params.takeoff:
                return Phase.SEEK if self.t_liftoff_tp is None else Phase.RISE
            return Phase.RISE  # --launch throttle ramp
        if t_air > self.params.seconds:
            return Phase.LAND
        return Phase.HOVER

    def _make_frame(self) -> dict:
        phase = self._derive_phase()
        age_ms = self.age * 1e3 if math.isfinite(self.age) else None
        acc = list(self.tel.imu["acc_raw"]) if self.tel.imu else [0, 0, 0]
        tilt_deg = math.degrees(math.hypot(self.roll, self.pitch))
        return {
            "type": "frame",
            "phase": phase.value,
            "step": self.tick,
            "t": self._t_air,
            "t_flight": self._t_fl,
            "telemetry": {
                "roll": self.roll, "pitch": self.pitch,
                "p": self.p, "q": self.q, "r": self.r,
                "vbat": self.tel.vbat, "rpm_rms": self._rpm_now,
                "obs_age_ms": age_ms, "acc": acc,
            },
            "cmd": {"us_roll": self.us[0], "us_pitch": self.us[1],
                    "us_thr": self.us[2], "us_yaw": self.us[3]},
            "metrics": {
                "tilt_deg": tilt_deg, "vz_est": self.vz, "thrust_norm": self._thrust_norm,
                "hover_eff": self.hover_eff, "trim": self.thr_trim, "us_corr": self.us_corr,
                "link_age_ms": age_ms, "battery_v": self.tel.vbat,
            },
            "status": {
                "armed": self.armed_seen, "override_on": self.override_on,
                "link_ok": math.isfinite(self.age) and self.age <= self.params.max_obs_age,
            },
        }
