"""Course catalog for the Studio — seeded YAML courses + named arena presets.

Two kinds of selectable course back the Studio's course dropdown:

* **seeded files** under ``assets/courses/*.yaml`` (schema ``{name, gates: [{pos, radius}]}``,
  mirroring ``neural-whoop-lab``) — shareable, deterministic, bigger-than-default tracks;
* **presets** from :data:`neural_whoop.course.ARENA_PRESETS` (``tight``/``spread``/``big``/
  ``giant``) — flagged ``preset:<name>``, generating a *fresh* random course of that geometry.

:func:`resolve_course` turns either selector into ``(gate_pos, gate_rad)`` torch tensors the env's
``fixed_course`` hook consumes. Pure stdlib + yaml + torch (no fastapi/sim) so the listing routes
stay light.
"""

from __future__ import annotations

import re
from pathlib import Path

import torch
import yaml
from torch import Tensor

from neural_whoop import course as course_mod

PRESET_PREFIX = "preset:"


def slugify(name: str) -> str:
    """Filesystem-safe slug from a course name (lowercase, dashes, alnum only)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "course"


def load_course_yaml(path: str | Path) -> dict:
    """Load a course YAML file into ``{name, gates: [{pos:[x,y,z], radius}]}``."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    gates = doc.get("gates", []) or []
    return {
        "name": str(doc.get("name", Path(path).stem)),
        "gates": [
            {"pos": [float(v) for v in g["pos"]], "radius": float(g.get("radius", 0.45))}
            for g in gates
        ],
    }


def course_to_tensors(course: dict, device: torch.device | str = "cpu") -> tuple[Tensor, Tensor]:
    """Adapt a ``{gates: [...]}`` course doc to ``(gate_pos (ng,3), gate_rad (ng,))`` tensors."""
    gates = course["gates"]
    if not gates:
        raise ValueError(f"course {course.get('name')!r} has no gates")
    pos = torch.tensor([g["pos"] for g in gates], dtype=torch.float32, device=device)
    rad = torch.tensor([g["radius"] for g in gates], dtype=torch.float32, device=device)
    return pos, rad


def course_to_yaml(course: dict) -> str:
    """Serialize a course doc to the ``load_course_yaml`` schema (round-trips through it)."""
    return yaml.safe_dump(
        {"name": course["name"], "gates": [
            {"pos": [float(x) for x in g["pos"]], "radius": float(g["radius"])}
            for g in course["gates"]
        ]},
        sort_keys=False,
    )


def list_courses(courses_dir: str | Path) -> list[dict]:
    """List seeded YAML courses under ``courses_dir`` as ``{name, num_gates, kind: "file"}``."""
    courses_dir = Path(courses_dir)
    if not courses_dir.exists():
        return []
    out: list[dict] = []
    for path in sorted(courses_dir.glob("*.yaml")):
        try:
            course = load_course_yaml(path)
        except Exception:  # noqa: BLE001 - a malformed file shouldn't break the listing
            continue
        out.append({"name": path.stem, "num_gates": len(course["gates"]), "kind": "file"})
    return out


def list_presets() -> list[dict]:
    """List named arena presets as ``{name: "preset:<k>", preset, radius, kind: "preset"}``."""
    return [
        {
            "name": f"{PRESET_PREFIX}{key}",
            "preset": key,
            "radius": float(spec.radius),
            "step_min": float(spec.step_min),
            "step_max": float(spec.step_max),
            "kind": "preset",
        }
        for key, spec in course_mod.ARENA_PRESETS.items()
    ]


def resolve_course_file(courses_dir: str | Path, stem: str) -> Path:
    """Resolve a seeded course by stem under ``courses_dir`` (guards path traversal)."""
    courses_dir = Path(courses_dir).resolve()
    target = (courses_dir / f"{stem}.yaml").resolve()
    if not target.is_relative_to(courses_dir):
        raise ValueError(f"course name escapes courses dir: {stem!r}")
    if not target.is_file():
        raise ValueError(f"no such course: {stem!r}")
    return target


def resolve_course(
    spec: str,
    courses_dir: str | Path,
    *,
    n_gates: int = 6,
    seed: int = 0,
    device: torch.device | str = "cpu",
) -> tuple[Tensor, Tensor, str]:
    """Resolve a course selector to ``(gate_pos, gate_rad, label)``.

    ``spec`` is either ``preset:<name>`` (generate a fresh random course of that arena geometry)
    or a seeded YAML course stem under ``courses_dir``.
    """
    if spec.startswith(PRESET_PREFIX):
        key = spec[len(PRESET_PREFIX):]
        arena = course_mod.ARENA_PRESETS.get(key)
        if arena is None:
            raise ValueError(f"unknown preset: {key!r}")
        gen = torch.Generator(device=device).manual_seed(int(seed))
        pos, rad = course_mod.random_courses(1, int(n_gates), arena, device=device, generator=gen)
        return pos[0], rad[0], f"{key} ({n_gates} gates)"
    course = load_course_yaml(resolve_course_file(courses_dir, spec))
    pos, rad = course_to_tensors(course, device=device)
    return pos, rad, course["name"]
