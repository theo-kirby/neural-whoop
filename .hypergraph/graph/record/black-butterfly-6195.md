---
node_id: 19fc0763-e80d-5a96-acf9-ee31ef25a1b5
slug: black-butterfly-6195
title: 'Airframe option (set aside): BetaFPV Meteor75 Pro (~31 g) — closest to current sim mass, but too heavy'
created_at: '2026-06-29T09:53:53.832810+00:00'
parents:
- bitter-fire-0679
summary: 'Candidate airframe weighed during the 2026-06-29 selection and set aside. Meteor75 Pro: ~31 g AUW, 1102 22kKV, 45 mm props, Matrix G473, 1S 550mAh, ELRS. Its appeal was being the closest match to our current sim mass DR (28-36 g) — a near drop-in for already-trained policies — plus payload margin and forgiving handling. Set aside as the heaviest, least ''true tiny-whoop'' option, least agile. Recorded because it shaped the decision (it''s why we noticed the sim was Meteor75-massed).'
origin:
  backend: flywheel
  node_id: 19fc0763-e80d-5a96-acf9-ee31ef25a1b5
  slug: black-butterfly-6195
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 9f887b4b-7b1c-565d-9d24-205582ddbb13
  slug: young-wood-2510
  revision: 0
  pushed_at: '2026-08-09T21:26:36+00:00'
  content_sha256: 32bd923ecdc4e67ae05568ba650b59d6b09904b26f33eb7f45cf10a6fa3e5a83
---
# Airframe option: Meteor75 Pro (set aside)

A candidate considered in the airframe selection; documented because it was a real input to the decision, not the pick.

**Specs.** BetaFPV Meteor75 Pro — ~31 g AUW, 80.8 mm wheelbase, 1102 22000KV motors, 45 mm props, Matrix 1S FC (STM32G473), LAVA/BT2.0 1S ~550mAh, serial ELRS 2.4, analog/HD options.

**Why it was in the running.** Closest to our current sim airframe DR (28-36 g) — a near drop-in for policies we've already trained, minimal re-center. Bigger/heavier => more forgiving and more payload margin for a flow deck + markers.

**Why set aside.** Heaviest of the three and the least 'true tiny-whoop'; less agile; further from the light north-star. The realization that our sim is Meteor75-massed (the 28-36 g DR) is *itself* a finding this comparison surfaced.

**Lineage.** Child of the sim2real plan (bitter-fire-0679); a considered alternative to the chosen Air65 II.