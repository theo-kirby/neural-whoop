---
node_id: c92c91db-f24b-5e40-b2ac-24715b3ed01c
slug: rapid-union-8239
title: 'hand_follow speed-envelope: the EMA''s benefit on ABRUPT motion decays with speed and VANISHES at ~4.5 m/s (operating range mapped)'
created_at: '2026-06-28T07:02:48.689029+00:00'
parents:
- wandering-mode-7957
- cold-sky-6425
summary: 'Maps where the hand_follow GREEN (cold-sky-6425, EMA recovers abrupt-motion follow) reaches its limit -- the lag caveat it flagged. Swept the zigzag hand speed 1.8/3.0/4.5 m/s for detector+EMA(0.85) vs raw detector, d*=0.8, [128,128]@120M seed0, eval 2048x1500 seed12345. RESULT: the EMA''s advantage DECAYS MONOTONICALLY with speed and crosses ZERO around 4.5. follow_hold_rate EMA-over-detector gap: +0.355 @1.8 (0.985 vs 0.630), +0.186 @3.0 (0.692 vs 0.506), +0.003 @4.5 (0.443 vs 0.440 -- gone); and track_err CROSSES OVER -- at 4.5 the EMA (0.592) is actually WORSE than raw detector (0.564). Mechanism: on a fast, sharply-reversing hand the EMA''s smoothing LAG can''t track the reversals, so the lag cost exactly cancels the variance-reduction benefit. So the EMA is the right primitive within an OPERATING RANGE (near-total recovery <=1.8, partial <=3.0, no benefit past ~4.5). This is the ABRUPT-motion analogue of the smooth-motion speed envelope (wandering-mode-7957) and ties the perception branch together: past the envelope no simple CAUSAL (lag-introducing) filter helps -- consistent with the filtering-thread close (old-pond-5686, residual gap = detector information limit). Configs 6834fb1; measurement, no code change.'
origin:
  backend: flywheel
  node_id: c92c91db-f24b-5e40-b2ac-24715b3ed01c
  slug: rapid-union-8239
  revision: 6
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: cb34b133-4999-5ecc-ab8c-2ec1ae7f3fdf
  slug: hidden-truth-3948
  revision: 0
  pushed_at: '2026-08-09T21:27:48+00:00'
  content_sha256: 2e019824814580acc7da81bf143bd3665de63876709bfe2012c36e86a366cda0
---
## Setup
`hand_follow` GREEN (`cold-sky-6425`) showed the EMA recovers abrupt-motion follow at zigzag speed 1.8, but flagged: 'a faster/sharper hand could eventually expose the EMA lag.' This hop maps that boundary -- swept the zigzag hand speed **1.8 / 3.0 / 4.5 m/s** for **detector+EMA(0.85)** vs **raw detector** (d*=0.8, [128,128]@120M seed 0, eval 2048x1500 seed 12345; 1.8 = the `cold-sky-6425` anchors).

## Results
| speed | filter | follow_hold_rate | track_err (m) | in_view |
|---|---|---|---|---|
| 1.8 | detector | 0.630 | 0.359 | 0.986 |
| 1.8 | **+EMA** | **0.985** | 0.153 | 0.995 |
| 3.0 | detector | 0.506 | 0.491 | 0.930 |
| 3.0 | **+EMA** | **0.692** | 0.319 | 0.952 |
| 4.5 | detector | 0.440 | 0.564 | 0.890 |
| 4.5 | **+EMA** | 0.443 | **0.592** | 0.912 |
| | | EMA hold-gain: **+0.355 / +0.186 / +0.003** | | |

## Findings
1. **The EMA's benefit decays monotonically with speed and vanishes at ~4.5.** hold-rate gain over raw detector: +0.355 (1.8) -> +0.186 (3.0) -> +0.003 (4.5). At 4.5 the EMA is statistically no better than no filter on hold.
2. **track_err CROSSES OVER.** At 4.5 the EMA (0.592) is actually WORSE than the raw detector (0.564) -- the smoothing lag is now a net cost.
3. **Mechanism = lag.** On a fast sharply-reversing hand, the EMA can't follow the reversals (it averages across them), so its lag cost exactly cancels the per-fix variance-reduction benefit. This is the same lag the predictive filters tried (and failed) to remove (`autumn-cherry-1696`/`old-pond-5686`).
4. **Operating range.** The EMA is excellent <=1.8 (near-total recovery), useful at 3.0 (partial), and provides no benefit past ~4.5. A clean deployable envelope for the primitive.

## Verdict
**Measurement: the EMA precision primitive has an OPERATING RANGE on abrupt motion (~<=3 m/s); past ~4.5 m/s its smoothing lag cancels the benefit and no simple causal filter helps.** Quantifies + confirms the `cold-sky-6425` lag caveat. Ties the perception branch together: this is the abrupt-motion twin of the smooth-motion envelope (`wandering-mode-7957`), and the past-envelope regime is exactly the detector INFORMATION limit the filtering thread closed on (`old-pond-5686`). To follow a very fast jerky hand you need a better detector (lower per-fix noise), not a cleverer causal filter. Configs committed as the reproducible recipe; no code change.

## Honesty / limits
Single seed per point; the cross-over is sharp and monotonic, so the qualitative envelope is robust, but the exact break speed (~4.5) is approximate. d*=0.8 close-follow throughout. A non-causal (smoother, look-both-ways) filter could in principle beat the EMA past the envelope but isn't deployable (needs future fixes); a predictive filter doesn't help (filtering thread). So the honest deployable story is: EMA within range, better detector beyond.

## Lineage
- **builds-on** `bfdbedd7` (cold-sky-6425, hand_follow GREEN): maps the operating envelope of the abrupt-motion EMA recovery it demonstrated.
- **informed-by** `8c66efec` (wandering-mode-7957, smooth-motion speed envelope): the same lag-vs-speed tradeoff, now measured on abrupt motion.

## Artifacts
hand_speed_envelope.png (hold + track_err vs speed, EMA vs detector), hand_speed_envelope_table.json. Configs 6834fb1.