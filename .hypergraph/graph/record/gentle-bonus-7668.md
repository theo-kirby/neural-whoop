---
node_id: 2605c2cb-cd33-5c3e-a376-fa6bd4ec1372
slug: gentle-bonus-7668
title: 'Tooling: Studio light/dark theme toggle + universal greybox environment (sized per course)'
created_at: '2026-07-15T10:22:59.054402+00:00'
parents:
- plain-thunder-3982
summary: 'Built the Real tab''s greybox reference room out into a full theme system and made it universal, vs the 2-tab-overhaul parent (plain-thunder-3982). New web/studio/environment.js (createEnvironment(view) → setTheme/setSize/dispose) is the single owner of the greybox room + scene chrome (background/fog/light intensities), shared by BOTH scenes. A ☾/☀ toggle in the sidebar corner themes the 3D scenes AND the DOM sidebar together (data-theme + localStorage[''nw_theme'']); default = Light (soft-grey backdrop + white/grey sidebar), dark keeps the original near-black look — promoted the hardcoded state colours (command/chip/danger/issue tints, hero overlay) to CSS vars so both themes set them, and made the canvas charts read their strokes from --line/--fg/--on. The greybox is now on EVERY tab: the Sim scene switched grid:false and sizes the room per course (courseBounds now returns footprint+zMax → simEnv.setSize), the editor sizes it to the arena preset (onArena callback), Real keeps a fixed 10 m room. buildRoom gained a decoupled height + palette + a front-facing own-plane floor, which also fixed the label: the baked text was a mirrored ''[PROTOTYPE MAP]'' on BackSide faces → now reads ''PROTOTYPE'' the right way round on the floor. Verified: node --check on all edited/new JS + curl 200 for /, environment.js, geometry.js, scene.js, bench.js, main.js on the fake-bridge Mac serve; the exact-greys/contrast visual pass is Theo''s (WebGL can''t be driven headlessly). Commit e9c61e6; docs/STUDIO.md updated. Method node — no metric claim.'
origin:
  backend: flywheel
  node_id: 2605c2cb-cd33-5c3e-a376-fa6bd4ec1372
  slug: gentle-bonus-7668
  revision: 2
  exported_at: '2026-08-09T18:23:28+00:00'
flywheel:
  node_id: 5416c37f-ca5e-5799-8801-ba36c8bd159b
  slug: tight-pond-9831
  revision: 0
  pushed_at: '2026-08-09T21:28:03+00:00'
  content_sha256: 579623f189f661fc4e6dfb720c36ad0c3d30972ec10403659eeb16f626927340
---
## Goal

Build the Real tab's new greybox reference room (`buildRoom`/`greyboxTexture`, added in the greybox-room commits `a6580db`/`3093c8d`/`2cd14d8` on top of the 2-tab overhaul) into a **full theme system** and make it **universal**: a light/dark toggle that themes both the 3D scene and the DOM sidebar, a light backdrop by default, and the greybox on **every** tab — including the Simulation tab, which still used the flat 160 m ground + `GridHelper`.

Note on lineage: the three greybox-room commits were shipped but never got their own Flywheel node, so this node's true graph parent is the 2-tab-overhaul node (`e306e2c3` / plain-thunder-3982) and it folds the greybox-room context in here.

## Setup / what changed (vs parent `e306e2c3`, the 2-tab-overhaul state)

**1. New `web/studio/environment.js` — the themed environment manager.** `createEnvironment(view)` → `{ setTheme, setSize, dispose }` is the single owner of a scene's greybox room + scene chrome. It holds an extra room-fill `HemisphereLight` and, per theme, sets `scene.background` / `scene.fog` / the ground tint / the scene's hemi+sun+fill intensities (via light handles now returned from `scene.js`). Two palettes (tile texture + scene) — **light** (scene bg `#c4c8cf`, tiles `#9aa0a9`, soft gridlines `#d7dbe1`, dark-on-light label) and **dark** (bg `#141414`, tiles `#1c1c1c`, `#3a3a3a` lines — the original look). `setTheme` rebuilds the `CanvasTexture` from the active palette + swaps chrome; `setSize` disposes the old room (geometry + per-face textures) and rebuilds at a new footprint/height.

