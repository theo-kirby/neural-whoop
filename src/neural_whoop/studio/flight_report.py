"""Auto flight-report on landing — spawn the analysis pack, emit a headline to the browser.

When the always-on :class:`~neural_whoop.studio.flight.FlightManager` finishes a *completed* flight
(phase RELEASED, not a mid-air abort), it fires :func:`run_flight_report`, which detaches
``scripts/flight_report.py`` on the flight's CSV. The numpy/matplotlib work runs in **its own
process**, so the manager (and the whole real-flight path) stays torch/numpy-free; when the pack is
ready this reads the headline metrics out of ``flight_summary.json`` and emits a ``{type: report}``
message into the flight stream for the Bench tab to surface. Fully best-effort: any failure is
swallowed and never touches the flight loop.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "flight_report.py"


def run_flight_report(csv_path, released: bool, manager, *, runs_root=None) -> None:
    """Spawn the flight-report pack for a completed flight and emit its headline when ready.

    ``released`` gates it: a mid-air abort produces no report. Detaches immediately (a worker thread
    waits on the subprocess), so the flight thread is never blocked.
    """
    if not released or manager is None:
        return
    csv_path = Path(csv_path)
    if not csv_path.exists() or not _SCRIPT.exists():
        return
    out_dir = csv_path.parent / f"{csv_path.stem}_report"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(_SCRIPT), "--flight", str(csv_path), "--out", str(out_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - spawn failure must never touch the flight loop
        return
    threading.Thread(target=_await_and_emit, args=(proc, csv_path, out_dir, manager, runs_root),
                     daemon=True).start()


def _await_and_emit(proc, csv_path: Path, out_dir: Path, manager, runs_root) -> None:
    try:
        proc.wait(timeout=180)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    headline: dict = {}
    summary = out_dir / "flight_summary.json"
    if summary.exists():
        try:
            headline = _headline(json.loads(summary.read_text()).get("metrics", {}))
        except Exception:  # noqa: BLE001
            headline = {}
    try:
        manager.emit({
            "type": "report",
            "csv": _rel(csv_path, runs_root),
            "out_dir": _rel(out_dir, runs_root),
            "metrics": headline,
        })
    except Exception:  # noqa: BLE001
        pass


def _num(x):
    """Coerce to a JSON-safe number, mapping NaN/inf (and non-numbers) to None (json.dumps would
    otherwise emit bare ``NaN``, which the browser's JSON.parse rejects)."""
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _headline(m: dict) -> dict:
    """The four numbers the Bench panel shows: hover tilt, vz-rail count, link p99, battery sag."""
    sh = m.get("stable_hover", {}) or {}
    hq = m.get("hover_quality", {}) or {}
    v = m.get("vertical", {}) or {}
    lk = m.get("link", {}) or {}
    bt = m.get("battery", {}) or {}
    tilt = sh.get("median_tilt_deg")
    if _num(tilt) is None:
        tilt = hq.get("median_tilt_deg")
    return {
        "median_tilt_deg": _num(tilt),
        "vz_rail_frames": _num(v.get("vz_rail_frames")),
        "link_p99_ms": _num(lk.get("p99_ms")),
        "battery_sag_v": _num(bt.get("sag_v")),
    }


def _rel(p, runs_root) -> str:
    p = Path(p)
    if runs_root is not None:
        try:
            return p.resolve().relative_to(Path(runs_root).resolve()).as_posix()
        except ValueError:
            pass
    return p.name
