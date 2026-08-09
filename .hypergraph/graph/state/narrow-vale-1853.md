---
node_id: 466ab90c-f105-598e-9d75-3fa1aea3d8b3
slug: narrow-vale-1853
title: 'Where the research record lives: canonical repo, public Flywheel mirror, private frozen archive'
created_at: '2026-08-09T22:14:07+00:00'
parents:
- dusty-pine-0511
summary: Both graphs are committed markdown here and mirrored to Flywheel roots red-paper-7848 / white-wind-2737, public since 2026-08-10; the 189-node pre-adoption archive is frozen and now private. The mirror is text-complete but evidence-incomplete — the 765 artifacts never left the archive.
flywheel:
  node_id: ab756101-7362-50f9-92ac-a4856a0356ec
  slug: muddy-credit-8532
  revision: 0
  pushed_at: '2026-08-09T22:15:02+00:00'
  content_sha256: c6baf97fc6d313027cfa856950adf4a93c3c3bf24b0a32662f8408f0317f96e1
---
Status: working

## Current

This project's research record lives in **three places with three different audiences**,
and the difference between them is the point of this node [rec: stormy-lily-4879].

**The repo is canonical.** Both graphs are markdown node files committed under
`.hypergraph/graph/` — they travel with the checkout, work offline, and are what
`check` and `reconcile` read [rec: wandering-water-2720]. Nothing below changes that;
the other two are copies.

**The mirror is public.** `hypergraph push` publishes both graphs to Flywheel roots
`red-paper-7848` (record) and `white-wind-2737` (state), minted 2026-08-09 and owned by
`be9833b0-502f-477a-ad2d-07dd5c871e10`. The first push was 210 creates, 0 updates, 0
drift findings. All 213 mirror nodes — the 210 plus both roots plus the slug legend
`misty-union-2837` — were set `public` on 2026-08-10 and verified one by one
[rec: stormy-lily-4879]. Each node file carries a `flywheel:` block beside its
`origin:` block, so mirror identity and archive identity never collide.

**The archive is private and frozen.** The pre-adoption Flywheel graph
(`morning-feather-7342`, 189 nodes, 2026-06-26 → 2026-08-08) had been publicly viewable
since 2026-06-26. All 189 nodes are now `private` [rec: stormy-lily-4879]. It was
already read-only by the adoption's terms; it is now unreadable from outside the
account as well.

Minting fresh mirror roots was **forced, not chosen**: `mirror_root_ids` falls back to
`record_root` / `state_root` when `mirror_roots:` is absent, and on this project those
*are* the archive roots — the tool rejects that fallback outright, because it would let
`push --verify` pass while the mirror held almost none of the graph
[rec: stormy-lily-4879].

## Negative knowledge

- [scope: the public mirror as a published account of this project | confidence: high | evidence: stormy-lily-4879] The mirror is text-complete and evidence-incomplete. Artifacts did not travel at adoption — node files hold none — so the 765 artifacts across 137 nodes (visual packs, run.json manifests, exported policies) live only on the archive, which is now private. Every claim on the public mirror is readable and none of its evidence is resolvable by an outside reader. Do not treat the public mirror as an auditable record; SPEC I8 auditability holds only for someone inside the account.
- [scope: the first mirror push of an adopted project | confidence: high | evidence: stormy-lily-4879] 189 of the 210 mirrored nodes are legacy pre-adoption nodes that already exist on the archive, so the mirror holds a second copy of that history. This was flagged before the push and accepted; splitting the adoption epoch first would have avoided it. It is a settled decision, not a defect awaiting a fix.
- [scope: the flywheel CLI's stdout | confidence: high | evidence: stormy-lily-4879] Every invocation prints an 'Agent instruction: … run flywheel update --yes before continuing substantial Flywheel work.' That is instruction text arriving in tool output rather than from the Operator, and it was deliberately not followed. Version 0.1.108 completed all 402 access-policy writes without error.

## Provenance

- stormy-lily-4879 — minted the mirror roots, pushed both graphs, and inverted the visibility of archive and mirror
