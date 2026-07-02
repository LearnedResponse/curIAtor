# Backlog

Scoped-but-not-started ideas and work-orders. Each is a candidate, not a commitment; sequencing is
deliberate (ship, let the example demos surface what to prioritize).

## The release track (in order)

- [**public-release**](public-release.md) — release curIAtor externally on GitHub as v0.2.x with three
  public example collections (`curiator-aviato`, `curiator-ot`, math/geometry), the hero demo.gif, a
  portability pass (no machine-absolute paths in collections), SECURITY.md, and Zenodo DOI wiring.
- [**ot-hmi-demo**](ot-hmi-demo.md) — scaffolded in `galleries/curiator-ot` as the OT / HMI-maintenance
  flagship example: a "rainbow" HMI over a simulated process that curiator drags toward
  High-Performance-HMI / ISA-101 from operator feedback; the git log is the build story.
  **v1 = sim + Dash + a local historian; the MING compose is v2.**
- [**math-geometry-collection**](math-geometry-collection.md) — scaffolded in `galleries/curiator-geometry` as
  a public collection of interactive math/geometry explainers (public-knowledge classics only — the
  private research overlay stays private): the origin story made public, and the friction-free
  quickstart example.
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
  **Core landed & proven** (`curiator-aviato` runs React SSR + Rust via `proxy` mounts); what remains is
  scaffold templates, base-path/HMR ergonomics, and publishing the proof.
- [**phylogenetics-collection**](phylogenetics-collection.md) — scaffolded in
  `galleries/curiator-phylogenetics` as a **public-first** interactive companion to the tropical
  displayed-trees paper (displayed trees / tree-of-blobs / NC = D / TINNiK), seeded from an already-built
  Dash explorer **and a working Pyodide static port**. A domain-specialized sibling of
  `math-geometry-collection` for the phylo-networks community; first client-side-WASM-compute collection;
  four static-app curator receipts have landed through `7410acb`, and it ships with the paper's outreach.
- [**annotated-feedback**](annotated-feedback.md) — draw on the captured screenshot (box / arrow / numbered
  pin / redact) so feedback points at the exact element. **v1 burns the marks into the PNG** (rides the
  existing Read-the-PNG path, front-end only); **v2 resolves each mark to its DOM element** via same-origin
  `elementFromPoint` → a *code-locating* pointer a generic annotator can't produce. Core overlay feature —
  every collection benefits.
