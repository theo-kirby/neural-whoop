"""Pure flight-log load + metrics — the characterization core, unit-testable without the sim.

A ``scripts/pilot.py`` flight writes a 25-column CSV (:data:`LOG_COLUMNS`; 24-column pre-ToF
logs still load) — one row per control
step of a real tiny-whoop flight. This module parses that CSV into a :class:`FlightLog` (per-column
numpy arrays, empty cells -> NaN) and derives :func:`flight_metrics`: the phase segmentation, hover
quality, the vertical-estimator smoking-gun metrics (``vz_est`` railing + thrust-vs-``a_thr``
divergence), link latency percentiles, battery sag, and the open SIM2REAL props-on gyro amplitude.

Deliberately dependency-light (``csv`` + ``numpy``, both core): imports and unit-tests without
DiffAero, torch, or the ``viz`` extra — matching the repo's "pure modules tested without the
simulator" convention. The matplotlib renderers that draw these metrics live in
:mod:`neural_whoop.viz.render` behind the lazy ``viz`` extra; the CLI is ``scripts/flight_report.py``.

Background — why these metrics exist
------------------------------------
The first good flight of ``d50var_s8`` hovered near-perfectly for ~9 s (median tilt ~1.2 deg) then
hit the ceiling and tumbled. The root cause was NOT the policy: the pilot's accel-integrated
``vz_est`` drifted and **railed at its -2.0 m/s clamp** while the drone sat at ~1 deg tilt, so the
pilot's own altitude damper piled on thrust (``us_thr`` climbed while the policy's ``a_thr`` never
moved) -> climb -> ceiling contact. :func:`flight_metrics` measures exactly that signature
(``vertical.vz_rail_*`` + ``vertical.thrust_divergence``) so the documented follow-on RPM-anchor fix
can be proven from a later flight's pack.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: The pilot CSV schema (``scripts/pilot.py`` writer header) — the single source of truth for the
#: column order :func:`load_flight` expects. Angles (roll/pitch) are radians in sim convention;
#: body rates (p/q/r) rad/s; ``us_*`` are AETR microseconds; ``vz_est`` m/s; ``acc_*`` raw LSB;
#: ``tof_m`` the bridge's downward VL53L1X range in metres (empty when absent/invalid/stale —
#: the first *measured* height channel, everything before it is IMU-integrated estimate).
LOG_COLUMNS = [
    "t", "obs_age_ms", "roll", "pitch", "p", "q", "r",
    "a_thr", "a_wx", "a_wy", "a_wz", "us_roll", "us_pitch", "us_thr", "us_yaw",
    "vbat", "hover_eff", "vz_est", "trim", "acc_x", "acc_y", "acc_z",
    "rpm_rms", "us_corr", "tof_m",
]

#: Pre-ToF flights (through 2026-07) wrote 24 columns — everything up to ``us_corr``.
#: :func:`load_flight` still accepts them, padding ``tof_m`` with NaN.
_LEGACY_LOG_COLUMNS = LOG_COLUMNS[:-1]

#: The pilot's vertical-velocity estimate clamp (``scripts/pilot.py`` ``VZ_CLAMP``). A frame whose
#: ``|vz_est|`` reaches this is "railed" — the estimator has saturated and is lying about descent.
VZ_CLAMP = 2.0

#: Total tilt below this (degrees) counts as "stable hover" for phase segmentation. A healthy hover
#: sits ~1-2 deg; the departure/tumble blows past 45 deg, so any threshold in between segments
#: cleanly. Exposed as a :func:`flight_metrics` argument for flights with a looser hover.
STABLE_TILT_DEG = 8.0

#: A frame is "airborne" once ``us_thr`` rises this many microseconds above the idle floor (the
#: minimum ``us_thr`` seen, i.e. the countdown/waiting throttle). Below it the drone is on the
#: ground / in hand during the countdown.
AIRBORNE_US_OVER_IDLE = 60.0


@dataclass
class FlightLog:
    """A parsed pilot flight CSV: per-column float arrays (empty cells -> NaN) + derived timing.

    Access columns by name via :meth:`col` or the named convenience properties. All arrays share
    length :attr:`n` (the row count). ``t`` is the pilot's flight clock (seconds, 0 while it waits
    for the override switch), so leading rows can share ``t == 0``.
    """

    path: str
    data: dict[str, np.ndarray]

    @property
    def n(self) -> int:
        """Number of logged control steps (rows)."""
        return len(self.data["t"])

    def col(self, name: str) -> np.ndarray:
        """The named column as a float64 array (NaN where the CSV cell was empty)."""
        return self.data[name]

    # --- named convenience accessors (the columns the metrics/renderers reach for) ---
    @property
    def t(self) -> np.ndarray:
        return self.data["t"]

    @property
    def roll(self) -> np.ndarray:
        return self.data["roll"]

    @property
    def pitch(self) -> np.ndarray:
        return self.data["pitch"]

    @property
    def tilt_deg(self) -> np.ndarray:
        """Total tilt magnitude sqrt(roll^2 + pitch^2), in degrees (the headline quality signal)."""
        return np.degrees(np.hypot(self.data["roll"], self.data["pitch"]))

    @property
    def us_thr(self) -> np.ndarray:
        return self.data["us_thr"]

    @property
    def a_thr(self) -> np.ndarray:
        return self.data["a_thr"]

    @property
    def vz_est(self) -> np.ndarray:
        return self.data["vz_est"]

    @property
    def obs_age_ms(self) -> np.ndarray:
        return self.data["obs_age_ms"]

    @property
    def vbat(self) -> np.ndarray:
        return self.data["vbat"]

    @property
    def rpm_rms(self) -> np.ndarray:
        return self.data["rpm_rms"]

    @property
    def tof_m(self) -> np.ndarray:
        """Measured height (bridge VL53L1X, m); all-NaN on pre-ToF 24-column logs."""
        return self.data["tof_m"]

    @property
    def dt_median(self) -> float:
        """Median positive inter-step dt (s). Ignores the zero gaps of the pre-liftoff wait rows."""
        d = np.diff(self.t)
        pos = d[d > 0]
        return float(np.median(pos)) if pos.size else 0.0

    @property
    def control_hz(self) -> int:
        """Control rate rounded from :attr:`dt_median` (0 if timing is degenerate)."""
        dt = self.dt_median
        return int(round(1.0 / dt)) if dt > 0 else 0


def load_flight(path: str | Path) -> FlightLog:
    """Parse a pilot flight CSV into a :class:`FlightLog`.

    Validates the header against :data:`LOG_COLUMNS` (order matters), coerces every cell to
    float64, and maps the pre-liftoff empty cells (``vbat``/``hover_eff``/``vz_est``/``rpm_rms``/
    ``us_corr`` before telemetry/RPM come online) to NaN. Purely stdlib+numpy.

    Raises:
        ValueError: if the file is empty or its header does not match :data:`LOG_COLUMNS`.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path}: empty flight log (no header row)")
        if header not in (LOG_COLUMNS, _LEGACY_LOG_COLUMNS):
            raise ValueError(
                f"{path}: unexpected flight-log schema.\n  expected {LOG_COLUMNS}\n  got      {header}"
            )
        cols: list[list[float]] = [[] for _ in LOG_COLUMNS]
        for row in reader:
            if not row:
                continue
            # Pad short rows (defensive) so a truncated final line from a killed flight still loads.
            for i in range(len(LOG_COLUMNS)):
                cell = row[i].strip() if i < len(row) else ""
                cols[i].append(float(cell) if cell not in ("", "nan", "NaN") else float("nan"))
    data = {name: np.asarray(vals, dtype=np.float64) for name, vals in zip(LOG_COLUMNS, cols)}
    return FlightLog(path=str(path), data=data)


