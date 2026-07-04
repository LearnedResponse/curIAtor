# Backlog — curiator-phylogenetics collection (public interactive companion)

> **Status:** active dogfood collection as of 2026-07-03. The local collection and seeded loop are
> complete; keep local static-publish/browser-smoke evidence current and only mark Pages enable/run/URL
> wiring as external. Scaffolded 2026-07-02 in nested repo `galleries/curiator-phylogenetics`.
> Seed commit `713b39e` carries a **public-first** collection seeded from an already-built
> displayed-trees viz suite: a Pyodide static proxy app (`tinnik_static`) and a Dash local
> explorer (`tinnik_dash`). The seeded feedback loop is complete on `curiator/auto` through `b1b3586`:
> five static-app receipts and three Dash receipts cover the CF ternary explanation, boot-status
> phases, network-selector caveat, strictness-witness label, CF triple classifier, gamma-control copy,
> claim-boundary panel, and paper-story section map. Static GitHub Pages publishing is now prepared at
> `0095229` with a Pages workflow, `.nojekyll`, and publishing docs; remaining public-hosting work is
> external: enable/run Pages, capture the public URL, and link it from the paper/release surfaces.
> Captured 2026-06-30; first scaffold landed 2026-07-02.

## The pitch

A **public, server-less interactive gallery for tropical phylogenetic networks** —
displayed trees, tree-of-blobs, NC = D, quartet concordance factors, TINNiK — seeded
from a viz suite that already exists and maintained by curiator from a
phylogeneticist's feedback. It plays **three roles at once**:

1. **The interactive companion to the displayed-trees paper**
   (`kt_next/paper_drafts/tropical_displayed_tree_blobs/`) — the "differentiator no
   competing group will build" that the outreach plan flagged; it ships *with* the paper.
2. **A public phylo-networks gallery** for a real external community (the
   Allman / Rhodes / Baños / Mitchell TINNiK / MSCquartets / PhyloNetworks crowd) —
   track-record-building in a field that isn't the amplituhedron's.
3. **curiator's first client-side-compute (browser-WASM / Pyodide) collection** — the app
   does its math *in the browser*, served same-origin via the already-proven `proxy` mount;
   it stress-tests the overlay + curator loop over a *static-but-computational* page, and
   it's the domain-specialized sibling of
   [math-geometry-collection](completed/math-geometry-collection.md).

Why public-first is *reachable now*: the hard part is already done — a **validated
network-coalescent engine runs byte-identical in the browser** (CPython → WASM via
Pyodide, numpy + networkx), plotly.js renders, `plotly_click` drives detail panels,
and the whole thing is **pure static / GitHub-Pages-hostable** with CDN deps. No
server, no re-implementation.

## What's already built (the seed) — `kt_next/notes/viz/`

- **`tropical_displayed_trees/app.py`** — a Dash "TINNiK explorer" with six coupled
  panels: **CF-ternary** (clickable) → **quartet detail / Trop Gr(2,4) tripod** →
  **how NC is computed (integration over gene trees)** → **Lemma 9 (first coalescence
  fixes the topology)** → **NC = D made legible** → **continuous walls in 3-D**
  (tropical-coefficient space λ ∈ ℝ³).
- **`tropical_displayed_trees_web/`** — the Pyodide static port: the *same* validated
  `nmsc.py` engine in-browser, 13 networks, and all panel compute in `web_compute.py`
  (`cf_points`, `quartet_detail`, `nc_vs_d_rows`, `gamma_sweep`, `tree_of_blobs_graph`,
  `tripod_data`, `lemma9_data`, …). Deploys as four static files.
- **Supporting libraries** (validated, reused verbatim): `nmsc.py` (coalescent),
  `constructors.py` / `extra_nets.py` (network builders — the real lane networks, not
  toy data), `bhv.py` + `network_geodesics.py` (BHV treespace), `tinnik_plots.py`,
  `walls_3d.py`, `render_paper_figs.py` (the paper figures).
- **The papers + decks**: `paper_drafts/tropical_displayed_tree_blobs/` (+
  `…_continuous_walls/`); slides in `notes/external_presentations/`.

## Work-order

1. **Scaffold `galleries/curiator-phylogenetics`** via `curiator init galleries/curiator-phylogenetics --git` —
   done: standalone, **public-first** collection, `runner.mode: pinned`, **`git: {commit: true}`** (the build story is
   the deliverable), `auth:` set so a reviewer's feedback is attributed. README links wait for a public
   repository / deploy URL. `LICENSE`: Apache-2.0.
2. **Mount strategy (mixed).** Serve the Pyodide static panels via the already-proven
   **`proxy` mount** (point it at a static file server — e.g. `python3 -m http.server` — so
   the browser-WASM page loads same-origin under the overlay); the rich Dash explorer via
   `dash-inproc` for local iteration. First pass landed as `tinnik_static` (`python -m http.server`
   on port 8751) and `tinnik_dash` (Dash module `app`). **Wire the static/proxy path first** — it is the public
   path and the more interesting integration (a computational page, not a live app process).
3. **Seed the gallery.** First pass landed two source-preserving apps: the browser/Pyodide
   static explorer and the full Dash explorer. Follow-on: split the explorer's six panels into **focused apps** the curator
   can iterate independently (CF-ternary, quartet-tripod, NC-integration, Lemma-9, NC = D,
   continuous-walls-3D), plus the displayed-trees → tree-of-blobs viewers
   (`viz_displayed_trees`), BHV geodesics, and `walls_3d`. Tag each **instrument** (paper
   evidence) / **explainer** / **toy**, per the same discipline as the paper hygiene lint.
