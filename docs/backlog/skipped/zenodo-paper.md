# Backlog — the companion paper (Zenodo)

> **Status:** skipped/external as of 2026-07-03. Local paper/statistics/metadata/PDF scaffolding is in
> place; remaining work is final human review plus release-time Zenodo/DOI deposit. The original scoped
> paper plan follows for provenance. Scoped 2026-07-01; stats CLI, local Zenodo metadata, a conservative `docs/paper/`
> Markdown draft scaffold, draft related-work prose, draft acknowledgements, and command-backed
> `curiator stats --output` / `curiator release-preflight --output` evidence snapshots have landed.
> The public-collection publication blocker is cleared at the release-candidate heads; `make paper-stats`
> now refreshes a PDF-friendly paper summary from the three published example collections, while
> `make paper-pdf` regenerates the loop/provenance figures and exports a locally reviewed manuscript
> PDF. Paper/DOI publication work is still blocked on the tagged release, Zenodo wiring, and final
> human PDF review/deposit. A citable
> software/systems paper, self-archived on **Zenodo** with a DOI. Sequences last:
> the three public collections are its evaluation, so [public-release](public-release.md) → the
> collections → this.

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

1. `CITATION.cff` + `.zenodo.json` + the Zenodo webhook (rides the [release](public-release.md) item).
   The local metadata files exist and are updated by `make release-prepare`; after GitHub-Zenodo
   archiving is enabled, add the Zenodo concept DOI to `CITATION.cff`.
2. **`curiator stats` — core landed.** It reads a collection ledger + git log and emits the
   case-study numbers (cycles, status distribution, direct-fix/proposal/no-dispatch/human-intervention
   rates, per-app counts, reply latency, curator commits), with `--json` for machine-readable
   snapshots, `--markdown` for paper/release-note tables, and `--csv` for app-level spreadsheets or
   plotting scripts. `curiator stats compare <gallery>...` now emits the cross-collection case-study
   table directly, and `--output <path>` writes any selected stats report as a named paper evidence
   artifact without shell redirection.
   The release-candidate summary in `docs/paper/curiator-paper.md` now cites the exact command-backed
   snapshot from the three published example collection heads while keeping the full wide table in
   `release-evidence/`. Remaining paper work: rerun this at tag cut if any release head changes, then
   archive/cite the final output.
3. Draft in `docs/paper/` (markdown → pandoc PDF) — scaffolded with `curiator-paper.md` and
   `reproducibility.md`, including release-time `curiator stats` commands and a dated
   release-candidate evidence snapshot instead of invented numbers. The loop diagram source has landed at
   `docs/paper/figures/feedback-loop.mmd`, and the git-log provenance excerpt has landed at
   `docs/paper/figures/provenance-log-excerpt.md`. The shell feedback-panel figure and renderer have
   landed at `docs/paper/figures/shell-feedback-panel.png` and
   `docs/paper/figures/render_shell_feedback_panel.py`. The OT rainbow→ISA-101 before/after figure
   and renderer have landed at `docs/paper/figures/ot-rainbow-before-after.png` and
   `docs/paper/figures/render_ot_before_after.py`. The related-work and acknowledgement draft
   placeholders have also been filled. The release-candidate case-study summary has been refreshed from
   `make paper-stats` after public-head preflight passed. `make paper-pdf` now regenerates the
   feedback-loop and provenance-excerpt PNGs from repo-native sources and exports the ignored
   manuscript PDF under `release-evidence/` with Pandoc/XeLaTeX; the local PDF smoke/review passes at
   seven pages with embedded Figures 1-4. Remaining paper work is tag-time evidence refresh if needed,
   citation refresh, final acknowledgements, final human PDF review, and Zenodo deposit, not missing
   draft prose or draft figures.
4. Deposit on Zenodo; DOI badge in the README; decide on the JOSS submission after.

## Guardrails

- **Honest numbers only** — everything quantitative must be recomputable from the public collections'
  ledgers/git logs via `curiator stats`; the private collection appears only in aggregate, with that
  caveat stated in the text.
- **A tool paper, not a benchmark paper** — no agent-model comparisons beyond what the adapters
  naturally produced in the case studies; that's explicitly future work.
