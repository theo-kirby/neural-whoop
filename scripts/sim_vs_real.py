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
    # Task-keyed, exactly like the pilot's own gate: base_obs_dim 8 is BOTH the hover_flow obs and
    # the acro-flip one, and replaying an acro file against these columns would silently diff
    # gravity_body against roll/pitch.
    if pol.uses_flow:
        if pol.base_obs_dim != 8:
            sys.exit(f"unsupported hover_flow policy: base_obs_dim {pol.base_obs_dim} (expects 8)")
    elif pol.base_obs_dim not in (5, 6):
        sys.exit(f"unsupported policy: base_obs_dim {pol.base_obs_dim} (expects the 5/6-dim "
                 "hover_blind/hover_tof obs or an 8-dim hover_flow one — the families "
                 "scripts/pilot.py flies)")

    rows = list(csv.DictReader(Path(args.flight).open(newline="")))
    if not rows:
        sys.exit(f"{args.flight}: no data rows")
    idle_us = min(_f(r["us_thr"]) for r in rows if r.get("us_thr", "").strip())

    # Phases in which the POLICY commands the throttle. Everything else is the pilot's own
    # profile (seek/rise/land) or not flying at all, and must not be graded as policy divergence.
    _POLICY_PHASES = {"hover", "flip"}
    _phase_col = "phase" in rows[0]

    hist: deque = deque(maxlen=pol.obs_stack)   # replay the pilot's in-flight stacking, in order
    n_graded = 0
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
            if pol.uses_flow:
                # vx/vy likewise: the FUSED, faded channel, not the raw flow_dx/flow_dy counts.
                # Reconstructing these from the counts would need the held height, the gyro and
                # the fade clock, i.e. a reimplementation of the controller — which is the thing
                # this script exists to check rather than to assume.
                if "vx" not in r or "vy" not in r:
                    sys.exit(f"{args.flight}: a hover_flow policy needs the vx/vy columns "
                             "(33-column schema); this log predates them")
                base = base + [_f(r.get("vx", "")), _f(r.get("vy", ""))]
        elif pol.uses_vz:
            base = base + [_f(r["vz_est"])]
        obs = pilot.stack_frames(hist, base, pol.obs_stack)
        pred = pol(obs)
        logged = [_f(r[c]) for c in _ACT_COLS]
        # Grade ONLY the rows the policy actually commanded. The pilot owns the throttle in every
        # phase except HOVER/FLIP — SEEK ramps it to find liftoff, RISE holds the learned anchor,
        # LAND ramps it down — so diffing those rows against the policy's prediction measures the
        # pilot's takeoff/landing profile, not the deploy path's faithfulness. It reported
        # DIVERGENT (worst |err| 0.71) on a flight whose rate channels matched to 2.5e-05 because
        # the final 74 rows of 1063 were the ramp-down. The stack is still ADVANCED on every row
        # (the policy's obs history includes the climb-out), only the comparison is filtered.
        # Legacy logs have no phase column: fall back to grading everything, and say so.
        if _phase_col and r.get("phase", "").strip() not in _POLICY_PHASES:
            continue
        n_graded += 1
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
    if _phase_col:
        print(f"  grading {n_graded} of {len(rows)} rows — the policy-commanded phases "
              f"({'/'.join(sorted(_POLICY_PHASES))}); seek/rise/land are the PILOT's own throttle "
              f"profile and are not the policy's to reproduce.")
    else:
        print(f"  no `phase` column (pre-2026-08-12 log): grading ALL {n_graded} rows, which "
              f"INCLUDES the pilot-commanded takeoff ramp and land-out — expect a_thr to diverge "
              f"there for reasons that are not the deploy path's.")
    if not abs_err[0]:
        sys.exit("  no policy-commanded rows in this log: nothing to compare.")
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
