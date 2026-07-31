#!/usr/bin/env python
"""Generate the **reference flip** — the hand-authored "this is the one we want" maneuver.

Everything else in this repo renders a *policy rollout*: we watch what the drone did and grade it.
Nothing says what it **should** do. This builds that target, deterministically, with every physical
quantity — attitude, body rates, collective thrust, and the accelerometer the onboard IMU would
read — **derived** rather than guessed.

Nothing here trains or changes a policy. It is a generator, a chart pack, and a set of tests.

    uv run python scripts/reference_flip.py --axis roll --omega 9.0 \
        --z-entry 1.2 --out runs/reference/flip_roll
    uv run python scripts/reference_flip.py --axis roll --omega 9.0 --deployable \
        --out runs/reference/flip_roll_deployable

    uv run python scripts/capture_video.py --replay runs/reference/flip_roll/replay.json.gz \
        --out runs/reference/flip_roll/reference_flip.mp4 --preset hero --width 1080 --height 1080

Outputs ``replay.json.gz`` (the **video** artifact, 50 Hz), ``reference.json`` (the **data**
artifact, 1 kHz), ``reference_telemetry.png``, ``reference_envelope.png``, ``verify.json`` and
``run.json``. The capturer needs no changes.

**Two variants means two solves, not one stream under two limits.** The 0.25 throttle floor puts a
quarter g of *downward* thrust on an inverted drone across the whole coast, so the shoot returns a
genuinely different trajectory — a longer pop, a higher apex, and noticeably more lateral
excursion. The artifact names keep them apart. Motors-off is the default because it is the
aesthetic ideal for the video; if you are using this as an **RL target or a scoring reference, use
``--deployable``**, because the motors-off coast has *zero control authority* by construction
(zero thrust can produce no torque at all — the AIRMODE flip-stall failure in miniature), and
scoring against it would be scoring against something the airframe cannot recover from.
``verify.json`` reports both margins.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from neural_whoop.reference import emit, verify
from neural_whoop.reference.flatness import SingularFlatnessError
from neural_whoop.reference.limits import DEPLOY_MIN_THRUST_NORMED
from neural_whoop.reference.maneuvers import (
    FlipSpec,
    build_sequence,
    hover_entry_state,
    solve_flip,
)
from neural_whoop.reference.model import RefModel


def _run_meta(args, spec: FlipSpec, model: RefModel) -> dict:
    """The ``run.json`` reproducibility manifest.

    Uses the repo's shared builder when it is importable; the generator itself is pure numpy, so
    fall back to a minimal manifest rather than dragging torch in just to stamp a version.
    """
    extra = {
        "generator": "scripts/reference_flip.py",
        "kind": "hand-authored reference maneuver (no policy, no training)",
        "spec": {k: v for k, v in vars(spec).items()},
        "model": model.to_dict(),
    }
    try:
        from neural_whoop.eval.pack import build_run_meta
    except Exception:
        return {"command": list(sys.argv), "config": f"reference_flip_{spec.axis}", **extra}
    return build_run_meta(
        config=f"reference_flip_{spec.axis}", task="acro_flip",
        policy="hand-authored reference", seed=None, dr=False, extra=extra,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--axis", choices=["roll", "pitch"], default="roll")
    ap.add_argument("--omega", type=float, default=9.0,
                    help="peak body rate through the coast (rad/s). 9 is the hero number: a "
                         "longer, more legible inverted coast and roughly half the lateral "
                         "excursion of an 11 rad/s flip, which also compresses the level pop "
                         "beat to the point of invisibility.")
    ap.add_argument("--n-rotations", type=float, default=1.0)
    ap.add_argument("--z-entry", type=float, default=1.2, help="hover / flip-entry altitude (m)")
    ap.add_argument("--deployable", action="store_true",
                    help="coast at the deploy throttle floor (0.25) instead of motors-off. USE "
                         "THIS if the reference is an RL target or a scoring reference.")
    ap.add_argument("--thrust-flip", type=float, default=3.8,
                    help="collective held through the pop and roll-in (DiffAero normed units)")
    ap.add_argument("--t-climb", type=float, default=1.4)
    ap.add_argument("--t-hover", type=float, default=0.4)
    ap.add_argument("--t-recover", type=float, default=1.2)
    ap.add_argument("--t-land", type=float, default=2.2,
                    help="landing duration (s). Longer than you would expect, because this "
                         "simulator's oversized drag holds the airframe up on a descent: a quick "
                         "landing asks for a below-singular collective and the flatness map "
                         "refuses it.")
    ap.add_argument("--dt-fine", type=float, default=1e-3, help="fine-stream step (s)")
    ap.add_argument("--dt-replay", type=float, default=0.02, help="replay step (s)")
    ap.add_argument("--no-stage2", action="store_true",
                    help="skip the 5x5 'return to the point' attempt (it is expected to refuse)")
    ap.add_argument("--no-charts", action="store_true", help="skip the PNGs (no viz extra needed)")
    ap.add_argument("--out", default=None, help="output dir (default: runs/reference/flip_<axis>)")
    args = ap.parse_args()

    coast = DEPLOY_MIN_THRUST_NORMED if args.deployable else 0.0
    suffix = "_deployable" if args.deployable else ""
    out = Path(args.out or f"runs/reference/flip_{args.axis}{suffix}")
    out.mkdir(parents=True, exist_ok=True)

    model = RefModel()
    spec = FlipSpec(
        axis=args.axis, omega_peak=args.omega, n_rotations=args.n_rotations,
        z_entry=args.z_entry, thrust_flip=args.thrust_flip, coast_thrust=coast,
        t_climb=args.t_climb, t_hover=args.t_hover, t_recover=args.t_recover,
        t_land=args.t_land,
    )
    variant = "deployable (coast at the 0.25 throttle floor)" if args.deployable else "motors-off"
    print(f"reference flip: axis={spec.axis} Ω={spec.omega_peak:g} rad/s  variant={variant}")
    print(f"  model: m={model.mass:g} kg  D={model.D_xy:g} N/(m/s)  "
          f"terminal velocity {model.terminal_velocity_mps:.2f} m/s  K={model.K_angvel_rp:g} 1/s")

    # --- the shoot -----------------------------------------------------------------------
    entry = hover_entry_state(spec)
    solution = solve_flip(spec, model, entry, dt=args.dt_fine,
                          try_stage2=not args.no_stage2, verbose=True)
    print(f"  shoot: stage {solution.stage}, ‖r‖={solution.residual_norm:.2e} in "
          f"{solution.iterations} iterations")
    for k, v in solution.residuals.items():
        print(f"    {k:22s} {v:+.3e}")
    if solution.stage2_note:
        print(f"  note: {solution.stage2_note}")

    # --- sample ---------------------------------------------------------------------------
    traj = build_sequence(spec, model, solution)
    try:
        fine = traj.sample(model, args.dt_fine)
    except SingularFlatnessError as exc:
        print(f"\nERROR: {exc}\n\nThe flatness-authored beats (climb / recover / land) asked for "
              f"a collective the map cannot invert. Lengthen the offending beat (--t-land is the "
              f"usual culprit) and retry.", file=sys.stderr)
        return 1
    replay_idx = emit.decimate_indices(fine, args.dt_replay)
    replay_samples = emit.decimate(fine, args.dt_replay)
    hold_commands = emit.step_hold_commands(fine, replay_idx)
    print(f"  sampled: {len(fine)} fine @ {1/args.dt_fine:.0f} Hz -> {len(replay_samples)} replay "
          f"@ {1/args.dt_replay:.0f} Hz, {fine.t[-1]:.2f} s total")

    # --- verify ---------------------------------------------------------------------------
    checks = verify.verify_reference(fine, replay_samples, model, spec,
                                     min_thrust_normed=coast)
    lim, alloc = checks["limits"], checks["allocation"]
    print(f"  limits:  thrust ≤ {lim['max_normed_thrust']:.3f}/{lim['thrust_ceiling']:g} "
          f"({lim['thrust_headroom_frac']*100:.1f}% headroom), rate cmd ≤ "
          f"{lim['max_abs_rate_cmd_rp_rps']:.3f}/{lim['rate_cmd_ceiling_rps']:g} "
          f"({lim['rate_headroom_frac']*100:.1f}% headroom) -> "
          f"{'OK' if lim['within_envelope'] else 'OUT OF ENVELOPE'}")
    print(f"  allocation: min margin {alloc['min_margin']:+.4f} over all frames; "
          f"{alloc['min_margin_torqued']:+.4f} where torque is actually demanded "
          f"(t={alloc['worst_torqued_t_s']:.3f}s, phase {alloc['worst_torqued_phase']}) -> "
          f"{'FEASIBLE' if alloc['feasible'] else 'INFEASIBLE'}")
    print(f"              {alloc['zero_authority_frac']*100:.0f}% of the reference is flown with "
          f"the motors fully off (zero rate authority)")
    rf, rr = checks["dynamics_residual_fine"], checks["dynamics_residual_replay"]
    conv = checks["second_order_convergence"]
    print(f"  residual: vel rms {rf['vel_rms']:.3e} @1 kHz vs {rr['vel_rms']:.3e} @50 Hz "
          f"(ratio {conv['observed_vel_rms_ratio']:.0f}x, expect ~{conv['expected_ratio']:.0f}x)")

    # --- metrics --------------------------------------------------------------------------
    metrics = emit.reference_metrics(fine, spec, model)
    sens = emit.drag_sensitivity(traj, spec, model, args.dt_fine)
    print("  metrics (acro_flip's own names):")
    for k in ("max_lateral_drift", "peak_climb", "altitude_loss", "settle_pos_error",
              "flip_duration_s", "peak_normed_thrust", "peak_body_rate_rps"):
        print(f"    {k:22s} {metrics[k]:.4f}")
    print("  drag sensitivity (same commands, other drag models):")
    for label, row in sens.items():
        if "error" in row:
            print(f"    {label:9s} REFUSED: {row['error'][:70]}")
            continue
        print(f"    {label:9s} D={row['D']:.4f} (v_term {row['terminal_velocity_mps']:5.2f} m/s): "
              f"peak_climb {row['peak_climb_m']:+.3f} m  alt_loss {row['altitude_loss_m']:.3f} m  "
              f"lat {row['max_lateral_drift_m']:.3f} m  vz [{row['vz_min_mps']:+.2f},"
              f"{row['vz_max_mps']:+.2f}]")

    # --- emit -----------------------------------------------------------------------------
    rec = emit.build_replay(replay_samples, spec, model, solution,
                            dt_replay=args.dt_replay, min_thrust_normed=coast,
                            label=("deployable" if args.deployable else "motors-off"),
                            hold_commands=hold_commands)
    replay_path = rec.save(out / "replay.json.gz")
    doc = emit.build_reference_doc(fine, spec, model, solution, checks,
                                   metrics=metrics, sensitivity=sens, dt_fine=args.dt_fine)
    ref_path = emit.save_reference(doc, out / "reference.json")
    (out / "verify.json").write_text(json.dumps(checks, indent=2))
    (out / "run.json").write_text(json.dumps(_run_meta(args, spec, model), indent=2))
    print(f"\nwrote {replay_path}  (video artifact, {len(replay_samples)} frames)")
    print(f"wrote {ref_path}  (data artifact, {len(fine)} samples @ {1/args.dt_fine:.0f} Hz)")
    print(f"wrote {out/'verify.json'}, {out/'run.json'}")

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
            p2 = plot_reference_envelope(doc_replay, out / "reference_envelope.png", spec=spec)
            print(f"wrote {p1}\nwrote {p2}")

    if not lim["within_envelope"]:
        print("\nWARNING: the reference is OUTSIDE the act-v2 envelope.", file=sys.stderr)
        return 2
    if not alloc["feasible"]:
        print(f"\nNOTE: this variant is control-allocation INFEASIBLE by "
              f"{-alloc['min_margin']:.3f} normed collective at the catch — the airframe cannot "
              f"produce that torque at that throttle. Fine as a concept shot; do NOT use it as an "
              f"RL target. Re-run with --deployable.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
