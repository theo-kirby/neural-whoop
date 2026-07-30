#!/usr/bin/env python
"""Render a replay to an MP4 in the Studio's own look — the in-repo headless capturer.

This replaces the sibling ``../nw-viz`` Node project as the video seam. The scene is not a
reimplementation: ``web/capture/`` imports ``web/studio/``'s scene / environment / geometry /
drone-model / playback modules verbatim, so what you get is exactly the chassis CAD and the
"1 METER / PROTOTYPE" greybox room the dashboard shows, rendered clean and full-frame with a
fixed camera, true-scale airframe, spinning props and phase captions.

The driver is deliberately four small moving parts (the same shape ``capture.mjs`` had, in Python):

1. read the replay here (``viz.replay.load_run``, gzip-transparent) — the page never parses it;
2. serve ``web/`` from a stdlib ``ThreadingHTTPServer`` on an ephemeral loopback port;
3. drive headless Chromium (SwiftShader) frame by frame — ``renderFrame(i)`` then screenshot,
   so the frame INDEX is the only clock: no rAF, no wall time, no dropped or doubled frames;
4. pipe the PNGs into ffmpeg (``imageio_ffmpeg``'s bundled binary — there is no system ffmpeg).

    uv pip install -e '.[capture]' && playwright install chromium
    uv run python scripts/capture_video.py --replay runs/acro_flip/hero_seq/replay.json.gz \
        --out runs/acro_flip/hero_seq/takeoff_flip_land.mp4 --title "neural-whoop"

Iterate with ``--stride 40 --width 960 --height 540`` (a handful of frames), and use
``--stills 120,250`` to dump single PNGs instead of a video when you just want to look at a frame.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import socketserver
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
CAPTURE_PAGE = "capture/index.html"

#: Where the pinned three.js bundles are cached so a render needs no network after the first one.
CDN_CACHE = REPO_ROOT / ".cache" / "three"
#: The only external host the page touches (the importmap in web/*/index.html).
CDN_HOST = "cdn.jsdelivr.net"

#: SwiftShader — this bench Mac has no CUDA and headless Chromium has no GPU; ANGLE's software
#: rasterizer is the only path that gives the page a WebGL2 context.
CHROME_ARGS = [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
    "--use-gl=angle",
    "--hide-scrollbars",
]


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static file handler over ``web/``, no caching, no request logging."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args: Any) -> None:
        """Silence the stdlib access log."""


def _serve(root: Path) -> tuple[socketserver.TCPServer, str]:
    """Start a background HTTP server on an ephemeral loopback port; return it and its base URL."""
    handler = functools.partial(_Handler, directory=str(root))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _cdn_route(route: Any, request: Any) -> None:
    """Fulfil a jsDelivr request from ``.cache/three/``, fetching once on a miss.

    Pinning the bundle locally makes renders offline and byte-repeatable — the alternative is a
    network fetch per run, which is both slow under SwiftShader and a silent source of drift.
    """
    url = request.url
    name = hashlib.sha256(url.encode()).hexdigest()[:16] + "_" + url.rsplit("/", 1)[-1]
    cached = CDN_CACHE / name
    if not cached.exists():
        CDN_CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as resp:   # pinned CDN host
            cached.write_bytes(resp.read())
    ctype = "application/javascript" if cached.suffix == ".js" else "text/plain"
    route.fulfill(status=200, body=cached.read_bytes(), headers={"content-type": ctype})


def _ffmpeg_writer(out: Path, fps: float, crf: int, quiet: bool) -> subprocess.Popen:
    """Open an ffmpeg process reading a PNG stream on stdin (imageio-ffmpeg's bundled binary)."""
    from imageio_ffmpeg import get_ffmpeg_exe

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_ffmpeg_exe(), "-y",
        "-f", "image2pipe", "-framerate", f"{fps:g}", "-i", "pipe:0",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf),
        "-movflags", "+faststart", str(out),
    ]
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
    )