def _airborne_mask(log: FlightLog) -> np.ndarray:
    """Boolean per-frame mask: True once throttle has risen above the idle floor.

    Idle floor = the minimum commanded ``us_thr`` (the countdown/waiting throttle). A frame is
    airborne when ``us_thr`` exceeds it by :data:`AIRBORNE_US_OVER_IDLE`. Frames before the first
    airborne one stay False even if the throttle briefly dips later (the drone is up by then).
    """
    us = log.us_thr
    if not np.isfinite(us).any():
        return np.zeros(log.n, dtype=bool)
    idle = float(np.nanmin(us))
    up = np.nan_to_num(us, nan=idle) > idle + AIRBORNE_US_OVER_IDLE
    mask = np.zeros(log.n, dtype=bool)
    idx = np.flatnonzero(up)
    if idx.size:
        mask[idx[0]:] = True  # airborne from first throttle-up to end of flight
    return mask


def _longest_true_run(mask: np.ndarray) -> tuple[int, int]:
    """Return ``(start, stop)`` indices (half-open) of the longest contiguous True run in ``mask``.

    ``(0, 0)`` if there is no True frame.
    """
    best_start = best_stop = 0
    best_len = 0
    i = 0
    n = len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if j - i > best_len:
                best_len, best_start, best_stop = j - i, i, j
            i = j
        else:
            i += 1
    return best_start, best_stop


