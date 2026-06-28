#!/usr/bin/env python
"""Serve the neural-whoop Studio — the interactive browser viewer.

    uv pip install -e '.[studio]'              # one-time: fastapi/uvicorn
    uv run python scripts/serve.py             # -> http://127.0.0.1:8000

Open the URL, pick a saved policy, a course (seeded YAML or an arena preset), and a drone count,
then hit Fly: the server runs a fixed-course rollout on the GPU and streams back a v2 replay the
viewer plays (3D wide + FPV/top-down, play/pause/scrub). See docs/STUDIO.md.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Serve the neural-whoop Studio.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--device", default="cuda", help="Torch device for rollouts (cuda/cpu).")
    p.add_argument("--reload", action="store_true", help="Auto-reload on Python edits under src/ (dev).")
    args = p.parse_args()

    import uvicorn

    print(f"[studio] http://{args.host}:{args.port}  (device={args.device}{', reload' if args.reload else ''})")
    if args.reload:
        # uvicorn's reloader re-imports the app in a child process, so it needs an import-string
        # target (an app instance can't be reload-watched). Pass the device via env across that
        # boundary, and watch only src/ so per-rollout writes under runs/ never trigger a reload.
        os.environ["NW_STUDIO_DEVICE"] = args.device
        src_dir = Path(__file__).resolve().parents[1] / "src"
        uvicorn.run(
            "neural_whoop.studio.server:app_factory", factory=True,
            host=args.host, port=args.port, reload=True, reload_dirs=[str(src_dir)],
        )
    else:
        from neural_whoop.studio.server import create_app

        uvicorn.run(create_app(device=args.device), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
