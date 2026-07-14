#!/usr/bin/env python3
"""Convert the whoop chassis CAD (STEP) into the Studio's GLB drone mesh.

The Studio frontend (web/studio/drone-model.js) upgrades its procedural drone glyph with
web/studio/assets/whoop_chassis.glb when present. Three.js can't read STEP, so this script
tessellates the CAD assembly with OpenCASCADE (via the `cascadio` wheel) and reports the
resulting bounds so the frontend's scale/orientation constants can be sanity-checked.

Not part of the core deps — run it standalone when the CAD changes:

    uv run --with cascadio --with trimesh python scripts/chassis_to_glb.py \
        --step ~/Downloads/whoop_assembly_draft.step
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cascadio
import trimesh

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "web" / "studio" / "assets" / "whoop_chassis.glb"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", required=True, help="input STEP file (mm)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"output GLB (default {DEFAULT_OUT})")
    ap.add_argument("--tol-linear", type=float, default=0.15, help="tessellation tolerance, mm")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cascadio.step_to_glb(str(Path(args.step).expanduser()), str(out), tol_linear=args.tol_linear)

    scene = trimesh.load(out)
    lo, hi = scene.bounds
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")
    print(f"bounds min {lo.round(2).tolist()}  max {hi.round(2).tolist()}  extents {(hi - lo).round(2).tolist()}")
    print(f"triangles: {sum(g.faces.shape[0] for g in scene.geometry.values())}")


if __name__ == "__main__":
    main()
