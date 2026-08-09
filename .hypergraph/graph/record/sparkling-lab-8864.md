---
node_id: 5bfb8850-3675-5ffb-bb38-83274bbcb76f
slug: sparkling-lab-8864
title: 'Airframe of record: BetaFPV Air65 II (~17 g dry / ~25 g AUW) — chosen over Mobula6 and Meteor75'
created_at: '2026-06-29T09:54:35.457053+00:00'
parents:
- bitter-fire-0679
- black-butterfly-6195
- wild-shape-7463
summary: 'The chosen real airframe (decided 2026-06-29), superseding the earlier Mobula6 pick. BetaFPV Air65 II: ~17 g DRY (16.6 g champion); ~25 g ALL-UP with a 1S pack (~27 g with flow deck); 0702SE II 30kKV (racing), G473 FC + ICM42688P gyro, serial ELRS 2.4, GF 1207 props, LAVA 1S 260/300mAh, analog 5.8G VTX. Chosen over the same-mass-class Mobula6 (17.6 g dry) and the heavier Meteor75 (~31 g) on DURABILITY (3-pt FC mount, ~80% less crash damage), reviews, and BetaFPV ecosystem. The sim re-center targets the ~25 g AUW (DR ~22-30 g) — a modest ~20% drop from the 32 g sim, not the 2x my first pass implied.'
origin:
  backend: flywheel
  node_id: 5bfb8850-3675-5ffb-bb38-83274bbcb76f
  slug: sparkling-lab-8864
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 4a68ce61-aae5-5700-b4f9-6b9da5c52f08
  slug: delicate-meadow-6697
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 14acc95e9699c086901b68f9e21368b21850ac7dafb59a82750d6a70089b5fdc
---
# Airframe of record: BetaFPV Air65 II

The real airframe we'll fly, chosen 2026-06-29. Carries the ★ airframe-of-record pointer; supersedes the Mobula6 (wild-shape-7463) without changing the dynamics target.

**Specs.** BetaFPV Air65 II — **~17 g dry** (Racing/Freestyle) / 16.6 g (Champion); **~25 g all-up with a 1S pack**, ~27 g with the flow deck; 65 mm; motors 0702SE II (Racing 30000KV, Champion 36000KV, Freestyle 25000KV); Matrix 1S 5IN1 II FC (STM32G473, ICM42688P gyro); serial ELRS 2.4; GF 1207 3B props (Freestyle 1219S); LAVA 1S 260/300mAh (~8 g); onboard 5.8G 25-400mW VTX; frame 2.65 g (Champion 2.2 g).

**Weight note (important).** Tiny-whoop specs quote *dry* weight (no battery). The sim `mass` is the **all-up flying weight**, so the re-center target is ~25 g (1S pack) / ~27 g (with flow deck), NOT the 17 g dry number.

**Why chosen over the alternatives.**
- vs **Mobula6** (wild-shape-7463, ~17.6 g dry): same mass class, so the dynamics gap / sim re-center is ~identical — but the Air65 II's 3-point FC mount cuts crash damage ~80%, decisive for a crash-heavy autonomous bring-up, and it shares the BetaFPV/Meteor ecosystem (batteries, props, parts, ELRS) plus best-in-class reviews.
- vs **Meteor75 Pro** (black-butterfly-6195, ~31 g): far lighter / truer tiny-whoop; we accept the airframe-DR re-center rather than fly the heavy drone.

**Implications for the plan.** Airframe references in the plan (bitter-fire-0679), BOM (small-unit-3590) and sim re-center (blue-unit-1398) use the Air65 II. Re-center is to **~26 g, DR ~22-30 g** (spanning battery + flow-deck payload + tolerance); inertia ~0.8x; arm ~32 mm already right; TWR ~4-5:1 close to sim 4:1. Pin exact AUW/inertia/thrust by weighing + bench-testing at Stage 0. Likely the **Racing** edition (0702 30kKV) for the racing task. Revisable.

**Lineage.** Decision node: parents are the sim2real plan (bitter-fire-0679) and the two alternatives it was chosen over (Meteor75 black-butterfly-6195, Mobula6 wild-shape-7463).