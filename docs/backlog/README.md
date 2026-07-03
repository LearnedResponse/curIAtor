# Backlog — public roadmap

Scoped ideas and work-orders for the public curiator product. Each live item should still need a local
implementation, release action, or external operating step; shipped items move to
[`completed/`](completed/) so the backlog keeps reflecting what remains.

> Internal planning (product-direction/moat thinking, engineering refactors, strategy) lives in the
> **private `curiator-planning` repo**, surfaced to the loop as `.planning/` when present. This file is
> the public half — the release track and example collections.

## The release track (in order)

- [**public-release**](public-release.md) — release curIAtor externally on GitHub as v0.2.x with three
  public example collections (`curiator-aviato`, `curiator-ot`, math/geometry), the hero demo.gif, a
  portability pass (no machine-absolute paths in collections), SECURITY.md, and Zenodo DOI wiring.
- [**zenodo-paper**](zenodo-paper.md) — the companion software/systems paper, self-archived on Zenodo
  with a DOI (JOSS as the reviewed follow-up); the public collections are its evaluation, and a small
  `curiator stats` keeps its numbers reproducible.

## After the release

- [**public-playground**](public-playground.md) — hosted collections with **trust-tiered dispatch**,
  rolled out in phases: **phase 0 is velvet-gated** (invite-only accounts — deployable with today's
  runner, the invite list is the rate limit and the vetting), then self-serve accounts + quotas, then
  anonymous feedback held in a human-reviewed pool. The live complement to the static examples, and
  the enforcement mechanism for SECURITY.md's public-internet policy.

## Direction

- [**general-app-hosting**](general-app-hosting.md) — host *any* framework and *multi-file* apps.
  **Core landed & proven** (`curiator-aviato` runs React SSR + Rust via `proxy` mounts); framework
  scaffolds and a discoverable template menu now exist, so what remains is deeper per-framework
  hardening, live-HMR proxy ergonomics, and publishing the proof.
- [**phylogenetics-collection**](phylogenetics-collection.md) — scaffolded in
  `galleries/curiator-phylogenetics` as a **public-first** interactive companion to the tropical
  displayed-trees paper (displayed trees / tree-of-blobs / NC = D / TINNiK), seeded from an already-built
  Dash explorer **and a working Pyodide static port**. A domain-specialized sibling of
  [**math-geometry-collection**](completed/math-geometry-collection.md) for the phylo-networks
  community; first client-side-WASM-compute collection; the full eight-item seeded feedback loop is
  complete through `b1b3586`, and it ships with the paper's outreach.

## Shipped

Fully delivered public work-orders, retired to [`completed/`](completed/) for provenance.

- [**ot-hmi-demo**](completed/ot-hmi-demo.md) — OT/HMI v1 collection delivered: deterministic tank sim,
  local SQLite historian, Dash HMI, 10-item feedback-to-fix arc, and fresh-clone preflight — shipped
  `curiator-ot@36e21cf`.
- [**math-geometry-collection**](completed/math-geometry-collection.md) — seven public Dash/Plotly math
  explainers plus the first feedback-to-fix receipt and fresh-clone preflight — shipped
  `curiator-geometry@30bb155`.
