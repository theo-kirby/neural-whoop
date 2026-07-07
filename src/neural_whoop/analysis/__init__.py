"""Flight-log analysis — pure (stdlib + numpy) characterization of real pilot flights.

Turns a raw ``scripts/pilot.py`` flight CSV into a durable metrics dict + phase segmentation,
with no simulator, torch, or viz dependency (the renderers live behind the lazy ``viz`` extra in
:mod:`neural_whoop.viz.render`). This is the load+metrics core the ``scripts/flight_report.py``
CLI orchestrates into a Flywheel-native analysis pack. See :mod:`neural_whoop.analysis.flight_log`.
"""

from neural_whoop.analysis.flight_log import (
    FlightLog,
    LOG_COLUMNS,
    VZ_CLAMP,
    flight_metrics,
    load_flight,
)

__all__ = ["FlightLog", "LOG_COLUMNS", "VZ_CLAMP", "flight_metrics", "load_flight"]
