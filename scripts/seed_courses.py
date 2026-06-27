#!/usr/bin/env python
"""Seed a handful of shareable fixed courses under assets/courses/ from the arena presets.

    uv run python scripts/seed_courses.py            # writes assets/courses/*.yaml (idempotent)

A one-shot generator: each entry draws one deterministic random course (fixed seed) from a named
:data:`neural_whoop.course.ARENA_PRESETS` arena, so the repo ships bigger, more spread-out base
courses than the default tight indoor track. Saved in the ``{name, gates: [{pos, radius}]}`` schema
the Studio (and ``env.fixed_course``) consume.
"""

from __future__ import annotations

from pathlib import Path

import torch

from neural_whoop import course as course_mod
from neural_whoop.studio import courses as courses_mod

# (filename, preset, n_gates, seed) — a small curated spread of sizes/lengths.
SEED_COURSES = [
    ("spread-a", "spread", 6, 1),
    ("spread-b", "spread", 7, 7),
    ("big-loop", "big", 6, 3),
    ("big-sprint", "big", 8, 11),
    ("giant-circuit", "giant", 8, 5),
]


def main() -> int:
    out_dir = Path(__file__).resolve().parents[1] / "assets" / "courses"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, preset, n_gates, seed in SEED_COURSES:
        arena = course_mod.ARENA_PRESETS[preset]
        gen = torch.Generator(device="cpu").manual_seed(seed)
        pos, rad = course_mod.random_courses(1, n_gates, arena, device="cpu", generator=gen)
        course = {
            "name": name,
            "gates": [
                {"pos": [round(float(v), 4) for v in pos[0, g]], "radius": round(float(rad[0, g]), 4)}
                for g in range(n_gates)
            ],
        }
        path = out_dir / f"{name}.yaml"
        path.write_text(courses_mod.course_to_yaml(course))
        # Report the min inter-gate spacing so the seeded tracks are visibly spread.
        d = (pos[0, 1:] - pos[0, :-1]).norm(dim=-1)
        print(f"wrote {path.relative_to(out_dir.parents[1])}  "
              f"({n_gates} gates, preset={preset}, min hop {d.min():.2f} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
