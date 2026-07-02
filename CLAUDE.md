# CLAUDE.md — curIAtor

> **This is a software project, not research.** curIAtor is a self-hosted gallery for web apps with
> an in-context feedback loop an AI coding agent acts on. There is **no math/geometry here** — if you
> wandered in from a positive-geometry repo, that context does not apply. Stay in software.

## What it is (30 seconds)

A single-origin gallery that mounts each app at `/app/<name>`; you **★ / comment / screenshot** a live
app right in the browser; new feedback wakes a **headless coding agent** (or an interactive CLI session
via `curiator work`) that edits the app's source, smoke-tests, reloads it, and **replies in the feedback
panel** — optionally committing each run atomically (git-as-memory). Self-hosted, single-tenant: your
box, your apps, your agent, your blast radius. Read `README.md` (the pitch), `docs/DESIGN.md` (the
architecture), and `docs/USING_CURIATOR.md` (the user-facing workflow) before changing things.

## Repo map

```
gallery.yaml                  # THE public contract: apps/mounts + agent adapter + autonomy + runner mode
                              #   + auth + git-as-memory + shell port. Everything reads this.
curiator/
  cli.py                      # the whole CLI: up | serve | watch | reply | reload | revert | reflect |
                              #   link | status | context | work | done | open | commands | feedback |
                              #   seed | app create | init | user | demo*
  config.py                   # gallery.yaml → cfg. Resolution: $CURIATOR_GALLERY → cwd-up gallery.yaml →
                              #   a `.curiator/app.yaml` link → packaged default. ALSO the ONE home of the
                              #   app/mount schema helpers (mount_entries / app_specs / app_spec /
                              #   infer_current_app) that the shell, adapters, gitmem, and CLI all share.
  ledger.py                   # SQLite feedback ledger (feedback/app_feedback.sqlite, WAL). A legacy
                              #   app_feedback.json is a ONE-TIME import source, never a live copy.
  auth.py                     # feedback provenance: mode none | header | oidc | local (+ rate limiting)
  gitmem.py                   # git-as-memory: one atomic commit per agent run; revert/reflect → LESSONS.md
  shell/
    web_shell.py              # the DEFAULT shell — Flask + React overlay (assets/react_shell.*),
                              #   framework-neutral chrome around a same-origin iframe
    app_shell.py              # the legacy Dash shell (`curiator up --legacy-dash-shell`)
    registry.py               # gallery.yaml → ALL_APPS for the shell; puts app source dirs on sys.path
  loop/
    loop.py                   # poll the ledger, dispatch new feedback to the adapter
    runlog.py                 # per-feedback artifacts: feedback/tasks/<id>.md + live trace feedback/replies/<id>.md
    task_template.md          # the standing agent protocol (triage / smoke-test / reply / no self-git)
    adapters/                 # headless_cc (Claude, default) | codex | api (stub) | command (BYO)
examples/dash/                # 3 demo apps; `aviato` is DELIBERATELY broken (the demo's first patient)
feedback/                     # runtime state, ALL gitignored: SQLite ledger + shots/ + tasks/ + replies/
tests/                        # pytest suite; conftest builds a throwaway git collection in tmp
.github/workflows/            # CI (pytest matrix + ruff + DCO) and release
docs/                         # DESIGN, USING_CURIATOR, DEMO_SCRIPT, EXTRACTION_SCOPE, backlog/
```

## Run it

```bash
pip install -e .
curiator up               # this repo's own gallery.yaml → http://127.0.0.1:8300 (port is per-collection)
curiator watch            # (second terminal) arm the feedback→fix loop; `curiator serve` = both
python -m pytest -q       # the suite must stay green
```

## STATUS

**v0.1.0 shipped (2026-06-29)** — the full feedback→fix loop end-to-end. Since then (Unreleased in
`CHANGELOG.md`): the React/Flask overlay shell, the SQLite ledger, app directories + multi-endpoint
`mounts:` + same-origin `proxy` mounts (non-Python apps), `curiator app create` scaffolds, per-feedback
task/trace artifacts, elevated agent profiles, and the **interactive app-repo workflow**
(`link` / `status` / `context` / `work` / `done` / `commands`) so a Claude Code/Codex session drives the
same ledger/reply/reload/git path as the headless watcher.

Real collections dogfooding it (siblings of this repo):
- `../curiator-finance` — codex adapter, seeded "self-building demo" (Paola's feedback queue).
- `../curiator-aviato` — mixed content: multi-mount Dash dir, React/Node SSR + Rust via `proxy`, link + command shims.
- `../curiator-Kwisatz` — the original research repo with curIAtor overlaid: 63 generated `dash-inproc` apps.

The backlog (`docs/backlog/`) is now organized around a **public release track**: GitHub release v0.2.x
with three public example collections (aviato, OT/HMI, math/geometry) + Zenodo DOI + a companion paper.
See `docs/backlog/README.md` for sequencing.

## Conventions / guardrails

- **`gallery.yaml` is the public contract.** Its schema semantics (mount/mounts merge, root/source
  resolution) live ONLY in `config.py` — never re-derive them in a consumer.
- **The agent never runs git itself.** Default (`git.commit: false`) leaves edits uncommitted for review;
  with `git.commit: true` the *runner* makes one atomic commit per run (source + ledger). Never push.
- **The ledger is CLI-mediated.** Inspect/append via `curiator feedback` / `curiator reply`; nothing may
  treat the SQLite file as a writable API.
- **Shell cache:** the shell caches each app's build on first view — after an edit, `curiator reload <app>`
  (the `reply --status done` / `curiator done` paths do this automatically).
- **Verify, don't assert** — actually run `curiator up` / the loop and look; a green import isn't a green
  gallery, and green tests aren't a working demo.
- **Dash-first, not Dash-only.** `dash-inproc` is the convenience mount; `proxy` is the universal one.
  Keep the overlay/feedback/loop 100% framework-agnostic; isolate framework specifics in the mount.
- **Keep research out.** Nothing from any positive-geometry repo belongs here (curiator-Kwisatz consumes
  curIAtor; never the reverse).
- **The name:** curIAtor = curator + IA (also creator + curator). The broken demo app is `aviato` — the
  joke is that *this* one gets fixed. Don't rename either without reason.

## Provenance

The shell lineage traces to a private research repo's viewer infrastructure (proven over dozens of real
feedback→fix cycles) — lifted with **zero** research coupling, then generalized (React overlay, SQLite
ledger, proxy mounts). `docs/DESIGN.md` and `docs/EXTRACTION_SCOPE.md` carry the full rationale.
