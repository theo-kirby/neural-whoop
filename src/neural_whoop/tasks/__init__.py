"""Task catalog. Importing this package registers all built-in tasks into ``TASK_REGISTRY``.

The autonomous agent grows this package: each new policy/behaviour in ``docs/TASK_CATALOG.md``
is a new :class:`~neural_whoop.envs.registry.DroneTask` module imported here.
"""

from neural_whoop.tasks import acro_flip  # noqa: F401 - registers "acro_flip"
from neural_whoop.tasks import command_follow  # noqa: F401 - registers "command_follow"
from neural_whoop.tasks import gate_race  # noqa: F401 - registers "gate_race"
from neural_whoop.tasks import gesture_follow  # noqa: F401 - registers "gesture_follow"
from neural_whoop.tasks import hand_follow  # noqa: F401 - registers "hand_follow"
from neural_whoop.tasks import hover  # noqa: F401 - registers "hover"
from neural_whoop.tasks import hover_blind  # noqa: F401 - registers "hover_blind"
from neural_whoop.tasks import hover_blind_v2  # noqa: F401 - registers "hover_blind_v2"
from neural_whoop.tasks import hover_tof  # noqa: F401 - registers "hover_tof"
from neural_whoop.tasks import swarm_formation  # noqa: F401 - registers "swarm_formation"
from neural_whoop.tasks import swarm_race  # noqa: F401 - registers "swarm_race"
from neural_whoop.tasks import target_follow  # noqa: F401 - registers "target_follow"

__all__ = ["acro_flip", "command_follow", "gate_race", "gesture_follow", "hand_follow", "hover", "hover_blind", "hover_blind_v2", "hover_tof", "swarm_formation", "swarm_race", "target_follow"]
