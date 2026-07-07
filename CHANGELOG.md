# Changelog

All notable changes to curIAtor are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-07-02

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
  on curIAtor reload. The proxy **streams** the backend response incrementally (per-read chunks) instead
  of buffering it whole, so Server-Sent Events, chunked/progressive responses, and large bodies flow
  through in real time; the read timeout is relaxed for SSE/long-lived streams. **WebSocket upgrades are
  bridged** too: the built-in server hands the proxy the raw client socket (`werkzeug.socket`), which it
  transparently tunnels to the backend (replay the upgrade, relay the `101`, then pump bytes both ways) —
  no WS framing in the proxy and no new dependency, so live HMR, Node-RED's editor comms, and socket
  dashboards work same-origin. Behind a WSGI server that doesn't expose the socket (e.g. gunicorn) a WS
  upgrade degrades to an honest `501` instead of hanging.
  Proxy mounts can opt into preserving the `/app/<name>/` prefix for frameworks like Streamlit that
  need their own base path.
- `curiator app create` / `curiator init-app` to scaffold app directories and register them in
  `gallery.yaml` using Dash, static, tiny Python-server, dependency-light Node, Flask, FastAPI, Rust,
  React/Vite, Svelte/Vite, Vue/Vite, Next.js, Streamlit, or Gradio templates; JS scaffolds can
  auto-detect or explicitly set npm/pnpm/yarn/bun commands, and the Next scaffold uses a
  prefix-preserving proxy mount with `basePath`. Generated proxy scaffolds now also register concrete
  `commands.preview` commands so `curiator status` and `curiator context` show a standalone way to run
  the app.
- `curiator app import <source> <name> --template ...` copies a local app directory or clones a git URL
  into `apps/<name>` while preserving the app repo's own `.git/`, then registers the same template-driven
  mount, smoke, and preview metadata in `gallery.yaml`, with immediate doctor-style warnings for visible
  HMR, dependency-manifest, and framework base/root-path issues; git-as-memory now commits source
  changes inside nested imported app repos before committing the collection ledger plus updated gitlink.
- `curiator app templates` lists the supported scaffold/import templates with their mount kind,
  toolchain, and intended use, and exposes the same metadata as JSON for agents and docs.
- Per-feedback run artifacts: task bundles live under `feedback/tasks/<id>.md`, agent stdout/stderr
  streams live to `feedback/replies/<id>.md`, and feedback status badges link to a scrollable trace view.
- The trace/console view has a **Stop** button that cancels an in-flight agent run: the shell drops a
  cancel marker the watcher polls for, terminates the agent, and parks the item as `held` (reviewable
  and re-runnable from the moderation queue) with a note that the working tree may hold partial edits.
- Long runs now show a "… still working (Nm elapsed)" heartbeat in the trace after a stretch of silence,
  so a slow-but-healthy run reads as "taking a while" instead of looking frozen.
- Timeouts no longer retry forever: a run that exceeds `agent.timeout` posts a clear "taking longer than
  {timeout}s" note and is requeued up to `agent.max_timeouts` times (default 2), then parked as `held`
  with guidance to raise `agent.timeout` or narrow the request.
- The `headless-cc` adapter runs `claude -p` with `--output-format stream-json --verbose` and renders
  the JSONL events into the trace as readable progress — session start (visible within a second, so a
  launched run no longer looks hung), each tool use (`▸ Read(...)`, `▸ Bash: …`, `▸ Edit(...)`), and a
  final `● result` with turn count, duration, and cost. Set `agent.stream: false` for the old
  emit-only-at-the-end `--output-format text` behavior.
- The `headless-cc` adapter now pre-approves `WebSearch` and `WebFetch` by default, so the agent can do
  read-only web research (e.g. verify a paper or link) — headless `claude -p` cannot prompt, so these
  previously failed mid-run. Drop `WebFetch` from `agent.allowed_tools` (or deny it) for collections
  open to untrusted public feedback; see SECURITY.md.
