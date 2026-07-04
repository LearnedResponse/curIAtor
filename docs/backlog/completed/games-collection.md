# Backlog — curiator-games (dr4ft-led)

> **Status:** first local proof landed 2026-07-03 in `galleries/curiator-games@6b061f0`;
> seeded draft-table feedback round closed at `galleries/curiator-games@b7abc62`; synthetic
> engine-backed factory overlay landed at `galleries/curiator-games@9d130a3`; roguelike and fortress
> viewer breadth landed at `galleries/curiator-games@5314217`. The local stand-in proof is now complete
> for this backlog item. Remaining real-app work is external integration: upstream repo access/license
> review, user-supplied game binaries, mods/RCON/DFHack/NLE setup, public repos, or credentials. The
> current local proof has four dependency-light Node/proxy apps: a draft-table reviewer with synthetic
> public-domain card data and three feedback-to-fix receipts, a factory diagnostics dashboard, a
> roguelike run viewer, and a fortress KPI overlay. All use fixture/synthetic state, have browser-smoke
> evidence, and have no external assets/upstream repo requirement. A public collection of game/sim overlays the loop maintains — led by
> **dr4ft** (an existing open-source MTG draft web app), with engine-backed diagnostic overlays for
> **Factorio**, **Nethack**, and **Dwarf Fortress**. Sibling to `curiator-geometry` / `phylogenetics`.
> Post-release direction, not release-track. Captured 2026-07-03.

## The pitch

Games are ideal curiator demos: rich visual UIs, passionate communities that give *dense, specific*
feedback, and viral reach. Lead with the one that's a **pure web app** (dr4ft — bullseye loop fit); the
rest are **diagnostic/KPI surfaces over a deep sim engine**, which is the reusable "engine-backed app"
pattern (strategy note: `.planning/strategy/engine-backed-apps.md`). A beloved real app the loop visibly
improves is the most persuasive proof curiator works.

## The apps (tiered by loop-fit)

- **dr4ft — MTG drafting. BULLSEYE.** An existing open-source web app (Node/Vue) with an opinionated UX
  (card grid, pick timer, pool/deck views). Fork it, point the loop at the drafting interface, and
  feedback→screenshot→fix is *native*. Real drafter community = a feedback goldmine. This alone can carry
  the collection.
- **Factorio — industrial dashboard.** A web dashboard over game state (headless server + RCON / mod
  API): production ratios, throughput, bottleneck alerts. It's literally factory automation, so it
  **bridges to the OT digital-twin** work. Loop maintains the dashboard; the engine is substrate.
- **Nethack (NLE) — web viewer.** A tileset/terminal viewer + run controls over the NetHack Learning
  Environment. Strong hacker signal; the loop-maintained part is the viewer UX, not the policy.
- **Dwarf Fortress — DFHack overlay.** A dashboard/overlay driven by DFHack: fortress KPIs (population,
  mood, resources, threats, magma incidents). The deepest sim in the set — its *state* is the product,
  which makes it the purest example of a diagnostic surface over an engine.

## The shared shape

dr4ft is a pure web UI; the other three are web front-ends over a game engine (Factorio server / NLE /
DFHack). **The loop maintains the front-end; the engine is substrate.** That's the engine-backed app
pattern — build the backend mount once (RCON/websocket/API), and Factorio/Nethack/DF are all instances
of it. Same pattern the OT digital twin uses. See `.planning/strategy/engine-backed-apps.md`.

## Work-order

1. **Scaffold `galleries/curiator-games` — first pass landed.** `6b061f0` is a public-first nested
   collection with pinned runner mode, codex auto-small settings, repo-local curIAtor command/skill
   shims, a Node same-origin proxy app, seeded SQLite feedback ledger, and a synthetic draft table that
   does not bundle card art or external assets.
