"""Task catalog. Importing this package registers all built-in tasks into ``TASK_REGISTRY``.

The autonomous agent grows this package: each new policy/behaviour in ``docs/TASK_CATALOG.md``
is a new :class:`~neural_whoop.envs.registry.DroneTask` module imported here.
"""

from neural_whoop.tasks import gate_race  # noqa: F401 - registers "gate_race"
from neural_whoop.tasks import swarm_race  # noqa: F401 - registers "swarm_race"
from neural_whoop.tasks import target_follow  # noqa: F401 - registers "target_follow"

__all__ = ["gate_race", "swarm_race", "target_follow"]
