#!/usr/bin/env python
"""Generate the **reference flip** — a thin alias for ``reference_maneuver.py --maneuver flip``.

The reference package grew from "the flip" to "a maneuver" (the swing and the orbit are the other
two), and the generator moved with it. This entry point stays so every command already written down
— in ``CLAUDE.md``, in ``docs/REFERENCE_MANEUVER.md``, in the Flywheel nodes that produced the
shipped 1.2 m flip artifacts — keeps working unchanged. It is an alias, not a fork: there is one
implementation.

    uv run python scripts/reference_flip.py --axis roll --omega 9.0 \
        --z-entry 1.2 --out runs/reference/flip_roll
    uv run python scripts/reference_flip.py --axis roll --omega 9.0 --deployable \
        --out runs/reference/flip_roll_deployable

**Two variants means two solves, not one stream under two limits.** The 0.25 throttle floor puts a
quarter g of *downward* thrust on an inverted drone across the whole coast, so the shoot returns a
genuinely different trajectory — a longer pop, a higher apex, and noticeably more lateral excursion.
Motors-off is the default because it is the aesthetic ideal for the video; if you are using this as
an **RL target or a scoring reference, use ``--deployable``**, because the motors-off coast has
*zero control authority* by construction (zero thrust can produce no torque at all — the AIRMODE
flip-stall failure in miniature). ``verify.json`` reports both margins.
"""

from __future__ import annotations

import argparse

from reference_maneuver import add_arguments, generate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap, maneuver_flag=False)
    args = ap.parse_args()
    args.maneuver = "flip"
    if args.out is None:
        args.out = f"runs/reference/flip_{args.axis}{'_deployable' if args.deployable else ''}"
    return generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
