"""Unit tests for the RPM-anchored altitude damper in ``scripts/pilot.py`` (the vz-rail fix).

Background: the ``d50var_s8_f1`` first flight hovered near-perfectly for ~9 s, then the pilot's
accel-integrated ``vz_est`` drifted and RAILED at its -2.0 m/s clamp while the drone sat level, so
the old altitude damper piled on thrust and flew it into the ceiling (docs/SIM2REAL.md, Flywheel
``royal-bar-2003``). The fix replaces that drift-prone integral with a driftless RPM-anchored
climb rate: hover RPM (learned at breakaway = weight) is constant, so ``(rpm/rpm_hover)**2 - 1`` is
the measured net thrust-over-weight fraction and the damper is a bounded *proportional* term with
NO integrator — it cannot rail.

These are pure-math tests (``scripts/pilot.py`` is dependency-free stdlib): no MSP link, no sim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; pilot.py is a stdlib-only script (import is side-effect-free — the
# entrypoint is behind ``if __name__ == "__main__"``).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pilot  # noqa: E402

HOVER = 26000.0  # ~the d50var_s8_f1 breakaway RMS RPM (bidir-DShot, healthy)


# --- rpm_climb_rate: the driftless climb-rate estimate ----------------------------------------

def test_climb_rate_zero_at_hover():
    """rpm == rpm_hover is by construction net-zero thrust -> exactly 0 climb (no bias)."""
    assert pilot.rpm_climb_rate(HOVER, HOVER) == 0.0


def test_climb_rate_sign():
    """Above hover RPM = climbing (positive); below = sinking (negative)."""
    assert pilot.rpm_climb_rate(HOVER * 1.1, HOVER) > 0.0
    assert pilot.rpm_climb_rate(HOVER * 0.9, HOVER) < 0.0


def test_climb_rate_monotonic_in_rpm():
    """Strictly increasing in current RPM (thrust ~ rpm^2)."""
    rates = [pilot.rpm_climb_rate(HOVER * f, HOVER) for f in (0.8, 0.9, 1.0, 1.1, 1.2)]
    assert all(b > a for a, b in zip(rates, rates[1:]))


def test_climb_rate_matches_formula():
    """(rpm/rpm_hover)^2 - 1, times g, times the aero time constant."""
    got = pilot.rpm_climb_rate(HOVER * 1.1, HOVER)
    expect = (1.1**2 - 1.0) * 9.81 * pilot.VZ_AERO_TAU
    assert got == pytest.approx(expect)


def test_climb_rate_no_anchor_or_no_rpm_is_zero():
    """Before breakaway (no anchor) or bidir-DShot off (no RPM) -> inert 0.0, not a crash."""
    assert pilot.rpm_climb_rate(HOVER, None) == 0.0
    assert pilot.rpm_climb_rate(None, HOVER) == 0.0
    assert pilot.rpm_climb_rate(None, None) == 0.0
    assert pilot.rpm_climb_rate(0.0, HOVER) == 0.0        # falsy current RPM
    assert pilot.rpm_climb_rate(HOVER, 0.0) == 0.0        # falsy anchor: no div-by-zero


def test_climb_rate_small_in_normal_hover():
    """Across the RPM excursions of a real hover (+-20%) the estimate stays well inside the -2 m/s
    clamp — so the logged vz_est never spuriously trips flight_metrics' rail check during hover
    (the accel integral, by contrast, drifted to the rail while RPM sat at hover)."""
    for f in [x / 100 for x in range(80, 121)]:           # 0.8x .. 1.2x rpm_hover
        assert abs(pilot.rpm_climb_rate(HOVER * f, HOVER)) < pilot.VZ_CLAMP


# --- rpm_damper_trim: the proportional thrust trim (the actual control output) -----------------

def test_damper_zero_at_hover():
    """The regression guard: a level drone at hover RPM gets EXACTLY zero trim — no pile-on."""
    assert pilot.rpm_damper_trim(HOVER, HOVER, vz_gain=0.15) == 0.0


def test_damper_opposes_climb():
    """Climbing -> negative trim (pull thrust back); sinking -> positive trim (add thrust)."""
    assert pilot.rpm_damper_trim(HOVER * 1.1, HOVER, vz_gain=0.15) < 0.0
    assert pilot.rpm_damper_trim(HOVER * 0.9, HOVER, vz_gain=0.15) > 0.0


def test_damper_gain_zero_disables():
    assert pilot.rpm_damper_trim(HOVER * 1.2, HOVER, vz_gain=0.0) == 0.0


def test_damper_no_anchor_is_zero():
    assert pilot.rpm_damper_trim(HOVER, None, vz_gain=0.15) == 0.0
    assert pilot.rpm_damper_trim(None, HOVER, vz_gain=0.15) == 0.0


def test_damper_clamped_to_cap():
    """Even a wild RPM excursion cannot exceed the trim authority cap (bounded output)."""
    hot = pilot.rpm_damper_trim(HOVER * 3.0, HOVER, vz_gain=10.0)
    cold = pilot.rpm_damper_trim(HOVER * 0.2, HOVER, vz_gain=10.0)
    assert hot == pytest.approx(-pilot.VZ_TRIM_CAP)
    assert cold == pytest.approx(pilot.VZ_TRIM_CAP)


def test_damper_cannot_rail_across_full_range():
    """The core fix invariant: for ANY RPM the trim is finite and within the cap. There is no
    integrator to wind up, so the -2.0 m/s vz rail that piled +203 us of phantom thrust
    (d50var_s8_f1) cannot recur."""
    for f in [x / 100 for x in range(1, 400)]:            # 0.01x .. 4.0x rpm_hover
        trim = pilot.rpm_damper_trim(HOVER * f, HOVER, vz_gain=0.15)
        assert -pilot.VZ_TRIM_CAP - 1e-9 <= trim <= pilot.VZ_TRIM_CAP + 1e-9


def test_damper_is_stateless_no_accumulation():
    """Statelessness IS the anti-drift property: hovering at hover RPM for arbitrarily long
    yields the same 0 trim every frame — unlike the old accel integrator that accumulated a DC
    bias into the rail. Repeated identical inputs give an identical (zero) output."""
    trims = [pilot.rpm_damper_trim(HOVER, HOVER, vz_gain=0.15) for _ in range(1000)]
    assert set(trims) == {0.0}


def test_damper_independent_of_any_vz():
    """The trim is a function of the RPM ratio ONLY — there is no vz/accel input, so a phantom
    accel-integrated vz (the failure signal) can no longer influence the command."""
    import inspect
    params = inspect.signature(pilot.rpm_damper_trim).parameters
    assert "vz" not in params and "vz_est" not in params
    # Same RPM ratio -> same trim regardless of the absolute RPM scale (anchor-relative).
    a = pilot.rpm_damper_trim(20000 * 1.1, 20000, vz_gain=0.15)
    b = pilot.rpm_damper_trim(30000 * 1.1, 30000, vz_gain=0.15)
    assert a == pytest.approx(b)
