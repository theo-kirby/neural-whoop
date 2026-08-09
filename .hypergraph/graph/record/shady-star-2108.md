---
node_id: 6c3bdcc3-8bf0-5283-aacd-4a2615a913e2
slug: shady-star-2108
title: hypergraph 0.0.8, and the contract's frontier summary corrected
created_at: '2026-08-09T19:55:26+00:00'
parents:
- young-snow-0387
summary: 'Upgraded to 0.0.8; the AGENTS.md block carrying this project''s whole Flywheel-to-Hypergraph reconciliation was preserved rather than overwritten. The contract''s frontier summary now matches the interview: nothing broken, and open never means next. 0.0.8''s stricter citation rule surfaces 7 real uncited claims, left unfixed rather than guessed at.'
---
## What

Upgraded this project's hypergraph copies to **0.0.8** — five skills and the config
stamp — and corrected the agent contract's frontier summary, which the author interview
had made stale.

The AGENTS.md block was **not** overwritten. `upgrade` reported it as `customized` and
stepped back, which matters more here than in most repos: this block carries the
project's whole Flywheel-to-Hypergraph reconciliation — the replacement of the Operating
loop's step 1 and step 4, the note that artifacts and the `kind:`/`outcome:`/`cluster:`
tag taxonomy do not carry over, and the statement that the hosted 189-node graph is a
frozen read-only archive. Under 0.0.7 an upgrade would have deleted all of it and left
an agent following `docs/FLYWHEEL.md` straight back onto the archive.

## Why

Two of the three code fixes in 0.0.8 were found by this repo's own adoption, so it
should not stay on the release that had them. The contract also carried a frontier
summary — "three components are `broken`, two `blocked`, four `open`" — that the author
interview overturned the same day.

## Method

`hypergraph upgrade`, then the 0.0.8 opening paragraph merged into the block by hand
alongside the existing amendments, then `hypergraph sync`.

## Result

- 0.0.8 skills, `hypergraph_version: 0.0.8`, block intact.
- The contract now says **nothing is `broken`** (two `blocked`, seven `open`), citing
  `golden-banner-2676`, and states the thing a reader most needs: **an `open` status
  here means "work not yet done", never "next"** — swarm and racing are parked by
  decision (`young-snow-0387`), so picking work by visible headroom picks wrong.
- `sync`: 0 violations. **7 warnings**, all of them new, and all of them real:
  0.0.8's I1 rule checks prose paragraphs, which the old rule skipped entirely in any
  section containing a bullet. Uncited claims in `long-mountain-5811` (3),
  `peaceful-mist-1317` (2), `northern-rain-9996` and `vast-dune-7535` were never
  looked at before. **They are not fixed here.** Each needs the record node it derives
  from to be read; choosing a slug to silence a warning is invented provenance, which
  is the thing I8 exists to forbid.

## Repo

- repo: git@github.com:theo-kirby/neural-whoop.git
- branch: main
- commit: 965810f7c0b4c20a2794e495a3a9149287068b84

## State Impact

none: tooling and contract upkeep — the frontier statement it corrects was already folded from golden-banner-2676 and young-snow-0387, and the 7 citation warnings it surfaces are pre-existing gaps in claims this node does not change
