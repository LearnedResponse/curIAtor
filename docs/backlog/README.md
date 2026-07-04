# Backlog — public roadmap

Scoped ideas and work-orders for the public curiator product. Each live item should still need a local
implementation, release action, or external operating step; shipped items move to
[`completed/`](completed/) so the backlog keeps reflecting what remains.

> Internal planning (product-direction/moat thinking, engineering refactors, strategy) lives in the
> **private `curiator-planning` repo**, surfaced to the loop as `.planning/` when present. This file is
> the public half — the release track and example collections.

## Release Gate

These stay live until the public-release bar is met. The rule is: make as much local/dogfood progress as
possible, and mark only the irreducible external blockers (public repo ownership, API keys, paid
licenses, DOI services, hosted credentials) at the point they are actually reached.

- [**public-release**](public-release.md) — release curIAtor externally on GitHub as v0.2.x after the
  core examples and dogfood collections are fleshed out, browser-smoked, and reproducible. External
  blockers remain public pushes/tags, PyPI Trusted Publisher, GitHub/Zenodo wiring, badges, and
  off-machine release validation.
- [**zenodo-paper**](zenodo-paper.md) — the companion software/systems paper. Local stats, draft,
  figures, metadata, and PDF build scaffolding exist; continue refreshing evidence from dogfooded
  collections until final human review and Zenodo/DOI deposit.

## Dogfood Before Release

- [**general-app-hosting**](general-app-hosting.md) — framework-agnostic app hosting is landed and proven;
  keep hardening template/base-path/HMR behavior and dogfood proxy/static/Dash-suite combinations before
  release.
- [**phylogenetics-collection**](phylogenetics-collection.md) — local collection and seeded loop are in
  place; continue dogfooding/static-publish checks and mark only Pages/public-URL wiring as external.
- [**games-collection**](games-collection.md) — local stand-in breadth is complete across draft,
  factory, roguelike, and fortress overlays; remaining real-app work is parked on external upstream,
  licensed-engine, and public-demo operations.
- [**ot-digital-twin**](ot-digital-twin.md) — push OT v2 toward a local engine-backed/digital-twin proof;
  mark OpenModelica/FMU/toolchain or licensed-substrate blockers only when reached.
- [**curiator-ml**](curiator-ml.md) — build a local open-benchmark diagnostic loop before considering
  Kaggle/API-key paths.

## Hosted Pilot

- [**public-playground**](public-playground.md) — keep local hosted-pilot gates and dry-run evidence
  current; the actual external deployment remains blocked on hosting credentials and public exposure.

## Shipped

Fully delivered public work-orders, retired to [`completed/`](completed/) for provenance.

- [**ot-hmi-demo**](completed/ot-hmi-demo.md) — OT/HMI v1 collection delivered: deterministic tank sim,
  local SQLite historian, Dash HMI, 10-item feedback-to-fix arc, and fresh-clone preflight — shipped
  `curiator-ot@36e21cf`.
- [**math-geometry-collection**](completed/math-geometry-collection.md) — seven public Dash/Plotly math
  explainers plus the first feedback-to-fix receipt and fresh-clone preflight — shipped
  `curiator-geometry@30bb155`.
