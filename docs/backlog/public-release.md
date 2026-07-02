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
   strict public-gallery fresh-clone preflight, `docs/demo.gif` presence validation, package build, and `twine check`). The
   human release checklist now lives in [`docs/RELEASE.md`](../RELEASE.md). Local gate evidence from
   July 2, 2026: `make release-check` passed with 262 tests, public-gallery
   fresh-clone preflight `3/3` with zero publish-artifact hits, validated the browser-captured
   `docs/demo.gif`, built sdist/wheel, and `twine check` passed both artifacts. The final local launch
   gate, `make release-launch-check`, also passed: strict release docs were clean and required plus
   optional public-shaped galleries passed fresh-clone preflight `5/5`. Release metadata is cut locally
   for `0.2.0` / `2026-07-02` via `make release-prepare`. Remaining external setup is configuring the
   PyPI Trusted Publisher, publishing/pushing the example collection repositories, enabling
   GitHub-to-Zenodo, and pushing the matching `v0.2.0` tag.
2. **The hero `docs/demo.gif`** (absorbs the old M3) — done locally. The README now has a committed
   Brave-rendered browser capture at this path, produced by `make demo-capture`: a temporary gallery
   loads the broken `aviato`, feedback plus captured view appears in the rail, the thread moves through
   working/done, and the refreshed app shows axis titles, the legend above the plot, and wider margins.
   The old generated storyboard remains available via `make demo-gif` as a fallback only; it carries an
   internal placeholder marker, and `make release-launch-check` rejects that marker so the final
   public-launch pass cannot silently ship the fallback GIF. The same strict doc gate also rejects
   `docs/paper/curiator-paper.md` `TODO(release)` placeholders before the paper is published; those
   placeholders have been replaced with a release-candidate evidence snapshot.
3. **Portability pass — collections must survive leaving this machine.** The `.curiator/app.yaml` part
   is fixed: `curiator link` now writes relative paths when the gallery is reachable relatively. The
   generated task-bundle prompt surface is also fixed for self-contained collections: app roots,
   source scopes, screenshots, ledger paths, and ready commands are repo-relative instead of
   `/home/adamguetz/...`. `curiator commands install` now lays down repo-local interactive shims at
   `.claude/commands/curiator.md` and `.agents/skills/curiator/SKILL.md`; the three release
   collections carry those current paths and now default to `runner.mode: pinned` for standalone
   `pip install curiator` use (`curiator-aviato` `3719ac9`, `curiator-ot` `36e21cf`,
   `curiator-geometry` `30bb155` on `curiator/auto`). `curiator doctor` now gives a local preflight for
   machine-absolute paths, missing app roots/sources, weak smoke coverage, suspicious proxy port wiring,
   likely HMR dev-server proxy commands, missing framework base/root-path config, missing command
   executables, and common missing dependency manifests; `curiator smoke` runs the same per-app smoke
   hooks used by git-as-memory commits. From the runner checkout, `curiator release-preflight` runs
   those checks across the nested public galleries and also rejects dirty nested repos, tracked
   machine-local paths, local editable/path dependency pins, and tracked publish-unsafe runtime/auth artifacts such as local user stores,
   task/reply traces, screenshots, SQLite sidecars, env files, legacy JSON ledgers, generated caches,
   virtualenvs, and `node_modules`; `curiator
   release-preflight --fresh-clone` repeats the same gate from temporary clones of the committed
   gallery histories, and `--http-smoke` can add the proxy process + HTTP response check when the app
   dependencies are installed in the tree being checked. `--output <path>` writes the JSON payload as
   a release/paper evidence artifact. Remaining release work is publishing the example repos, then
   proving a fresh clone on a machine that isn't this one can run the loop with the released package.
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
   `curiator-finance` is now a verified optional fourth: its public-demo posture is pinned/no-login,
   the stale machine-local ledger note is sanitized, and
   `curiator release-preflight --gallery curiator-finance --fresh-clone --strict` passes at `d6270bd`.
   `curiator-phylogenetics` is also a verified paper-linked optional collection at `b1b3586`. To check
   the minimum set plus these optional public-shaped collections, run
   `curiator release-preflight --include-optional --fresh-clone --strict`. The three above remain the
   minimum release set unless scope expands.
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
   quota enforcement, separate `agent.dispatch.trusted_groups` and `agent.elevated.groups`) and again
   after the local `0.2.0` metadata cut; no policy text changes were needed.
6. **Repo hygiene** — issue templates are present (bug, feature, example-collection quickstart), labels
   are tracked in `.github/labels.yml`, and the first good-first seed queue has been drained.
   Remaining after publication: README badges for PyPI/DOI and creating/pinning any new GitHub issues.
   `CONTRIBUTING.md` and the DCO check already exist.
7. **Zenodo wiring** — `CITATION.cff` and `.zenodo.json` are present with release metadata, and
   `make release-prepare` updates both alongside `pyproject.toml` and `CHANGELOG.md`. Remaining
   release-time work is enabling the GitHub↔Zenodo integration so every release auto-archives with a
   DOI, then adding the Zenodo concept DOI to `CITATION.cff`. The [paper](zenodo-paper.md) builds on
   this.

Local publication-prep gate: `curiator release-preflight --fresh-clone --strict
--require-public-remotes` now checks the required galleries have `origin` remotes matching
`github.com/LearnedResponse/<gallery-name>` before the release tag is pushed. This is intentionally
offline; it proves the local repos are wired to the intended public destinations but does not create or
push the GitHub repositories. After the repositories are pushed,
`curiator release-preflight --fresh-clone --strict --require-public-remotes --require-published-head`
proves each required gallery's exact release-candidate HEAD is present on its origin.

## Guardrails

- **The examples are the pitch.** A broken quickstart in any published collection is a release
  blocker — "verify by running" applies to all three, from a fresh clone.
- **Don't rewrite collection history for cosmetics** — the per-fix commits with provenance trailers are
  the evidence the whole product stands on.
- **No security theater** — document what the container boundary contains and what it doesn't; never
  claim sandboxing the runner doesn't do.
