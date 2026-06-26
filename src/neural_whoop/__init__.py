"""neural-whoop: a GPU-parallel, swarm-capable whoop RL lab on DiffAero.

Importing this package makes the vendored DiffAero fork (``third_party/diffaero``) importable
as the top-level ``diffaero`` package, so the dynamics adapter can ``import diffaero`` from
anywhere (scripts, tests, notebooks) without an editable install or a PYTHONPATH dance.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"

# Repo layout: <repo>/src/neural_whoop/__init__.py  ->  parents[2] == <repo>
_REPO_ROOT = Path(__file__).resolve().parents[2]
_VENDOR = _REPO_ROOT / "third_party"


def _ensure_vendor_on_path() -> None:
    """Prepend ``third_party`` to ``sys.path`` so ``import diffaero`` resolves the vendored fork."""
    p = str(_VENDOR)
    if _VENDOR.is_dir() and p not in sys.path:
        sys.path.insert(0, p)


_ensure_vendor_on_path()
