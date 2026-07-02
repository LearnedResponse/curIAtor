# Changelog

All notable changes to curIAtor are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Flask + React overlay shell (`web_shell.py`) served by default, with the legacy Dash shell still
  available via `--legacy-dash-shell`. Dash remains supported as `dash-inproc`; the overlay itself is
  now framework-neutral.
- SQLite-backed feedback ledger (`feedback/app_feedback.sqlite`) as the single runtime source of
  truth, with one-time import from legacy `feedback/app_feedback.json` and a `curiator feedback`
  inspection CLI for agents and humans.
- App-directory source scopes via `root:` / directory-valued `source:`, plus `mounts:` so one folder can
  expose multiple gallery endpoints.
- Same-origin `proxy` mount support for local web servers under `/app/<name>/...`, with process restart
  on curIAtor reload.
  Proxy mounts can opt into preserving the `/app/<name>/` prefix for frameworks like Streamlit that
  need their own base path.
- `curiator app create` / `curiator init-app` to scaffold app directories and register them in
  `gallery.yaml` using Dash, static, tiny Python-server, React/Vite, Svelte/Vite, or Streamlit
  templates; React/Svelte scaffolds can auto-detect or explicitly set npm/pnpm/yarn/bun commands.
- Per-feedback run artifacts: task bundles live under `feedback/tasks/<id>.md`, agent stdout/stderr
  streams live to `feedback/replies/<id>.md`, and feedback status badges link to a scrollable trace view.
- Screenshot feedback can be annotated in-browser with boxes, arrows, numbered pins, and redaction
  blocks; annotations are burned into the PNG before it is saved to the ledger, and structured
  annotation metadata records per-mark notes plus same-origin DOM target hints for task bundles and
  saved-feedback preview.
- Interactive app-repo workflow: `curiator link`, `status`, `context`, `work`, `done`, `open`, and
  `commands install` let Claude Code/Codex sessions use the same ledger/task/reply/git path without
  spawning a separate headless agent.
- `curiator stats` summarizes feedback cycles, status distribution, per-app counts, first-reply
  latency, and git-as-memory commits, with JSON, Markdown, and CSV output for reproducible
  release/paper case studies.
- `curiator stats compare <gallery>...` emits collection-level case-study rows across multiple
  galleries, including reply rates, first-reply latency, and curator commit counts.
- `curiator link` now writes relative gallery paths when possible, so linked app repos keep working
  when moved or cloned next to their collection.
- Generated task bundles now use repo-relative app roots, source scopes, screenshots, ledger paths, and
  ready commands for self-contained collections, reducing machine-absolute paths in published examples.
- `curiator doctor` checks collection portability by flagging machine-absolute config paths and missing
  app roots/sources as errors, with release-hardening warnings for missing smoke hooks, proxy commands
  that do not mention their configured port, likely HMR dev-server proxy commands, missing command
  executables, and common missing dependency manifests such as `package.json`, `requirements.txt`, and
  `Cargo.toml`.
- `curiator smoke` runs each app's configured smoke command or fallback import check across a collection,
  with `--app`, `--jobs`, `--json`, and configurable `smoke_timeout` / `smoke.timeout` limits for
  release preflight automation.
- `curiator release-preflight` runs doctor/smoke/path checks across the nested public release
  collections, and `--fresh-clone` repeats those checks from temporary clones of the committed gallery
  histories.
- `curiator galleries` lists nested `galleries/curiator-*` collection repos with git head, dirty state,
  and the `CURIATOR_GALLERY=...` command for targeting one from the runner checkout.
- `curiator galleries adopt <repo>` moves or copies an existing sibling collection repo under
  `galleries/` while preserving its `.git` history and rewriting the safe checkout-runner path to the
  nested `../..` form.
- A generated `docs/demo.gif` storyboard now ships at the README hero path, with `make demo-gif` /
  `scripts/render_demo_gif.py` to regenerate it until the final live browser recording replaces it.
- `SECURITY.md` documents the prompt-injection caveat, collection-level containment boundary, autonomy
  defaults, elevated-run risks, and data-handling expectations for ledgers/screenshots/traces.
- Local-login accounts can be disabled and re-enabled without deleting the account record, giving
  velvet-gated hosted collections a revocation lever.
- A held-feedback moderation queue: `curiator feedback add --status held` records feedback without
  dispatching it, `/queue` gives admins a shell review view, and
  `curiator queue list|approve|reject|sweep` lets headless admins review, release, close, or dry-run
  stale cleanup of held items with ledger audit notes.
- `auth.allow_anonymous: true` for `local`/`oidc` hosted galleries lets logged-out users leave feedback,
  but it is always recorded as `held`; logged-in users keep the normal dispatch path.
- Anonymous hosted feedback is rate-limited per client IP with `auth.anonymous_feedback_max` and
  `auth.anonymous_feedback_window_seconds` before it reaches the held queue.
