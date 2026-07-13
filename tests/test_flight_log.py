"""Pure unit tests for the flight-log analysis core (no simulator / torch / viz extra).

Covers :func:`load_flight` (schema validation + pre-liftoff empty-cell -> NaN coercion),
:func:`flight_metrics` (phase split, vz_est rail detection, thrust-vs-a_thr divergence, obs_age
percentiles) on a hand-built synthetic flight, and :func:`flight_to_replay` (schema validity +
real-flight extras landing in the additive ``scene`` channel). Pure stdlib + numpy — follows the
repo's "pure modules tested without the simulator" convention.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from neural_whoop.analysis.flight_log import (
    LOG_COLUMNS,
    VZ_CLAMP,
    flight_metrics,
    load_flight,
)
from neural_whoop.viz.replay import (
    REPLAY_FORMAT,
    _FLIGHT_SCENE_EXTRAS,
    flight_to_replay,
    load_run,
)

# --- synthetic flight: 3 pre-liftoff (idle) + 10 stable-hover + 4 tumble rows ------------------
_IDLE_US = 1000

# obs_age pattern per row (ms) — drives the link-percentile assertions.
_AGE = [25, 0, 22,                                   # pre-liftoff
        20, 30, 45, 50, 25, 35, 60, 120, 40, 30,     # stable hover
        40, 50, 200, 80]                             # tumble
# vz_est for the 10 stable rows: drifts down and rails at the -2.0 clamp for the last 3.
_VZ_STABLE = [0.0, -0.3, -0.6, -0.9, -1.2, -1.5, -1.8, -2.0, -2.0, -2.0]


def _row(**over) -> list:
    """One CSV row (26 cols) with hover-ish defaults; override any column by name.

    ``tof_m``/``h_err`` default blank — the synthetic baseline flight predates the bridge ToF,
    so the legacy code paths (∫vz_est replay z, height.present=False) stay exercised.
    """
    base = {
        "t": 0.0, "obs_age_ms": 25, "roll": 0.0, "pitch": 0.0, "p": 0.0, "q": 0.0, "r": 0.0,
        "a_thr": -0.50, "a_wx": 0.0, "a_wy": 0.0, "a_wz": 0.0,
        "us_roll": 1500, "us_pitch": 1500, "us_thr": _IDLE_US, "us_yaw": 1500,
        "vbat": 4.10, "hover_eff": 1330, "vz_est": 0.0, "trim": 0.0,
        "acc_x": 0, "acc_y": 0, "acc_z": 2048, "rpm_rms": 26000, "us_corr": 0, "tof_m": "",
        "h_err": "",
    }
    base.update(over)
    return [base[c] for c in LOG_COLUMNS]


def _write_flight(path) -> None:
    rows = []
    # pre-liftoff: idle throttle, telemetry not yet online (vz_est/rpm_rms/us_corr blank).
    for i in range(3):
        rows.append(_row(t=0.0, obs_age_ms=_AGE[i], us_thr=_IDLE_US,
                         vz_est="", rpm_rms="", us_corr=""))
    # stable hover: throttle climbs 1200->1390 while a_thr stays pinned (-> divergence),
    # tilt ~1.6 deg (roll=pitch=0.02 rad), vz_est drifts to the rail.
    for i in range(10):
        us = 1200 + round((1390 - 1200) * i / 9)
        rows.append(_row(t=0.02 * (i + 1), obs_age_ms=_AGE[3 + i], roll=0.02, pitch=0.02,
                         a_thr=-0.50, us_thr=us, vz_est=_VZ_STABLE[i],
                         vbat=round(4.05 - 0.01 * i, 3)))
    # tumble: huge tilt, a_thr swings.
    for i in range(4):
        rows.append(_row(t=0.02 * (11 + i), obs_age_ms=_AGE[13 + i], roll=1.5, pitch=-0.8,
                         a_thr=-0.2 + 0.1 * i, us_thr=1450, vz_est=-1.0))
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        w.writerows(rows)


@pytest.fixture
def flight_csv(tmp_path):
    p = tmp_path / "synthetic_flight.csv"
    _write_flight(p)
    return p


# --- load_flight -------------------------------------------------------------------------------
def test_load_flight_shape_and_empty_cell_coercion(flight_csv):
    log = load_flight(flight_csv)
    assert log.n == 17
    # pre-liftoff blanks coerce to NaN; filled cells are real floats.
    assert np.isnan(log.vz_est[0]) and np.isnan(log.vz_est[1]) and np.isnan(log.vz_est[2])
    assert np.isnan(log.rpm_rms[0])
    assert log.vz_est[3] == 0.0                # first stable row is a real 0.0, not blank
    assert log.us_thr[0] == _IDLE_US
    assert log.control_hz == 50                # dt_median = 0.02


def test_load_flight_accepts_legacy_24col(tmp_path):
    # Pre-ToF flights wrote 24 columns (no tof_m/h_err): they must still load, all-NaN tails.
    p = tmp_path / "legacy.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS[:-2])
        for i in range(4):
            w.writerow(_row(t=0.02 * i, us_thr=1300)[:-2])
    log = load_flight(p)
    assert log.n == 4
    assert np.isnan(log.tof_m).all()
    m = flight_metrics(log)
    assert m["height"]["present"] is False


def test_load_flight_accepts_legacy_25col(tmp_path):
    # ToF-era pre-h_err flights wrote 25 columns: still load, h_err all-NaN.
    p = tmp_path / "legacy25.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS[:-1])
        for i in range(4):
            w.writerow(_row(t=0.02 * i, us_thr=1300, tof_m=0.5)[:-1])
    log = load_flight(p)
    assert log.n == 4
    assert np.isnan(log.data["h_err"]).all()
    assert (log.tof_m == 0.5).all()


def test_load_flight_rejects_bad_header(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="schema"):
        load_flight(p)


def test_load_flight_rejects_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("")
    with pytest.raises(ValueError, match="empty"):
        load_flight(p)


# --- flight_metrics ----------------------------------------------------------------------------
def test_phase_split(flight_csv):
    m = flight_metrics(load_flight(flight_csv))
    # 3 idle rows before the first throttle-up -> airborne from row 3.
    assert m["phases"]["pre_liftoff"]["frames"] == 3
    assert m["phases"]["airborne"]["frames"] == 14
    # longest stable-hover run = the 10 low-tilt airborne rows (tumble excluded by tilt).
    sh = m["stable_hover"]
    assert sh["frames"] == 10
    assert sh["median_tilt_deg"] == pytest.approx(np.degrees(np.hypot(0.02, 0.02)), rel=1e-3)


def test_vz_rail_detection(flight_csv):
    m = flight_metrics(load_flight(flight_csv))
    v = m["vertical"]
    assert v["vz_clamp"] == VZ_CLAMP
    assert v["vz_rail_frames"] == 3            # the three -2.0 stable rows
    # first rail is stable row index 7 -> t = 0.02 * 8.
    assert v["vz_first_rail_t"] == pytest.approx(0.16, abs=1e-6)
    assert v["vz_min"] == pytest.approx(-2.0)


def test_thrust_divergence(flight_csv):
    m = flight_metrics(load_flight(flight_csv))
    div = m["vertical"]["thrust_divergence"]
    assert div["detected"] is True
    assert div["us_thr_rise"] > 40.0           # throttle climbed across the hover window
    assert div["a_thr_iqr"] < 0.05             # while the policy's thrust stayed flat
    assert div["a_thr_median"] == pytest.approx(-0.50, abs=1e-6)


def test_link_percentiles(flight_csv):
    m = flight_metrics(load_flight(flight_csv))
    lk = m["link"]
    ages = np.array(_AGE, dtype=float)
    assert lk["median_ms"] == pytest.approx(np.percentile(ages, 50))
    assert lk["p99_ms"] == pytest.approx(np.percentile(ages, 99))
    assert lk["frac_over_40ms"] == pytest.approx((ages > 40).mean())
    assert lk["frac_over_100ms"] == pytest.approx((ages > 100).mean())
    assert lk["p99_ms"] >= lk["median_ms"]


def test_battery_sag(flight_csv):
    m = flight_metrics(load_flight(flight_csv))
    bt = m["battery"]
    assert bt["v0"] == pytest.approx(4.10)
    assert bt["v_min"] <= bt["v0"]
    assert bt["sag_v"] == pytest.approx(bt["v0"] - bt["v_min"])


def test_metrics_never_raise_on_never_lifted(tmp_path):
    # A flight that never leaves idle: metrics degrade to NaN/empty, no exceptions.
    p = tmp_path / "ground.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        for _ in range(5):
            w.writerow(_row(us_thr=_IDLE_US))
    m = flight_metrics(load_flight(p))
    assert m["phases"]["airborne"]["frames"] == 0
    assert m["stable_hover"]["frames"] == 0
    assert m["vertical"]["vz_first_rail_t"] is None


def test_height_metrics_from_tof(tmp_path):
    # A ToF-equipped flight: measured height drives the metrics' height block.
    p = tmp_path / "tof_flight.csv"
    heights = [0.50, 0.55, 0.60, 0.55, 0.50, 0.52, 0.58, 0.54, 0.51, 0.55]
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        for i in range(3):
            w.writerow(_row(t=0.0, us_thr=_IDLE_US, tof_m=0.03))
        for i, h in enumerate(heights):  # stable hover with a real height signal (one dropout)
            w.writerow(_row(t=0.02 * (i + 1), roll=0.02, pitch=0.02, us_thr=1350,
                            tof_m=h if i != 4 else ""))
    m = flight_metrics(load_flight(p))
    hm = m["height"]
    assert hm["present"] is True
    valid = [h for i, h in enumerate(heights) if i != 4]
    assert hm["hover_mean_m"] == pytest.approx(np.mean(valid), rel=1e-6)
    assert hm["max_m"] == pytest.approx(max(valid))
    assert hm["coverage_airborne"] == pytest.approx(9 / 10)


# --- flight_to_replay --------------------------------------------------------------------------
def test_flight_to_replay_schema_and_extras(flight_csv):
    log = load_flight(flight_csv)
    doc = flight_to_replay(log, policy="test policy")
    assert doc["format"] == REPLAY_FORMAT
    meta = doc["meta"]
    assert meta["task"] == "hover_blind"
    assert meta["pos_is_stub"] is True
    assert meta["control_hz"] == 50
    ep = doc["episodes"][0]
    assert len(ep["frames"]) == log.n
    fr = ep["frames"][5]
    assert len(fr["obs"]) == 5 and len(fr["action"]) == 4
    # the real-flight extras land in the additive scene channel, as scalars.
    assert set(_FLIGHT_SCENE_EXTRAS).issubset(fr["scene"].keys())
    assert all(isinstance(fr["scene"][k], float) for k in _FLIGHT_SCENE_EXTRAS)
    # pos is the vertical-only stub: x = y = 0, z is the vz integral (no ToF in this flight).
    assert fr["pos"][0] == 0.0 and fr["pos"][1] == 0.0
    assert meta["pos_z_measured"] is False


def test_flight_to_replay_measured_z_from_tof(tmp_path):
    # With tof_m samples in the log, replay z is the measured height (gaps interpolated).
    p = tmp_path / "tof_flight.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        w.writerow(_row(t=0.02, us_thr=1350, tof_m=0.40))
        w.writerow(_row(t=0.04, us_thr=1350, tof_m=""))      # dropout: interpolated
        w.writerow(_row(t=0.06, us_thr=1350, tof_m=0.60))
    doc = flight_to_replay(load_flight(p))
    assert doc["meta"]["pos_z_measured"] is True
    zs = [f["pos"][2] for f in doc["episodes"][0]["frames"]]
    assert zs == pytest.approx([0.40, 0.50, 0.60])
    assert doc["episodes"][0]["frames"][0]["scene"]["tof_m"] == pytest.approx(0.40)


def test_flight_to_replay_roundtrips_through_gzip(flight_csv, tmp_path):
    import gzip
    import json

    doc = flight_to_replay(load_flight(flight_csv))
    out = tmp_path / "replay.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    reloaded = load_run(out)
    assert reloaded["meta"]["source"] == "pilot-flight"
    assert len(reloaded["episodes"][0]["frames"]) == len(doc["episodes"][0]["frames"])
