#!/usr/bin/env python
"""Render a hero replay of the full blind take-off -> flip -> land sequence.

The pilot/fake-bridge path produces only a vertical-only ``pos`` stub, so for a real 3D hero
shot we reproduce the SAME system-level sequence in DiffAero (real positions + attitudes). **Both
halves are the shipped policies**, exactly the deploy split: the deployed 1.0 m ``hover_tof``
policy (``runs/hover_tof_air65_w128u15``, the same weights ``scripts/pilot.py`` and the Studio
Bench tab fly on the real Air65 II) owns take-off / hover / recover / land against a moving
setpoint, and the trained ``acro_flip`` policy owns the flip window. Pass ``--hover-weights pd``
for the old hand-written altitude/attitude PD. We drive ``WhoopDynamics`` directly, record every
control step into the versioned replay schema, and hand the result to the headless capturer.

The harness closes exactly one loop neither policy can: **heading**. obs-v4 drops yaw (not
observable without a magnetometer), so the hover policy has no yaw reference and settles on a
small constant yaw-rate bias — benign in a hover, fatal at the flip handoff, because DiffAero's
rate loop is not yaw-invariant (see ``FLIP_YAW_LIMIT_DEG``). The harness holds heading on the
gyro-integrated yaw the real pilot already forwards from ``MSP_ATTITUDE``.

The drone starts and ends **resting on the floor** (``pos.z == WHOOP_REST_Z_M``, the true-scale
airframe half-height) and each frame carries a numeric ``scene.phase`` code whose labels live in
``meta.scene_info.phase_labels`` — that is what the renderer turns into on-screen captions.

    uv run python scripts/takeoff_flip_land.py --axis roll --out runs/acro_flip/hero_seq
    uv run python scripts/capture_video.py --replay runs/acro_flip/hero_seq/replay.json.gz \
        --out runs/acro_flip/hero_seq/takeoff_flip_land.mp4 \
        --preset hero --width 1080 --height 1080
"""

from __future__ import annotations

import argparse
import math
from collections import deque
from pathlib import Path

import torch

import neural_whoop  # noqa: F401 - makes third_party/diffaero importable
from neural_whoop.contract import WHOOP_REST_Z_M, ActionLimits, action_to_diffaero, world_to_body
from neural_whoop.dynamics.whoop import WhoopDynamics, WhoopParams
from neural_whoop.pilot import Policy
from neural_whoop.pilot.policy import stack_frames
from neural_whoop.viz.replay import (
    ACTION_LAYOUT,
    COORDINATE_FRAME,
    STATE_LAYOUT,
    UNITY_HINT,
    RunRecorder,
)

_AXIS_IDX = {"roll": 0, "pitch": 1}

#: The obs-8 maneuver clock's window (s) — must match the trained task's ``maneuver_len_s``
#: (configs/acro_flip_v2.yaml) and the pilot's ``FlightParams.maneuver_len_s``, or the policy sees a
#: differently-scaled clock than it learned on. The flip starts when the hover half has settled,
#: which is the same handoff the real pilot's trigger is.
MANEUVER_LEN_S = 1.2
#: The pilot's free-flight throttle floor (``FlightParams.min_thrust_frac``), in normed thrust units.
MIN_THRUST_NORMED = 0.25

#: The shipped 1.0 m hover policy (★ studio-baseline) — the same weights scripts/pilot.py and the
#: Studio Bench tab fly on the real Air65 II. It owns climb / hover / recover / land here.
DEFAULT_HOVER_WEIGHTS = "runs/hover_tof_air65_w128u15/policy_weights.json"
#: The bridge ToF's range ceiling (configs/hover_tof_air65_w128u15.yaml, tof_max_m) —
#: the policy never sees a height above this, so neither do we.
TOF_MAX_M = 1.3

#: Caption labels for the numeric ``scene.phase`` channel, index == code. The recorder coerces
#: every ``scene`` value through ``_vec()``, so the per-frame channel has to be a NUMBER; the
#: human-readable strings ride once in ``meta.scene_info.phase_labels``.
PHASE_LABELS = ["TAKE-OFF", "HOVER", "FLIP", "RECOVER", "LAND"]
_PHASE_CODE = {"climb": 0, "hover": 1, "flip": 2, "recover": 3, "land": 4}


