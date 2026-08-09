---
node_id: 678a6c3c-7157-5ef2-87c0-56a7d83e6a03
slug: wild-shape-7463
title: 'Airframe option (superseded): Happymodel Mobula6 2024 V3 (~17.6 g) — the initial pick, later swapped for Air65 II'
created_at: '2026-06-29T09:54:04.087451+00:00'
parents:
- bitter-fire-0679
summary: 'Candidate airframe that was the leading pick during the 2026-06-29 discussion before being superseded by the BetaFPV Air65 II. Mobula6 2024 V3: ~17.6 g, 65 mm, 0702 28kKV, CrazyG473, analog Nano5 155° cam, OpenVTX, serial ELRS. Chosen first as the true light/twitchy tiny-whoop. Superseded by the Air65 II (same ~17 g mass class, so the sim re-center is unchanged) on durability + BetaFPV-ecosystem grounds. Kept as the decision-history record.'
origin:
  backend: flywheel
  node_id: 678a6c3c-7157-5ef2-87c0-56a7d83e6a03
  slug: wild-shape-7463
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: de82e999-8385-52ca-be6c-7560666d37f8
  slug: white-brook-3805
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 09ffd8f6731907920c86d77bdf6dcb5f143b3ffd15839ff96de29970e19fb83d
---
# Airframe option: Mobula6 2024 V3 (superseded)

The initial leading pick in the sim2real discussion, recorded for the decision history before the switch to the Air65 II.

**Specs.** Happymodel Mobula6 2024 V3 — ~17.6 g, 65 mm wheelbase, 0702 28000KV, Gemfan 1208 props, CrazyG473 5in1 (STM32G473), analog Nano5 1200TVL 155° cam, OpenVTX, serial ELRS 2.4.

**Why it led first.** The true light/twitchy ~17 g tiny-whoop — the closest match to the light north-star, well below the Meteor75 mass.

**Why superseded by Air65 II.** Same ~17 g mass class (so the sim re-center window is unchanged), but the Air65 II wins on durability (3-point FC mount, ~80% less crash damage — decisive for a crash-heavy autonomous bring-up), best-in-class reviews, and BetaFPV ecosystem / parts / battery commonality. The dynamics gap is ~identical either way; the call was about iteration cost on hardware.

**Lineage.** Child of the sim2real plan (bitter-fire-0679); the alternative the chosen Air65 II was picked over.