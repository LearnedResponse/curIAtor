# Backlog — math/geometry example collection (public)

> **Status:** scaffolded 2026-07-01 in nested repo `galleries/curiator-geometry`. The third public example for the
> [release](public-release.md) — and the origin story made public: curIAtor's shell was proven over
> dozens of feedback→fix cycles in a private research repo full of interactive geometry explainers
> before it was extracted. **The IP guardrail up front:** this is a NEW collection of public-knowledge
> classics. `curiator-Kwisatz` (the private 63-app research overlay) stays private; nothing
> research-novel crosses over. The runner stays research-free (CLAUDE.md) — math here is *content* in a
> collection repo, exactly like revenue charts are content in `curiator-aviato`.

## Why a math collection at all

- **It's the native habitat.** Interactive explainers — one idea, one figure, sliders — are the
  highest-density demo of the loop: "label the axes," "the legend covers the chart," "add the
  degenerate case ε=0 as a view" is exactly the feedback a curator dispatches well, and it's the actual
  usage pattern the private origin repo proved at 63-app scale.
- **It's the friction-free example.** Pure Dash/Plotly + numpy: no external data (finance), no live
  feed (OT), no Node/Rust toolchain (aviato). `git clone` → `curiator up` just works — likely the first
  collection a stranger actually runs, so it carries the quickstart.
- **It's the audience.** Researchers and educators who build one-off visualizations are exactly who
  self-hosts a tool like this — and who the Zenodo/paper distribution channel reaches.

## The apps (public-knowledge classics; one deliberately rough)

Textbook material only, each one idea + sliders:

- **Polytope explorer** — Platonic/Archimedean solids, Schlegel projection, V−E+F (Euler) live counter.
- **Voronoi ⇄ Delaunay playground** — drag points, watch the duality flip.
- **Domain coloring** — the complex phase-portrait classic (zeros/poles as hue singularities).
- **Curvature explainer** — osculating circle rolling along a parametric curve.
- **Convex hull, step by step** — incremental construction with a step slider.
- **Simple normal crossings and blow-up** — public local-chart explainer inspired by the high-rated
  private `snc_explainer`, rebuilt from scratch as textbook content.
- **Conifold slice explorer** — public `xy - zw = 0` slice explainer inspired by high-rated
  singularity feedback, again rebuilt from scratch.

One of these ships **deliberately rough** (missing labels, clipped legend, no edge-case handling) — the
collection's `aviato`; the seeded queue fixes it on camera. Each app exports `build_app()` +
module-level `app`, `dash-inproc` mount, per-app `smoke:`, `git: {commit: true}` — the self-building
mechanism proven in `curiator-finance`.

## Candidate filter from `curiator-Kwisatz`

The private 63-app Kwisatz gallery is a useful taste signal, not a source repository. The current
feedback ledger has 12 apps with at least one 4+ star rating:

- **Promote to public-safe toy models:** `snc_explainer`, `conifold_schur_explainer`, and pieces of
  `cag_playground`, because the core ideas can be expressed as textbook algebraic-geometry explainers.
- **Keep as inspiration only:** `bcfw_tile_viewer`, `m1_amplituhedron_viewer`, `m2_amplituhedron_viewer`,
  `plabic_bridge_viewer`, `meadows_viewer`, `general_viewer`, and `a1032_tile_atlas`. They are good
  interaction patterns, but too close to private research/proof lanes unless reimplemented as clearly
  public toy examples with no private claims or data.
- **Maybe later:** `qda_genus_explainer` and `nontop_optima`; useful visual patterns, but not the
  first quickstart story.

## Work-order

1. `curiator init galleries/curiator-geometry` — done.
2. Write the apps — numpy/plotly only, deterministic, no data files beyond generated ones — done for
   the first seven-app seed.
3. `seed/feedback.yaml` authored as a mathematician-reviewer — done; the feedback must read like a colleague
   at a whiteboard ("the ±√μ branches need distinct line styles — solid stable, dashed unstable"), not
   a QA checklist.
4. Run the loop, keep the commits: the git log = the collection polishing itself.
5. README + link from the main repo's Examples — README link prepared; the before/after screenshots
   feed the [paper](zenodo-paper.md)'s case-study section.

## Current checks

- `curiator doctor` against `galleries/curiator-geometry/gallery.yaml`: passing, no errors or warnings.
- `curiator smoke` against `galleries/curiator-geometry/gallery.yaml`: passing for all seven apps.
- Direct import/build check: every Dash module exposes a layout through `build_app()`.
- `galleries/curiator-geometry` is initialized as a git repo on `main` with seed commit `c409fcf`; current
  head `e6d9141` adds repo-local `.claude/commands/curiator.md` /
  `.agents/skills/curiator/SKILL.md` interactive shims and switches the public collection to
  `runner.mode: pinned`.

## Guardrails

- **Public-knowledge math only** — nothing from active research, nothing from Kwisatz. Rule of thumb:
  if an app needs a citation more recent than a textbook, it's out of scope.
- **Zero toolchain, stays zero** — numpy + plotly, seeded RNG where any randomness exists. This
  collection is the "no-friction" proof and must remain the easiest of the three to run.
