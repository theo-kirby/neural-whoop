"""The offboard-pilot flight engine — pure-stdlib (zero torch/numpy).

Extracted from the old monolithic ``scripts/pilot.py`` so the same control code drives both the CLI
(``scripts/pilot.py``, now a thin shim) and the always-on web dashboard
(:mod:`neural_whoop.studio.flight`). The public surface is re-exported here (and every ``config``
constant), so ``from neural_whoop.pilot import ...`` reaches the policy, telemetry, controller, and
tuning constants in one import.
"""

from __future__ import annotations

from .config import *  # noqa: F401,F403 - re-export every tuning constant (single source of truth)
from .config import (
    DEFAULT_WEIGHTS,
    VZ_AERO_TAU,
    VZ_CLAMP,
    VZ_TRIM_CAP,
)
from .controller import (
    FlightController,
    FlightParams,
    FlightSetupError,
    Phase,
)
from .policy import (
    Policy,
    action_to_us,
    check_policy_family,
    check_policy_family_acro,
    obs_from_msp,
    obs_from_msp_acro,
    rpm_climb_rate,
    rpm_damper_trim,
    stack_frames,
)
from .telemetry import Telemetry, stream_rc

__all__ = [
    "DEFAULT_WEIGHTS",
    "VZ_AERO_TAU",
    "VZ_CLAMP",
    "VZ_TRIM_CAP",
    "FlightController",
    "FlightParams",
    "FlightSetupError",
    "Phase",
    "Policy",
    "Telemetry",
    "action_to_us",
    "check_policy_family",
    "check_policy_family_acro",
    "obs_from_msp",
    "obs_from_msp_acro",
    "rpm_climb_rate",
    "rpm_damper_trim",
    "stack_frames",
    "stream_rc",
]