def _act_v2_from_ctbr(ctbr: torch.Tensor, lim: ActionLimits) -> list[float]:
    """Invert ``action_to_diffaero`` so the recorded act-v2 matches the DiffAero action we sent."""
    t = ctbr[0].item() / lim.max_thrust_normed * 2.0 - 1.0
    wx = ctbr[1].item() / lim.max_body_rate_rp_rps
    wy = ctbr[2].item() / lim.max_body_rate_rp_rps
    wz = ctbr[3].item() / lim.max_body_rate_yaw_rps
    return [max(-1.0, min(1.0, v)) for v in (t, wx, wy, wz)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weights", default=None, help="acro policy_weights.json (default: by --axis)")
    ap.add_argument("--axis", choices=["roll", "pitch"], default="roll")
    ap.add_argument("--n-rotations", type=float, default=1.0)
    ap.add_argument("--out", default="runs/acro_flip/hero_seq", help="output dir for replay.json.gz")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--hover-weights", default=DEFAULT_HOVER_WEIGHTS,
                    help="deployed hover policy (obs-6 hover_tof) that owns climb/hover/land; "
                         "pass 'pd' to fall back to the old altitude/attitude PD")
    ap.add_argument("--z-hover", type=float, default=1.0,
                    help="hover/flip altitude (m). The deployed hover policy was trained on a "
                         "0.5-1.1 m setpoint band with a 1.3 m ToF ceiling — going above that is "
                         "out of distribution for it, and unmeasurable on the real bridge.")
    ap.add_argument("--z-ground", type=float, default=WHOOP_REST_Z_M,
                    help="rest altitude (m): the airframe's half-height, i.e. sitting on the floor")
    args = ap.parse_args()

    axis = _AXIS_IDX[args.axis]
    weights = args.weights or (
        "runs/acro_flip/policy_weights.json" if args.axis == "roll"
        else "runs/acro_flip_pitch/policy_weights.json")
    pol = Policy(weights)
    assert pol.base_obs_dim == 8, (
        f"expected the obs-8 acro policy [gravity_body(3), p, q, r, rotation_remaining, "
        f"maneuver_phase], got base_obs_dim {pol.base_obs_dim}. An obs-7 (v1) file cannot be fed "
        f"here — the clock is a real input, not padding. Retrain with configs/acro_flip_v2.yaml.")

    # The hover half of the sequence: the SHIPPED policy, not a hand-written PD. Same weights the
    # Bench dashboard and scripts/pilot.py fly on the real Air65 II, run through the same pure-Python
    # actor — so both halves of this video are trained policies, which is the whole point of showing
    # the sequence at all.
    hov = None if args.hover_weights == "pd" else Policy(args.hover_weights)
    if hov is not None:
        assert hov.uses_tof and hov.base_obs_dim == 6, (
            f"expected the obs-6 hover_tof deploy policy, got task={hov.task!r} "
            f"base_obs_dim={hov.base_obs_dim}")
        print(f"hover: {args.hover_weights} (hover_tof, obs-6 x {hov.obs_stack} stacked)")
        print(f"flip:  {weights} (acro_flip, obs-7)")

    dev = torch.device(args.device)
    # The deploy throttle floor, exactly as configs/acro_flip_v2.yaml trains against and
    # pilot/controller.py clamps at (FlightParams.min_thrust_frac). The v2 flip is a COAST, so the
    # floor is load-bearing here: rendering without it would show a maneuver the real drone can't fly.
    lim = ActionLimits(min_thrust_normed=MIN_THRUST_NORMED)
    dt = 0.02
    # Fixed airframe (no DR) for a clean, repeatable hero shot.
    params = WhoopParams(randomize_airframe=False, dt=dt)
    dyn = WhoopDynamics(1, params=params, device=dev)
    down = torch.tensor([[0.0, 0.0, -1.0]], device=dev)

    # Spawn level, at rest, on the ground.
    idx = torch.arange(1, device=dev)
    dyn.set_state(
        idx,
        pos=torch.tensor([[0.0, 0.0, args.z_ground]], device=dev),
        vel=torch.zeros(1, 3, device=dev),
        quat_xyzw=torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=dev),
        ang_vel=torch.zeros(1, 3, device=dev),
    )

    phi_target = 2.0 * math.pi * args.n_rotations

    # --- meta (hand-built: no live env; mirrors viz.replay.build_meta) ---
    meta = {
        "config": f"takeoff_flip_land_{args.axis}",
        "policy": (f"acro_flip ({args.axis}) flip + "
                   + ("hover_tof deploy policy" if hov is not None else "PD")
                   + " take-off/hover/land — the real deploy split"),
        "task": "acro_flip",
        "obs_version": "obs-v4", "action_version": "act-v2", "substrate": "diffaero",
        "control_hz": int(round(1.0 / dt)), "sim_hz": int(round(1.0 / dt)) * params.n_substeps,
        "dt": dt,
        "coordinate_frame": COORDINATE_FRAME, "state_layout": STATE_LAYOUT,
        "action_layout": ACTION_LAYOUT,
        "action_limits": {
            "max_thrust_normed": lim.max_thrust_normed, "hover_thrust_normed": lim.hover_thrust_normed,
            "max_body_rate_rp_rps": lim.max_body_rate_rp_rps, "max_body_rate_yaw_rps": lim.max_body_rate_yaw_rps,
        },
        "unity_hint": UNITY_HINT,
        "scene_info": {
            "command_label": f"{args.axis}-flip phase (remaining)",
            "phase_labels": list(PHASE_LABELS),
            "rest_z": WHOOP_REST_Z_M,
        },
    }
    rec = RunRecorder(meta)
    rec.begin_episode(1, gates=[], drone=0)

    # --- phase schedule (s) ---
    T_SETTLE0, T_CLIMB, T_HOVER = 0.4, 2.0, 1.2   # ground -> climb -> settle-at-hover
    T_RECOVER, T_SETTLE1 = 1.2, 0.8   # post-flip hover, then time parked on the ground at the end
    FLIP_MAX = 1.5
    LAND_RATE = 0.55               # descent-ramp speed (m/s) — a pilot walking it down, not a drop

    # PD gains (the --hover-weights pd fallback only).
    KP_Z, KD_Z = 1.6, 1.1          # altitude -> thrust
    KP_ATT, KD_ATT, KD_YAW = 9.0, 0.9, 1.2   # attitude -> body rates

    #: Heading hold for the hover-policy path (see hover_ctbr): yaw error -> yaw rate.
    KP_YAW = 2.0
    #: Hand off to the acro policy only when the airframe is level AND pointed where it started.
    #: The 6 deg bound is measured, not guessed — swept in this harness, the flip completes cleanly
    #: (phi/Phi 1.02, ~0.4 m of altitude lost) up to |yaw| ~6 deg and then falls apart hard
    #: (phi/Phi > 5, >3.8 m lost). Root cause is NOT either policy: DiffAero's RateController
    #: measures the rate error as `desired_body - R_i2b @ w` while our wrapper (and the whole
    #: obs contract) treats `_state[10:13]` as ALREADY body-frame, so the loop is only correct at
    #: R == I. Open loop, the same constant CTBR command gives 12 rad/s at yaw 0 and a saturated
    #: 40/40/16 rad/s tumble at yaw -22 deg. Fixing that means retraining every policy in the repo,
    #: so it is recorded, not patched here — and the sequence simply keeps its nose straight.
    FLIP_YAW_LIMIT_DEG = 4.0

    def ground_contact() -> None:
        """Minimal ground plane: DiffAero has no contact model, so stop the drone at the floor.

        Without this the airframe would be asymptotically-but-never-quite landed (a pure altitude
        PD approaches its setpoint exponentially) and, before take-off, would sag below the floor
        while the props spool. Clamps ``pos.z`` to the rest height and kills any downward velocity
        — nothing else, so the flight itself is untouched.
        """
        with torch.no_grad():
            st = dyn.model._state
            if st[0, 2].item() < args.z_ground:
                st[0, 2] = args.z_ground
                st[0, 9] = torch.clamp(st[0, 9], min=0.0)   # vz: no sinking through the floor

    def pd_ctbr(z_target: float) -> torch.Tensor:
        """Altitude+attitude PD -> DiffAero CTBR (level-hold, thrust to hold z_target).

        The ``--hover-weights pd`` fallback only; the default path flies the shipped policy.
        """
        z = dyn.pos[0, 2].item()
        vz = dyn.vel_world[0, 2].item()
        roll, pitch, _ = dyn.rpy[0].tolist()
        p, q, r = dyn.ang_vel_body[0].tolist()
        thrust = 1.0 + KP_Z * (z_target - z) - KD_Z * vz
        thrust = max(0.3, min(2.0, thrust))
        wx = max(-8.0, min(8.0, -KP_ATT * roll - KD_ATT * p))
        wy = max(-8.0, min(8.0, -KP_ATT * pitch - KD_ATT * q))
        wz = max(-6.0, min(6.0, -KD_YAW * r))
        return torch.tensor([[thrust, wx, wy, wz]], device=dev)

    # The deployed hover policy's frame history (obs_stack frames, oldest->newest), seeded on the
    # first call exactly like the env's reset and the pilot's — see pilot.policy.stack_frames.
    hov_hist: deque = deque(maxlen=hov.obs_stack if hov else 1)

    def hover_ctbr(z_target: float) -> torch.Tensor:
        """The SHIPPED hover policy -> DiffAero CTBR, tracking ``z_target``.

        obs-6 ``[roll, pitch, p, q, r, height_err]`` exactly as ``tasks/hover_tof.py`` builds it,
        with the measured height clamped into the bridge ToF's band (``h_meas``); no sensor DR, so
        this is the clean-eval reading. Moving ``z_target`` is how the sequence climbs and lands —
        the same setpoint the pilot feeds on the real drone, walked up and down.
        """
        roll, pitch, _ = dyn.rpy[0].tolist()
        p, q, r = dyn.ang_vel_body[0].tolist()
        h_meas = min(max(dyn.pos[0, 2].item(), 0.0), TOF_MAX_M)
        frame = [roll, pitch, p, q, r, z_target - h_meas]
        act = hov(stack_frames(hov_hist, frame, hov.obs_stack))
        # Close the ONE loop the hover policy deliberately doesn't: heading. obs-v4 drops yaw
        # ("not observable without a magnetometer"), so the policy has no yaw reference and settles
        # on a small constant yaw-rate bias (~-5.8 deg/s here) — harmless for hovering, and exactly
        # what the real bridge sees. It is NOT harmless for the flip handoff (see the FLIP_YAW_LIMIT
        # note below), so the harness holds heading on the gyro-integrated yaw the pilot already
        # forwards from MSP_ATTITUDE. This overrides only the yaw channel; thrust/roll/pitch stay
        # the policy's.
        yaw = dyn.rpy[0, 2].item()
        act = list(act)
        act[3] = max(-1.0, min(1.0, -KP_YAW * yaw / lim.max_body_rate_yaw_rps))
        return action_to_diffaero(torch.tensor([act], device=dev), lim), act

    phi = 0.0
    t = 0.0
    step = 0
    flipping = False
    flip_started = False
    flip_t0 = 0.0
    z_hold = args.z_hover
    land_t0: float | None = None
    touchdown_t: float | None = None
    z_land0 = args.z_hover
    phase = "climb"

    # Cap the total sequence generously.
    for _ in range(1200):
        # --- decide the control action for this step ---
        rot_rem = 1.0
        if not flip_started and t >= T_SETTLE0 + T_CLIMB + T_HOVER:
            # Trigger the flip once settled at hover: level, and nose-aligned (FLIP_YAW_LIMIT_DEG).
            tilt = math.hypot(*dyn.rpy[0, :2].tolist())
            yaw_off = abs(math.degrees(dyn.rpy[0, 2].item()))
            if math.degrees(tilt) < 8.0 and yaw_off < FLIP_YAW_LIMIT_DEG:
                flipping, flip_started, flip_t0 = True, True, t
                phi = 0.0

        if flipping:
            phase = "flip"
            grav = world_to_body(down, dyn.R)[0]              # gravity_body = -R[2,:]
            p, q, r = dyn.ang_vel_body[0].tolist()
            rate_axis = p if axis == 0 else q
            phi += rate_axis * dt
            rot_rem = (phi_target - min(max(phi, 0.0), phi_target)) / phi_target
            # The maneuver clock, running 1->0 across MANEUVER_LEN_S from the handoff (flip_t0) —
            # the same t_trigger the task assumes and the pilot supplies. Paired with rot_rem, which
            # is the gyro integral: the clock lets the policy plan the pop, the integral keeps it
            # honest if the roll runs long.
            man_phase = min(1.0, max(0.0, 1.0 - (t - flip_t0) / MANEUVER_LEN_S))
            obs = [grav[0].item(), grav[1].item(), grav[2].item(), p, q, r, rot_rem, man_phase]
            act = pol(obs)                                    # act-v2 [-1,1]
            ctbr = action_to_diffaero(torch.tensor([act], device=dev), lim)
            act_v2 = act
            tilt = math.hypot(*dyn.rpy[0, :2].tolist())
            if (phi >= phi_target and math.degrees(tilt) < 15.0) or (t - flip_t0) >= FLIP_MAX:
                flipping = False
                z_hold = dyn.pos[0, 2].item()
                rec_recover_t0 = t
        else:
            if t < T_SETTLE0:
                # Sitting on the floor with the props spooling — still the take-off beat.
                phase, z_tgt = "climb", args.z_ground
            elif not flip_started:
                phase, z_tgt = ("climb" if t < T_SETTLE0 + T_CLIMB else "hover"), args.z_hover
            elif t < flip_t0 + FLIP_MAX + T_RECOVER:
                phase, z_tgt = "recover", z_hold
            else:
                # Descent RAMP that keeps going THROUGH the floor: the setpoint walks down at
                # LAND_RATE, and ground_contact() is what stops the airframe. A setpoint that
                # stops at the floor only ever decays toward it (a PD's steady-state lag), so the
                # drone would hover a few cm up forever; letting it run under keeps the throttle
                # cut after touchdown, exactly like a pilot's.
                if land_t0 is None:
                    land_t0, z_land0 = t, dyn.pos[0, 2].item()
                phase = "land"
                z_tgt = z_land0 - LAND_RATE * (t - land_t0)
            if hov is not None:
                ctbr, act_v2 = hover_ctbr(z_tgt)
            else:
                ctbr = pd_ctbr(z_tgt)
                act_v2 = _act_v2_from_ctbr(ctbr[0], lim)

        # --- step + record ---
        dyn.step(ctbr)
        ground_contact()
        step += 1
        t += dt
        rec.add_frame(
            t=t, step=step,
            pos=dyn.pos[0], quat=dyn.quat_xyzw[0], rpy=dyn.rpy[0],
            vel=dyn.vel_world[0], angvel=dyn.ang_vel_body[0],
            action=act_v2, action_diffaero=ctbr[0],
            reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=0.0, laps=0,
            scene={"command": rot_rem, "phase": _PHASE_CODE[phase]},
        )

        # Done once the airframe has been settled on the ground for T_SETTLE1.
        if (land_t0 is not None and touchdown_t is None
                and dyn.pos[0, 2].item() <= args.z_ground + 1e-4):
            touchdown_t = t
        if touchdown_t is not None and t >= touchdown_t + T_SETTLE1:
            break

    rec.end_episode({"steps": step, "ended": "landed", "sequence": "takeoff->flip->land"})
    out = Path(args.out)
    path = rec.save(out / "replay.json.gz")
    frames = rec._episodes[0]["frames"]
    zmin = min(f["pos"][2] for f in frames)
    zmax = max(f["pos"][2] for f in frames)
    phases = [PHASE_LABELS[int(f["scene"]["phase"])] for f in frames]
    order = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
    print(f"wrote {path}  ({step} frames, {step * dt:.1f}s, flip@{flip_t0:.1f}s, "
          f"phi/Φ={phi / phi_target:.2f}, z {zmin:.2f}->{zmax:.2f} m)")
    print(f"  start z={frames[0]['pos'][2]:.4f} m  end z={frames[-1]['pos'][2]:.4f} m  "
          f"(rest {args.z_ground:.4f} m)")
    print("  phases: " + " -> ".join(order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
