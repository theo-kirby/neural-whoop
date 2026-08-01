#!/usr/bin/env python
"""Generate a **hand-authored reference maneuver** — "this is the one we want", as data.

Everything else in this repo renders a *policy rollout*: we watch what the drone did and grade it.
Nothing says what it **should** do. This builds that target, deterministically, with every physical
quantity — attitude, body rates, collective thrust, and the accelerometer the onboard IMU would
read — **derived** rather than guessed. Nothing here trains or changes a policy.

Three maneuvers, and the interesting thing is that they need three *different* authoring
mechanisms:

``flip``   a point-in-space flip. Differential flatness **cannot** author it (through inversion the
           map would demand negative thrust), so the commands are authored and the path is what
           physics returns, with the boundary conditions closed by a damped-Newton **shoot**.
``swing``  a pendulum U on the roll axis. The exact complement: flatness authors the *whole* beat
           and it closes on its own start point at machine precision. **No shoot at all.**
``orbit``  a banked revolution about a vertical anchor axis. The first maneuver here that is
           genuinely 3D, and the one that breaks ``ψ ≡ 0`` — which is what exposes DiffAero's
           rate-loop frame bug (``controller.py:93``). Valid reference, valid video; **not flyable
           in this simulator**. See ``verify.json``'s ``rate_loop_stability``.

    uv run python scripts/reference_maneuver.py --maneuver swing --video \
        --out runs/reference/swing_roll
    uv run python scripts/reference_maneuver.py --maneuver orbit --video \
        --out runs/reference/orbit_z
    uv run python scripts/reference_maneuver.py --maneuver flip --z-entry 0.9 \
        --out runs/reference/flip_roll_z09 --video

Outputs ``replay.json.gz`` (the **video** artifact, 50 Hz), ``reference.json`` (the **data**
artifact, 1 kHz), ``reference_telemetry.png``, ``reference_envelope.png``, ``verify.json`` and
``run.json`` — plus, with ``--video``, the MP4.

**``--video`` takes no flags on purpose.** It shells out to the one standardized invocation
(``--preset hero --width 1080 --height 1080``, see ``neural_whoop.reference.video``) so no per-clip
camera tuning can creep in and the three maneuvers stay comparable *pictures*. The framing check the
capturer prints is captured into ``run.json`` rather than left in a terminal scrollback.

``scripts/reference_flip.py`` remains as a thin alias for the flip, so every command already
documented keeps working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from neural_whoop.reference import emit, verify
from neural_whoop.reference.flatness import SingularFlatnessError
from neural_whoop.reference.limits import DEPLOY_MIN_THRUST_NORMED
from neural_whoop.reference.maneuvers import FlipSpec, ManeuverSpec, RateEnvelopeError
from neural_whoop.reference.maneuvers_orbit import OrbitSpec
from neural_whoop.reference.maneuvers_swing import SwingSpec
from neural_whoop.reference.model import RefModel
from neural_whoop.reference.video import HERO_VIDEO_ARGS, render_hero_video

MANEUVERS = ("flip", "swing", "orbit")


def build_spec(args) -> ManeuverSpec:
    """Turn the parsed flags into the one spec object the rest of the pipeline consumes."""
    if args.maneuver == "flip":
        return FlipSpec(
            axis=args.axis, omega_peak=args.omega, n_rotations=args.n_rotations,
            z_entry=args.z_entry if args.z_entry is not None else 1.2,
            thrust_flip=args.thrust_flip,
            coast_thrust=DEPLOY_MIN_THRUST_NORMED if args.deployable else 0.0,
            t_climb=args.t_climb, t_hover=args.t_hover,
            t_recover=args.t_settle if args.t_settle is not None else 1.2,
            t_land=args.t_land if args.t_land is not None else 2.2,
        )
    if args.maneuver == "swing":
        return SwingSpec(
            arc_length=args.arc_length, amplitude_deg=args.amplitude_deg,
            freq_scale=args.freq_scale, n_swings=args.n_swings,
            z_entry=args.z_entry if args.z_entry is not None else 0.9,
            ramp_frac=args.ramp_frac if args.ramp_frac is not None else 0.25,
            t_climb=args.t_climb, t_hover=args.t_hover,
            t_settle=args.t_settle if args.t_settle is not None else 0.6,
            t_land=args.t_land if args.t_land is not None else 1.8,
        )
    return OrbitSpec(
        radius=args.radius, omega_orbit=args.omega_orbit, n_revs=args.n_revs, nose=args.nose,
        z_entry=args.z_entry if args.z_entry is not None else 0.9,
        ramp_frac=args.ramp_frac if args.ramp_frac is not None else 0.30,
        t_climb=args.t_climb, t_hover=args.t_hover,
        t_settle=args.t_settle if args.t_settle is not None else 0.6,
        t_land=args.t_land if args.t_land is not None else 1.8,
    )


def run_meta(args, spec: ManeuverSpec, model: RefModel, extra: dict | None = None) -> dict:
    """The ``run.json`` reproducibility manifest.

    Uses the repo's shared builder when it is importable; the generator itself is pure numpy, so
    fall back to a minimal manifest rather than dragging torch in just to stamp a version.
    """
    payload = {
        "generator": "scripts/reference_maneuver.py",
        "maneuver": spec.name,
        "kind": "hand-authored reference maneuver (no policy, no training)",
        "spec": {k: v for k, v in vars(spec).items()},
        "model": model.to_dict(),
        "video_contract": {
            "args": list(HERO_VIDEO_ARGS),
            "note": ("every reference maneuver's MP4 comes out of this one invocation, so the "
                     "clips are comparable pictures rather than separate camera tunes"),
        },
        **(extra or {}),
    }
    try:
        from neural_whoop.eval.pack import build_run_meta
    except Exception:
        return {"command": list(sys.argv), "config": f"reference_{spec.name}", **payload}
    return build_run_meta(
        config=f"reference_{spec.name}", task="acro_flip",
        policy="hand-authored reference", seed=None, dr=False, extra=payload,
    )


def add_arguments(ap: argparse.ArgumentParser, *, maneuver_flag: bool = True) -> None:
    """The full flag set. ``reference_flip.py`` reuses this without the ``--maneuver`` selector."""
    if maneuver_flag:
        ap.add_argument("--maneuver", choices=MANEUVERS, default="flip",
                        help="flip: commands authored + damped-Newton shoot. swing: authored "
                             "entirely by flatness, no shoot. orbit: 3D, breaks psi==0, NOT "
                             "flyable in DiffAero as vendored")
    # --- shared -------------------------------------------------------------------------
    ap.add_argument("--z-entry", type=float, default=None,
                    help="hover / maneuver altitude (m). Default 1.2 for the flip, 0.9 otherwise")
    ap.add_argument("--t-climb", type=float, default=1.4)
    ap.add_argument("--t-hover", type=float, default=0.4)
    ap.add_argument("--t-settle", type=float, default=None,
                    help="settle/recover duration (s). Default 1.2 for the flip, 0.6 otherwise")
    ap.add_argument("--t-land", type=float, default=None,
                    help="landing duration (s). Longer than you would expect, because this "
                         "simulator's oversized drag holds the airframe up on a descent: a quick "
                         "landing asks for a below-singular collective and the flatness map "
                         "refuses it. Default 2.2 for the flip, 1.8 otherwise")
    ap.add_argument("--ramp-frac", type=float, default=None,
                    help="swing/orbit: envelope ramp fraction at each end. Defaults 0.25 (swing) / "
                         "0.30 (orbit). This is what SPENDS the rate budget — see the swing's "
                         "docstring for the measured sweep")
    ap.add_argument("--dt-fine", type=float, default=1e-3, help="fine-stream step (s)")
    ap.add_argument("--dt-replay", type=float, default=0.02, help="replay step (s)")
    ap.add_argument("--no-charts", action="store_true", help="skip the PNGs (no viz extra needed)")
    ap.add_argument("--video", action="store_true",
                    help="also render the MP4 through the STANDARD hero invocation "
                         f"({' '.join(HERO_VIDEO_ARGS)}). Takes no camera flags on purpose")
    ap.add_argument("--out", default=None, help="output dir (default: runs/reference/<name>)")
    # --- flip ---------------------------------------------------------------------------
    ap.add_argument("--axis", choices=["roll", "pitch"], default="roll", help="flip: rotation axis")
    ap.add_argument("--omega", type=float, default=9.0,
                    help="flip: peak body rate through the coast (rad/s). 9 is the hero number: a "
                         "longer, more legible inverted coast and roughly half the lateral "
                         "excursion of an 11 rad/s flip, which also compresses the level pop beat "
                         "to the point of invisibility")
    ap.add_argument("--n-rotations", type=float, default=1.0, help="flip: turns")
    ap.add_argument("--thrust-flip", type=float, default=3.8,
                    help="flip: collective held through the pop and roll-in (normed units)")
    ap.add_argument("--deployable", action="store_true",
                    help="flip: coast at the deploy throttle floor (0.25) instead of motors-off. "
                         "USE THIS if the reference is an RL target or a scoring reference. The "
                         "swing and the orbit are fully powered and must NOT get this implicitly")
    ap.add_argument("--no-stage2", action="store_true",
                    help="flip: skip the 5x5 'return to the point' attempt (expected to refuse)")
    # --- swing --------------------------------------------------------------------------
    ap.add_argument("--arc-length", type=float, default=0.9, help="swing: rope length L (m)")
    ap.add_argument("--amplitude-deg", type=float, default=50.0,
                    help="swing: peak swing angle off vertical. NOT the bank angle — peak tilt "
                         "runs ~1.4x this because drag leans the thrust axis into travel")
    ap.add_argument("--n-swings", type=float, default=2.0, help="swing: full sin periods")
    ap.add_argument("--freq-scale", type=float, default=0.8,
                    help="swing: drive frequency as a fraction of resonance sqrt(g/L). 1.0 is OUT "
                         "OF ENVELOPE for the shipped sizing (89 deg tilt, 15.45 rad/s command "
                         "against an 11.64 ceiling) and the generator will refuse it")
    # --- orbit --------------------------------------------------------------------------
    ap.add_argument("--radius", type=float, default=0.5, help="orbit: radius (m)")
    ap.add_argument("--omega-orbit", type=float, default=7.0,
                    help="orbit: steady-state orbital rate (rad/s); speed is radius*omega")
    ap.add_argument("--n-revs", type=float, default=3.0, help="orbit: revolutions")
    ap.add_argument("--nose", choices=["in", "out"], default="in",
                    help="orbit: 'in' points the nose at the anchor axis (the lean is a pitch and "
                         "the drone travels sideways round the ring)")


def generate(args) -> int:
    """The whole pipeline: build -> sample -> verify -> metrics -> emit -> charts -> video."""
    model = RefModel()
    spec = build_spec(args)
    out = Path(args.out or f"runs/reference/{spec.name}")
    out.mkdir(parents=True, exist_ok=True)

    print(f"reference {spec.name}: {spec.describe(None)}")
    print(f"  model: m={model.mass:g} kg  D={model.D_xy:g} N/(m/s)  "
          f"terminal velocity {model.terminal_velocity_mps:.2f} m/s  K={model.K_angvel_rp:g} 1/s")

    # --- build (a shoot for the flip; nothing to solve for the others) --------------------
    kwargs = {"try_stage2": not args.no_stage2} if spec.name == "flip" else {}
    try:
        build = spec.build(model, dt=args.dt_fine, verbose=True, **kwargs)
    except RateEnvelopeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    solution = build.solution
    if solution is not None:
        print(f"  shoot: stage {solution.stage}, ‖r‖={solution.residual_norm:.2e} in "
              f"{solution.iterations} iterations")
        for k, v in solution.residuals.items():
            print(f"    {k:22s} {v:+.3e}")
        if solution.stage2_note:
            print(f"  note: {solution.stage2_note}")
    else:
        print("  no shoot: this maneuver is authored entirely by differential flatness and closes "
              "on its own start point analytically.")

    # --- sample ---------------------------------------------------------------------------
    try:
        fine = build.traj.sample(model, args.dt_fine)
    except SingularFlatnessError as exc:
        print(f"\nERROR: {exc}\n\nThe flatness-authored beats (climb / settle / land) asked for a "
              f"collective the map cannot invert. Lengthen the offending beat (--t-land is the "
              f"usual culprit) and retry.", file=sys.stderr)
        return 1
    replay_idx = emit.decimate_indices(fine, args.dt_replay)
    replay_samples = emit.decimate(fine, args.dt_replay)
    hold_commands = emit.step_hold_commands(fine, replay_idx)
    print(f"  sampled: {len(fine)} fine @ {1/args.dt_fine:.0f} Hz -> {len(replay_samples)} replay "
          f"@ {1/args.dt_replay:.0f} Hz, {fine.t[-1]:.2f} s total")

    # --- verify ---------------------------------------------------------------------------
    floor = spec.min_thrust_normed
    checks = verify.verify_reference(fine, replay_samples, model, spec, min_thrust_normed=floor)
    lim, alloc, loop = checks["limits"], checks["allocation"], checks["rate_loop_stability"]
    print(f"  limits:  thrust ≤ {lim['max_normed_thrust']:.3f}/{lim['thrust_ceiling']:g} "
          f"({lim['thrust_headroom_frac']*100:.1f}% headroom), rate cmd ≤ "
          f"{lim['max_abs_rate_cmd_rp_rps']:.3f}/{lim['rate_cmd_ceiling_rps']:g} "
          f"({lim['rate_headroom_frac']*100:.1f}% headroom), yaw ≤ "
          f"{lim['max_abs_rate_cmd_yaw_rps']:.3f}/{lim['yaw_cmd_ceiling_rps']:g} -> "
          f"{'OK' if lim['within_envelope'] else 'OUT OF ENVELOPE'}")
    print(f"  allocation: min margin {alloc['min_margin']:+.4f} over all frames; "
          f"{alloc['min_margin_torqued']:+.4f} where torque is actually demanded -> "
          f"{'FEASIBLE' if alloc['feasible'] else 'INFEASIBLE'}")
    print(f"              {alloc['zero_authority_frac']*100:.0f}% of the reference is flown with "
          f"the motors fully off (zero rate authority)")
    print(f"  rate loop:  max attitude from identity "
          f"{loop['max_attitude_from_identity_deg']:.1f}°, "
          f"{loop['frac_above_90deg']*100:.0f}% of frames past 90°, ω-to-fixed-axis alignment "
          f"{loop['min_omega_fixed_axis_alignment']:.6f} -> the LEGACY (pre-2026-08-01) loop was "
          f"{'STABLE' if loop['legacy_loop_stable'] else 'DIVERGENT'}; the patched fork tracks it")
    print(f"              {loop['stability_reason']}")
    if spec.is_planar:
        pl = checks["planarity"]
        print(f"  planarity:  max |ω_z| {pl['max_abs_omega_z_rps']:.2e}, max off-axis quat "
              f"{pl['max_abs_off_axis_quat']:.2e}")
    rf, rr = checks["dynamics_residual_fine"], checks["dynamics_residual_replay"]
    conv = checks["second_order_convergence"]
    print(f"  residual: vel rms {rf['vel_rms']:.3e} @1 kHz vs {rr['vel_rms']:.3e} @50 Hz "
          f"(ratio {conv['observed_vel_rms_ratio']:.0f}x, expect ~{conv['expected_ratio']:.0f}x)")
    real_breaks = [s for s in checks["seams"] if abs(s["d_acc_mps2"]) > 1.0]
    print(f"  seams:    {len(real_breaks)} acceleration step(s) across {len(checks['seams'])} "
          f"segment joins" + ("" if real_breaks else " — nothing steps the motor command anywhere"))

    # --- metrics --------------------------------------------------------------------------
    metrics = emit.reference_metrics(fine, spec, model)
    sens = emit.drag_sensitivity(build.traj, spec, model, args.dt_fine)
    print("  metrics (acro_flip's own names first):")
    for k in ("max_lateral_drift", "peak_climb", "altitude_loss", "settle_pos_error"):
        print(f"    {k:26s} {metrics[k]:.4f}")
    for k, v in sorted(metrics.items()):
        if k not in ("max_lateral_drift", "peak_climb", "altitude_loss", "settle_pos_error"):
            print(f"    {k:26s} {v:.4f}")
    print("  drag sensitivity (the SAME authored maneuver, re-derived under other drag models):")
    for label, row in sens.items():
        if "error" in row:
            print(f"    {label:9s} REFUSED: {row['error'][:70]}")
            continue
        tail = "".join(
            f"  {k.replace('_deg', '')} {row[k]:.1f}°" for k in
            ("peak_bank_deg", "axis_pointing_error_deg") if k in row
        )
        print(f"    {label:9s} D={row['D']:.4f} (v_term {row['terminal_velocity_mps']:5.2f} m/s): "
              f"peak_climb {row['peak_climb_m']:+.3f} m  lat {row['max_lateral_drift_m']:.3f} m  "
              f"thrust {row['peak_normed_thrust']:.2f}{tail}")

    # --- emit -----------------------------------------------------------------------------
    rec = emit.build_replay(replay_samples, spec, model, solution, dt_replay=args.dt_replay,
                            min_thrust_normed=floor, label=spec.name,
                            hold_commands=hold_commands)
    replay_path = rec.save(out / "replay.json.gz")
    doc = emit.build_reference_doc(fine, spec, model, solution, checks, metrics=metrics,
                                   sensitivity=sens, dt_fine=args.dt_fine, derived=build.derived)
    ref_path = emit.save_reference(doc, out / "reference.json")
    (out / "verify.json").write_text(json.dumps(checks, indent=2))
    print(f"\nwrote {replay_path}  (video artifact, {len(replay_samples)} frames)")
    print(f"wrote {ref_path}  (data artifact, {len(fine)} samples @ {1/args.dt_fine:.0f} Hz)")

    # --- charts ---------------------------------------------------------------------------
    if not args.no_charts:
        try:
            from neural_whoop.viz.render import plot_reference_envelope, plot_reference_telemetry
        except ImportError as exc:
            print(f"(charts skipped: {exc} — install the viz extra: uv pip install -e '.[viz]')")
        else:
            doc_replay = rec.to_dict()
            p1 = plot_reference_telemetry(
                doc_replay, checks, out / "reference_telemetry.png", metrics=metrics,
                residual_series=verify.dynamics_residual_series(replay_samples, model),
            )
            p2 = plot_reference_envelope(doc_replay, out / "reference_envelope.png")
            print(f"wrote {p1}\nwrote {p2}")

    # --- the video, through the ONE standard invocation ------------------------------------
    video = None
    if args.video:
        print(f"\n[video] the reference video contract: {' '.join(HERO_VIDEO_ARGS)}")
        video = render_hero_video(replay_path, out / f"reference_{spec.name}.mp4")
        fr = video.get("framing") or {}
        if fr.get("left_frame"):
            print(f"[video] FRAMING FAILURE: worst |NDC| {fr.get('worst_ndc')} — the hero preset "
                  f"could not hold this shot. Report the measurement and the fallback taken "
                  f"(--drone-frac, then --max-drift, then --shot fit); do NOT silently retune the "
                  f"preset.", file=sys.stderr)
        elif fr:
            print(f"[video] framing: worst |NDC| {fr['worst_ndc']:.2f}, apparent size "
                  f"{fr.get('apparent_size_min_frac', 0)*100:.1f}-"
                  f"{fr.get('apparent_size_max_frac', 0)*100:.1f}% of frame height "
                  f"(spread {fr.get('apparent_size_spread', float('nan'))*100:.0f}%)")

    (out / "run.json").write_text(json.dumps(
        run_meta(args, spec, model, {"video": video} if video else None), indent=2))
    print(f"wrote {out/'verify.json'}, {out/'run.json'}")

    if not lim["within_envelope"]:
        print("\nWARNING: the reference is OUTSIDE the act-v2 envelope.", file=sys.stderr)
        return 2
    if not alloc["feasible"]:
        print(f"\nNOTE: this variant is control-allocation INFEASIBLE by "
              f"{-alloc['min_margin']:.3f} normed collective — the airframe cannot produce that "
              f"torque at that throttle. Fine as a concept shot; do NOT use it as an RL target.",
              file=sys.stderr)
    if not loop["legacy_loop_stable"]:
        print(f"\nNOTE: this maneuver takes the attitude past 90° from identity "
              f"({loop['max_attitude_from_identity_deg']:.0f}° max) off ω's fixed axis, which the "
              f"rate loop could NOT track before the 2026-08-01 controller fix. It is flyable on "
              f"the patched fork (the orbit tracks to 1.8 cm), but any artifact generated before "
              f"that date was flown on the divergent loop — see verify.json's rate_loop_stability.",
              file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    return generate(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
