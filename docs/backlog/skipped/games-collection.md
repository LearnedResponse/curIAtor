# Backlog — curiator-games (dr4ft-led)

> **Status:** skipped/deferred as of 2026-07-03. This is a post-release public-demo direction, not an
> active local work-order; reopening it requires external app/game substrate choices and public repo
> integration. Original scope: a public collection of game/sim overlays the loop maintains — led by
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

1. Scaffold `galleries/curiator-games` (public-first, like geometry/phylo).
2. **dr4ft first** — fork, mount, seed one feedback round on the drafting UI. Proves the loop on a real,
   loved app with zero engine complexity.
3. **Engine-backed mount** — a reusable backend-process mount (RCON / websocket / API); Factorio's
   dashboard is the first engine-backed app on it.
4. **Nethack + Dwarf Fortress overlays** as follow-ons on the same mount.
5. Ship as a viral public demo alongside the release.

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
