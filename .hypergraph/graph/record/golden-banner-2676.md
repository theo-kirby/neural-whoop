---
node_id: 1fed1097-fa05-52d0-89d8-945f9dfd1967
slug: golden-banner-2676
title: 'The author interview, run after the adoption: nothing here is broken'
created_at: '2026-08-09T19:02:38+00:00'
parents:
- wandering-water-2720
summary: The interview the adoption could not run. Nothing in the project is broken — the three broken nodes are the frontier being worked, not regressions. Swarm is parked by decision; racing is a live goal deliberately off the frontier; the frontier is single-drone flight quality, latency, hover and acro.
flywheel:
  node_id: c181dec4-a4a7-5b05-a2be-4a176ad23dca
  slug: aged-morning-1142
  revision: 0
  pushed_at: '2026-08-09T21:28:32+00:00'
  content_sha256: fbe6f9f0e5285af17edb21bb684b8abbaaf2e28df8b819681a09c20b7101f793
---
## What

The author interview the adoption could not run (`wandering-water-2720`, "The author
interview did not happen") was run afterwards, against the list of questions the
evidence could not settle. This node carries the answers. It is the first
author-informed content in this project's state graph; everything before it was
derived from the repository and the imported graph alone.

## Why

The adoption's own disclosure said what the gap cost: "it does not record which of
the timeline's boundaries the author would call an era, which decisions he would
relitigate, what he is deliberately not doing, or what is only in his head." Three
of those four are now on the record. The distilled statuses were guesses about
intent, and two of them were wrong in the same direction — the evidence reads a
paused branch and a crashed bench as damage, where the author reads deliberate
scope.

## Method

Questions put to the author; answers recorded verbatim in substance below. No
repository evidence was re-read for this node — its whole content is intent, which
is the half that cannot be derived.

## Result

**Nothing in this project is `broken`.** Asked directly about the three nodes the
adoption marked `broken` — the 1.0 m hover setpoint, the real-drone deploy path, and
measurement/documentation integrity — the author's answer was that none of them are
really broken: *"they're just maybe not in the best state."*

That is a status correction, not a factual one. Every measurement those nodes cite
still stands: the ToF band mechanism, the tumbling crash, the unreachable
`exit_probe.py` branches. What changes is the reading. `broken` in this protocol
means "was working or attempted, currently fails", and the author's point is that
these are the *frontier being worked*, not regressions from a working state. They
become `open` — planned, known, work not yet done.

**Swarm is dormant on purpose.** *"It was a branch of the system that we were
exploring but just decided to go in other ways and haven't worked on it in a while.
It's still valuable but it's not something that's under active development."* The
adoption inferred dormancy from the fact that nothing had touched it since
2026-06-28 and stated it as fact; it is intent. The distinction matters to the next
agent: a parked branch is not a gap to be filled.

**The ~37% racing headroom is still a goal, and racing is not being pursued.** Both
halves are the author's: *"That seems like a good goal, but again, haven't looked at
it or worked on it in a while."* Racing is a real part of the project and a real
open lever — SHAC/BPTT has never been run — and it is deliberately not on the
frontier. The adoption marked this `open` on the ambiguity between "abandoned" and
"still the plan"; the answer is neither, and the node should say so rather than
leave a reader to guess which.

**What the project is deliberately not doing**, in the author's words: swarm,
racing, and multi-drone work with other sensors. These are not gaps. They are
scope, and they are recorded as a decision in a sibling node rather than as state.

**What the frontier actually is**: getting the drone to fly properly — the lowest
latency achievable, a hover that settles, and acro manoeuvres. Every item the author
named as current work is single-drone flight quality on the real airframe.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 6d1712f55cbe2fe3dad3edb422eccfe660756dc4

## State Impact

- target: lucky-lodge-5696 — Status broken -> open. The author reviewed this node and does not consider it broken: the measured ToF-band mechanism at the 1.0 m setpoint stands, but the 1.0 m operating point was left behind rather than regressing, and Desk-Hover at 0.10 m is planned work that has never been flown. Every measurement in the node is unchanged.
- target: modest-raven-7153 — Status broken -> open. The author reviewed this node and does not consider it broken. The deploy path's spine holds — the radio-owned safety interlock, faithful telemetry, the fake-bridge headless tests — and what does not yet hold is a settled hover on the real airframe, which is the frontier being worked rather than a regression. The tumbling crash, the stale attitude frames and the airframe rewiring all stand as measured; they are the work, not damage to be repaired before work resumes.
- target: autumn-bell-7061 — Status broken -> open. The author reviewed this node and does not consider it broken. The exit_probe.py defect, the re-measured 9.5% vertical exit rate, the missing denominators and the four contradicted documents all stand exactly as recorded; what they describe is outstanding cleanup rather than a component that fails.
- target: peaceful-mist-1317 — Swarm is dormant by decision, not by neglect: an explored branch the project chose not to pursue further, still considered valuable, not under active development. The adoption inferred dormancy from the 2026-06-28 last-touch date and stated it as fact; this replaces the inference with the author's intent, and a reader should treat swarm as parked scope rather than as a gap to fill.
- target: autumn-stream-8410 — The ~37% racing headroom is still a real goal and racing is deliberately not being pursued right now. Both halves are the author's own: SHAC/BPTT remains the named open lever and has never been run, and racing is a branch the project is interested in rather than pushing. This replaces the adoption's open-on-ambiguity reading, which could not tell abandonment from an unexecuted plan.
- target: NEW deliberate-scope — decision: the project is deliberately not working on swarm, racing, or multi-drone work with other sensors. These are scope decisions rather than gaps. The current frontier is single-drone flight quality on the real airframe: lowest achievable latency, a hover that settles, and acro manoeuvres.
