---
node_id: 47a7a096-6f8d-5608-903c-e0e7cfb5a372
slug: bitter-violet-6954
title: 'Method: Flywheel conventions + run.json reproducibility manifest (no-empty-nodes discipline) + graph re-audit'
created_at: '2026-06-28T11:48:50.294450+00:00'
parents:
- square-smoke-0918
- old-truth-3996
summary: 'Conventions + tooling upgrade aligning neural-whoop with the boxwheel/campaign discipline. Code (commit b171c30): a run.json reproducibility manifest in the standard visual pack (invoking command / config / ckpt / task / seed / eval protocol envs*steps + DR on-off / git SHA+dirty / torch + the pinned DiffAero commit), best-effort & non-fatal, no replay-contract bump; verified the viz pack emits run.json into the pack + pack_manifest, pytest -q (85) + env_check green. Docs (commits 34d0c1c, 92384b1): stated the cardinal rule (no empty nodes), the summary + body skeleton with the time_penalty exemplar (morning-base-2167), the verify-after-commit definition-of-done, deduped the stop_reason vocabulary into docs/FLYWHEEL.md, replaced the stale root->control->baseline ASCII placeholder with the real branchy multi-parent DAG, and documented the run.json row in VISUAL_CONTRACT. Graph re-audit: backfilled the 4 empirical nodes that had ZERO artifacts (flagship b4c3466f studio-baseline now carries the full 15-artifact pack incl. run.json + the decisive cross-scale table; fc3019c1 / b4681823 / 4d5ed6b9 backfilled), fixed 3 missing cluster tags on the racing trunk (ff881809 + bd57f350 -> reward-shaping, 08c0c825 -> capacity-budget; connected-subgraph respected), and added the State-of-the-frontier synthesis node (ae3fa47c). stop_reason=improved.'
origin:
  backend: flywheel
  node_id: 47a7a096-6f8d-5608-903c-e0e7cfb5a372
  slug: bitter-violet-6954
  revision: 5
  exported_at: '2026-08-09T18:23:28+00:00'
---
# Conventions + tooling upgrade (method node)

Aligns neural-whoop's Flywheel docs + the live graph with the boxwheel / campaign discipline we were missing -- the **cardinal rule (no empty nodes)**, a definition-of-done / verify step, the summary+body skeleton, and a `run.json` reproducibility manifest -- WITHOUT importing the irrelevant constraints (CPU-only / ephemeral box / publish-public-repo; we are persistent, local-on-5090, already pushing public nodes). Repairs the drift the flagship studio-baseline `b4c3466f` exhibited (a GREEN ★ node with zero artifacts).

## Code (commit b171c30)
- `eval/pack.py`: `build_run_meta()` + a `run_meta` param on `build_pack()` -> writes `run.json`: the invoking command (sys.argv), config / checkpoint / task, seed, eval protocol (n_envs x steps, DR on/off), git SHA + dirty flag, and key versions (torch + the pinned DiffAero upstream commit 291ea14). Best-effort / non-fatal (a missing git binary or torch import degrades to {}/null, matching the renderer's graceful-degradation style). Populated from the CLI args in `scripts/viz.py` and `scripts/eval.py --viz`. No replay-schema change (no contract version bump).
- Verified: the viz pack on the studio-baseline ckpt emits `run.json` into the pack dir + `pack_manifest.json`; `pytest -q` (85) and `scripts/env_check.py` green.

## Docs (commits 34d0c1c, 92384b1)
- **CLAUDE.md**: stated the cardinal rule, the summary + body skeleton (Hypothesis -> Setup -> Results(delta) -> Verdict/Honesty -> Lineage) with the `time_penalty` exemplar (`morning-base-2167`), the verify-after-commit definition-of-done, and a one-line MCP tool/skill pointer. Kept the strong true-parents / varied-kinds / honest paragraph + the tag taxonomy unchanged.
- **docs/FLYWHEEL.md**: new "Node conventions / definition of done" subsection owning the cardinal rule, the skeleton, the single `stop_reason` vocabulary (de-duplicated from AGENTS.md), the tag-every-node rule, and verify-after-commit; replaced the stale `root->control->baseline` ASCII placeholder with an honest description of the real branchy multi-parent DAG (+ synthesis nodes); fixed the baseline section so it reads as the START node, not the graph's end.
- **AGENTS.md**: tightened step 3 (cardinal rule + run.json) and step 4 (verify-after-commit); `stop_reason` now points to FLYWHEEL.md.
- **docs/VISUAL_CONTRACT.md**: documented the `run.json` row + its fields.
- (92384b1) fixed the exemplar reference: `morning-base-2167` resolves to the `time_penalty` node, not `command_follow`.

## Graph re-audit (this session)
- **Backfilled the 4 empirical nodes that had ZERO artifacts.** The flagship `b4c3466f` (the ★ studio-baseline) now carries the full 15-artifact pack incl. `run.json` + the decisive cross-scale completion table. `fc3019c1` (scale curriculum, checkpoint survives -> full pack) and `b4681823` / `4d5ed6b9` (checkpoints gone -> recovered cross-scale tables + provenance notes) backfilled.
- **Fixed missing cluster tags** on the early racing trunk: `ff881809` + `bd57f350` -> `cluster:reward-shaping`; `08c0c825` -> `cluster:capacity-budget` (respecting the connected-subgraph rule, anchor-first).
- **Added the multi-parent "State of the frontier" synthesis node** (`ae3fa47c`) over each cluster's current best -- the campaign's "what won and why" navigational anchor our deep graph lacked.

## Stop reason: improved (tooling/method -- discipline imported, flagship drift repaired)