# Backlog — public release (GitHub, three example collections, a DOI)

> **Status:** release infrastructure started 2026-07-01. The decision: release curIAtor externally on
> GitHub as v0.2.x with **three public example collections** — `curiator-aviato` (mixed frameworks,
> local and same-machine temp-clone portability preflights now pass; off-machine fresh-clone gate
> remains), `curiator-ot`
> ([the OT/HMI flagship](ot-hmi-demo.md), scaffolded in `galleries/curiator-ot`), and a
> [math/geometry explainer collection](math-geometry-collection.md) (scaffolded in `galleries/curiator-geometry`) — plus a Zenodo-archived,
> DOI-citable release and a companion paper ([zenodo-paper](zenodo-paper.md)).

## The bar

"Released" ≠ "the repo is public." Released = **a stranger reaches a working loop in under ten
minutes**: `pip install curiator` → clone an example collection (or `curiator init`) → `curiator up` →
leave feedback → watch the fix land and the ⚙ reply arrive. Every item below serves that bar.

## Work-order

1. **Ship v0.2.0** — cut the Unreleased CHANGELOG batch (overlay shell, SQLite ledger, proxy mounts,
   app scaffolds, run traces, the interactive `link`/`work`/`done` workflow) as a tagged GitHub
   release. The release workflow builds/attaches artifacts and has a PyPI trusted-publishing job with
   a tag-vs-`pyproject.toml` version guard; `make release-check` now runs the local gate (lint, tests,
   public-gallery fresh-clone preflight, demo GIF regeneration, package build, and `twine check`). Local
   gate evidence from July 2, 2026: `make release-check` passed with 186 tests, public-gallery
   fresh-clone preflight `3/3`, regenerated `docs/demo.gif`, built sdist/wheel, and `twine check`
   passed both artifacts.
   Remaining external setup is configuring the PyPI Trusted Publisher, then running
   `make release-prepare VERSION=0.2.0 DATE=<release-date>` and pushing the matching `v0.2.0` tag.
2. **The hero `docs/demo.gif`** (absorbs the old M3) — the README now has a committed generated
   storyboard at this path (`make demo-gif`), so the launch page no longer has a broken image.
   Before release, replace it with the real take per `docs/DEMO_SCRIPT.md`: feedback on the broken
   `aviato` → the fix lands live → the ⚙ reply. Nothing sells the loop faster than watching it close
   once.
3. **Portability pass — collections must survive leaving this machine.** The `.curiator/app.yaml` part
   is fixed: `curiator link` now writes relative paths when the gallery is reachable relatively. The
   generated task-bundle prompt surface is also fixed for self-contained collections: app roots,
   source scopes, screenshots, ledger paths, and ready commands are repo-relative instead of
   `/home/adamguetz/...`. `curiator commands install` now lays down repo-local interactive shims at
   `.claude/commands/curiator.md` and `.agents/skills/curiator/SKILL.md`; the three release
   collections carry those current paths and now default to `runner.mode: pinned` for standalone
   `pip install curiator` use (`curiator-aviato` `b23e0bc`, `curiator-ot` `36e21cf`,
   `curiator-geometry` `30bb155` on `curiator/auto`). `curiator doctor` now gives a local preflight for
   machine-absolute paths, missing app roots/sources, weak smoke coverage, suspicious proxy port wiring,
   likely HMR dev-server proxy commands, missing command executables, and common missing dependency
   manifests; `curiator smoke` runs the same per-app smoke hooks used by git-as-memory commits. From the
   runner checkout,
   `curiator release-preflight` runs those checks across the nested public galleries and also rejects
   dirty nested repos or tracked machine-local paths; `curiator release-preflight --fresh-clone` repeats
   the same gate from temporary clones of the committed gallery histories. Remaining release work is
   the fresh-clone check on a machine that isn't this one, and the loop must close there.
4. **Publish the three example collections** as public sibling repos, each linked from the README's
   Examples section. README links are prepared for `LearnedResponse/curiator-aviato`,
   `LearnedResponse/curiator-ot`, and `LearnedResponse/curiator-geometry`; publication and
   fresh-clone verification remain. Sanitize machine paths and anything private, but **keep the feedback→fix
   commits** — the ledger and the git log *are* the demo; a laundered squeaky-clean history shows
   nothing. `curiator-geometry` now has seven public Dash/Plotly apps (including two algebraic-geometry
   explainers filtered from 4+ star Kwisatz taste signals), one completed convex-hull feedback→fix cycle
   at `30bb155`, and passing `curiator doctor`, `curiator smoke`, direct Dash import/build, and
   same-machine fresh-clone preflight checks. `curiator-ot` now has a deterministic tank sim, local SQLite historian, rough rainbow Dash HMI,
   10-item operator feedback queue, repo-local curIAtor skill shims, seed commit `6c5e2d6`, and latest
   release-hygiene commit `36e21cf`; its
   seeded feedback loop is complete on `curiator/auto` with ten curator commits from rainbow baseline
   toward HP-HMI, and `curiator release-preflight --gallery curiator-ot --fresh-clone --json` passes at
   `36e21cf`.
   (`curiator-finance` can join as a fourth if the cleanup is cheap; the three above are the release set.)
5. **SECURITY.md — reviewed against current defaults; re-read once at release cut.** The product auto-runs a coding agent against
   feedback text. The first policy now states: one-container-per-collection as the blast-radius unit,
   the autonomy dial, group-gated elevated profiles, dispatch quotas/trusted dispatch groups as admission
   controls rather than elevated execution rights, deny-lists — and the **prompt-injection caveat
   plainly** (public feedback is untrusted input to an agent with edit rights; `auth.mode` +
   `propose-only` are mitigations, not a solved problem). The release-example nuance is now explicit:
   `auth.mode: none` + `auto-small` is acceptable for clone-and-run examples, not hosted public forms;
   hosted examples need auth/propose-only or a human-reviewed queue. Screenshot redaction is documented
   as a manual browser-side pre-save tool, not an automatic guarantee. Reread on July 2, 2026 against
   the current config/loop defaults (`runner.mode: pinned`, explicit anonymous held before dispatch,
   quota enforcement, separate `agent.dispatch.trusted_groups` and `agent.elevated.groups`). Before
   release, do one final reread against the tag's adapter defaults.
6. **Repo hygiene** — issue templates are present (bug, feature, example-collection quickstart), labels
   are tracked in `.github/labels.yml`, and the first good-first seed queue has been drained.
   Remaining after publication: README badges for PyPI/DOI and creating/pinning any new GitHub issues.
   `CONTRIBUTING.md` and the DCO check already exist.
7. **Zenodo wiring** — `CITATION.cff` and `.zenodo.json` are present with release metadata, and
   `make release-prepare` updates both alongside `pyproject.toml` and `CHANGELOG.md`. Remaining
   release-time work is enabling the GitHub↔Zenodo integration so every release auto-archives with a
   DOI, then adding the Zenodo concept DOI to `CITATION.cff`. The [paper](zenodo-paper.md) builds on
   this.

## Guardrails

- **The examples are the pitch.** A broken quickstart in any published collection is a release
  blocker — "verify by running" applies to all three, from a fresh clone.
- **Don't rewrite collection history for cosmetics** — the per-fix commits with provenance trailers are
  the evidence the whole product stands on.
- **No security theater** — document what the container boundary contains and what it doesn't; never
  claim sandboxing the runner doesn't do.