- Screenshot feedback can be annotated in-browser with boxes, arrows, numbered pins, and redaction
  blocks; annotations are burned into the PNG before it is saved to the ledger, and structured
  annotation metadata records per-mark notes plus same-origin DOM target hints for task bundles and
  saved-feedback preview, including a modal replay overlay reconstructed from the saved mark
  coordinates and an editable-copy path back into the reply composer. DOM target lookup now explicitly
  degrades to coordinates-only when the mounted app frame is unreadable or cross-origin.
- Signed-in reviewers can use an opt-in browser-native screen capture fallback (`getDisplayMedia`) when
  `html2canvas` misses canvas/WebGL-heavy app pixels; anonymous-held feedback remains limited to
  same-origin Capture view.
- Interactive app-repo workflow: `curiator link`, `status`, `context`, `work`, `done`, `open`, and
  `commands install` let Claude Code/Codex sessions use the same ledger/task/reply/git path without
  spawning a separate headless agent.
- `curiator feedback add` and YAML `curiator seed` items can carry sanitized screenshot annotation
  metadata, giving headless dogfood queues the same structured task-bundle hints as browser-marked
  feedback.
- `curiator stats` summarizes feedback cycles, status distribution, per-app counts, first-reply
  latency, direct-fix/proposal/no-dispatch/human-intervention rates, and git-as-memory commits, with
  JSON, Markdown, and CSV output for reproducible release/paper case studies.
- `curiator stats compare <gallery>...` emits collection-level case-study rows across multiple
  galleries, including runner version/git head, collection git branch/head, reply rates, first-reply
  latency, and curator commit counts.
- `curiator playground-preflight --strict` makes hosted-pilot posture and doctor warnings fail the
  preflight command, useful for CI or final pre-pilot gates where warnings should not be skipped.
- `curiator link` now writes relative gallery paths when possible, so linked app repos keep working
  when moved or cloned next to their collection.
- Generated task bundles now use repo-relative app roots, source scopes, screenshots, ledger paths, and
  ready commands for self-contained collections, reducing machine-absolute paths in published examples.
- `curiator doctor` checks collection portability by flagging machine-absolute config paths and missing
  app roots/sources as errors, with release-hardening warnings for missing smoke hooks, proxy commands
  that do not mention their configured port, likely HMR dev-server proxy commands, missing command
  executables, and common missing dependency manifests such as `package.json`, `requirements.txt`, and
  `Cargo.toml`; it now also detects missing Python dependency manifests for FastAPI, Gradio, and
  Streamlit apps from top-level imports, plus missing Vite/Next/FastAPI/Gradio/Streamlit base-path or
  root-path configuration for `/app/<name>/` proxy mounts.
- `curiator smoke` runs each app's configured smoke command or fallback import check across a collection,
  with `--app`, `--jobs`, `--json`, and configurable `smoke_timeout` / `smoke.timeout` limits for
  release preflight automation. Directory/proxy apps without explicit `smoke:` now get conservative
  inferred checks for obvious Python, Node, and Rust server roots instead of silently passing with
  `n/a`; `curiator smoke --http` can also start proxy apps briefly and verify a configured
  `smoke_http` path or default app URL responds over HTTP.
- `curiator release-preflight` runs doctor/smoke/path checks across the nested public release
  collections, rejects tracked publish-unsafe runtime/auth artifacts such as local user stores, task
  traces, screenshots, SQLite sidecars, env files, and legacy JSON ledgers, as well as generated caches,
  virtualenvs, `node_modules`, and local editable/path dependency pins in requirements files; `--fresh-clone` repeats
  those checks from temporary clones of the committed gallery histories; `--strict` makes doctor
  warnings fail release publication gates; `--include-optional` adds the finance and phylogenetics
  public-shaped galleries to the default release set; `--http-smoke` also runs the proxy HTTP response
  check during nested or dependency-prepared preflight; `make release-check` uses strict fresh-clone mode; and
  `make release-launch-check` rejects final-launch demo/paper placeholders plus optional-gallery drift.