def render(
    replay: Path,
    out: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: float | None = None,
    crf: int = 18,
    stride: int = 1,
    episode: int = 0,
    theme: str = "light",
    room_size: float | None = None,
    cam_dir: tuple[float, float, float] = (0.9, 0.35, 1.0),
    cam_dist: float = 1.15,
    fov: float = 40.0,
    track: bool = False,
    drone_frac: float = 0.14,
    scale: float | None = None,
    prop_rate: float = 0.8,
    title: str = "neural-whoop",
    title_frames: int = 40,
    stills: list[int] | None = None,
    quiet: bool = False,
) -> Path | None:
    """Render ``replay`` to ``out`` (MP4), or to numbered PNG stills when ``stills`` is given.

    Args:
        replay: Path to a ``neural-whoop-replay`` document (``.json`` or ``.json.gz``).
        out: Output ``.mp4`` (or, with ``stills``, the stem for ``<stem>_f<idx>.png``).
        width/height: Output size in px (forced even for libx264).
        fps: Output frame rate; ``None`` -> the replay's ``meta.control_hz`` (i.e. real time).
        crf: libx264 quality (lower = better).
        stride: Render every Nth frame — the fast smoke path.
        episode: Which episode of the replay to render.
        theme: ``light`` (the bright prototype-map room) or ``dark``.
        room_size: Greybox room footprint (m); ``None`` -> derived from the flight's own bounds.
        cam_dir/cam_dist/fov: Fixed camera direction, distance multiplier, lens.
        track: Tripod shot — the camera position stays fixed but it pans/tilts to follow the
            drone. The only way to get genuinely close at true scale: with the whole flight in a
            fixed frame, an 82 mm airframe can occupy at most ~5% of the frame height. The cost
            is that you no longer see the whole trajectory at once.
        drone_frac: With ``track``, the fraction of the frame height the airframe should fill —
            this, not the flight extent, is what sets the camera distance.
        scale: Drone tip-to-tip footprint (m); ``None`` -> the true 82 mm airframe.
        prop_rate: Stylized prop spin, radians per frame at hover thrust.
        title/title_frames: Opening/closing card text and how long each is held (frames).
        stills: Frame indices to dump as PNGs instead of encoding a video.
        quiet: Suppress progress output.

    Returns:
        The written path (the MP4, or the stills' directory), or ``None`` if nothing rendered.
    """
    from playwright.sync_api import sync_playwright

    from neural_whoop.viz.replay import load_run

    doc = load_run(replay)
    meta = doc.get("meta", {})
    if fps is None:
        fps = float(meta.get("control_hz") or round(1.0 / float(meta.get("dt") or 0.02)))
    fps = fps / max(1, stride)
    width, height = (width // 2) * 2, (height // 2) * 2

    page_opts = {
        "episode": episode, "theme": theme, "camDir": list(cam_dir), "camDist": cam_dist,
        "propRate": prop_rate, "title": title, "titleFrames": title_frames,
        "fov": fov, "track": track, "droneFrac": drone_frac,
    }
    if room_size is not None:
        page_opts["roomSize"] = room_size
    if scale is not None:
        page_opts["scale"] = scale

    httpd, base = _serve(WEB_ROOT)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=CHROME_ARGS)
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1)
            page.route(f"**/{CDN_HOST}/**", _cdn_route)
            page.add_init_script(
                f"window.__REPLAY_DOC__ = {json.dumps(doc)};"
                f"window.__CAPTURE_OPTS__ = {json.dumps(page_opts)};")
            page.on("console", lambda m: None if quiet or m.type != "error" else
                    print(f"[page] {m.text}", file=sys.stderr))
            page.goto(f"{base}/{CAPTURE_PAGE}", wait_until="load")
            page.wait_for_function("window.NW_CAPTURE_READY === true", timeout=120_000)

            n = int(page.evaluate("window.NW_CAPTURE.frameCount"))
            app = page.locator("#app")
            indices = list(range(0, n, max(1, stride)))

            if stills:
                out.parent.mkdir(parents=True, exist_ok=True)
                for idx in stills:
                    page.evaluate("i => window.NW_CAPTURE.renderFrame(i)", min(idx, n - 1))
                    png = out.with_name(f"{out.stem}_f{idx:05d}.png")
                    png.write_bytes(app.screenshot(type="png"))
                    if not quiet:
                        print(f"[still] {png}")
                browser.close()
                return out.parent

            if not quiet:
                print(f"[capture] {n} frames -> {len(indices)} @ {fps:g} fps, {width}x{height}")
            proc = _ffmpeg_writer(out, fps, crf, quiet)
            assert proc.stdin is not None
            try:
                for k, idx in enumerate(indices):
                    page.evaluate("i => window.NW_CAPTURE.renderFrame(i)", idx)
                    proc.stdin.write(app.screenshot(type="png"))
                    if not quiet and (k % 25 == 0 or k == len(indices) - 1):
                        print(f"\r[capture] {k + 1}/{len(indices)}", end="", flush=True)
            finally:
                proc.stdin.close()
                rc = proc.wait()
                if not quiet:
                    print()
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    if rc != 0:
        raise RuntimeError(f"ffmpeg exited {rc} while writing {out}")
    if not quiet:
        print(f"[capture] {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--replay", required=True, help="replay.json[.gz] to render")
    p.add_argument("--out", required=True, help="output .mp4")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=float, default=None, help="default: the replay's control_hz")
    p.add_argument("--crf", type=int, default=18)
    p.add_argument("--stride", type=int, default=1, help="render every Nth frame (smoke path)")
    p.add_argument("--episode", type=int, default=0)
    p.add_argument("--theme", choices=["light", "dark"], default="light")
    p.add_argument("--room-size", type=float, default=None, help="greybox room footprint (m)")
    p.add_argument("--cam-dir", default="0.9,0.35,1.0", help="fixed camera direction (three-frame)")
    p.add_argument("--cam-dist", type=float, default=1.15,
                   help="pull-back on the exact box fit (1.0 = the flight touches the frame edges)")
    p.add_argument("--fov", type=float, default=40.0, help="vertical field of view (deg)")
    p.add_argument("--track", action="store_true",
                   help="tripod shot: fixed camera position, panning/tilting to follow the drone "
                        "(lets the shot get close; you lose the whole-trajectory framing)")
    p.add_argument("--drone-frac", type=float, default=0.14,
                   help="with --track, fraction of the frame height the airframe fills")
    p.add_argument("--scale", type=float, default=None,
                   help="drone footprint in m (default: the true 0.082 m airframe)")
    p.add_argument("--prop-rate", type=float, default=0.8,
                   help="stylized prop spin, rad/frame at hover thrust")
    p.add_argument("--title", default="neural-whoop")
    p.add_argument("--title-frames", type=int, default=40, help="0 disables the title/end cards")
    p.add_argument("--stills", default=None,
                   help="comma-separated frame indices to dump as PNGs instead of a video")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    render(
        Path(a.replay), Path(a.out),
        width=a.width, height=a.height, fps=a.fps, crf=a.crf, stride=a.stride,
        episode=a.episode, theme=a.theme, room_size=a.room_size,
        cam_dir=tuple(float(v) for v in a.cam_dir.split(",")), cam_dist=a.cam_dist, fov=a.fov,
        track=a.track, drone_frac=a.drone_frac,
        scale=a.scale, prop_rate=a.prop_rate, title=a.title, title_frames=a.title_frames,
        stills=[int(v) for v in a.stills.split(",")] if a.stills else None,
        quiet=a.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
