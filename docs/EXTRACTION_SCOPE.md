# curIAtor OSS Extraction Scope

> **Status:** landed. This document is now an archival extraction receipt plus the current launch
> boundary. The original June 28, 2026 plan was to lift the research-gallery shell, feedback ledger,
> task template, and watcher into a standalone OSS package named **curIAtor**. That extraction has
> happened in this repository.

## What Landed

The standalone package is no longer a scratch extraction. The current package shape is:

```text
curiator/
  cli.py                       # collection/app/git/release/playground commands
  config.py                    # gallery.yaml normalization
  ledger.py                    # SQLite feedback ledger API
  shell/
    web_shell.py               # default Flask + React overlay shell
    app_shell.py               # legacy Dash-compatible shell
    registry.py                # gallery.yaml registry loader
    assets/                    # capture, annotation, CSS, localtime, responsive JS
  loop/
    loop.py                    # ledger watcher + dispatch policy
    task_template.md           # standing agent protocol
    adapters/                  # headless-cc, codex, command, api stubs
```

The original extraction bets are resolved:

- **Shell:** default serving is now Flask + React, with the older Dash shell still available as a
  compatibility path.
- **Registry:** `gallery.yaml` is the app registry; `curiator/config.py` owns app/mount normalization.
- **Mounts:** `dash-inproc` remains for Dash apps, while `proxy` hosts framework-neutral app processes
  under the same origin.
- **Ledger:** `feedback/app_feedback.sqlite` is the runtime source of truth. Legacy JSON is import-only.
- **Loop:** configured adapters replace the live-session prototype path. The package ships
  `headless-cc`, `codex`, `command`, and an API-adapter boundary.
- **Git as memory:** collections can opt into one commit per feedback run with structured trailers.
- **Scaffolds/import:** `curiator app create` and `curiator app import` support Dash, static, Python,
  Node, Flask, FastAPI, Rust, React/Vite, Svelte/Vite, Vue/Vite, Next.js, Streamlit, and Gradio.
- **Nested galleries:** example collections live under `galleries/` as separate git repositories, so
  agents can edit them from the runner checkout without collapsing their history.

## Landed Gates

Current local release gates cover the extraction:

```bash
ruff check curiator tests scripts
pytest -q
python scripts/check_release_docs.py
curiator release-preflight --fresh-clone --strict
curiator release-preflight --include-optional --fresh-clone --strict
```

`make release-check` runs lint, tests, release-doc validation, required-gallery fresh-clone preflight,
package build, and `twine check`. `make release-launch-check` is intentionally stricter and enforces
the real public-launch demo GIF plus command-backed paper evidence.

## Current Boundary

Extraction is complete; public launch is not. Local release-candidate evidence is in place: the
browser demo GIF is captured, and the paper has a dated local evidence snapshot. The remaining work
belongs to the external release track:

- refresh the paper evidence from the published collection repositories;
- publish the example collections and verify a fresh clone on a machine that is not this one;
- configure PyPI Trusted Publishing and GitHub-Zenodo archival before pushing the release tag.

Those gates are tracked in [`docs/backlog/public-release.md`](backlog/public-release.md) and
[`docs/RELEASE.md`](RELEASE.md). Do not treat this extraction document as the active release checklist.

## Historical Notes

The old plan named prototype files such as `feedback_watch.sh`, `feedback_loop_task.md`,
`shell_assets/`, and a research-local shell module. The equivalent shipped paths are now package paths:

| Prototype concept | Shipped path |
|---|---|
| live-session watcher | `curiator/loop/loop.py` plus configured adapters |
| feedback task prompt | `curiator/loop/task_template.md` |
| shell assets | `curiator/shell/assets/` |
| app registry | `gallery.yaml` plus `curiator/config.py` / `curiator/shell/registry.py` |
| feedback storage | `feedback/app_feedback.sqlite` through `curiator/ledger.py` |

Private research apps and ledgers remain outside the public package boundary.
