---
node_id: b7c16c24-dcd9-5045-8dec-f5ef2599c07d
slug: autumn-stream-8410
title: 'Gate-racing lap time: five levers exhausted against a standing control limit'
created_at: '2026-08-09T18:42:32+00:00'
parents:
- cold-pebble-7468
summary: The lab's first beachhead. Best lap 2.32-2.54 s over 3 seeds at 95-98% completion, but the honest oracle showed ~37% headroom remaining and five separate levers have been refuted against it. The standing conclusion is that the residual is a control/algorithm limit. The named next lever (SHAC/BPTT) has never been run.
flywheel:
  node_id: 4f6c5727-c9f6-5c23-8b51-004f65cf25f2
  slug: winter-pine-1130
  revision: 0
  pushed_at: '2026-08-09T21:28:39+00:00'
  content_sha256: 1c3b32a8b4fc0b2bc2a28352b9a2c0f019b1e23f9e3ccbfb2df4f49ec20d09c8
---
Status: open

## Current

`gate_race` is the locked first beachhead — single-drone time-optimal gate racing,
state and oracle based so it never touches the Blackwell-broken camera path, metric
= lap time [rec: morning-feather-7342]. The first baseline was 3.87 s best lap
against a 3.47 s oracle at about 91% completion [rec: winter-sun-1382].

Current best is the deploy recipe of record: hybrid-obs split latency x Muon x
reliability shaping, 2.32-2.54 s best lap clean at 95.5-98.3% completion across three
seeds, clearing every pre-registered bar on every seed [rec: muddy-mouse-2952].

The yardstick matters more than the number. Replacing the path-length oracle with an
honest dynamically-feasible one showed roughly **37% lap-time headroom remains**
[rec: silent-math-9686], and that gap has never been closed.

**Racing is deliberately not being pursued right now, and the headroom is still considered a real goal** [rec: golden-banner-2676]. Both halves are the author's: the ~37% gap is "a good goal", and racing is "another branch" the project is interested in rather than pushing. So `open` here means an unexecuted plan, **not** an abandoned one and **not** a queue item — an agent picking work by visible headroom would pick this first and be wrong. The standing scope decision is `young-snow-0387`.

**Open, and named but unrun** [rec: morning-feather-7342]**:** SHAC / BPTT through DiffAero's differentiable path
(`--algo shac` is reserved in `scripts/train.py`, and `AGENTS.md` and
`docs/TASK_CATALOG.md` both name it). No node in the record graph reports running it.
That is the standing candidate against a limit that five reward and exploration
levers could not move.

## Negative knowledge

- [scope: reward-weight tuning on gate_race | confidence: high | evidence: bitter-meadow-7267, aged-darkness-9566] Reward-weight tuning is saturated, and a racing-line / next-gate-speed reward is refuted outright — it reward-hacks.
- [scope: exploration and budget levers on gate_race | confidence: high | evidence: square-cake-5756, shrill-limit-5398] An ent_coef sweep is RED / no-effect, and the training-budget knee is at 120 M steps with 160 M and 200 M flat. Neither more exploration nor more budget buys lap time.
- [scope: the residual ~37% headroom | confidence: medium | evidence: square-cake-5756, silent-math-9686] The standing attribution is that the residual is a CONTROL or algorithm limit rather than a reward, exploration or budget one. It is medium confidence because the alternative — a finer action representation or a differentiable-control method — has never been tried, so the attribution is by elimination rather than by demonstration.

## Provenance

- winter-sun-1382 — the first green baseline and its numbers
- silent-math-9686 — the honest oracle and the 37% headroom it exposed
- muddy-mouse-2952 — the current best, 3 seeds
- bitter-meadow-7267 — reward-weight tuning saturated
- aged-darkness-9566 — the racing-line reward, refuted for reward hacking
- square-cake-5756 — the exploration lever, refuted, and the control-limit conclusion
- shrill-limit-5398 — the training-budget knee
