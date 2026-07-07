#!/usr/bin/env python
"""Turn a raw pilot flight CSV into a durable, Flywheel-native analysis pack.

Orchestrates the pure flight-log core (:mod:`neural_whoop.analysis.flight_log`), the scalar
telemetry renderers (:mod:`neural_whoop.viz.render`), and the flight->replay converter
(:mod:`neural_whoop.viz.replay`) into a pack that mirrors the visual contract:

    flight_telemetry.png   stacked hover telemetry (attitude / rates / us_thr-vs-a_thr / vz_est / link)
    link_histogram.png     obs_age distribution with the 40 ms cliff + p99 marked
    flight_summary.json     the full flight_metrics dict + meta
    flight_metrics.csv      flat headline metrics (one row per key)
    replay.json.gz          the Studio-playable/scrubbable replay (pos is a vertical-only stub)
    run.json                reproducibility manifest (command / csv / git / versions)
    comparison.csv          side-by-side headline metrics vs --baseline (battery comparisons)

    uv run python scripts/flight_report.py --flight runs/pilot/d50var_s8_f1.csv --out runs/pilot/f1_report

The metrics/JSON/replay half is pure (stdlib + numpy) and runs anywhere, including the bench Mac;
the two PNGs need the ``viz`` extra (matplotlib) and are skipped with a notice if it is absent —
so the pack degrades gracefully. ``--flywheel`` prints the finalized artifact list + the node
recipe for the manual MCP upload pass (this script does not call the Flywheel MCP itself).
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neural_whoop.analysis.flight_log import flight_metrics, load_flight  # noqa: E402
from neural_whoop.viz.replay import flight_to_replay  # noqa: E402

#: Pinned DiffAero upstream commit — mirrored from :mod:`neural_whoop.eval.pack` but inlined here so
#: this script imports without the torch-heavy eval stack (it must run on the bench Mac).
DIFFAERO_PIN = "291ea14196aefbebcf7387dd71f7e096c83878b7"


def _git_state() -> dict:
    """Best-effort current commit SHA + dirty flag; ``{}`` if git is unavailable (never raises)."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip())
        return {"sha": sha, "dirty": dirty}
    except Exception:
        return {}


def _flat_metrics(m: dict) -> list[tuple[str, object]]:
    """Flatten the nested metrics dict to dotted ``(key, value)`` rows for the CSV (skips lists)."""
    rows: list[tuple[str, object]] = []

    def walk(prefix: str, val: object) -> None:
        if isinstance(val, dict):
            for k, v in val.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(val, list):
            return  # histograms/edges live in the JSON, not the flat headline CSV
        else:
            rows.append((prefix, val))

    walk("", m)
    return rows


