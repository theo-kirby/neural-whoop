"""FastAPI app for the neural-whoop Studio — list policies/courses, run a fixed-course rollout,
serve the resulting replay to the static Three.js frontend.

``create_app`` is a factory (tests redirect the runs/courses/web dirs into a ``tmp_path``). Only
``fastapi`` is imported at module scope (the ``studio`` extra); everything that needs torch/sim is
reached through :func:`neural_whoop.studio.rollout.studio_rollout` (function-local imports), so the
module — and the GET listing routes — import without a GPU. A module-level single-flight lock
guards the rollout route (the batched GPU sim is not re-entrant); the route returns HTTP 409 while
one is running and offloads the blocking work off the event loop.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from neural_whoop import course as course_mod
from neural_whoop.studio import courses as courses_mod

#: Repo root (src/neural_whoop/studio/server.py -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The sibling nw-viz capture entrypoint (../nw-viz/capture.mjs), mirroring scripts/viz.py.
_NW_VIZ_CAPTURE = _REPO_ROOT.parent / "nw-viz" / "capture.mjs"

#: Single-flight guard: only one rollout runs at a time (the batched GPU sim isn't re-entrant).
ROLLOUT_LOCK = asyncio.Lock()
#: Single-flight guard: only one hero-MP4 capture runs at a time (headless Chromium is heavy).
EXPORT_LOCK = asyncio.Lock()


class RolloutRequest(BaseModel):
    """Request to fly a saved policy over a chosen course with a chosen drone count."""

    policy: str                                   # repo-relative ckpt path under runs/
    course: str                                   # "preset:<name>" or a seeded YAML stem
    drone_count: int = Field(default=3, ge=1, le=16)
    dr: bool = False
    max_steps: int = Field(default=1200, ge=1, le=4000)
    n_gates: int = Field(default=6, ge=1, le=24)   # for preset courses
    seed: int = 0


class GateModel(BaseModel):
    """One omnidirectional spherical gate (sim frame, meters)."""

    pos: list[float] = Field(min_length=3, max_length=3)
    radius: float = 0.35


class CourseModel(BaseModel):
    """An authored course payload (name + gate list) for validate/save."""

    name: str = "course"
    gates: list[GateModel] = Field(default_factory=list)

    def gate_dicts(self) -> list[dict]:
        return [{"pos": list(g.pos), "radius": float(g.radius)} for g in self.gates]


class ExportRequest(BaseModel):
    """Render a loaded replay to a hero MP4 via the sibling nw-viz capture pipeline."""

    run_path: str                                   # runs-relative replay path (from /api/rollout)
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=720, ge=240, le=2160)
    fps: float | None = Field(default=None, ge=1, le=120)
    crf: int = Field(default=18, ge=0, le=51)


#: The deployed hover policy the Bench dashboard flies by default.
_DEFAULT_FLIGHT_WEIGHTS = "runs/hover_blind_air65_d50var_s8/policy_weights.json"


def create_app(
    repo_root: Path | None = None,
    *,
    runs_dir: Path | None = None,
    courses_dir: Path | None = None,
    studio_dir: Path | None = None,
    device: str = "cuda",
    bridge: str | None = None,
    flight_weights: str = _DEFAULT_FLIGHT_WEIGHTS,
    flight_manager=None,
) -> FastAPI:
    """Build the Studio FastAPI app. Dirs default to the repo layout; override for tests.

    ``bridge`` (``host[:port]`` / ``"fake"`` / ``None``) enables the always-on real-drone Bench
    dashboard: when set, a :class:`~neural_whoop.studio.flight.FlightManager` is spun up in the
    startup hook (torch-free) and served over ``/ws/flight``. ``None`` (and no ``NW_FLIGHT_FAKE``)
    leaves ``/ws/flight`` reporting "no bridge configured".
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    runs_dir = (runs_dir or (root / "runs")).resolve()
    courses_dir = (courses_dir or (root / "assets" / "courses")).resolve()
    studio_dir = studio_dir or (root / "web" / "studio")

    app = FastAPI(title="neural-whoop studio", version="0.1.0")
    app.state.flight = None

    @app.middleware("http")
    async def _no_store_static(request, call_next):
        """Serve the static frontend with no-store so a code/browser-cache mismatch can't show a
        stale `playback.js` (the static dir isn't reload-watched; the API is untouched)."""
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    # ----------------------------------------------------------------- policies
    @app.get("/api/policies")
    def get_policies() -> list[dict]:
        return _list_policies(runs_dir, root)

    # ----------------------------------------------------------------- courses
    @app.get("/api/courses")
    def get_courses() -> dict:
        return {
            "courses": courses_mod.list_courses(courses_dir),
            "presets": courses_mod.list_presets(),
        }

    @app.get("/api/courses/{name}")
    def get_course(name: str) -> dict:
        """Load a single course (curated or authored ``_web/``) as ``{name, gates}`` for editing."""
        try:
            return courses_mod.load_course_named(courses_dir, name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/courses/validate")
    def validate_course(course: CourseModel, preset: str = "tight") -> dict:
        """Flyability check against an arena preset's bounds — pure geometry, no sim."""
        from neural_whoop.studio import course_validate

        return course_validate.validate_gates(course.gate_dicts(), _arena_for(preset))

    @app.post("/api/courses")
    def save_course(course: CourseModel, preset: str = "tight") -> dict:
        """Validate + persist an authored course under ``assets/courses/_web/<slug>.yaml``."""
        try:
            return courses_mod.save_course(
                courses_dir, course.name, course.gate_dicts(), _arena_for(preset),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ----------------------------------------------------------------- training scalars (TB)
    @app.get("/api/policies/{run}/scalars")
    def get_scalars(run: str) -> dict:
        from neural_whoop.studio import tbscalars

        run_dir = (runs_dir / run).resolve()
        if not run_dir.is_relative_to(runs_dir) or not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"no such run: {run!r}")
        return {"run": run, "tags": tbscalars.run_scalars(run_dir)}

    # ----------------------------------------------------------------- runs (replay files)
    @app.get("/api/runs/{path:path}")
    def get_run(path: str) -> FileResponse:
        try:
            target = _resolve_run(runs_dir, path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Serve gzip raw (octet-stream, no Content-Encoding) so the browser doesn't auto-inflate —
        # the frontend's DecompressionStream handles .gz itself.
        return FileResponse(target, media_type="application/octet-stream", filename=target.name)

    # ----------------------------------------------------------------- rollout (sim-backed)
    @app.post("/api/rollout")
    async def rollout(req: RolloutRequest) -> dict:
        from neural_whoop.studio.rollout import studio_rollout

        policy_abs = _resolve_under(root, req.policy)
        if not policy_abs.is_file():
            raise HTTPException(status_code=404, detail=f"no such policy: {req.policy}")
        if ROLLOUT_LOCK.locked():
            raise HTTPException(status_code=409, detail="a rollout is already running")
        async with ROLLOUT_LOCK:
            try:
                _, summary = await anyio.to_thread.run_sync(
                    lambda: studio_rollout(
                        policy_abs, req.course, req.drone_count, dr=req.dr,
                        max_steps=req.max_steps, seed=req.seed, n_gates=req.n_gates,
                        device=device, courses_dir=courses_dir, runs_dir=runs_dir,
                    )
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return summary

    # ----------------------------------------------------------------- live (interactive sim)
    @app.websocket("/ws/live")
    async def live(ws: WebSocket) -> None:
        """Drive a live :class:`LiveSession`: build from a setup message, then step at ~50 Hz while
        applying browser disturbance commands and streaming frames back.

        Single-flight via :data:`ROLLOUT_LOCK` (the batched GPU sim isn't re-entrant) — shared with
        ``/api/rollout`` so a rollout and a live session can't run at once (either rejects the other).
        All sim work (build / step / commands) runs off the event loop via ``anyio.to_thread``.
        """
        await ws.accept()
        if ROLLOUT_LOCK.locked():
            await ws.send_json({"type": "error", "detail": "the GPU sim is busy (a rollout or live "
                                                           "session is already running)"})
            await ws.close()
            return
        async with ROLLOUT_LOCK:
            try:
                setup = await ws.receive_json()
            except (WebSocketDisconnect, ValueError):
                return
            from neural_whoop.studio.live import LiveSession

            policy_abs = _resolve_under(root, str(setup.get("policy", "")))
            if not policy_abs.is_file():
                await ws.send_json({"type": "error", "detail": f"no such policy: {setup.get('policy')}"})
                await ws.close()
                return
            try:
                session = await anyio.to_thread.run_sync(lambda: LiveSession.build(
                    policy_abs, drone_count=int(setup.get("drone_count", 1)),
                    dr=bool(setup.get("dr", False)), seed=int(setup.get("seed", 0)),
                    course=setup.get("course"), device=device,
                    courses_dir=courses_dir, runs_dir=runs_dir,
                ))
            except Exception as exc:  # noqa: BLE001 - report any build error to the client
                await ws.send_json({"type": "error", "detail": str(exc)})
                await ws.close()
                return
            await ws.send_json({"type": "ready", "info": session.info()})

            cmds: asyncio.Queue = asyncio.Queue()

            async def _reader() -> None:
                """Drain inbound command messages into the queue until the socket closes."""
                try:
                    while True:
                        await cmds.put(await ws.receive_json())
                except (WebSocketDisconnect, ValueError, RuntimeError):
                    await cmds.put({"type": "_disconnect"})

            reader = asyncio.create_task(_reader())
            speed = 1.0
            try:
                while True:
                    disconnect = False
                    while not cmds.empty():
                        msg = cmds.get_nowait()
                        mtype = msg.get("type")
                        if mtype == "_disconnect":
                            disconnect = True
                            break
                        if mtype == "speed":
                            speed = max(0.1, min(8.0, float(msg.get("value", 1.0))))
                        else:
                            await anyio.to_thread.run_sync(lambda m=msg: session.command(m))
                    if disconnect:
                        break
                    if not session.paused:
                        frame = await anyio.to_thread.run_sync(session.step)
                        await ws.send_json({"type": "frame", **frame})
                    await asyncio.sleep(session.dt / max(0.1, speed))
            except WebSocketDisconnect:
                pass
            finally:
                reader.cancel()
                await anyio.to_thread.run_sync(session.close)

    # ----------------------------------------------------------------- export (hero MP4 via nw-viz)
    @app.post("/api/export")
    async def export_video(req: ExportRequest) -> dict:
        try:
            replay_abs = _resolve_run(runs_dir, req.run_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        node = shutil.which("node")
        if node is None or not _NW_VIZ_CAPTURE.exists():
            raise HTTPException(
                status_code=503,
                detail=("video export needs node + ../nw-viz; "
                        "run `cd ../nw-viz && npm install` (and install node) to enable it"),
            )
        if EXPORT_LOCK.locked():
            raise HTTPException(status_code=409, detail="a video export is already running")

        stem = replay_abs.name
        for ext in (".json.gz", ".json"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        out_mp4 = replay_abs.with_name(f"{stem}.mp4")
        async with EXPORT_LOCK:
            await anyio.to_thread.run_sync(
                lambda: _run_capture(node, replay_abs, out_mp4, req)
            )
        return {"video_path": out_mp4.resolve().relative_to(runs_dir.resolve()).as_posix()}

    # ----------------------------------------------------------------- flight (real drone)
    _flight_enabled = bool(bridge) or _flight_fake_env()

    @app.on_event("startup")
    def _start_flight() -> None:
        """Spin up the always-on FlightManager (lazy import so torch-less/bridge-less installs
        still import the app). No-op when no bridge is configured."""
        if flight_manager is not None:      # tests inject a pre-built manager
            flight_manager.start()
            app.state.flight = flight_manager
            return
        if not _flight_enabled:
            return
        from neural_whoop.studio.flight import FlightManager

        def _on_done(csv_path, released):
            # Phase 5: auto flight-report on landing (lazy + optional so the manager stands alone).
            try:
                from neural_whoop.studio.flight_report import run_flight_report
            except ImportError:
                return
            run_flight_report(csv_path, released, app.state.flight, runs_root=runs_dir)

        weights_abs = _resolve_under(root, flight_weights)
        mgr = FlightManager(
            bridge or "fake", weights=weights_abs, runs_dir=runs_dir / "pilot",
            on_flight_done=_on_done,
        )
        mgr.start()
        app.state.flight = mgr

    @app.on_event("shutdown")
    def _stop_flight() -> None:
        mgr = app.state.flight
        if mgr is not None:
            mgr.stop()
            app.state.flight = None

    @app.websocket("/ws/flight")
    async def flight(ws: WebSocket) -> None:
        """Stream the always-on real-drone flight to the browser; forward start/abort/params.

        NOT wrapped in :data:`ROLLOUT_LOCK` (that guards the GPU sim; the MSP link is a separate
        resource and multiple viewers may watch the same telemetry). The FlightManager is itself the
        single-flight guard for the sequence, and it never writes arm/aux — the radio owns kill.
        """
        await ws.accept()
        mgr = app.state.flight
        if mgr is None:
            await ws.send_json({"type": "error", "detail": "no bridge configured "
                                "(set NW_BRIDGE or pass --bridge / NW_FLIGHT_FAKE=1)"})
            await ws.close()
            return

        async def _reader() -> None:
            try:
                while True:
                    msg = await ws.receive_json()
                    if msg.get("type") in ("start", "abort", "params"):
                        mgr.command(msg)
            except (WebSocketDisconnect, ValueError, RuntimeError):
                pass

        reader = asyncio.create_task(_reader())
        last_seq = -1
        try:
            while True:
                await asyncio.sleep(0.02)
                for m in mgr.drain_messages():   # out-of-band (e.g. flight-report ready)
                    await ws.send_json(m)
                f = mgr.latest()
                if f is not None and f.get("seq") != last_seq:
                    last_seq = f["seq"]
                    await ws.send_json(f)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader.cancel()

    # ----------------------------------------------------------------- static studio (LAST)
    if studio_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(studio_dir), html=True), name="studio")

    return app


def _flight_fake_env() -> bool:
    import os

    return str(os.environ.get("NW_FLIGHT_FAKE", "")).lower() in ("1", "true", "yes", "on")


def app_factory() -> FastAPI:
    """Import-string factory for ``uvicorn --reload`` (needs a re-importable target, not an app
    instance). Device/bridge/weights come from env (set by ``scripts/serve.py`` across the reloader
    boundary), mirroring the ``NW_STUDIO_DEVICE`` pattern."""
    import os

    return create_app(
        device=os.environ.get("NW_STUDIO_DEVICE", "cuda"),
        bridge=os.environ.get("NW_BRIDGE") or None,
        flight_weights=os.environ.get("NW_FLIGHT_WEIGHTS", _DEFAULT_FLIGHT_WEIGHTS),
    )


# --------------------------------------------------------------------------- helpers
def _arena_for(preset: str) -> course_mod.ArenaSpec:
    """Arena bounds for a validation preset name; unknown names fall back to the tight default."""
    return course_mod.ARENA_PRESETS.get(preset, course_mod.ArenaSpec())


def _run_capture(node: str, replay_abs: Path, out_mp4: Path, req: "ExportRequest") -> None:
    """Shell out to ``node ../nw-viz/capture.mjs`` to render the hero MP4 (blocking; off-thread).

    Mirrors ``scripts/viz.py::_maybe_render_video`` — byte-identical to the committed pipeline.
    Raises ``RuntimeError`` (-> 500) with the captured stderr tail on a non-zero exit.
    """
    cmd = [node, str(_NW_VIZ_CAPTURE), "--replay", str(replay_abs), "--out", str(out_mp4),
           "--width", str(req.width), "--height", str(req.height), "--crf", str(req.crf)]
    if req.fps is not None:
        cmd += ["--fps", str(req.fps)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_NW_VIZ_CAPTURE.parent))
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        raise RuntimeError("nw-viz capture failed:\n" + "\n".join(tail))


def _rel(path: Path, root: Path) -> str:
    """Repo-relative POSIX path, falling back to the absolute path if outside the repo."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve_under(root: Path, rel: str) -> Path:
    """Resolve a repo-relative path under ``root``, guarding traversal."""
    root = root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail=f"path escapes repo: {rel!r}")
    return target


def _resolve_run(runs_dir: Path, rel: str) -> Path:
    """Resolve a runs-relative replay path, guarding traversal; raise ``ValueError`` if missing."""
    runs_dir = runs_dir.resolve()
    target = (runs_dir / rel).resolve()
    if not target.is_relative_to(runs_dir):
        raise ValueError(f"path escapes runs dir: {rel!r}")
    if not target.is_file():
        raise ValueError(f"no such run: {rel!r}")
    return target


def _list_policies(runs_dir: Path, root: Path) -> list[dict]:
    """List ``runs/*/ckpt_final.pt`` policies with display metadata.

    Each entry carries enough for the Studio's policy panel to render without a second round-trip:
    ``task``/``obs_dim``/``act_dim``/``step`` from the meta sidecar, ``created`` (checkpoint mtime,
    epoch seconds), the full ``eval`` metrics dict when an ``eval.json`` exists (``best_lap`` kept as
    a flat convenience for the selector label), and ``has_scalars`` so the UI knows whether to offer
    training charts.
    """
    out: list[dict] = []
    if not runs_dir.exists():
        return out
    for ckpt in sorted(runs_dir.glob("*/ckpt_final.pt")):
        run_name = ckpt.parent.name
        info: dict = {
            "path": _rel(ckpt, root), "name": run_name, "run": run_name,
            "task": "gate_race", "obs_dim": None, "act_dim": None, "step": None,
            "best_lap": None, "eval": None, "created": None, "has_scalars": False,
            "family": "gate", "needs_course": True,
        }
        try:
            info["created"] = ckpt.stat().st_mtime
        except OSError:
            pass
        meta_path = ckpt.with_suffix(ckpt.suffix + ".meta.json")
        if meta_path.is_file():
            try:
                m = json.loads(meta_path.read_text())
                info.update(task=m.get("task", "gate_race"), obs_dim=m.get("obs_dim"),
                            act_dim=m.get("act_dim"), step=m.get("step"))
            except Exception:  # noqa: BLE001 - skip an unreadable sidecar
                pass
        # Family flag drives the UI (gateless tasks hide the course selector; the picker groups by
        # family and floats the recommended runs). Derived from the task — no hardcoded task names.
        from neural_whoop.studio.rollout import (
            FAMILY_LABELS, GATELESS_TASKS, RECOMMENDED_RUNS, task_family,
        )
        fam = task_family(info["task"])
        info["family"] = fam
        info["family_label"] = FAMILY_LABELS.get(fam, fam)
        info["needs_course"] = info["task"] not in GATELESS_TASKS
        info["recommended"] = run_name in RECOMMENDED_RUNS
        # Eval metrics from a recorded eval.json (runs/<run>/eval.json or viz/eval.json).
        for cand in (ckpt.parent / "eval.json", ckpt.parent / "viz" / "eval.json"):
            if cand.is_file():
                try:
                    ev = json.loads(cand.read_text())
                    info["eval"] = ev
                    bl = ev.get("best_lap_time")
                    if bl is not None:
                        info["best_lap"] = float(bl)
                    break
                except Exception:  # noqa: BLE001
                    pass
        info["has_scalars"] = any(ckpt.parent.glob("events.out.tfevents.*"))
        out.append(info)
    return out
