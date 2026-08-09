---
node_id: a4497e46-c568-5026-991a-6ca90a97f672
slug: old-leaf-3989
title: 'Hypothesis: a tighter standoff reward makes detector-hardening robust AND accurate (no back-off)'
created_at: '2026-06-27T19:53:32.026361+00:00'
parents:
- cool-resonance-0983
summary: 'Branches off the mixed perception result (cool-resonance-0983). That experiment showed detector-training buys robustness (condition-invariance + 65x fewer crashes) by BACKING OFF to 2.17m (track_err 0.91) instead of holding the 1.5m standoff the clean policy nails (0.08) — a conservative local optimum the wide, asymmetric reward permits (track_sigma=0.6 + flat in_view bonus => excess distance is cheap insurance). HYPOTHESIS: a tighter / asymmetric standoff reward (smaller track_sigma, an explicit penalty for distance > d*, and/or gating the in_view bonus on being near d*) removes the cheap-margin escape, so a detector-trained policy becomes BOTH robust (crash-rate ~= the current detector policy, condition-invariant) AND accurate (track_err <= ~0.2m, ~= the clean policy). Pre-registered refutation: if the tightened reward still lands at distance >> d* under noise, or only recovers accuracy by giving back crash-robustness, the back-off is a fundamental risk/accuracy tradeoff under this detector, not a reward artifact. Untested.'
origin:
  backend: flywheel
  node_id: a4497e46-c568-5026-991a-6ca90a97f672
  slug: old-leaf-3989
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
## Why
`cool-resonance-0983` found the detector-hardened target_follow policy is robust but conservative: it sits at 2.17 m vs d*=1.5 m (track_err 0.91) while the oracle-clean policy holds 1.52 m (track_err 0.08). The hardened policy even earns LOWER reward (1.17) than the clean policy does under the same noise (1.69), so it's a conservative local optimum, not the reward optimum. The current reward lets it back off for free: `track = exp(-((d-d*)/0.6)^2)` is wide (at 2.17 m it still scores 0.29) and `in_view_bonus` is a flat +0.5 regardless of distance, so extra standoff trades a little track reward for big robustness (target rarely exits FOV, dropouts matter less).

## Prediction
A reward that punishes excess distance removes the cheap-margin escape. Candidate levers (any/all):
- shrink `track_sigma` 0.6 -> ~0.3 (sharper standoff peak),
- add an explicit asymmetric penalty for `d > d*` (overshoot costs more than undershoot),
- gate `in_view_bonus` on `|d - d*|` small (only reward in-view when actually at standoff).
Expect a detector-trained policy that is BOTH robust (crash ~= 1e-5 /step, noisy==clean) AND accurate (track_err <= ~0.2 m), i.e. it beats the current detector policy's accuracy without losing its robustness.

## Refutation condition (pre-registered)
If, under the tightened reward, the detector-trained policy still sits at distance significantly above d* under noise, OR only recovers standoff accuracy by regressing crash-robustness back toward the naive policy's 4.85e-4 /step, then the back-off is a genuine risk/accuracy tradeoff forced by the detector (dropout/FOV) at this noise level — not a reward-shaping artifact — and the lever is the detector magnitudes / an explicit risk budget, not the standoff term.

## Also queued (separate hops)
- Multi-seed confirmation of cool-resonance-0983 (it is n=1; effect sizes are large but unconfirmed).
- A harsher detector regime (higher dropout / narrower FOV / bigger bearing noise) to find where the NAIVE oracle policy actually loses the target — the noise level where idea 96fbd7ef's 'collapse' framing becomes true.

## Lineage
- branches-off `00a0ca61` (the mixed detector-hardening result whose back-off this explains and proposes to fix).