2. **dr4ft first — local stand-in landed; upstream import still pending.** The current `draft_table`
   app proves the drafting-interface loop shape without cloning upstream code: pack cards, lane signals,
   pick history, table read, neighboring-seat provenance, selection-impact summaries, and a compact
   draft artifact for done replies. Seeded feedback items `250840ee`, `0665d7f0`, and `88708ebd` are
   closed through `b7abc62`. Actual dr4ft import/fork is still a true external step until the upstream
   repository URL/access and license review are pinned.
3. **Engine-backed mount — local first pass landed.** `factory_overlay` is a synthetic factory-sim
   dashboard over `engine_snapshot.json`, exposed through the same proxy mount shape and `/engine.json`
   diagnostic artifact. It proves the dashboard-over-substrate pattern without bundling Factorio,
   paid binaries, API credentials, or upstream code. A real Factorio dashboard is still an external
   follow-on until the user-supplied engine/mod/RCON boundary is pinned.
4. **Nethack + Dwarf Fortress overlays — local first pass landed.** `roguelike_viewer` is a terminal-like
   viewer over `run_snapshot.json` with `/run.json`; `fortress_overlay` is a KPI dashboard over
   `fortress_state.json` with `/fortress.json`. They prove the viewer/KPI-overlay shape without bundling
   NetHack, NLE, Dwarf Fortress, DFHack, tilesets, save files, models, or upstream code. Real NLE/DFHack
   integrations are external follow-ons until the user-supplied engine/mod boundary is pinned.
5. **Ship as a viral public demo alongside the release — external/publication step.** The local demo is
   ready at `5314217`; public repo exposure, public URLs, and any real-app community loop are release
   operations, not local code blockers.

## Scaffold verification

- `curiator --gallery galleries/curiator-games/gallery.yaml doctor --json`: passing, no errors or
  warnings.
- `curiator --gallery galleries/curiator-games/gallery.yaml smoke --json`: passing for
  `draft_table`, `factory_overlay`, `roguelike_viewer`, and `fortress_overlay` (`node --check server.js`).
- `curiator release-preflight --gallery curiator-games --fresh-clone --strict --browser-smoke --json`:
  passing at `5314217`; no tracked machine-local paths or publish-unsafe runtime artifacts.
- Feedback `250840ee` closed at `918cb58`, `0665d7f0` closed at `76c4388`, and `88708ebd` closed at
  `b7abc62`, each with rendered browser-smoke artifacts and zero console errors.
- `factory_overlay` browser smoke passed at `9d130a3`, and its `/engine.json` artifact reports the
  bottleneck, throughput gap, and no external-engine/commercial-binary/upstream-repo requirement.
- `roguelike_viewer` and `fortress_overlay` browser smoke passed at `5314217`; `/run.json` and
  `/fortress.json` report the key diagnostic state plus no external-engine/commercial-binary/upstream-repo
  requirement.

## External blockers now explicitly parked

- Actual dr4ft import/fork: blocked on upstream repo URL/access and license review.
- Real Factorio/NLE/Dwarf Fortress integrations: blocked on user-supplied engines, mods/RCON/DFHack/NLE
  setup, and any required commercial binaries or credentials.
- Public community demo loop: blocked on public repository/URL exposure and release operations.

## Guardrails

- **Loop maintains the front-end, not the engine.** Don't try to make the loop edit Factorio/DF/NLE
  internals — it iterates the overlay/dashboard/viewer.
- **Ship the overlay, not the game.** dr4ft, NLE, and DFHack are open; Factorio and Dwarf Fortress are
  commercial — bundle *our overlay code*, never game binaries; document the user-supplies-the-game step.
- **Public-knowledge only** — no private research overlay in a public collection.

## Why curiator

A beloved real app (dr4ft) is the most convincing proof the loop works, and game communities give the
densest visual feedback you can get. The engine-backed apps also **de-risk the mount pattern** before
enterprise customers depend on the same shape for OT digital twins — games are the fun, public rehearsal
for the serious substrate.
