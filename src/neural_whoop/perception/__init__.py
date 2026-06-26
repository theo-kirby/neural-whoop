"""Perception front-end: the swappable seam that produces the body-frame target vector.

Primary training stays **render-free** via :class:`~neural_whoop.perception.estimator.OracleEstimator`
(the validated trick ported from neural-whoop-lab): the env hands the policy the ground-truth
target-relative vector, optionally corrupted by a batched detector-error model so the flight
policy learns to survive real detection noise without rendering a single pixel. Honest
camera-only evaluation later swaps in DiffAero's depth render (works on Blackwell); photoreal
RGB / Isaac Lab is a deferred Flywheel branch.
"""

from neural_whoop.perception.estimator import (
    DetectorNoise,
    OracleEstimator,
    apply_detector_noise,
)

__all__ = ["OracleEstimator", "DetectorNoise", "apply_detector_noise"]