def _headline(m: dict) -> dict:
    """The comparison-worthy scalars (hover quality / vertical / link / battery) for comparison.csv."""
    sh, vt, lk, bt = m["stable_hover"], m["vertical"], m["link"], m["battery"]
    return {
        "stable_hover_s": sh["duration_s"],
        "median_tilt_deg": sh["median_tilt_deg"],
        "p90_tilt_deg": sh["p90_tilt_deg"],
        "vz_rail_frames": vt["vz_rail_frames"],
        "vz_first_rail_t": vt["vz_first_rail_t"],
        "thrust_diverged": vt["thrust_divergence"]["detected"],
        "obs_age_p50_ms": lk["median_ms"],
        "obs_age_p99_ms": lk["p99_ms"],
        "frac_over_40ms": lk["frac_over_40ms"],
        "v0": bt["v0"],
        "v_min": bt["v_min"],
        "sag_v": bt["sag_v"],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Analyze a pilot flight CSV into a Flywheel-native pack.")
    p.add_argument("--flight", type=str, required=True, help="Pilot flight CSV (scripts/pilot.py log).")
    p.add_argument("--out", type=str, default=None,
                   help="Output dir (default: <flight_dir>/<stem>_report).")
    p.add_argument("--baseline", type=str, default=None,
                   help="A second flight CSV to compare against (writes comparison.csv).")
    p.add_argument("--policy", type=str, default="pilot flight (real)",
                   help="Policy label baked into the replay meta.")
    p.add_argument("--stable-tilt-deg", type=float, default=8.0,
                   help="Total-tilt threshold (deg) for the stable-hover phase (default 8).")
    p.add_argument("--flywheel", action="store_true",
                   help="Print the finalized artifact list + node recipe for the manual MCP pass.")
    args = p.parse_args()

    flight = Path(args.flight)
    if not flight.exists():
        sys.exit(f"no such flight CSV: {flight}")
    out = Path(args.out) if args.out else flight.parent / f"{flight.stem}_report"
    out.mkdir(parents=True, exist_ok=True)

    log = load_flight(flight)
    metrics = flight_metrics(log, stable_tilt_deg=args.stable_tilt_deg)
    artifacts: dict[str, str] = {}

    # --- summary JSON + flat metrics CSV (pure — always emitted) ---
    summary = {"flight": str(flight), "metrics": metrics}
    (out / "flight_summary.json").write_text(json.dumps(summary, indent=2))
    artifacts["flight_summary.json"] = "json"
    with (out / "flight_metrics.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerows(_flat_metrics(metrics))
    artifacts["flight_metrics.csv"] = "csv"

    # --- portable replay (pure — always emitted) ---
    import gzip
    doc = flight_to_replay(log, policy=args.policy)
    with gzip.open(out / "replay.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    artifacts["replay.json.gz"] = "replay"

    # --- run.json reproducibility manifest ---
    run_meta = {
        "command": list(sys.argv),
        "flight_csv": str(flight),
        "out": str(out),
        "n_frames": metrics["n_frames"],
        "control_hz": metrics["control_hz"],
        "git": _git_state(),
        "versions": {"diffaero": DIFFAERO_PIN},
    }
    (out / "run.json").write_text(json.dumps(run_meta, indent=2))
    artifacts["run.json"] = "json"

    # --- renderers (viz extra: matplotlib) — skip gracefully if absent ---
    try:
        from neural_whoop.viz import render
    except ImportError as e:
        print(f"[viz] renderers skipped (need the viz extra: pip install -e '.[viz]'): {e}")
    else:
        try:
            render.plot_hover_telemetry(log, metrics, out / "flight_telemetry.png")
            artifacts["flight_telemetry.png"] = "image"
            render.plot_link_histogram(log, out / "link_histogram.png", metrics)
            artifacts["link_histogram.png"] = "image"
        except ImportError as e:  # matplotlib missing under the lazy _mpl()
            print(f"[viz] renderers skipped (matplotlib unavailable): {e}")

    # --- optional baseline comparison (battery / link deltas) ---
    if args.baseline:
        base = Path(args.baseline)
        if not base.exists():
            print(f"[baseline] skipped: no such file {base}")
        else:
            bm = flight_metrics(load_flight(base), stable_tilt_deg=args.stable_tilt_deg)
            h_a, h_b = _headline(metrics), _headline(bm)
            with (out / "comparison.csv").open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["metric", flight.stem, base.stem])
                for k in h_a:
                    w.writerow([k, h_a[k], h_b[k]])
            artifacts["comparison.csv"] = "csv"
            print(f"[baseline] comparison vs {base.name} -> comparison.csv")

    # --- report ---
    sh, vt, lk = metrics["stable_hover"], metrics["vertical"], metrics["link"]
    print(f"\nflight report: {flight.name}  ({metrics['n_frames']} frames @ {metrics['control_hz']} Hz)")
    print(f"  stable hover : {sh['duration_s']:.2f} s @ {sh['median_tilt_deg']:.2f}° median tilt "
          f"(p90 {sh['p90_tilt_deg']:.2f}°)")
    rail_t = vt["vz_first_rail_t"]
    print(f"  vz_est rail  : {vt['vz_rail_frames']} frames"
          + (f", first at t={rail_t:.2f} s" if rail_t is not None else " (none)"))
    div = vt["thrust_divergence"]
    print(f"  thrust diverg: {'YES' if div['detected'] else 'no'} "
          f"(us_thr +{div['us_thr_rise']:.0f} µs, a_thr IQR {div['a_thr_iqr']:.3f})")
    print(f"  link obs_age : p50 {lk['median_ms']:.0f} / p99 {lk['p99_ms']:.0f} ms, "
          f"{lk['frac_over_40ms'] * 100:.0f}% past the 40 ms cliff")
    print(f"\npack -> {out}")
    for name in sorted(artifacts):
        print(f"    {name}")

    if args.flywheel:
        print("\n[flywheel] manual MCP upload pass:")
        print("  1. prepare -> PUT bytes (202) -> finalize each artifact above")
        print("  2. commit a node under fancy-smoke-0094 (bench-check), parents = the policy's")
        print(f"     studio-baseline node; summary = the flight's verdict; tags: kind:measurement,")
        print("     cluster:deploy-hw, outcome:<flight-quality>. Re-read projection=full to confirm.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
