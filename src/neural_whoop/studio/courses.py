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
from neural_whoop.studio import course_validate

PRESET_PREFIX = "preset:"

#: Subdir where browser-authored courses are written, kept apart from the curated/seeded set.
WEB_SUBDIR = "_web"


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
    """List selectable YAML courses as ``{name, num_gates, kind}``.

    Seeded curated courses under ``courses_dir/*.yaml`` (``kind: "file"``) plus browser-authored
    courses under ``courses_dir/_web/*.yaml`` (``kind: "web"``), so a freshly saved course appears
    in the Player's picker without a restart.
    """
    courses_dir = Path(courses_dir)
    if not courses_dir.exists():
        return []
    out: list[dict] = []
    for path, kind in [(p, "file") for p in sorted(courses_dir.glob("*.yaml"))] + [
        (p, "web") for p in sorted((courses_dir / WEB_SUBDIR).glob("*.yaml"))
    ]:
        try:
            course = load_course_yaml(path)
        except Exception:  # noqa: BLE001 - a malformed file shouldn't break the listing
            continue
        out.append({"name": path.stem, "num_gates": len(course["gates"]), "kind": kind})
    return out


def load_course_named(courses_dir: str | Path, name: str) -> dict:
    """Load a single course by stem (checks the curated dir, then ``_web/``) for editing."""
    return load_course_yaml(resolve_course_file(courses_dir, name))


def save_course(courses_dir: str | Path, name: str, gates: list[dict],
                arena: course_mod.ArenaSpec | None = None) -> dict:
    """Validate then write an authored course to ``courses_dir/_web/<slug>.yaml``.

    Args:
        courses_dir: Root course dir; the file lands under its ``_web/`` subdir (created if absent).
        name: Display name; slugified for the filename.
        gates: ``[{pos:[x,y,z], radius}, ...]``.
        arena: Bounds to validate against (defaults to the tight :class:`ArenaSpec`).

    Returns ``{name, path, num_gates}``. Raises :class:`ValueError` (-> HTTP 422) if validation
    finds any error-level issue, so an unflyable course is never persisted.
    """
    report = course_validate.validate_gates(gates, arena)
    if not report["ok"]:
        errs = "; ".join(i["message"] for i in report["issues"] if i["level"] == "error")
        raise ValueError(f"course is not flyable: {errs}")
    course = {
        "name": str(name),
        "gates": [{"pos": [float(v) for v in g["pos"]],
                   "radius": float(g.get("radius", 0.35))} for g in gates],
    }
    web_dir = Path(courses_dir) / WEB_SUBDIR
    web_dir.mkdir(parents=True, exist_ok=True)
    path = web_dir / f"{slugify(name)}.yaml"
    path.write_text(course_to_yaml(course), encoding="utf-8")
    return {"name": course["name"], "path": str(path), "num_gates": len(course["gates"])}


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
    """Resolve a course by stem (curated dir, then the ``_web/`` authored dir); guards traversal."""
    courses_dir = Path(courses_dir).resolve()
    for base in (courses_dir, courses_dir / WEB_SUBDIR):
        target = (base / f"{stem}.yaml").resolve()
        if not target.is_relative_to(courses_dir):
            raise ValueError(f"course name escapes courses dir: {stem!r}")
        if target.is_file():
            return target
    raise ValueError(f"no such course: {stem!r}")


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
