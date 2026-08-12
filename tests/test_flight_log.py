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
    """One CSV row (current schema) with hover-ish defaults; override any column by name.

    ``tof_m``/``h_err``/``bridge_loop_max_ms``/``flow_*`` default blank — the synthetic baseline
    flight predates the bridge ToF, the loop-timing firmware and the flow sensor, so the legacy
    code paths (∫vz_est replay z, height.present=False) stay exercised.

    Unlisted columns default blank rather than raising, so appending a column to LOG_COLUMNS does
    not break every test in this file at once. The row is still built in LOG_COLUMNS order, so a
    genuine ordering change is still caught.
    """
    base = {
        "t": 0.0, "obs_age_ms": 25, "roll": 0.0, "pitch": 0.0, "p": 0.0, "q": 0.0, "r": 0.0,
        "a_thr": -0.50, "a_wx": 0.0, "a_wy": 0.0, "a_wz": 0.0,
        "us_roll": 1500, "us_pitch": 1500, "us_thr": _IDLE_US, "us_yaw": 1500,
        "vbat": 4.10, "hover_eff": 1330, "vz_est": 0.0, "trim": 0.0,
        "acc_x": 0, "acc_y": 0, "acc_z": 2048, "rpm_rms": 26000, "us_corr": 0, "tof_m": "",
        "h_err": "", "bridge_loop_max_ms": "",
    }
    base.update(over)
    return [base.get(c, "") for c in LOG_COLUMNS]


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


@pytest.mark.parametrize("width,label", [
    (24, "pre-ToF (through 2026-07): no tof_m/h_err/bridge_loop_max_ms/flow_*"),
    (25, "ToF-era, pre-h_err"),
    (26, "pre-bridge_loop_max_ms"),
    (27, "pre-flow: every real flight through 2026-08-11"),
    (31, "raw-flow: passive --log-flow counts, before the fused vx/vy channels"),
    (33, "pre-phase: the obs-8 rehearsal schema, before the controller phase column"),
])
def test_load_flight_accepts_legacy_schemas(tmp_path, width, label):
    """Every historical schema must still load, with the missing tail all-NaN.

    Widths are EXPLICIT, not `LOG_COLUMNS[:-n]`. The relative form silently re-aims at a
    different schema every time a column is appended — these three cases were written as
    [:-2]/[:-1] and had been testing 25/26 columns under the names "24col"/"25col" ever since
    bridge_loop_max_ms landed. The production `_LEGACY_HEADERS` had the identical bug, where it
    would have broken loading for all 27-column flights the moment flow was added.
    """
    p = tmp_path / f"legacy{width}.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS[:width])
        for i in range(4):
            w.writerow(_row(t=0.02 * i, us_thr=1300, tof_m=0.5)[:width])
    log = load_flight(p)
    assert log.n == 4, label
    for missing in LOG_COLUMNS[width:]:
        if missing == "phase":
            # `phase` is TEXT, so it is not in the numeric arrays at all. On a legacy log it is
            # absent entirely, and `log.phase` is the empty tuple — which is the signal every
            # consumer must check before trusting it (sim_vs_real falls back to grading all rows).
            assert missing not in log.data
            continue
        assert np.isnan(log.data[missing]).all(), f"{missing} should be NaN on a {width}-col log"
    assert log.phase == (), "a legacy log has no phase information"
    if width >= 25:
        assert (log.tof_m == 0.5).all()
    else:
        assert np.isnan(log.tof_m).all()
        assert flight_metrics(log)["height"]["present"] is False


def test_load_flight_reads_the_flow_columns(tmp_path):
    """The passive PMW3901 channels: raw counts + the bridge-measured interval + squal.

    Counts, deliberately, not a velocity — rad_per_count is what the calibration flight exists to
    measure, so a logged velocity would bake a placeholder into the record.
    """
    p = tmp_path / "flow.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        w.writerow(_row(t=0.00, us_thr=1300, flow_dx=120, flow_dy=-45,
                        flow_dt_s=0.0200, flow_squal=78))
        w.writerow(_row(t=0.02, us_thr=1300))  # no new sample this tick -> blank, NOT zero
    log = load_flight(p)
    assert log.data["flow_dx"][0] == 120 and log.data["flow_dy"][0] == -45
    assert log.data["flow_dt_s"][0] == 0.02 and log.data["flow_squal"][0] == 78
    # A tick with no sample must be NaN: a 0 would read as "measured, not moving".
    assert np.isnan(log.data["flow_dx"][1])


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


def test_pilot_and_analysis_schemas_match():
    """``scripts/pilot.py`` duplicates LOG_COLUMNS to stay pure-stdlib on the bench Mac. The
    duplication is deliberate; the drift was not.

    That copy sat at 26 entries from 2026-07-30 to 2026-08-12 while the controller emitted 27, so
    every flight in the window wrote a header describing fewer columns than its rows carried.
    Nothing failed — 26 is an accepted legacy width and the loader reads by index past the header
    — which is exactly why it went unnoticed for two weeks and eleven flights.
    """
    import importlib.util
    from pathlib import Path

    pilot_py = Path(__file__).resolve().parents[1] / "scripts" / "pilot.py"
    spec = importlib.util.spec_from_file_location("_pilot_schema_probe", pilot_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.LOG_COLUMNS == LOG_COLUMNS, (
        "scripts/pilot.py's inline LOG_COLUMNS has drifted from analysis/flight_log.py's.\n"
        f"  pilot:    {mod.LOG_COLUMNS}\n  analysis: {LOG_COLUMNS}"
    )
