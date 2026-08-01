#!/usr/bin/env python
"""Render a replay to an MP4 in the Studio's own look — the in-repo headless capturer.

This replaces the sibling ``../nw-viz`` Node project as the video seam. The scene is not a
reimplementation: ``web/capture/`` imports ``web/studio/``'s scene / environment / geometry /
drone-model / playback modules verbatim, so what you get is exactly the chassis CAD and the
"1 METER / PROTOTYPE" greybox floor the dashboard shows, rendered clean and full-frame with a
fixed camera, true-scale airframe, spinning props and phase captions.

**There is no ``--preset``.** The standardized look (follow rig, fogged cyclorama, scale-matched
grid, steep key) is the *default* — ``neural_whoop.video.look.VIDEO_LOOK`` — because the two
callers that matter most, ``scripts/viz.py`` and the Studio's ``/api/export``, call ``render()``
directly and a flag could never have reached them. Reach for
``neural_whoop.video.render.render_video`` rather than this CLI when the clip is one of the named
kinds (reference / policy / comparison); it derives the per-maneuver framing and records it.

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

sys.path.insert(0, str(REPO_ROOT / "src"))

from neural_whoop.video.look import VIDEO_LOOK  # noqa: E402

#: Where the pinned three.js bundles are cached so a render needs no network after the first one.
CDN_CACHE = REPO_ROOT / ".cache" / "three"
#: The only external host the page touches (the importmap in web/*/index.html).
CDN_HOST = "cdn.jsdelivr.net"

#: The look is not a preset any more — it is the default. ``VIDEO_LOOK`` lives in the package
#: (``neural_whoop.video.look``) rather than here, because ``scripts/viz.py`` and the Studio's
#: ``/api/export`` call ``render()`` directly and never see this CLI; pinning ``render()``'s
#: keyword defaults against it is what gives those two the same picture as everything else.
#: ``tests/test_video_look.py`` holds both halves of that lock.

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


def page_options(
    *,
    episode: int,
    theme: str,
    cam_dir: tuple[float, float, float],
    cam_dist: float,
    prop_rate: float,
    title: str,
    title_frames: int,
    fov: float,
    shot: str,
    track: bool,
    drone_frac: float,
    cam_above: float,
    track_smooth: int,
    track_amount: float,
    subject_y: float,
    max_drift: float,
    frame_height: float | None,
    aim_z: float | None,
    room_labels: bool,
    aim: tuple[float, float, float] | None,
    grid_pitch: float | None,
    grid_minor: float | None,
    fog: tuple[float, float] | None,
    key_dir: tuple[float, float, float] | None,
    exposure: float | None,
    room_size: float | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """Translate a resolved look into the ``window.__CAPTURE_OPTS__`` the capture page reads.

    This is the ONE seam between Python and ``web/capture/capture.js`` — snake_case here,
    camelCase there — and nothing about it is checked by the runtime: a renamed key simply
    falls back to the page's own ``DEFAULTS`` and still encodes a perfectly plausible video
    with the wrong camera. It is a pure function (no playwright, no browser) precisely so
    ``tests/test_capture_opts_contract.py`` can diff it against ``DEFAULTS`` on every run.

    ``room_size`` and ``scale`` are the only conditional keys: omitting them leaves the page on
    its own derivation (footprint from the flight's bounds; the true 82 mm airframe).
    """
    opts: dict[str, Any] = {
        "episode": episode, "theme": theme, "camDir": list(cam_dir), "camDist": cam_dist,
        "propRate": prop_rate, "title": title, "titleFrames": title_frames,
        "fov": fov, "shot": shot, "track": track, "droneFrac": drone_frac,
        "camAbove": cam_above, "trackSmooth": track_smooth, "trackAmount": track_amount,
        "subjectY": subject_y, "maxDrift": max_drift,
        "frameHeight": frame_height, "aimZ": aim_z, "roomLabels": room_labels,
        "aim": list(aim) if aim else None,
        "gridPitch": grid_pitch, "gridMinor": grid_minor,
        "fog": list(fog) if fog else None, "keyDir": list(key_dir) if key_dir else None,
        "exposure": exposure,
    }
    if room_size is not None:
        opts["roomSize"] = room_size
    if scale is not None:
        opts["scale"] = scale
    return opts


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
    # --- the standardized look. These defaults ARE neural_whoop.video.look.VIDEO_LOOK, field for
    # field, and a test asserts it. That is what makes scripts/viz.py and the Studio's /api/export —
    # which call render() directly, never main() — render the same picture as everything else.
    theme: str = "dark",
    shot: str = "follow",
    room_size: float | None = None,
    cam_dir: tuple[float, float, float] = (0.85, 0.30, 1.0),
    cam_dist: float = 1.15,
    fov: float = 40.0,
    track: bool = False,
    drone_frac: float = 0.22,
    cam_above: float = 0.30,
    track_smooth: int = 20,
    track_amount: float = 1.0,
    subject_y: float = -0.06,
    max_drift: float = 0.26,
    frame_height: float | None = None,
    aim: tuple[float, float, float] | None = None,
    aim_z: float | None = None,
    grid_pitch: float | None = None,
    grid_minor: float | None = None,
    fog: tuple[float, float] | None = None,
    key_dir: tuple[float, float, float] | None = (0.22, 1.0, 0.15),
    exposure: float | None = 0.95,
    room_labels: bool = True,
    scale: float | None = None,
    prop_rate: float = 0.8,
    title: str = "neural-whoop",
    title_frames: int = 0,
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
        shot: ``fit`` (locked off, whole flight in frame), ``tripod`` (fixed position, pans/tilts
            to follow), or ``follow`` — the standardized hero rig, where the camera holds a
            constant offset from a smoothed subject track. ``follow`` is the one to reach for on a
            concept render: apparent size is fixed by construction (``drone_frac`` of the frame
            height in every frame of every clip) and the camera's orientation never changes, so the
            horizon stays put and only the ground parallaxes past.
        room_size: Stage-floor footprint (m); ``None`` -> derived from the fog, which is derived
            from the camera standoff — so the plane always runs past its own fade.
        cam_dir/cam_dist/fov: Fixed camera direction, distance multiplier, lens.
        track: Deprecated spelling of ``shot="tripod"``.
        drone_frac: With ``follow``/``tripod``, the fraction of the frame height the airframe
            fills — this, not the flight extent, is what sets the camera distance.
        cam_above: With ``tripod``, metres the camera is parked above the flight's highest point.
            This is what guarantees the shot never tilts upward: level or looking down, always.
        track_smooth: Symmetric smoothing half-window (frames) applied to the subject track.
            Bigger = a calmer camera that the drone leads further through fast moves.
        subject_y: With ``follow``, the subject's resting NDC height. Negative sits it below
            centre, leaving headroom for a climb; 0 is dead centre.
        max_drift: With ``follow``, how far (NDC) the airframe may lead the smoothed camera before
            the rig stops smoothing and pulls it back — the guarantee it never leaves frame.
        frame_height: ``fit`` framing: how many metres of world the frame spans vertically. The
            airframe is then exactly ``scale / frame_height`` of the picture — the direct
            "how big is the drone" control.
        aim: ``fit`` aim point, sim ``(x, y, z)`` in metres; ``None`` -> the median hero position.
            With a level ``cam_dir`` the camera sits at the aim's height, i.e. dead straight-on.
        aim_z: Aim height only (sim z, m), when ``aim`` is not given.
        grid_pitch: Greybox grid pitch (m); ``None`` -> chosen from the shot's own framing, so an
            82 mm airframe lands at roughly one tile instead of 1/12 of a metre square.
        grid_minor: Finer subdivision (m); ``None`` -> ``grid_pitch / 5``, ``0`` -> none.
        fog: ``(near, far)`` in m for the cyclorama; ``None`` -> from the camera standoff.
        key_dir: Sun direction ``(x, y, z)`` in three-frame (Y up); ``None`` leaves the base rig's
            aim alone. A steep key keeps the cast shadow under the airframe instead of a metre away.
        exposure: ACES tone-mapping exposure. The scene's light rig is tuned for the wide
            Studio view; a close shot needs the highlights rolled off or the near gridlines
            clip to flat white. ``None`` disables tone mapping entirely (the legacy look).
        room_labels: Bake the pitch / "PROTOTYPE" text into the greybox tiles.
        track_amount: With ``tripod``, 1.0 locks the drone dead centre; below 1.0 the camera stays
            partly parked on the flight's centre and swings less.
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

    page_opts = page_options(
        episode=episode, theme=theme, cam_dir=cam_dir, cam_dist=cam_dist, prop_rate=prop_rate,
        title=title, title_frames=title_frames, fov=fov, shot=shot, track=track,
        drone_frac=drone_frac, cam_above=cam_above, track_smooth=track_smooth,
        track_amount=track_amount, subject_y=subject_y, max_drift=max_drift,
        frame_height=frame_height, aim_z=aim_z, room_labels=room_labels, aim=aim,
        grid_pitch=grid_pitch, grid_minor=grid_minor, fog=fog,
        key_dir=key_dir, exposure=exposure, room_size=room_size, scale=scale,
    )

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
            fit = page.evaluate("window.NW_CAPTURE.framing")
            worst = max(fit["x"], fit["y"])
            # Two measured numbers, so "is this framed right?" is never something you check by
            # scrubbing: worst |NDC| (1.0 = the frame edge) and the spread of apparent size over
            # the flight (a follow rig should be flat; a swing means the subject balloons/shrinks).
            size = (f"size {100 * fit['sizeMin']:.1f}-{100 * fit['sizeMax']:.1f}% of frame height"
                    if fit.get("sizeMax") else "")
            if worst >= 1.0:
                print(f"[capture] WARNING: the drone leaves frame (worst |NDC| {worst:.2f} > 1.0; "
                      f"x {fit['x']:.2f}, y {fit['y']:.2f}). Widen --frame-height / lower "
                      "--drone-frac, or use --shot follow.", file=sys.stderr)
            elif not quiet:
                print(f"[capture] framing: worst |NDC| {worst:.2f} "
                      f"(x {fit['x']:.2f}, y {fit['y']:.2f}) — 1.0 is the frame edge; {size}")
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
    p.add_argument("--theme", choices=["light", "dark"])
    p.add_argument("--shot", choices=["fit", "tripod", "follow"],
                   help="fit: locked off, whole flight in frame. tripod: fixed position, pans to "
                        "follow. follow: constant offset from a smoothed subject track — the "
                        "standardized hero rig (fixed apparent size, fixed horizon)")
    p.add_argument("--room-size", type=float, default=None,
                   help="stage-floor footprint in m (default: derived from the fog, so the plane "
                        "always runs past its own fade)")
    p.add_argument("--cam-dir", help="fixed camera direction (three-frame)")
    p.add_argument("--cam-dist", type=float,
                   help="pull-back on the exact box fit (1.0 = the flight touches the frame edges)")
    p.add_argument("--fov", type=float, help="vertical field of view (deg)")
    p.add_argument("--track", action="store_true", help="deprecated spelling of --shot tripod")
    p.add_argument("--drone-frac", type=float,
                   help="with --shot follow/tripod, fraction of the frame height the airframe fills")
    p.add_argument("--cam-above", type=float,
                   help="with --shot tripod, metres the camera sits above the flight's highest "
                        "point (this is what keeps the shot from ever tilting upward)")
    p.add_argument("--track-smooth", type=int,
                   help="subject-track smoothing half-window in frames (bigger = calmer camera)")
    p.add_argument("--subject-y", type=float,
                   help="with --shot follow, the subject's resting NDC height (<0 = below centre, "
                        "leaving headroom for the climb)")
    p.add_argument("--max-drift", type=float,
                   help="with --shot follow, how far (NDC) the drone may lead the smoothed camera "
                        "before it is pulled back — the never-leaves-frame guarantee")
    p.add_argument("--frame-height", type=float, default=None,
                   help="--shot fit: metres of world the frame spans vertically (drone size = "
                        "--scale / --frame-height). Smaller = bigger drone, less flight in frame")
    p.add_argument("--aim", default=None,
                   help="--shot fit: aim point as sim x,y,z (m) — default the median hero position")
    p.add_argument("--aim-z", type=float, default=None,
                   help="--shot fit: sim-z the shot is centred on (default: the flight's centre)")
    p.add_argument("--grid-pitch", type=float,
                   help="greybox grid pitch in m (default: chosen from the shot's own framing, so "
                        "the airframe reads as about one tile)")
    p.add_argument("--grid-minor", type=float,
                   help="finer grid subdivision in m (default: pitch/5; 0 disables)")
    p.add_argument("--fog", help="floor backdrop fade as near,far in m (default: from the standoff)")
    p.add_argument("--key-dir", help="sun direction x,y,z in three-frame (Y up). A steep key keeps "
                                     "the cast shadow under the airframe instead of a metre away")
    p.add_argument("--exposure", type=float,
                   help="ACES tone-mapping exposure (the scene's light rig is tuned for the wide "
                        "Studio view; a close shot clips its highlights without this)")
    p.add_argument("--no-room-labels", dest="room_labels", action="store_const", const=False,
                   help="drop the baked pitch / 'PROTOTYPE' text from the greybox tiles")
    p.add_argument("--track-amount", type=float,
                   help="with --shot tripod, 1.0 locks the drone centre; lower keeps the camera "
                        "nearer the flight centre and swinging less")
    p.add_argument("--scale", type=float, default=None,
                   help="drone footprint in m (default: the true 0.082 m airframe)")
    p.add_argument("--prop-rate", type=float, default=0.8,
                   help="stylized prop spin, rad/frame at hover thrust")
    p.add_argument("--title", default="neural-whoop")
    p.add_argument("--title-frames", type=int, help="0 disables the title/end cards")
    p.add_argument("--stills", default=None,
                   help="comma-separated frame indices to dump as PNGs instead of a video")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    # Resolve the look: an explicit flag wins, else the standard value. Every look flag declares
    # NO argparse default, so `None` here means "you didn't say" — a flag with its own default
    # would silently outrank VIDEO_LOOK and nothing would notice. Pinned by
    # tests/test_video_look.py::test_every_look_flag_declares_no_argparse_default.
    look = dict(VIDEO_LOOK)
    for key, value in look.items():
        if getattr(a, key) is None:
            setattr(a, key, value)
    if a.track and a.shot == "fit":
        a.shot = "tripod"

    def vec(s):
        """A 3-vector from either `--flag x,y,z` or a VIDEO_LOOK tuple that fell through."""
        if not s:
            return None
        if isinstance(s, (tuple, list)):
            return tuple(float(v) for v in s)
        return tuple(float(v) for v in str(s).split(","))

    render(
        Path(a.replay), Path(a.out),
        width=a.width, height=a.height, fps=a.fps, crf=a.crf, stride=a.stride,
        episode=a.episode, theme=a.theme, shot=a.shot, room_size=a.room_size,
        cam_dir=vec(a.cam_dir), cam_dist=a.cam_dist, fov=a.fov,
        track=a.track, drone_frac=a.drone_frac, cam_above=a.cam_above,
        track_smooth=a.track_smooth, track_amount=a.track_amount,
        subject_y=a.subject_y, max_drift=a.max_drift,
        frame_height=a.frame_height, aim_z=a.aim_z, room_labels=a.room_labels,
        grid_pitch=a.grid_pitch, grid_minor=a.grid_minor,
        fog=vec(a.fog), key_dir=vec(a.key_dir), exposure=a.exposure,
        aim=vec(a.aim),
        scale=a.scale, prop_rate=a.prop_rate, title=a.title, title_frames=a.title_frames,
        stills=[int(v) for v in a.stills.split(",")] if a.stills else None,
        quiet=a.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