def _pct(x: np.ndarray, q: float) -> float:
    """Percentile of the finite entries of ``x`` (NaN if none)."""
    finite = x[np.isfinite(x)]
    return float(np.percentile(finite, q)) if finite.size else float("nan")


def _lag1_rho(x: np.ndarray) -> float:
    """Lag-1 autocorrelation of the finite entries of ``x`` (NaN if <2 samples or zero variance)."""
    finite = x[np.isfinite(x)]
    if finite.size < 2:
        return float("nan")
    a, b = finite[:-1], finite[1:]
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / denom) if denom > 0 else float("nan")


def flight_metrics(log: FlightLog, *, stable_tilt_deg: float = STABLE_TILT_DEG) -> dict[str, Any]:
    """Characterize a flight: phases, hover quality, the vertical smoking-gun, link, battery, DR.

    Args:
        log: A :class:`FlightLog` from :func:`load_flight`.
        stable_tilt_deg: Total-tilt threshold (deg) below which an airborne frame counts as stable
            hover (see :data:`STABLE_TILT_DEG`).

    Returns:
        A JSON-native dict (all plain ``float``/``int``/``bool``/``list``). Keys: ``n_frames``,
        ``duration_s``, ``control_hz``, ``dt_median_s``, ``phases``, ``stable_hover``,
        ``hover_quality``, ``vertical``, ``link``, ``battery``, ``sim2real``, ``height``. Metrics degrade to
        ``NaN``/empty rather than raising when a section has no data (e.g. a flight that never lifts).
    """
    n = log.n
    t = log.t
    airborne = _airborne_mask(log)
    a_idx = np.flatnonzero(airborne)
    tilt = log.tilt_deg

    # --- phases: pre-liftoff / airborne, and the stable-hover window inside airborne ---
    if a_idx.size:
        air_start, air_stop = int(a_idx[0]), int(a_idx[-1]) + 1
        air_t0, air_t1 = float(t[air_start]), float(t[air_stop - 1])
    else:
        air_start = air_stop = 0
        air_t0 = air_t1 = float("nan")

    stable_mask = airborne & (tilt < stable_tilt_deg) & np.isfinite(tilt)
    hov_start, hov_stop = _longest_true_run(stable_mask)
    hov_tilt = tilt[hov_start:hov_stop]

    phases = {
        "pre_liftoff": {
            "frames": air_start,
            "t_end": float(t[air_start]) if air_start > 0 and n else air_t0,
        },
        "airborne": {
            "frames": int(airborne.sum()),
            "t_start": air_t0,
            "t_end": air_t1,
            "duration_s": (air_t1 - air_t0) if a_idx.size else float("nan"),
        },
    }

    stable_hover = {
        "t_start": float(t[hov_start]) if hov_stop > hov_start else float("nan"),
        "t_end": float(t[hov_stop - 1]) if hov_stop > hov_start else float("nan"),
        "duration_s": (float(t[hov_stop - 1]) - float(t[hov_start]))
        if hov_stop > hov_start else float("nan"),
        "frames": int(hov_stop - hov_start),
        "median_tilt_deg": float(np.median(hov_tilt)) if hov_tilt.size else float("nan"),
        "p90_tilt_deg": float(np.percentile(hov_tilt, 90)) if hov_tilt.size else float("nan"),
    }

    air_tilt = tilt[airborne]
    hover_quality = {
        "median_tilt_deg": float(np.median(air_tilt)) if air_tilt.size else float("nan"),
        "p90_tilt_deg": float(np.percentile(air_tilt, 90)) if air_tilt.size else float("nan"),
    }

    # --- vertical: vz_est railing + thrust-vs-a_thr divergence (the exoneration signature) ---
    vz = log.vz_est
    railed = np.isfinite(vz) & (np.abs(vz) >= VZ_CLAMP - 1e-6)
    rail_idx = np.flatnonzero(railed)
    vz_finite = vz[np.isfinite(vz)]

    # Divergence measured over the stable-hover window (policy happy, a_thr should be flat): if
    # us_thr climbs while a_thr barely moves, the thrust rise came from the pilot's altitude damper,
    # NOT the policy. Compare the first vs last few frames' mean us_thr against the a_thr spread.
    us = log.us_thr
    ath = log.a_thr
    win = slice(hov_start, hov_stop)
    us_win = us[win][np.isfinite(us[win])]
    ath_win = ath[win][np.isfinite(ath[win])]
    edge = max(1, min(len(us_win) // 5, 10)) if us_win.size else 0
    if us_win.size >= 2:
        us_rise = float(us_win[-edge:].mean() - us_win[:edge].mean())
    else:
        us_rise = float("nan")
    ath_iqr = float(np.subtract(*np.percentile(ath_win, [75, 25]))) if ath_win.size else float("nan")
    diverged = bool(
        np.isfinite(us_rise) and np.isfinite(ath_iqr) and us_rise > 40.0 and ath_iqr < 0.05
    )
    vertical = {
        "vz_clamp": VZ_CLAMP,
        "vz_rail_frames": int(rail_idx.size),
        "vz_rail_frac": float(rail_idx.size / airborne.sum()) if airborne.any() else float("nan"),
        "vz_first_rail_t": float(t[rail_idx[0]]) if rail_idx.size else None,
        "vz_min": float(vz_finite.min()) if vz_finite.size else float("nan"),
        "vz_max": float(vz_finite.max()) if vz_finite.size else float("nan"),
        "thrust_divergence": {
            "detected": diverged,
            "us_thr_rise": us_rise,          # us climb across the stable-hover window
            "a_thr_iqr": ath_iqr,            # policy thrust spread (near 0 == steady == exonerated)
            "us_thr_start": float(us_win[:edge].mean()) if us_win.size else float("nan"),
            "us_thr_end": float(us_win[-edge:].mean()) if us_win.size else float("nan"),
            "a_thr_median": float(np.median(ath_win)) if ath_win.size else float("nan"),
        },
    }

    # --- link latency: obs_age percentiles + the 40 ms cliff / 100 ms tail ---
    age = log.obs_age_ms
    age_f = age[np.isfinite(age)]
    counts, edges = (np.histogram(age_f, bins=20) if age_f.size else (np.array([]), np.array([])))
    link = {
        "median_ms": _pct(age, 50),
        "p90_ms": _pct(age, 90),
        "p99_ms": _pct(age, 99),
        "max_ms": float(age_f.max()) if age_f.size else float("nan"),
        "frac_over_40ms": float((age_f > 40).mean()) if age_f.size else float("nan"),
        "frac_over_100ms": float((age_f > 100).mean()) if age_f.size else float("nan"),
        "histogram": {
            "edges": [float(e) for e in edges],
            "counts": [int(c) for c in counts],
        },
    }

    # --- battery: v0 / min / sag, plus the mean voltage during the stable-hover window ---
    vb = log.vbat
    vb_f = vb[np.isfinite(vb)]
    vb_hov = vb[win][np.isfinite(vb[win])]
    battery = {
        "v0": float(vb_f[0]) if vb_f.size else float("nan"),
        "v_min": float(vb_f.min()) if vb_f.size else float("nan"),
        "sag_v": float(vb_f[0] - vb_f.min()) if vb_f.size else float("nan"),
        "hover_window_v_mean": float(vb_hov.mean()) if vb_hov.size else float("nan"),
    }

    # --- open SIM2REAL item: props-on gyro amplitude (sd) + lag-1 rho in stable hover ---
    def _gyro_stats(name: str) -> dict[str, float]:
        g = log.data[name][win]
        gf = g[np.isfinite(g)]
        return {"sd_rps": float(gf.std()) if gf.size else float("nan"), "lag1_rho": _lag1_rho(g)}

    sim2real = {
        "props_on_gyro": {axis: _gyro_stats(axis) for axis in ("p", "q", "r")},
        "note": "props-on gyro sd/rho measured in the stable-hover window (motors loaded, level).",
    }

    # --- measured height (bridge VL53L1X): the first non-integrated altitude channel.
    # hover_* over the stable-hover window is the real height-hold number; coverage says how
    # much of the airborne time the sensor actually returned valid range (dropout diagnostic).
    tof = log.tof_m
    tof_air = tof[airborne][np.isfinite(tof[airborne])]
    tof_hov = tof[win][np.isfinite(tof[win])]
    height = {
        "present": bool(np.isfinite(tof).any()),
        "coverage_airborne": float(np.isfinite(tof[airborne]).mean()) if airborne.any() else float("nan"),
        "hover_mean_m": float(tof_hov.mean()) if tof_hov.size else float("nan"),
        "hover_sd_m": float(tof_hov.std()) if tof_hov.size else float("nan"),
        "max_m": float(tof_air.max()) if tof_air.size else float("nan"),
    }

    return {
        "n_frames": n,
        "duration_s": float(t[-1] - t[0]) if n else float("nan"),
        "control_hz": log.control_hz,
        "dt_median_s": log.dt_median,
        "stable_tilt_deg": float(stable_tilt_deg),
        "phases": phases,
        "stable_hover": stable_hover,
        "hover_quality": hover_quality,
        "vertical": vertical,
        "link": link,
        "battery": battery,
        "sim2real": sim2real,
        "height": height,
    }