- `curiator galleries` lists nested `galleries/curiator-*` collection repos with git head, dirty state,
  and the `curiator --gallery ...` command for targeting one from the runner checkout; it now also reports
  legacy sibling `curiator-*` checkouts or aliases next to the runner so they can be adopted or archived.
- `curiator galleries clone <repo>` clones public/example collection repos directly into the nested
  `galleries/` workspace, refusing non-gallery clones and preserving each collection's independent git
  history.
- `curiator galleries adopt <repo>` moves or copies an existing sibling collection repo under
  `galleries/` while preserving its `.git` history and rewriting the safe checkout-runner path to the
  nested `../..` form.
- A generated `docs/demo.gif` storyboard now ships at the README hero path, with `make demo-gif` /
  `scripts/render_demo_gif.py` to regenerate it until the final live browser recording replaces it;
  generated storyboards carry a marker that the final launch gate rejects.
- `SECURITY.md` documents the prompt-injection caveat, collection-level containment boundary, autonomy
  defaults, elevated-run risks, and data-handling expectations for ledgers/screenshots/traces.
- Local-login accounts can be disabled and re-enabled without deleting the account record, giving
  velvet-gated hosted collections a revocation lever.
- A held-feedback moderation queue: `curiator feedback add --status held` records feedback without
  dispatching it, `/queue` gives admins a shell review view, and
  `curiator queue list|approve|reject|sweep` lets headless admins review, release, close, or dry-run
  stale cleanup of held items with ledger audit notes.
- `curiator playground-preflight` checks one collection's hosted public-playground posture by combining
  doctor/smoke with runner/auth/git/user-store/anonymous-hold/quota/held-queue checks before an
  invite-only pilot; `--http-smoke` also starts proxy apps and polls their HTTP endpoints when app
  dependencies are installed in the checked collection.
- Hosted local-auth preflight now rejects inline `auth.users` password hashes plus tracked, unignored,
  outside-root, or group/world-readable users files; `auth.users_file` must remain the gitignored
  owner-only credential store for public pilots.
- Hosted OIDC preflight now rejects missing `auth.issuer`, missing `auth.client_id`, and unset
  `auth.client_secret_env` variables, while reporting only secret presence in JSON evidence.
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
- `docs/RELEASE.md` records the human release runbook: metadata preparation, local gates, real demo GIF
  replacement, collection publication, PyPI Trusted Publishing, Zenodo, tag push, and post-release
  smoke checks.
- The release workflow now publishes tagged builds through PyPI trusted publishing and blocks tags
  unless version matching, lint, tests, release-doc checks, package build, and `twine check` pass.
- CI now lints runner code, tests, and scripts, runs the release-doc check, builds the sdist/wheel, and
  runs `twine check`, so package metadata and launch-doc regressions are caught before a release tag is pushed.
- `make release-check` runs the local release gate without rewriting the hero GIF: lint, tests,
  release-doc validation that `docs/demo.gif` exists, public-gallery fresh-clone preflight, package
  build, and `twine check`.
- `curiator stats --output <path>` writes JSON, Markdown, CSV, or human-readable stats reports directly
  to a named artifact, so paper/release evidence snapshots do not depend on shell redirection.
- `curiator release-preflight --output <path>` writes the JSON preflight payload to a named artifact,
  giving release and paper evidence a stable command-backed snapshot.
- `curiator playground-preflight --output <path>` does the same for hosted-pilot posture checks.
- `make release-evidence` refreshes the standard gitignored release/paper evidence bundle under
  `release-evidence/`, including both required-gallery and optional-public fresh-clone preflight JSON.
- `curiator context` now gives a collection-level context summary when no app is selected in a
  multi-app gallery, so repo-local Claude/Codex shims can run status+context from the runner root.
- The obsolete live-session `curiator/loop/feedback_watch.sh` prototype watcher has been removed; the
  packaged loop is the configured adapter dispatcher.
- The release-doc gate now enforces the standard `release-evidence/` raw JSON/CSV evidence location,
  while allowing portable Markdown excerpts under the paper figures directory.
