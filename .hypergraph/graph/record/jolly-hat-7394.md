---
node_id: 45bd6fa5-22fa-5e61-b00d-d4be5279052e
slug: jolly-hat-7394
title: 'Tooling/viz: render the whole follow/formation thread — additive `scene` channel (Studio + nw-viz)'
created_at: '2026-06-28T09:25:59.563607+00:00'
parents:
- square-smoke-0918
- lucky-bush-5765
- plain-block-5937
- wispy-dust-3157
- raspy-moon-0909
- little-feather-5786
- proud-field-5681
- small-art-6235
summary: 'Tooling/viz that makes the gateless follow/formation thread watchable: it adds one generic, additive per-frame `scene` channel to the replay contract (a `scene` dict + a DroneTask.scene_objects()/scene_info() hook) carrying a moving target/anchor/slot marker plus an optional command value, with static descriptors (standoff, command labels, formation radius) in meta.scene_info — purely additive, so REPLAY_VERSION stays at 2 and old replays are untouched. Both viewers (in-repo Studio and sibling nw-viz) now draw the target/anchor spheres, slot rings, and a command HUD chip and hide gate UI; studio/rollout.py was rewritten to task families so follow and swarm_formation policies get the right substrate. Previously these policies (target/hand/gesture/command_follow + swarm_formation) rendered nothing; verified end-to-end with new tests plus group replays and hero MP4s for all five. Multi-parent over the perception, swarm, and tooling threads.'
origin:
  backend: flywheel
  node_id: 45bd6fa5-22fa-5e61-b00d-d4be5279052e
  slug: jolly-hat-7394
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
---
**Gap.** The visual contract recorded gate geometry only. So the entire follow/perception thread (`target_follow` -> `hand_follow` -> `gesture_follow` -> `command_follow`) and the second swarm task (`swarm_formation`) — all of which chase a moving target/anchor instead of gates, two of them carrying a command channel — rendered NOTHING in the Studio (`studio_rollout` crashed follow tasks on an unexpected `n_gates=` kwarg and gave `swarm_formation` the wrong substrate) and as empty courses in nw-viz. The recent arc lived only as static `runs/_perception_matrix/` PNGs.

**Design — one generic, additive `scene` channel (no version bump).** Rather than bespoke per-task fields, add a single optional per-frame `scene` dict + a `DroneTask.scene_objects(env)` / `scene_info()` hook (default `{}`):
- follow tasks -> `{target: (n_drones,3)}`; gesture/command_follow add `{command}` (0/1 ; 0/1/2); `swarm_formation` -> `{anchor, slot}` (shared anchor broadcast + per-drone ring slot). Gate tasks keep returning `{}` (gates already travel in `episode.gates`).
- Static descriptors (standoff, `command_labels` STOP/GO·NEAR·FAR, `d_near`/`d_far`, `formation_radius`) ride in `meta.scene_info` so viewers label/scale markers without hardcoding task names.
- Purely additive optional fields, so `REPLAY_VERSION` STAYS at 2 (the contract's documented rule); old replays + the matplotlib pack are untouched.

**Layers touched.** Task hooks (registry + the 5 tasks); `viz/replay.py` (`_build_frame`/`add_frame` carry `scene`, `build_meta` auto-pulls `scene_info` off the task); `eval/rollout.py` snapshots `scene_objects` per hero step alongside the pose; `studio/rollout.py` rewritten to task FAMILIES — gateless tasks skip course resolution and use their own arena, follow -> `n_envs=drone_count` independent followers, `swarm_formation` -> `n_agents=drone_count` ring in one env; `studio/server.py` exposes `family`/`needs_course`. Both frontends (`web/studio/` + sibling `../nw-viz/`) draw target/anchor spheres (cyan/amber) + slot rings, tint the target by command, show a command HUD chip, hide gate UI, and pick the gateless hero by lowest mean target/slot distance.

**Verified end-to-end.** New round-trip + back-compat replay tests and gateless studio-rollout tests pass; full suite green. Generated Studio-loadable group replays + headless hero MP4s for all five policies (`target_follow_clean`, `hand_follow_ema`, `gesture_follow`, `command_follow` at 3 followers; `swarm_formation` at 6) — the command_follow MP4 shows the cyan NEAR target + 'command NEAR' chip; the swarm_formation MP4 shows the amber anchor with six drone trails ringing it. These replays/MP4s are the deliverable record of the perception arc.

**Honest caveat.** Command tasks are visualized from the recorded rollout (no live interactive control — keeps the replay-based architecture). The command marker/chip can lag the reward by 1-2 steps (the command evolves inside `observe()` after `reward_and_done`); negligible since the command flips only ~once per 2.5 s.

neural-whoop @ 998068fed68b6b578efe43a9c8a6c05279258766 (3 commits: contract+tasks+backend, frontends, docs); nw-viz @ 2dafba1a313f09bcba517d8e36305bb6a8c819b2.