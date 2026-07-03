# Backlog — public roadmap

Scoped ideas and work-orders for the public curiator product. Each live item should still need a local
implementation, release action, or external operating step; shipped items move to
[`completed/`](completed/) so the backlog keeps reflecting what remains.

> Internal planning (product-direction/moat thinking, engineering refactors, strategy) lives in the
> **private `curiator-planning` repo**, surfaced to the loop as `.planning/` when present. This file is
> the public half — the release track and example collections.

## Live

No live public backlog items. Local implementation work has either shipped or moved out of the active
public backlog. External publication/hosting/DOI work is parked under [`skipped/`](skipped/) until a
human chooses to reopen it with concrete credentials, remotes, or deployment targets.

## Skipped / External

Skipped items are not shipped; they are parked so the local backlog stays drainable.

- [**public-release**](skipped/public-release.md) — local release gates and example-collection
  publication prep are in place, but the remaining work is external: push/tag/publication, PyPI Trusted
  Publisher, GitHub/Zenodo wiring, badges, and off-machine release validation.
- [**zenodo-paper**](skipped/zenodo-paper.md) — local stats, draft, figures, metadata, and PDF build
  scaffolding exist; final DOI/deposit and human PDF review are external release-time steps.
- [**public-playground**](skipped/public-playground.md) — moderation, quotas, hosted preflight, and
  backup/restore gates exist; the actual velvet-gated hosted pilot is an external deployment.
- [**general-app-hosting**](skipped/general-app-hosting.md) — the core framework-agnostic hosting work is
  landed and proven locally; remaining items are deeper hardening, HMR ergonomics, engine-backed mounts,
  and publishing the proof.
- [**phylogenetics-collection**](skipped/phylogenetics-collection.md) — the collection and seeded loop
  are complete locally; remaining work is external Pages enable/run/URL wiring plus optional expansion.
- [**games-collection**](skipped/games-collection.md) — post-release public demo direction requiring
  external/open-source game app integration and user-supplied game substrates.
- [**ot-digital-twin**](skipped/ot-digital-twin.md) — post-release engine-backed OT v2 direction that
  needs a real FMU/digital-twin substrate, beyond the shipped OT v1 local demo.
- [**curiator-ml**](skipped/curiator-ml.md) — post-release diagnostic-backend direction requiring an
  external benchmark/dataset choice and metric contract.

## Shipped

Fully delivered public work-orders, retired to [`completed/`](completed/) for provenance.

- [**ot-hmi-demo**](completed/ot-hmi-demo.md) — OT/HMI v1 collection delivered: deterministic tank sim,
  local SQLite historian, Dash HMI, 10-item feedback-to-fix arc, and fresh-clone preflight — shipped
  `curiator-ot@36e21cf`.
- [**math-geometry-collection**](completed/math-geometry-collection.md) — seven public Dash/Plotly math
  explainers plus the first feedback-to-fix receipt and fresh-clone preflight — shipped
  `curiator-geometry@30bb155`.
