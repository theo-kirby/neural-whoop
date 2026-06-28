"""Pure flyability validation for authored Studio courses — no torch, no sim.

The web course editor needs to tell a user *before* they save (or fly) whether a course is sane:
gates inside the arena, sensible heights, not an impossible zig-zag. This module answers that from
geometry alone, reusing :class:`neural_whoop.course.ArenaSpec` as the **single source of truth**
for the bounds (so the editor, the validator, and ``random_courses`` all agree). It is consumed by
``POST /api/courses/validate`` + :func:`neural_whoop.studio.courses.save_course`, and unit-tested
without any sim extra. Ported from ``neural-whoop-lab``'s ``envs/course_validate.py``, adapted to
work on a plain ``[{pos:[x,y,z], radius}]`` gate list (no ``Course`` class).

Severity model:

- **error**  — the course can't be flown / placed as-is (no gates, non-positive radius, a gate
  outside the arena radius, a gate height outside the band). ``ok`` is False if any present.
- **warning** — flyable but suspect (an inter-gate spacing outside ``[step_min, step_max]``).
  These don't flip ``ok``. (Sharp-turn warnings are intentionally absent — omnidirectional sphere
  gates are threadable from any direction, so a tight turn isn't a flyability concern.)
"""

from __future__ import annotations

import math
from typing import Any

from neural_whoop.course import ArenaSpec


def _issue(level: str, gate_index: int, code: str, message: str) -> dict[str, Any]:
    """A single validation finding (``level`` ∈ ``{"error","warning"}``; ``gate_index`` -1 = course-level)."""
    return {"level": level, "gate_index": gate_index, "code": code, "message": message}


def validate_gates(gates: list[dict], arena: ArenaSpec | None = None) -> dict[str, Any]:
    """Validate a gate list against arena/flyability bounds.

    Pure and deterministic — geometry only, no simulation. ``gates`` is a list of
    ``{"pos": [x, y, z], "radius": r}`` dicts; ``arena`` supplies the bounds (defaults to the
    tight :class:`ArenaSpec`, the same spec procedural courses are generated within).

    Returns ``{"ok": bool, "issues": [{level, gate_index, code, message}, ...]}``; ``ok`` is
    False iff any error-level issue exists.
    """
    arena = arena or ArenaSpec()
    issues: list[dict] = []

    if not gates:
        return {"ok": False, "issues": [_issue("error", -1, "no_gates", "Course has no gates.")]}

    centers: list[tuple[float, float, float]] = []
    for i, gate in enumerate(gates):
        pos = gate.get("pos", [0.0, 0.0, 0.0])
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        radius = float(gate.get("radius", arena.gate_radius))
        centers.append((x, y, z))

        if radius <= 0.0:
            issues.append(_issue(
                "error", i, "non_positive_radius",
                f"Gate {i} radius must be > 0 (got {radius:.3f}).",
            ))

        xy_norm = math.hypot(x, y)
        if xy_norm > arena.radius:
            issues.append(_issue(
                "error", i, "gate_outside_arena",
                f"Gate {i} is {xy_norm:.2f} m from origin, beyond arena radius {arena.radius:.2f} m.",
            ))

        if z < arena.z_min or z > arena.z_max:
            issues.append(_issue(
                "error", i, "gate_height_out_of_band",
                f"Gate {i} height {z:.2f} m is outside the band "
                f"[{arena.z_min:.2f}, {arena.z_max:.2f}] m.",
            ))

    # Pairwise (warning-level) spacing checks between consecutive gates. (Sharp-turn warnings are
    # intentionally dropped: with omnidirectional spheres a tight turn is flyable.)
    for i in range(1, len(centers)):
        step = math.hypot(centers[i][0] - centers[i - 1][0], centers[i][1] - centers[i - 1][1])
        if step < arena.step_min or step > arena.step_max:
            issues.append(_issue(
                "warning", i, "spacing_out_of_range",
                f"Gates {i - 1}->{i} are {step:.2f} m apart, outside the typical "
                f"[{arena.step_min:.2f}, {arena.step_max:.2f}] m spacing.",
            ))

    ok = not any(it["level"] == "error" for it in issues)
    return {"ok": ok, "issues": issues}
