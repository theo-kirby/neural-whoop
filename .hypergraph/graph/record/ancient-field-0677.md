---
node_id: 569ce496-0422-5c01-bac9-fd60c8fb00ce
slug: ancient-field-0677
title: 'Muon + reliability shaping: near-miss band buys back most of the completion (86.0→90.8%) at 2.54 s — hop-11''s NO-GO band pays off in the crash-limited regime; misses the promotion bar by 1.8 pt'
created_at: '2026-07-02T12:02:24.329196+00:00'
parents:
- royal-field-3745
- black-silence-5752
- aged-term-6809
summary: 'Muon lr 2.5e-3 + reliability shaping: crash_penalty 10→30 alone is flat (86.0→86.8%), adding the hop-11 near-miss band recovers completion to 90.8% at 2.536 s (keeps 90% of the −23% lap gain, crash halved) — partially inverts hop-11''s NO-GO: the band pays off in the crash-limited regime. Misses the pre-registered 92.6% promotion bar by 1.8 pt → no studio-baseline move; DR-on completion (0.60 vs adam 0.79) is the real deploy blocker. Packs + DR-on table attached.'
origin:
  backend: flywheel
  node_id: 569ce496-0422-5c01-bac9-fd60c8fb00ce
  slug: ancient-field-0677
  revision: 3
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 387a4a70-3516-518c-9178-86c7d7b03939
  slug: winter-thunder-0563
  revision: 0
  pushed_at: '2026-08-09T21:26:51+00:00'
  content_sha256: fd997c6529be08ab75a1248f5aaf089514dd85b5e66cd482ddc9cee506db1530
---
# Muon lr 2.5e-3 + reliability shaping — crash penalty vs near-miss band

**Hypothesis.** The Muon record-lap policy (black-silence-5752: 2.461 s, −23% vs baseline) lost −6.6 pt completion because it flies crash-limited (crash/step 3.4e-4 = 4× the adam baseline). Pricing crashes higher — crash_penalty 10→30, and additionally the hop-11 near-miss band (boundary_penalty 1.0 / margin 0.4, a NO-GO stand-alone on the adam baseline) — buys completion back without giving up the lap. Pre-registered promotion bar (control royal-field-3745): completion ≥ 92.6% at best lap ≤ ~2.83 s → studio-baseline candidate.

**Setup.** Two forks of `gate_race_air65_muon25` (commit 865f53e), ONLY reward shaping differs: `_cp30` = crash_penalty 30; `_rel` = crash_penalty 30 + boundary_penalty 1.0/0.4. [128,128]@120M on the 5090 (~5.5 min each). Eval: standard no-DR (seed 12345, 2048×1500) + DR-on companion; baselines seed-matched `gate_race_air65` (adam, 3.203 s / 92.6%) and `gate_race_air65_muon25` (2.461 s / 86.0%).

**Results (no-DR headline).**
| policy | best lap | Δ vs adam | completion | crash/step |
|---|---|---|---|---|
| air65 adam baseline | 3.203 s | — | 92.6% | 0.8e-4 |
| muon25 (parent) | 2.461 s | −23.2% | 86.0% | 3.4e-4 |
| **muon25_cp30** | **2.454 s** | −23.4% | 86.8% | 2.7e-4 |
| **muon25_rel** | **2.536 s** | −20.8% | **90.8%** | **1.7e-4** |

DR-on companion (each under its own training DR; artifact `dr_on_evals.json`): muon25 0.554 / 2.1e-3 crash → cp30 0.599 / 1.3e-3 → rel 0.597 / 1.4e-3, vs the adam baseline's 0.79 / 3e-4 (blue-unit-1398).

**Verdict — mixed/Pareto (no promotion).**
1. **The near-miss band, not the crash price, does the work.** Tripling crash_penalty alone: +0.8 pt (flat). Adding the hop-11 band: +4.0 pt more (86.8→90.8%) for only +0.08 s lap — crash/step halves to 1.7e-4. This **partially inverts hop-11 (aged-term-6809)**: the band was a NO-GO on the adam baseline because non-completion there was timeout-limited; on a genuinely crash-limited policy it pays. The primitive's value is regime-dependent, exactly as hop-11's insight predicted.
2. **Not promoted.** rel keeps 90% of the Muon speed gain (−20.8% lap) with completion 90.8% — 1.8 pt short of the pre-registered ≥92.6% bar → the ★ studio-baseline pointer stays where it is.
3. **Honesty — the DR-on gap is the real blocker for deployment.** All Muon-family policies collapse under the air65 DR (0.55–0.60 vs adam's 0.79); shaping recovers only +4.5 pt. The record lap is a clean-condition result; the adam baseline remains the deploy pick. Next lever (staged): DR-robustness for Muon (e.g. Muon with the DR-on gap as the explicit target, lr grid, or Muon→adam anneal), not more reward shaping — shaping is now within 2 pt of its no-DR ceiling.

**Lineage.** Builds on black-silence-5752 (Muon record lap, the policy being shaped) + aged-term-6809 (the near-miss primitive + the NO-GO this result conditions) under control royal-field-3745. Configs committed at 865f53e. Artifacts: full standard pack for the winner (rel) incl. run.json manifest; cp30 supporting eval/run/comparison/table; DR-on companion table.