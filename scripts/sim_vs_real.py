#!/usr/bin/env python
"""Offline sim-vs-real action diff: re-run the exported policy on a flight's logged obs.

Feeds each logged real observation row back through the **same pure-Python policy**
(:class:`scripts.pilot.Policy` + the stacking the pilot used in flight) and diffs the predicted
``a_thr/a_wx/a_wy/a_wz`` against what the pilot actually streamed. Because the ``hover_blind`` obs
layout is exactly the CSV ``[roll, pitch, p, q, r]`` (+ ``vz_est`` for a v2 policy) and the log
records the policy's own output, a faithful export reproduces the in-flight actions to rounding —
the quantitative **"the policy is faithful in-flight; the crash was the deploy harness"** statement.

Zero heavy deps: pure stdlib + ``scripts/pilot.py`` (no torch, no numpy) so it runs on the bench Mac.

    python3 scripts/sim_vs_real.py --flight runs/pilot/d50var_s8_f1.csv \
        --weights runs/hover_blind_air65_d50var_s8/policy_weights.json
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import math
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `import pilot`

import pilot  # noqa: E402  (pure-Python Policy + stack_frames; imports only bench.msp)

_ACT_COLS = ["a_thr", "a_wx", "a_wy", "a_wz"]
_ACT_LABELS = ["a_thr", "a_wx", "a_wy", "a_wz"]


def _f(cell: str) -> float:
    """Parse a CSV cell to float, empty -> 0.0 (pre-liftoff blanks)."""
    cell = cell.strip()
    return float(cell) if cell not in ("", "nan", "NaN") else 0.0


def main() -> int:
    p = argparse.ArgumentParser(description="Offline sim-vs-real action diff on a pilot flight CSV.")
    p.add_argument("--flight", type=str, required=True, help="Pilot flight CSV.")
    p.add_argument("--weights", type=str, required=True, help="Exported policy_weights.json.")
    p.add_argument("--airborne-us-over-idle", type=float, default=60.0,
                   help="us_thr above idle floor to count a frame as airborne (steadiness stat).")
    p.add_argument("--stable-tilt-deg", type=float, default=8.0,
                   help="Total-tilt threshold (deg) for the stable-hover steadiness window.")
    args = p.parse_args()

    pol = pilot.Policy(args.weights)
    if pol.base_obs_dim not in (5, 6):
        sys.exit(f"unsupported policy: base_obs_dim {pol.base_obs_dim} (expects the 5/6-dim "
                 "hover_blind obs — same family scripts/pilot.py flies)")

    rows = list(csv.DictReader(Path(args.flight).open(newline="")))
    if not rows:
        sys.exit(f"{args.flight}: no data rows")
    idle_us = min(_f(r["us_thr"]) for r in rows if r.get("us_thr", "").strip())

    hist: deque = deque(maxlen=pol.obs_stack)   # replay the pilot's in-flight stacking, in order
    abs_err = [[] for _ in _ACT_COLS]
    pred_thr_air: list[float] = []
    log_thr_air: list[float] = []
    n_air = 0
    for r in rows:
        base = [_f(r["roll"]), _f(r["pitch"]), _f(r["p"]), _f(r["q"]), _f(r["r"])]
        if pol.uses_tof:
            # h_err (col 26) is the channel exactly as the pilot fed it (tilt-corrected,
            # last-valid-held, minus the flight's target height) — replay is exact.
            base = base + [_f(r.get("h_err", ""))]
        elif pol.uses_vz:
            base = base + [_f(r["vz_est"])]
        obs = pilot.stack_frames(hist, base, pol.obs_stack)
        pred = pol(obs)
        logged = [_f(r[c]) for c in _ACT_COLS]
        for k in range(pol.act_dim):
            abs_err[k].append(abs(pred[k] - logged[k]))
        airborne = _f(r["us_thr"]) > idle_us + args.airborne_us_over_idle
        tilt_deg = math.degrees(math.hypot(base[0], base[1]))
        if airborne and tilt_deg < args.stable_tilt_deg:  # stable hover only (excludes the tumble)
            n_air += 1
            pred_thr_air.append(pred[0])
            log_thr_air.append(logged[0])

    print(f"sim-vs-real · {Path(args.flight).name} · {len(rows)} frames "
          f"(policy base {pol.base_obs_dim} × {pol.obs_stack} stack, act {pol.act_dim})")
    print(f"  per-channel action MAE (predicted vs logged):")
    worst = 0.0
    for k in range(pol.act_dim):
        mae = statistics.fmean(abs_err[k])
        mx = max(abs_err[k])
        worst = max(worst, mx)
        print(f"    {_ACT_LABELS[k]:6s}  MAE {mae:.2e}   max|err| {mx:.2e}")
    faithful = worst < 1e-3
    print(f"  -> {'FAITHFUL' if faithful else 'DIVERGENT'} "
          f"(worst |err| {worst:.2e} vs the log's 1e-4 rounding floor): the exported policy "
          f"reproduces the in-flight commands{'' if faithful else ' — INVESTIGATE'}.")

    if pred_thr_air:
        print(f"  a_thr steadiness over {n_air} stable-hover frames: "
              f"predicted std {statistics.pstdev(pred_thr_air):.4f} "
              f"(median {statistics.median(pred_thr_air):+.4f}), "
              f"logged std {statistics.pstdev(log_thr_air):.4f} "
              f"(median {statistics.median(log_thr_air):+.4f})")
        print("     a pinned a_thr near hover (−0.50) with tiny std == the policy never commanded "
              "the climb; the thrust rise came from the pilot's altitude damper (see flight_report).")
    return 0 if faithful else 1


if __name__ == "__main__":
    raise SystemExit(main())