- The watcher enforces `agent.quotas.per_user_daily` and `agent.quotas.global_daily`: explicit
  anonymous feedback and over-budget account feedback are degraded to `held` with a ledger note before
  any agent launch.
- `docs/SCREENSHOT_CAPTURE.md` documents the current same-origin `html2canvas` capture path, upload
  fallback, and native/server-side capture tradeoffs.
- `CITATION.cff` provides machine-readable software citation metadata for GitHub and Zenodo.
- GitHub issue templates cover runner bugs, feature requests, and example-collection quickstart
  failures.
- Repository labels and `docs/GOOD_FIRST_ISSUES.md` track publish-time good-first issue seeds; the
  initial release-hardening seeds have been implemented.
- The release workflow now publishes tagged builds through PyPI trusted publishing and blocks tags
  whose `vX.Y.Z` does not match `pyproject.toml`.
- CI now builds the sdist/wheel and runs `twine check`, so package metadata regressions are caught
  before a release tag is pushed.
- `make release-check` runs the local release gate: lint, tests, public-gallery fresh-clone preflight,
  demo GIF regeneration, package build, and `twine check`.
- `.zenodo.json` provides GitHub-Zenodo archive metadata, and
  `make release-prepare VERSION=... DATE=...` cuts release metadata by updating `pyproject.toml`,
  `CITATION.cff`, `.zenodo.json`, and the Keep-a-Changelog links in one tested step.

### Fixed
- `curiator commands install` now writes the Codex repo skill to `.agents/skills/curiator/SKILL.md`,
  matching current Codex skill discovery, while keeping Claude's `.claude/commands/curiator.md`;
  generated legacy `.codex/skills/curiator/SKILL.md` shims are cleaned up on reinstall.
- Ledger inspection commands now open existing SQLite ledgers read-only, so `curiator status`,
  `context`, and `feedback show` do not dirty git-tracked collection ledgers.
- Git-as-memory replies no longer mutate the SQLite ledger after creating a curator commit; the commit
  SHA is printed and remains queryable from git, while the collection stays clean after `curiator done`.
- `SECURITY.md` now distinguishes clone-and-run public examples (`auth.mode: none` plus `auto-small`)
  from hosted public feedback forms, which require authentication/propose-only or human review.
- Package metadata now uses SPDX license fields and explicitly packages shell assets, removing
  setuptools release-build deprecation warnings.

## [0.1.0] — 2026-06-29

First public release — the full feedback→fix loop, end-to-end, Dash-first.

### Added
- **Single-origin gallery shell.** Every Dash app mounts at `/app/<name>` behind one Flask server
  (lazy in-process mount; build failure shows in the iframe, never breaks the shell). Catalog +
  live-app iframe + feedback panel, with a mobile collapse-to-one-column layout.
- **Same-origin feedback.** ★ rating + comment + one-click `html2canvas` **screenshot** of the live
  app (the thing separate ports made impossible) + upload fallback, persisted to a git-tracked JSON
  ledger. A runner-aware **◆ General** channel for feedback on the gallery/runner itself.
- **The closed loop.** New feedback wakes a headless agent (`curiator watch`) that reads the
  comment + screenshot + source, edits the app, smoke-tests, **reloads it live** (`/reload/<app>`),
  and **replies in the panel** — with an autonomy dial (`auto-small` / `propose-only`) and pluggable
  adapters (`headless-cc` default, `api` stub, `command` BYO).
- **Git as the memory.** Opt-in `git: { commit: true }` makes every agent run one atomic commit
  (source edit **and** ledger update together) on a sandbox branch, with structured trailers
  (`Curiator-App`/`Curiator-Feedback`), DCO sign-off, and the SHA echoed into the ⚙ reply.
  `curiator revert` undoes a fix while keeping the conversation; `curiator reflect` distills the
  history into `LESSONS.md` that each one-shot loads.
- **Start your own collection.** `curiator init <dir>` scaffolds a collection (gallery.yaml + a
  sample app + requirements + feedback dir); `runner: { mode }` routes General-channel feedback
  (checkout → patch the runner; pinned → draft an upstream PR). The runner resolves apps + the
  ledger against the **collection** dir, so a collection works as a separate repo.
- **Sandbox.** `Dockerfile` + `docker-compose.yml` — one container per collection (the blast-radius
  boundary, since the curator auto-edits and runs code), with a persistent collection volume.
- **Turnkey demo.** `curiator demo-up` (a.k.a. `make demo`) resets the deliberately-broken `aviato`,
  starts the gallery + the loop, and prints the URL — one command, record-ready.
- **Project foundation.** Apache-2.0 + DCO; pytest suite + CI (Python 3.10–3.12, ruff, DCO check);
  `curiator serve` one-process runner; `pip install curiator` packaging.

[Unreleased]: https://github.com/LearnedResponse/curiator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/LearnedResponse/curiator/releases/tag/v0.1.0
