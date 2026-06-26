import os

DIFFAERO_ROOT_DIR = os.path.dirname(os.path.realpath(__file__))
DIFFAERO_ENVS_DIR = os.path.join(DIFFAERO_ROOT_DIR, 'envs')

# neural-whoop vendored fork: the upstream __init__ eagerly imported env/algo/network/script,
# which drag in the full rendering + training stack (hydra, wandb, taichi, pytorch3d, open3d).
# neural-whoop uses only the pure-torch dynamics core (diffaero.dynamics + diffaero.utils.math/
# randomizer), so those subpackages are made lazy: `import diffaero` stays cheap, and the heavy
# subpackages still resolve on explicit attribute access (e.g. diffaero.algo) if ever needed.
__all__ = ["env", "algo", "network", "script", "utils", "dynamics"]


def __getattr__(name):
    if name in __all__:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
