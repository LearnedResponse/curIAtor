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
  **Core landed & proven** (`curiator-aviato` runs React SSR + Rust via `proxy` mounts); framework
  scaffolds and a discoverable template menu now exist, so what remains is deeper per-framework
  hardening, live-HMR proxy ergonomics, and publishing the proof.
- [**phylogenetics-collection**](phylogenetics-collection.md) — scaffolded in
  `galleries/curiator-phylogenetics` as a **public-first** interactive companion to the tropical
  displayed-trees paper (displayed trees / tree-of-blobs / NC = D / TINNiK), seeded from an already-built
  Dash explorer **and a working Pyodide static port**. A domain-specialized sibling of
  `math-geometry-collection` for the phylo-networks community; first client-side-WASM-compute collection;
  the full eight-item seeded feedback loop is complete through `b1b3586`, and it ships with the paper's outreach.
- [**annotated-feedback**](annotated-feedback.md) — **core landed**: captured screenshots can be marked
  up with boxes, arrows, pins, redactions, and per-mark notes; marks burn into the PNG, structured
  annotation metadata rides through the ledger/task bundle, and the React shell records same-origin DOM
  targets when available. A reproducible Brave dogfood check now covers capture/draw/save/task-bundle;
  remaining work is the native-capture fidelity follow-on.
- [**voice-feedback**](voice-feedback.md) — talk through the fix instead of typing it. Three tiers
  (OS dictation / Web Speech / local Whisper), where the **privacy moat** picks **local Whisper as the
  default** (on-device, works on Linux, zero egress). North star: **"narrated feedback"** — voice +
  annotation on a *shared clock*, so a review becomes an ordered, intent-per-mark tour the agent
  follows. Composes with `annotated-feedback`; accessibility wins for motor/low-vision (voice +
  DOM-target snapping). Tier 0 dictation is documented; local transcription is command-backed and
  opt-in; annotation marks and transcript segments now both carry task-bundle timing fields for the
  future narrative merge.
