---
node_id: 0c2d1899-2159-5e34-ac8e-127d101da66f
slug: young-snow-0387
title: 'Decision: swarm, racing and multi-drone sensing are parked; the frontier is single-drone flight quality'
created_at: '2026-08-09T19:03:20+00:00'
parents:
- golden-banner-2676
summary: Scope decision from the 2026-08-09 interview. Swarm, racing and multi-drone work with other sensors are deliberately not being worked on — parked, not declined, and not gaps. The frontier is lowest latency, a hover that settles, and acro on the real airframe.
---
## What

A decision, stated by the author on 2026-08-09: **swarm, racing, and multi-drone
work with other sensors are deliberately not being worked on.** The current frontier
is single-drone flight quality on the real airframe — the lowest achievable latency,
a hover that settles, and acro manoeuvres.

## Why

Follows the interview. This is the answer to "what are you deliberately *not* doing,
and why", and it is recorded here rather than as a state claim because it is a
point-in-time bet about where effort goes, not a fact about the world. A state node
phrased as a gap invites an agent to close it; scope phrased as a decision does not.
Changing the plan never mutates this node — a later decision supersedes it.

## Method

Author's own words, taken directly. No inference.

## Result

**Parked, deliberately:**

- **Swarm.** An explored branch the project decided not to pursue further. *"It's
  still valuable but it's not something that's under active development as much as
  the other things."* Nothing has touched it since 2026-06-28, and that is the
  decision showing, not neglect.
- **Racing.** *"It's another branch. It's something that we're interested in and
  something that is part of the project, but it's not something that's currently
  really being pushed on the frontier."* The ~37% headroom the graph identifies is
  still considered a good goal and SHAC/BPTT is still the named open lever — nobody
  has run it, and nobody currently intends to.
- **Multi-drone work with other sensors.** Same category.

**Being worked:** getting the drone to fly properly. Lowest latency, a hover that
settles, acro. Every current item is single-drone flight quality on real hardware.

**Why this distinction is load-bearing for an agent.** The three items above look
identical to unfinished work from inside the repository: open levers, a dormant
cluster, an unexecuted plan with a quantified prize on it. An agent optimising for
visible gaps would pick racing first — it has the clearest metric and the largest
stated headroom in the whole graph. It is the wrong thing to work on, and no amount
of reading the tree says so.

This is also the standing answer to the ROADMAP's "Declined" list of 2026-07-11
(NFC, stereo cameras, external accel, WiFi FTM, ESP-side gamepad), which was not
re-litigated: those remain declined, and this node adds three larger branches to the
same category — parked rather than declined, because the author's framing is that
they keep their value and are not being pushed.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 6d1712f55cbe2fe3dad3edb422eccfe660756dc4

## State Impact

none: this is a scope decision; the state nodes it bears on (peaceful-mist-1317 for swarm, autumn-stream-8410 for racing) take their impacts from golden-banner-2676, which cites this node for the reason
