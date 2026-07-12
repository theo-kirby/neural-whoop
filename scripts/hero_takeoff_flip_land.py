#!/usr/bin/env python
"""Render a hero replay of the full blind take-off -> flip -> land sequence.

The pilot/fake-bridge path produces only a vertical-only ``pos`` stub, so for a real 3D hero
shot we reproduce the SAME system-level sequence in DiffAero (real positions + attitudes): a
simple altitude+attitude PD owns take-off / hover / land (standing in for the pilot's open-loop
state machine) and the **trained acro_flip policy** owns the flip window (exactly the deploy
split). We drive ``WhoopDynamics`` directly, record every control step into the versioned replay
schema, and hand the result to nw-viz for the composited hero MP4.

    uv run python scripts/hero_takeoff_flip_land.py --axis roll --out runs/acro_flip/hero_seq
    cd ../nw-viz && node capture.mjs --replay ../neural-whoop/runs/acro_flip/hero_seq/replay.json.gz \
        --out out/takeoff_flip_land.mp4
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import torch

import neural_whoop  # noqa: F401 - makes third_party/diffaero importable
from neural_whoop.contract import ActionLimits, action_to_diffaero, world_to_body
from neural_whoop.dynamics.whoop import WhoopDynamics, WhoopParams
from neural_whoop.pilot import Policy
from neural_whoop.viz.replay import (
    ACTION_LAYOUT,
    COORDINATE_FRAME,
    STATE_LAYOUT,
    UNITY_HINT,
    RunRecorder,
)

_AXIS_IDX = {"roll": 0, "pitch": 1}


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
    ap.add_argument("--z-hover", type=float, default=2.3, help="hover/flip altitude (m)")
    ap.add_argument("--z-ground", type=float, default=0.25, help="rest altitude (m)")
    args = ap.parse_args()

    axis = _AXIS_IDX[args.axis]
    weights = args.weights or (
        "runs/acro_flip/policy_weights.json" if args.axis == "roll"
        else "runs/acro_flip_pitch/policy_weights.json")
    pol = Policy(weights)
    assert pol.base_obs_dim == 7, f"expected obs-7 acro policy, got {pol.base_obs_dim}"

    dev = torch.device(args.device)
    lim = ActionLimits()
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
        "policy": f"acro_flip ({args.axis}) + PD take-off/land — blind system sequence",
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
        "scene_info": {"command_label": f"{args.axis}-flip phase (remaining)"},
    }
    rec = RunRecorder(meta)
    rec.begin_episode(1, gates=[], drone=0)

    # --- phase schedule (s) ---
    T_SETTLE0, T_CLIMB, T_HOVER = 0.4, 2.0, 1.2   # ground -> climb -> settle-at-hover
    T_RECOVER, T_LAND, T_SETTLE1 = 1.2, 2.2, 0.5  # post-flip hover -> descend -> ground
    FLIP_MAX = 1.5

    # PD gains.
    KP_Z, KD_Z = 1.6, 1.1          # altitude -> thrust
    KP_ATT, KD_ATT, KD_YAW = 9.0, 0.9, 1.2   # attitude -> body rates

    def pd_ctbr(z_target: float) -> torch.Tensor:
        """Altitude+attitude PD -> DiffAero CTBR (level-hold, thrust to hold z_target)."""
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

    phi = 0.0
    t = 0.0
    step = 0
    flipping = False
    flip_started = False
    flip_t0 = 0.0
    z_hold = args.z_hover
    phase = "settle"

    # Cap the total sequence generously.
    for _ in range(1200):
        # --- decide the control action for this step ---
        rot_rem = 1.0
        if not flip_started and t >= T_SETTLE0 + T_CLIMB + T_HOVER:
            # Trigger the flip once settled at hover & near-level.
            tilt = math.hypot(*dyn.rpy[0, :2].tolist())
            if math.degrees(tilt) < 8.0:
                flipping, flip_started, flip_t0 = True, True, t
                phi = 0.0

        if flipping:
            phase = "flip"
            grav = world_to_body(down, dyn.R)[0]              # gravity_body = -R[2,:]
            p, q, r = dyn.ang_vel_body[0].tolist()
            rate_axis = p if axis == 0 else q
            phi += rate_axis * dt
            rot_rem = (phi_target - min(max(phi, 0.0), phi_target)) / phi_target
            obs = [grav[0].item(), grav[1].item(), grav[2].item(), p, q, r, rot_rem]
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
                phase, z_tgt = "settle", args.z_ground
            elif not flip_started:
                phase, z_tgt = ("climb" if t < T_SETTLE0 + T_CLIMB else "hover"), args.z_hover
            elif t < flip_t0 + FLIP_MAX + T_RECOVER:
                phase, z_tgt = "recover", z_hold
            elif t < flip_t0 + FLIP_MAX + T_RECOVER + T_LAND:
                phase, z_tgt = "land", args.z_ground
            else:
                phase, z_tgt = "settle", args.z_ground
            ctbr = pd_ctbr(z_tgt)
            act_v2 = _act_v2_from_ctbr(ctbr[0], lim)

        # --- step + record ---
        dyn.step(ctbr)
        step += 1
        t += dt
        rec.add_frame(
            t=t, step=step,
            pos=dyn.pos[0], quat=dyn.quat_xyzw[0], rpy=dyn.rpy[0],
            vel=dyn.vel_world[0], angvel=dyn.ang_vel_body[0],
            action=act_v2, action_diffaero=ctbr[0],
            reward=0.0, cum_reward=0.0, gate_idx=0, dist_to_gate=0.0, laps=0,
            scene={"command": rot_rem},
        )

        # Done once we're back on the ground after the land phase.
        done_land = flip_started and t >= flip_t0 + FLIP_MAX + T_RECOVER + T_LAND + T_SETTLE1
        if done_land:
            break

    rec.end_episode({"steps": step, "ended": "landed", "sequence": "takeoff->flip->land"})
    out = Path(args.out)
    path = rec.save(out / "replay.json.gz")
    zmin = min(f["pos"][2] for f in rec._episodes[0]["frames"])
    zmax = max(f["pos"][2] for f in rec._episodes[0]["frames"])
    print(f"wrote {path}  ({step} frames, {step * dt:.1f}s, flip@{flip_t0:.1f}s, "
          f"phi/Φ={phi / phi_target:.2f}, z {zmin:.2f}->{zmax:.2f} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