**2. `geometry.js` — extended `buildRoom` + fixed the mirrored label.** Signature now `buildRoom(world, {size, height=size, floorZ, palette})`: footprint decoupled from height so big spread courses don't get an absurd ceiling; per-axis texture repeats keep every square 1 m on walls even when height≠footprint. `greyboxTexture(palette, rx, ry)` is palette-driven. **The label read a mirrored `[PROTOTYPE MAP]`** (baked onto `BackSide` box faces) — the floor is now its own **front-facing `DoubleSide` `PlaneGeometry`** sitting just above the box bottom, so its baked text reads correctly as **`PROTOTYPE`** / **`1 METER`**; the four walls + ceiling stay a `BackSide` box so near walls cull and never occlude the drone.

**3. `scene.js`** — returns light + ground handles (`lights:{hemi,sun,fill}`, `ground`) so `environment.js` owns bg/fog/intensities instead of baking a dark value; the Sim tab now passes `grid:false` (the room replaces the flat grid+ground).

**4. `main.js`** — theme state + `nw_theme` persistence applied to `data-theme` early (no flash) + `applyTheme(theme)` (sets `data-theme`, writes localStorage, calls `simEnv.setTheme` + `bench.setTheme`, updates the toggle glyph, repaints charts). Constructs `simEnv = createEnvironment(view)`; sizes the Sim room per course after `playback.setEpisode` (`courseBounds` now also returns `footprint`+`zMax`). Chart strokes now read `--line`/`--fg`/`--on` from CSS vars so they repaint per theme. `☾/☀` toggle wired mirroring the divider pattern.

**5. `bench.js`** — uses `createEnvironment` (10 m room) instead of the ad-hoc `buildRoom` + hemi light; exposes `setTheme`; trend strokes read `--fg` (cyan/amber stay fixed signal hues).

**6. `editor.js`** — `onArena(radius)` callback so edit mode sizes the room to the arena preset (guarded to edit mode in `main.js` so the editor's async preset-init can't shrink a course-sized room in play mode).

**7. `index.html`** — `:root` holds the dark set as the fallback; `:root[data-theme="light"]` overrides to the white/grey palette; the hardcoded state colours (`.hud .v.cmd-*`, `.chip.cmd-*`, `.btn.danger`, `.issue.*`, hero-overlay chrome) are promoted to vars with dark+light values; a light-theme `<select>` chevron (darker stroke); the theme-toggle button in a flex `.brand` row.

## Results

- `node --check` clean on all edited/new JS (`environment.js`, `geometry.js`, `scene.js`, `bench.js`, `editor.js`, `cameras.js`, `main.js`, `playback.js`).
- Fake-bridge serve on the bench Mac (`NW_FLIGHT_FAKE=1`, CPU venv): `/`, `/environment.js`, `/geometry.js`, `/scene.js`, `/bench.js`, `/main.js`, `/cameras.js`, `/editor.js`, `/index.html` all **200**; `/api/policies` + `/api/courses` still 200 (backend untouched). Served `index.html` carries the `data-theme="light"` block + the `data-h="theme"` toggle; served `environment.js` carries `THEME_PALETTES`.
- Pure frontend / viz change — no obs/act contract, env, or training-path touch.

## Verdict / Honesty

Shipped (method node — no metric claim). The final **visual** pass — exact greys, drone contrast on the dark floor, light-mode legibility, room sizing across `tight`/`giant`/`spread` — is **Theo's**: WebGL can't be driven headlessly here, so it's backed by `node --check` + curl-200 + the annotated light-vs-dark schematic (attached). Palette values are first-pass and meant to be tuned on that visual pass. The procedural drone glyph's dark plastics are left as-is (the light room floor is mid-grey so it stays visible; the loaded CAD replaces it anyway).

## Lineage

- Parent `e306e2c3` (plain-thunder-3982) — the Studio 2-tab overhaul; this node's genuine graph ancestor and the base the greybox-room commits built on. The greybox room itself landed in `a6580db`/`3093c8d`/`2cd14d8` (no node of their own — folded in here).
- Commit `e9c61e6` (`theo-kirby/neural-whoop`, main). Docs: `docs/STUDIO.md` updated (theme toggle + universal greybox).