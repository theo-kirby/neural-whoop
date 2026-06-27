"""neural-whoop Studio — the interactive browser viewer's Python backend.

A small FastAPI server (:mod:`neural_whoop.studio.server`) that lists saved policies and courses,
runs a fixed-course rollout on demand (:mod:`neural_whoop.studio.rollout`), and serves the
resulting replay to the static Three.js frontend under ``web/studio/``. The successor to
``neural-whoop-lab``'s studio, ported onto this repo's DiffAero env + v2 group-replay contract.

Only :mod:`neural_whoop.studio.courses` is import-light (stdlib + yaml + torch). ``server`` needs
the ``studio`` extra (fastapi/uvicorn); ``rollout`` reaches the sim stack lazily, so the GET
listing routes work without a GPU.
"""
