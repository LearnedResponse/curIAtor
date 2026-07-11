# Backlog — public roadmap

Scoped ideas and work-orders for the public curiator product. Each live item should still need a local
implementation, release action, or external operating step; shipped items move to
[`completed/`](completed/) so the backlog keeps reflecting what remains.

> Internal planning (product-direction/moat thinking, engineering refactors, strategy) lives in the
> **private `curiator-planning` repo**, surfaced to the loop as `.planning/` when present. This file is
> the public half — the release track and example collections.

## External Release Gate

No local implementation backlog remains in this section. These stay live until the public-release bar is
met, and now represent external/human release operations: public repo/tag pushes, hosted credentials,
PyPI/Zenodo setup, DOI/badge updates, off-machine validation, and final paper review/deposit.

- [**public-release**](public-release.md) — release curIAtor externally on GitHub as v0.2.x after the
  core examples and dogfood collections are fleshed out, browser-smoked, and reproducible. External
  blockers remain public pushes/tags, PyPI Trusted Publisher, GitHub/Zenodo wiring, badges, and
  off-machine release validation.
- [**zenodo-paper**](zenodo-paper.md) — the companion software/systems paper. Local stats, draft,
  figures, metadata, and PDF build scaffolding exist; continue refreshing evidence from dogfooded
  collections until final human review and Zenodo/DOI deposit.

## Dogfood Before Release

No live local dogfood items remain. New public/dogfood work should enter here only if it still needs
local implementation before release.

## Direction (post-release experiments)

- [**nodered-overlay**](nodered-overlay.md) — **implemented and dogfooded; awaiting the root
  implementation commit/retirement.** The one-command scaffold, doctor rules, example collection,
  feedback history, real health/WebSocket checks, and strict dependency-prepared fresh-clone browser
  preflight are complete at `curiator-nodered@7e964fb`.
- [**per-run-branches**](per-run-branches.md) — **implemented and dogfooded; awaiting the root
  implementation commit/retirement.** Worktree-isolated runs, Git-ref proposal registry, live branch
  preview, admin Approve/Reject, conflict aborts, CLI inspection, same-app superseding, and independent
  app coexistence are covered. `curiator-proposals@8515e44` and nested app `b41c57dd` record the real
  feedback -> preview -> in-shell approval cycle. Publishing/materializing the nested app repo in a
  stranger's fresh clone remains an external release operation.

## Shipped

Fully delivered public work-orders, retired to [`completed/`](completed/) for provenance.

- [**ot-hmi-demo**](completed/ot-hmi-demo.md) — OT/HMI v1 collection delivered: deterministic tank sim,
  local SQLite historian, Dash HMI, 10-item feedback-to-fix arc, and fresh-clone preflight — shipped
  `curiator-ot@36e21cf`.
- [**math-geometry-collection**](completed/math-geometry-collection.md) — seven public Dash/Plotly math
  explainers plus the first feedback-to-fix receipt and fresh-clone preflight — shipped
  `curiator-geometry@30bb155`.
- [**games-collection**](completed/games-collection.md) — draft-table feedback loop plus synthetic
  factory, roguelike, and fortress overlays; real-app integrations parked on external upstream,
  licensed-engine, and public-demo operations — shipped `curiator-games@5314217`.
- [**phylogenetics-collection**](completed/phylogenetics-collection.md) — Pyodide static companion,
  Dash explorer, eight feedback-to-fix receipts, Pages workflow, and strict fresh-clone browser
  preflight; public Pages URL remains external — shipped `curiator-phylogenetics@38cefee`.
- [**curiator-ml**](completed/curiator-ml.md) — deterministic classification and regression diagnostic
  dashboards with metric artifacts, seeded feedback receipts, and strict fresh-clone browser preflight;
  Kaggle/API/live-data paths remain external — shipped `curiator-ml@508162e`.
- [**public-playground**](completed/public-playground.md) — hosted-pilot moderation, auth, quota,
  preflight, backup-restore, and runbook primitives are delivered; actually running a public/velvet-gated
  deployment remains external — shipped runner state `curiator@94f3717`.
- [**general-app-hosting**](completed/general-app-hosting.md) — app directories, proxy mounts,
  scaffold/import templates, browser/HTTP smoke, and engine-backed lifecycle/health checks are landed
  and dogfooded; WebSocket/Docker hardening is demand-paced follow-on work — shipped runner
  `curiator@2b59bb3` and OT dogfood `curiator-ot@ad198e5`.
- [**ot-digital-twin**](completed/ot-digital-twin.md) — local engine-backed twin diagnostics proof
  landed with Modelica source, engine health, HTTP smoke, and fresh-clone browser smoke; true FMU export
  and a feedback round against that FMU backend are parked on OpenModelica/FMU runtime availability —
  shipped `curiator-ot@ad198e5`.