- `.zenodo.json` provides GitHub-Zenodo archive metadata, and
  `make release-prepare VERSION=... DATE=...` cuts release metadata by updating `pyproject.toml`,
  `CITATION.cff`, `.zenodo.json`, and the Keep-a-Changelog links in one tested step.
- The companion paper draft now includes related-work and acknowledgement prose; the normal release-doc
  gate rejects lingering `TODO(draft)` placeholders while still allowing release-blocked evidence, and
  `--strict-launch` rejects `TODO(release)` placeholders before publication.

### Changed
- Git-as-memory now defaults `git.branch` to `null` — agent commits land on the current `HEAD` (`main`)
  instead of a separate `curiator/auto` branch. A shared curator branch on a monorepo of many apps isn't
  a useful review unit (no per-app boundary, and the shell hot-reloads on edit so there's no
  commit-vs-live gap); commit to `main` and use the log (`revert`/cherry-pick). Set `git.branch: <name>`
  to opt back into branch isolation — worth it for an app in its own repo, not a shared collection.

### Fixed
- `curiator app create` / `app import` now indent the new `gallery.yaml` app entry to match the
  gallery's existing app items instead of hardcoding two spaces. Galleries whose list items sit at
  column 0 (e.g. ones generated by an external index) previously got an over-indented entry that YAML
  read as nested under the prior app, corrupting the file.
- The overlay now forwards deep-link query args to the mounted app: `/?app=X&node=crit` loads the app
  iframe as `/app/X/?node=crit`, so app-to-app links (and any shared link with app-specific params)
  reach the app instead of being dropped at the wrapper. The args are cleared when you switch apps.
- The catalog "sort: number" option now sorts by the number shown on each row (the app's port),
  numerically, instead of by the app's module key as a string — so it no longer looks unordered in
  galleries whose keys differ from their displayed numbers. Apps without a number sort last.
- `docs/USING_CURIATOR.md` no longer says the curator never commits; it now describes the current
  default-uncommitted behavior plus `git.commit: true` git-as-memory commits.
- The adapter package overview now matches the current task protocol: agents never run git directly,
  but `curiator reply`/`done` may trigger runner-owned git-as-memory commits when the collection opts in.
- `docs/DESIGN.md` no longer presents the original Dash/JSON-ledger extraction checklist as still
  unlanded; it now records the current Flask/React, proxy, SQLite, scaffold, and release-gate state.
- `docs/EXTRACTION_SCOPE.md` is now an archival extraction receipt with current package paths and
  launch gates instead of the original prototype-file lift plan.
- `curiator commands install` installs the interactive `curiator` shim as a model-invokable Skill for
  both agents — `.claude/skills/curiator/SKILL.md` (Claude Code) and `.agents/skills/curiator/SKILL.md`
  (Codex) — so the coding agent reaches for it on its own when a task matches, rather than only when a
  user types a slash command. Previously-generated `.claude/commands/curiator.md` slash commands and
  legacy `.codex/skills/curiator/SKILL.md` shims are relocated to the skill paths on reinstall;
  user-customized shims at those paths are kept and flagged. It also merges a `Bash(curiator *)`
  permission allow rule into the shared `.claude/settings.json` (merge-safe and idempotent) so a
  Claude Code session runs `curiator` commands without a per-command prompt, scoped to the curIAtor
  CLI while any repo/user `deny` rule still wins.
- Ledger inspection commands now open existing SQLite ledgers read-only, so `curiator status`,
  `context`, and `feedback show` do not dirty git-tracked collection ledgers.
- Screenshot annotation sanitization now drops empty DOM-target class lists instead of persisting
  meaningless `target: {classes: []}` metadata in the ledger.
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

[Unreleased]: https://github.com/LearnedResponse/curIAtor/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/LearnedResponse/curIAtor/releases/tag/v0.2.0
[0.1.0]: https://github.com/LearnedResponse/curIAtor/releases/tag/v0.1.0
