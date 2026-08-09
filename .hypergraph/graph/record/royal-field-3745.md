---
node_id: 66b9c0fb-1e0c-54de-b79a-34566b0d8827
slug: royal-field-3745
title: 'Control: Muon reliability shaping + O-3 hybrid-obs latency split (staged-frontier pass)'
created_at: '2026-07-02T11:46:01.946406+00:00'
parents:
- summer-boat-5684
- dawn-field-3426
summary: 'CLOSED (objective_met): both staged-frontier items executed — (1) Muon+rel shaping: completion 86.0→90.8% at 2.536 s (90% of the lap gain kept) but misses the 92.6% promotion bar, studio-baseline NOT moved; DR-on collapse (0.60 vs 0.79) is the real Muon blocker. (2) O-3 hybrid-obs (GREEN): uplink-staleness seam shipped; onboard latency split is ~6% faster everywhere at equal completion — offboard''s cost is a baked-in conservatism tax. ~0.6 h of 3 h, 0 credits. Next: compose hybrid+Muon+rel.'
origin:
  backend: flywheel
  node_id: 66b9c0fb-1e0c-54de-b79a-34566b0d8827
  slug: royal-field-3745
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 1a1710c1-73dc-5a14-ac30-b20776419f1e
  slug: old-cake-9286
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: 0fa304307e0ce9be9d4ff3fbec325bdb50e8aaef4c32c0ed58591282f6fac60e
---
## Run contract

- Objective: Execute the two top staged-frontier items from the prior closed passes, in priority order:
  1. **Muon + reliability shaping** (from dawn-field-3426 frontier item 1): at Muon lr 2.5e-3 (record 2.461 s lap, black-silence-5752), bump crash/boundary penalties to buy back the −6.6 pt completion loss. Studio-baseline candidate if completion recovers to ≥ baseline (92.6%) while keeping ≥ half the −23% lap gain (i.e. best lap ≤ ~2.83 s).
  2. **O-3 hybrid-obs retrain** (from summer-boat-5684 frontier item 1): split the latency DR to model the onboard architecture — fresh local state obs (vel/att/rates), stale ~30 Hz + uplink-latency target channel — and quantify how much of the full-offboard latency tax (blue-unit-1398) onboard execution buys back.
- Decision criterion: standard no-DR + DR-on evals (seed 12345, n_envs 2048, steps 1500) vs the seed-matched air65 baseline `runs/gate_race_air65` (best lap 3.203 s, completion 92.6%) and, for (2), vs blue-unit-1398's DR-on numbers (completion 0.79). Every empirical node carries the standard visual pack + run.json.
- Start nodes: dawn-field-3426, summer-boat-5684 (closed controls staging this frontier); baselines black-silence-5752, blue-unit-1398.
- Budget ceiling: 3
- Budget unit: hours of local wall-clock on the single RTX 5090 (started 2026-07-02 ~11:45 UTC)
- Compute approval cap: 0 Flywheel credits — local-only per locked decision #3; managed compute disabled (AGENTS.md).
- Lookahead depth: 1
- Frontier width: 1 (single shared GPU; experiments run sequentially)
- Terminal condition: both experiment nodes committed with packs and verdicts, or budget ceiling reached.
- Stop reason: **objective_met** (2026-07-02; ~0.6 h of 3 h used; 0 credits; both experiment nodes committed with full packs + verdicts).

## Outcome

1. **ancient-field-0677** (Muon + reliability shaping, mixed/Pareto): crash_penalty 10→30 alone is flat (86.0→86.8%); adding the hop-11 near-miss band recovers completion to **90.8% at 2.536 s** (keeps 90% of the −23% lap gain, crash halved) — partially inverts hop-11's NO-GO (regime-dependent: the band pays on a crash-limited policy). **Missed the pre-registered 92.6% promotion bar by 1.8 pt → ★ studio-baseline NOT moved.** Honest blocker found: all Muon-family policies collapse under full DR (0.55–0.60 vs adam 0.79).
2. **soft-moon-6755** (O-3 hybrid-obs, GREEN): new uplink-staleness DR seam (commits 55ff26e/4925a61); moving 0–100 ms latency from actions to a ~25 Hz zero-order-held target channel makes the policy **~6% faster everywhere** (3.203→3.021 s clean, 3.29→3.07 DR-on) at equal-or-better completion — offboard's real cost is a conservatism tax; completion floor (~0.80) is set by non-latency DR. Quantifies the Path-B payoff before any hardware purchase.

Code: 865f53e (shaping configs), 55ff26e (uplink seam + hybrid config + tests), 4925a61 (CONTRACT.md) — all pushed to main.

## Staged frontier (next pass candidates, priority order)
1. **Compose the winners: hybrid + Muon + rel shaping** — train `gate_race_air65_hybrid` with Muon lr 2.5e-3 + the rel reward; if the −20% lap survives the onboard DR regime with completion ≥0.80 DR-on, it becomes the deploy-recipe candidate. Cheap (~6 min), highest expected value.
2. **Muon DR-robustness** — close the 0.60-vs-0.79 DR-on gap (finer lr grid 1e-3..2.5e-3, or DR-curriculum interaction); reward shaping is exhausted (within 2 pt of its no-DR ceiling).
3. **Multi-seed confirm** of the hybrid +2 pt DR-on completion (the −6% lap is outside seed noise; the completion delta is not).
4. O-2 Betaflight Air65 II flash-headroom build (Path-A go/no-go); O-1 uplink bench blocked on BOM approval.
5. Motor lag (k_mot) in WhoopDynamics + DR — confirmed modeling gap from the PufferLib comparison (dawn-field-3426 item 2).

Per-candidate note: items 1–3 are pure-GPU and fit any future grant; 4 needs a local toolchain check; 5 touches the vendored dynamics (version the change per AGENTS.md).