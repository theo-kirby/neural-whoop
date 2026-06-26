# Vendored DiffAero fork (neural-whoop)

Upstream: https://github.com/flyingbitac/diffaero (BSD-3-Clause)
Pinned at commit: **291ea14196aefbebcf7387dd71f7e096c83878b7** (main, 2025-12-18)

neural-whoop uses **only DiffAero's pure-torch dynamics core** (`dynamics/`, `utils/math.py`,
`utils/randomizer.py`) as its GPU-parallel quadrotor substrate. The env/algo/rendering layers
(hydra/wandb/taichi/open3d/pytorch3d) are **not** installed; the only DiffAero runtime deps we pull
are `torch` and `omegaconf`.

## Our edits (so the core runs on Blackwell without the heavy stack)

- `utils/p3d_compat.py` *(new)* — pure-torch `quaternion_to_matrix` / `quaternion_raw_multiply` /
  `matrix_to_quaternion`. pytorch3d is a compiled CUDA extension that won't build against cu128
  wheels and is only used for these trivial quaternion ops.
- `dynamics/base_dynamics.py`, `dynamics/controller.py`, `dynamics/pointmass.py`, `utils/math.py` —
  the 4 `pytorch3d.transforms` import sites now point at `diffaero.utils.p3d_compat`.
- `__init__.py` — lazy subpackage imports (the eager `from . import env/algo/network/script` dragged
  in the full training/rendering stack); `import diffaero` stays cheap.
- `dynamics/base_dynamics.py` — removed an unused `from diffaero.utils.logger import Logger` (only
  referenced in a commented debug line; the import pulled in hydra).
- `utils/math.py` — `quaternion_to_euler` clamps the `asin` argument to `[-1, 1]`. A slightly
  non-unit quaternion (numerical drift at near-vertical pitch) made `asin(>1)` return NaN, which
  poisoned the policy during racing. This is a genuine numerical-robustness bug fix.

Additional whoop-specific guards live in **our** code (`src/neural_whoop/dynamics/whoop.py`), not in
the fork: identity-quaternion state initialization and per-step rate/velocity saturation (DiffAero
defines but never applies its `_X_ub`/`_X_lb` state bounds, and a whoop's tiny inertia makes the RK4
rotational dynamics unstable past the rate limit).

To re-sync from upstream: re-fetch the pinned tarball and re-apply the edits above (all are small and
marked with `neural-whoop:` comments).
