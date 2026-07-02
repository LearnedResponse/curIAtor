# Backlog — the companion paper (Zenodo)

> **Status:** scoped 2026-07-01; stats CLI landed, paper/DOI work not started. A citable
> software/systems paper, self-archived on **Zenodo** with a DOI. Sequences last: the three public
> collections are its evaluation, so [public-release](public-release.md) → the collections → this.

## The claim (one sentence)

Putting the feedback affordance *inside* the running app — same-origin ★/comment/screenshot — and
wiring it to a headless coding agent turns app maintenance into a conversation, and the git log into
the durable record of that conversation.

## Venue & shape

- **Zenodo first** — a self-archived PDF alongside the software's concept DOI (the GitHub↔Zenodo
  integration from the release item gives versioned DOIs per release). No gatekeeper, citable
  immediately.
- **JOSS as the reviewed follow-up** — the Journal of Open Source Software is the natural fit: working
  OSS + a short paper, and the review is *of the software*, which plays to curIAtor's strength (it
  runs, with receipts).
- **arXiv mirror (cs.SE / cs.HC)** — optional, for reach; decide while drafting.

## Outline

1. **Motivation** — the feedback gap: users experience apps, maintainers experience issue trackers.
   Coding agents make small fixes cheap enough that the bottleneck moves to *capturing feedback in
   context* — which is exactly what the overlay captures (the comment, the stars, the screenshot, the
   app, the moment).
2. **Design** — the single-origin overlay (why same-origin is the screenshot moat), the SQLite ledger
   as conversation record, task bundles (standing protocol + item + thread context + accumulated
   lessons), pluggable agent adapters (Claude / Codex / BYO), the autonomy dial + group-gated
   elevation, git-as-memory (one atomic commit per run; revert/reflect).
3. **Case studies** — the three public collections (mixed-framework, OT/HMI rainbow→ISA-101, math
   explainers) plus the private origin repo reported in aggregate: feedback→fix cycles run, fix vs
   propose vs no-change rates, reply latency, human-intervention rate.
4. **Lessons & limitations** — hot-reload semantics against live apps, prompt injection via public
   feedback (untrusted input to an editing agent), positive-feedback wakes (a full agent run per
   compliment), html2canvas fidelity limits, single-tenant assumptions.
5. **Related work** — agentic coding CLIs (Claude Code, Codex, aider), in-context visual feedback /
   annotation tools, ChatOps, research-software engineering (JOSS-style tooling papers).
6. **Availability** — GitHub, PyPI, Zenodo DOI, Apache-2.0.

## Work-order

1. `CITATION.cff` + the Zenodo webhook (rides the [release](public-release.md) item). The citation
   file exists; after GitHub-Zenodo archiving is enabled, add the Zenodo concept DOI to it.
2. **`curiator stats` — core landed.** It reads a collection ledger + git log and emits the
   case-study numbers (cycles, status distribution, per-app counts, reply latency, curator commits),
   with `--json` for machine-readable snapshots, `--markdown` for paper/release-note tables, and
   `--csv` for app-level spreadsheets or plotting scripts. `curiator stats compare <gallery>...`
   now emits the cross-collection case-study table directly.
   Remaining paper work: run it against each public collection after publication and cite the exact
   command/output snapshot.
3. Draft in `docs/paper/` (markdown → pandoc PDF). Figures: the shell with the feedback panel, one
   loop diagram, a rainbow→ISA-101 before/after, a git-log excerpt with provenance trailers.
4. Deposit on Zenodo; DOI badge in the README; decide on the JOSS submission after.

## Guardrails

- **Honest numbers only** — everything quantitative must be recomputable from the public collections'
  ledgers/git logs via `curiator stats`; the private collection appears only in aggregate, with that
  caveat stated in the text.
- **A tool paper, not a benchmark paper** — no agent-model comparisons beyond what the adapters
  naturally produced in the case studies; that's explicitly future work.