4. **Public hosting.** Local publishing path is prepared: `.github/workflows/pages.yml` validates the
   static Python/JS assets, uploads `apps/tinnik_pyodide_static/`, and deploys via GitHub Pages Actions;
   `.nojekyll` keeps the Python/Pyodide assets served directly. Remaining external work: enable Pages
   from GitHub Actions, run the workflow on the public repo, capture the URL, and **link it from the
   paper** ("interactive companion at [URL]").
5. **Seeded phylogeneticist feedback** (`seed/feedback.yaml`, authored as a
   computational-phylogeneticist — **this is where Adam's domain voice plugs in**): ~8–12
   items such as *"overlay the empirical CFs on the theoretical ternary," "let me paste my
   own quartet CFs," "add a species-tree toggle," "collapse trivial blobs," "make the
   TINNiK inference (CFs → tree-of-blobs) interactive," "explain why it's structure not
   weights," "show the min-plus envelope over displayed trees as the reticulation mixture."*
   First seed file landed with eight reviewer items; all eight are now done.
6. **Run the loop** — `curiator seed && curiator watch`: the curator evolves each app
   fix-by-fix, committing per fix with `Feedback-From` trailers → the git log *is* the
   gallery growing from paper-figures into an explorable public companion. Eight loop receipts
   have landed through `b1b3586`; no seeded reviewer items remain open.
7. **Verify by running** (not asserting): the static apps load in-browser (Pyodide boots,
   panels compute, clicks work); the Dash explorer mounts; the seeded feedback actually
   transforms them (diff before → after); a fresh public deploy serves the improved gallery.

## Scaffold verification

- `curiator --gallery galleries/curiator-phylogenetics/gallery.yaml doctor`: passing, no
  errors or warnings.
- `curiator --gallery galleries/curiator-phylogenetics/gallery.yaml smoke`: passing for both
  apps (`tinnik_static`, `tinnik_dash`).
- `curiator stats --json`: 8 cycles, 8 replied/done cycles, 8 curator commits, latest feedback-loop
  receipt `b1b3586`.
- `curiator release-preflight --gallery curiator-phylogenetics --fresh-clone --json`: passing at
  `0095229`; the temp clone runs both app smoke hooks and finds no tracked machine-local paths.
- Static app checks: `python -m py_compile ...` and `node --check app.js` passed; a temporary
  `python -m http.server` on port 8751 returned HTTP 200 for `/`.
- Static publishing checks: `.github/workflows/pages.yml` parses as YAML, the workflow's Python syntax
  check avoids writing `__pycache__` into the Pages artifact, and `.nojekyll` is included.
- Dash app check: `python -m compileall -q apps/dash_suite` passed.
- `galleries/curiator-phylogenetics` is initialized as its own git repo with seed commit `713b39e`;
  the current head is `0095229`.

## Expansion apps (beyond the seed)

- **Empirical-CF simulator** — sample gene trees under the NMSC → observed CFs overlaid on
  the theoretical ternary (the empirical → theoretical bridge).
- **Interactive TINNiK inference** — paste CFs → infer the tree-of-blobs (the actual method,
  as a teaching tool).
- **Tropical-mixture / reticulation explorer** — the min-plus envelope over displayed trees,
  showing reticulation *as* mixture.
- **Continuous-walls companion** — the second paper (`…_continuous_walls`).
- **BHV geodesic between two networks** / displayed-tree distance calculator.

## Guardrails

- **Public but honest.** The apps are paper companions; every claim matches the paper's
  status — NC = D is **proved**, but the adjacency criterion (single-flip
  restricted-Voronoi-activeness) is **open**; don't let an app imply otherwise. Link the
  paper's `claim_boundary.md`.
- **Byte-identical engine.** The browser runs the *same* validated `nmsc.py` — never a JS
  re-implementation (that is the port's whole integrity claim). The web copies are
  byte-identical to the Dash source; keep them in sync, don't fork them.
- **Pure static / no server / no PII** for the public tier (CDN deps over HTTPS).
- **License:** Apache-2.0 (matches curiator and the paper's artifact bundle).
- **Scope:** seed from the built suite first; the expansion apps are follow-on, not v1.

## Strategic dependency (the reverse pointer)

This collection is **part of the displayed-trees paper's outreach, not a side quest**. It
is the interactive companion the outreach plan named as a differentiator. It slots into the
**public-release track** as another public collection (a domain-specialized sibling of
[math-geometry-collection](completed/math-geometry-collection.md)) and as an evaluation collection for
`zenodo-paper.md`. Build
it **alongside** the paper's arXiv/timestamp step so the paper can link it on day one.

## Platform spectrum (roadmap, not scope)

- **Pyodide static** (public, server-less) — this demo's public tier, ready now.
- **Dash-inproc** (local, rich) — the full explorer for iteration.
- **Public curiator instance** (later) — hosting multiple collections behind one overlay.

## Dogfood payoff

Different from the other collections: this is the **first client-side-WASM-compute**
collection (Pyodide math in the browser) and the **first tied to a specific paper's
outreach**. It stress-tests the same-origin overlay + curator loop over a
*static-but-computational* page and a public deploy — expect it to *find* proxy-mount and
static-asset bugs. That's the point.
