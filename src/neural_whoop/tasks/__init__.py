"""Task catalog. Importing this package registers all built-in tasks into ``TASK_REGISTRY``.

The autonomous agent grows this package: each new policy/behaviour in ``docs/TASK_CATALOG.md``
is a new :class:`~neural_whoop.envs.registry.DroneTask` module imported here.
"""

from neural_whoop.tasks import gate_race  # noqa: F401 - registers "gate_race"

__all__ = ["gate_race"]
