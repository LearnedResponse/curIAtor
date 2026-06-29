# CLAUDE.md — CurIAtor

> **This is a software project, not research.** CurIAtor is a self-hosted gallery for Dash apps with
> an in-context feedback loop an AI coding agent acts on. There is **no math/geometry here** — if you
> wandered in from a positive-geometry repo, that context does not apply. Stay in software.

## What it is (30 seconds)

A single-origin gallery that mounts each app at `/app/<name>`; you **★ / comment / screenshot** a live
app right in the browser; new feedback wakes a **headless coding agent** that edits the app's source,
smoke-tests, restarts it, and **replies in the feedback panel.** Self-hosted, single-tenant: your box,
your apps, your agent, your blast radius. Read `README.md` (the pitch) and `docs/DESIGN.md` (the full
architecture + the agent-adapter/deployment-mode reasoning) before changing things.

## Repo map

```
gallery.yaml                  # the registry: apps + agent adapter + autonomy. The contract everything reads.
curiator/
  cli.py                      # `curiator up | watch | reply | demo`
  config.py                   # load gallery.yaml → cfg dict (lightweight; no shell import)
  ledger.py                   # feedback ledger read/write (status, ⚙ replies) — factored out of the shell
  shell/
    app_shell.py              # THE SHELL (lifted from a research repo, 0 research-coupling). Flask+Dash,
                              #   mounts apps same-origin, catalog + iframe + feedback panel + screenshot.
                              #   Already de-coupled: `import all_apps_index` → `import registry` (line ~56, done).
    registry.py               # NEW — gallery.yaml → ALL_APPS (drop-in for the old all_apps_index)
    assets/                   # capture.js (html2canvas trigger), html2canvas.min.js, shell.css, mobile_responsive.js
  loop/
    loop.py                   # NEW — poll ledger, dispatch new feedback to the adapter
    task_template.md          # the standing agent protocol (triage / smoke-test / reply / NO auto-commit)
    feedback_watch.sh         # the research-era watcher, kept for reference (loop.py supersedes it)
    adapters/{headless_cc,api,command}.py   # headless-cc = default; api = team stub; command = BYO
examples/dash/{aviato,sales_overview,cohort_explorer}.py   # demo apps; aviato is DELIBERATELY broken
feedback/                     # app_feedback.json (the ledger, tracked) + shots/ (gitignored)
docs/{DESIGN,EXTRACTION_SCOPE,DEMO_SCRIPT}.md
```

## Run it

```bash
pip install -e .          # or: pip install dash plotly flask pyyaml
curiator up               # gallery at http://127.0.0.1:8200
curiator watch            # (second terminal) arm the feedback→fix loop
```

## STATUS — done vs next

**Done (M0 — lift & strip):** repo structure; the proven shell + assets copied verbatim (0 research
coupling); the registry seam swapped to `registry.py`/`gallery.yaml`; 3 demo apps incl. the broken
`aviato`; the loop + adapters scaffold; `ledger.py`/`config.py`/`cli.py`; packaging (MIT, pyproject,
`curiator` entrypoint); README + docs.

**Next — pick up here, in order:**

- **M1 — make `curiator up` actually boot the gallery.** The shell was written for apps living *next to*
  it (`HERE / file`); CurIAtor's apps live in `examples/dash/`. `registry.py` already (a) gives each app
  an **absolute** `file` path and a `source`, and (b) inserts the source dirs on `sys.path` so
  `importlib.import_module("aviato")` resolves. Verify/finish:
  1. In `app_shell.py`, `load_registry()` decides `kind` via `(HERE / f).exists()` — with absolute paths
     from `registry.py` that check needs to use the path as-is (not `HERE / f`). Fix the ~2 lines.
  2. Confirm the in-process mount (sets `DASH_REQUESTS_PATHNAME_PREFIX`, `importlib.import_module(key)`,
     takes `.build_app().server` / `.app.server`) finds the 3 demo apps. They each export `build_app()`
     **and** module-level `app`.
  3. `curiator up` → all three show in the catalog; `aviato` renders (ugly, on purpose).
  - **Shell-cache gotcha (carried over):** the shell caches each app's built module on first view. After
    the agent edits an app, the loop must restart the shell (or invalidate that module) for the fix to
    show. Decide where that restart lives (probably the adapter post-edit, or a shell endpoint).

- **M2 — close the loop end-to-end on `aviato`.** Finalize `headless_cc.run()` (the `claude -p` flags:
  model, `--allowedTools` for edit+bash, permission mode) and the **reply path**: the task bundle should
  tell the agent to call `curiator reply <app> <id> "<text>" --status done` (already implemented in
  `cli.py`) after it edits + smoke-tests + restarts. Then: drop feedback on `aviato` ("axis labels
  missing, legend covers the chart") → confirm the curator fixes `examples/dash/aviato.py`, the gallery
  shows it fixed, and a ⚙ reply lands. That cycle is the product.

- **M3 — record `docs/demo.gif`** per `docs/DEMO_SCRIPT.md` (the README hero image). Ship v0.

- **Deferred (M4):** the `api` adapter (team mode + context bundle / graphify), non-Dash `proxy` mounts,
  auth, PR-review/rollback. Don't build these until the loop has earned it. The `api.py` stub raises on
  purpose.

## Conventions / guardrails

- **Dash-first.** Own the niche. The `proxy` mount kind is the door to other frameworks later, not now.
- **The agent never auto-commits.** Edits land in the working tree for review (`task_template.md`
  enforces this). Autonomy dial: `auto-small` (fix clear small things) vs `propose-only` (plan first).
- **Verify, don't assert** — actually run `curiator up` / the loop and look; a green import isn't a green
  gallery.
- **Keep research out.** Nothing from any positive-geometry repo belongs here. The shell's 0-coupling is
  the whole reason this extraction is clean — keep it that way.
- **The name:** CurIAtor = curator + IA (also creator + curator). The broken demo app is `aviato` — the
  joke is that *this* one gets fixed. Don't rename either without reason.

## Provenance

The shell (`app_shell.py`), assets, and `task_template.md` were lifted from a private research repo's
viewer infrastructure (proven over ~dozens of real feedback→fix cycles), which had **zero** coupling to
the research — only the registry (`all_apps_index`, now `registry.py`) was research-specific and was
replaced. The planning docs (`docs/DESIGN.md`, `docs/EXTRACTION_SCOPE.md`) carry the full rationale.
