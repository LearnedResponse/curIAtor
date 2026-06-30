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
- `curiator app create` / `curiator init-app` to scaffold app directories and register them in
  `gallery.yaml` using Dash, static, or tiny Python-server templates.
- Per-feedback run artifacts: task bundles live under `feedback/tasks/<id>.md`, agent stdout/stderr
  streams live to `feedback/replies/<id>.md`, and feedback status badges link to a scrollable trace view.

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
