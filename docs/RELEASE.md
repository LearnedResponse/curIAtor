# Release runbook

This is the human checklist for cutting a curIAtor release. The automated release workflow is
`.github/workflows/release.yml`; this file records the local and external steps around it.

## 1. Confirm the release scope

Start from the public-release backlog:

```bash
sed -n '1,140p' docs/backlog/public-release.md
```

The v0.2.x release bar is that a stranger can reach a working loop in under ten minutes:
`pip install curiator`, clone or initialize a collection, run `curiator up`, leave feedback, and see a
curator reply.

## 2. Prepare metadata

Run this only when intentionally cutting a release:

```bash
make release-prepare VERSION=0.2.0 DATE=2026-07-02
```

This updates `pyproject.toml`, `curiator/__init__.py`, `CITATION.cff`, `.zenodo.json`, and
`CHANGELOG.md`. Review the diff before continuing.

## 3. Run local gates

Run the full gate from the runner checkout:

```bash
make release-check
make release-evidence
make paper-stats
curiator release-preflight --include-optional --fresh-clone --strict
curiator release-preflight --gallery curiator-aviato --http-smoke
curiator release-preflight --fresh-clone --json --output release-evidence/release-preflight.json
```

`make release-check` runs lint, the full pytest suite, release-doc checks, strict fresh-clone preflight
for the three required public collections, `docs/demo.gif` presence validation, package build, and
`twine check`. It does not rewrite `docs/demo.gif`, so a recorded browser capture is not replaced by
the generated storyboard fallback. The optional preflight adds finance and phylogenetics. The HTTP-smoke variant starts
proxy apps briefly and polls configured `smoke_http` paths or default app URLs; it expects app
dependencies to be installed in the tree being checked, so use it against the nested workspace or a
fresh clone after dependency installation.

Use the `--output` form when you need a durable release or paper evidence artifact. It writes the full
JSON payload, including runner checks, gallery heads, doctor issues, smoke results, path hits, and
publish-artifact hits. Keep raw JSON evidence under the gitignored `release-evidence/` directory
because it records local clone/source paths. `make release-evidence` refreshes the standard local
bundle: required-gallery preflight JSON (`release-evidence/release-preflight.json`), optional-gallery
preflight JSON (`release-evidence/release-preflight-optional.json`), and the three-collection
case-study stats in `release-evidence/case-study-stats.md` and
`release-evidence/case-study-stats.json`. Run `make paper-stats` from a clean runner tree; it refreshes
the companion paper's marked case-study stats block from that Markdown table so the tracked paper
excerpt is command-backed too.

Clean local build artifacts after inspection if needed:

```bash
rm -rf dist build curiator.egg-info
```

## 4. Refresh the browser demo GIF

`docs/demo.gif` should be a real browser-rendered capture, not the generated storyboard fallback.
Refresh it when the shell, feedback rail, or Aviato demo changes:

```bash
make demo-capture
```

The capture uses Brave headless against a temporary curIAtor collection and writes the feedback-to-fix
loop described in `docs/DEMO_SCRIPT.md`: feedback on the broken `aviato`, the curator reply/thread
state, and the fixed chart after reload.

Use `make demo-gif` only when you intentionally want to regenerate the fallback storyboard.

Then run the final launch-only gate:

```bash
make release-launch-check
```

Unlike `make release-check`, this rejects the generated storyboard marker in `docs/demo.gif`, rejects
`TODO(release)` placeholders in `docs/paper/curiator-paper.md`, and runs the optional-gallery
fresh-clone preflight. It should pass only after the real browser capture is in place, the paper's
release evidence placeholders are filled, and the optional public-shaped collections are still clean.

## 5. Publish example collections

The required public examples are:

- `LearnedResponse/curiator-aviato`
- `LearnedResponse/curiator-ot`
- `LearnedResponse/curiator-geometry`

Before publishing, keep the feedback-to-fix commits but confirm each collection is clean and portable:

```bash
curiator release-preflight --gallery curiator-aviato --fresh-clone --strict
curiator release-preflight --gallery curiator-ot --fresh-clone --strict
curiator release-preflight --gallery curiator-geometry --fresh-clone --strict
```

After creating/setting the public GitHub remotes, add the offline remote gate:

```bash
curiator release-preflight --fresh-clone --strict --require-public-remotes
```

This checks each required gallery has an `origin` remote matching
`github.com/LearnedResponse/<gallery-name>` without pushing anything.

After pushing the collection repositories, prove the remote contains each release-candidate commit:

```bash
curiator release-preflight --fresh-clone --strict --require-public-remotes --require-published-head
```

Before pushing the runner release tag, prove this checkout's public `origin` is correct and contains
the release-candidate runner commit:

```bash
curiator release-preflight --fresh-clone --strict --require-public-remotes --require-published-head \
  --require-runner-public-remote --require-runner-published-head
```

Then verify from a separate fresh clone that the quickstart works with the released package, not only
the local checkout. Before the external/off-machine proof, run the local installed-wheel smoke:

```bash
make release-package-smoke
```

This runs `make release-check`, installs the freshly built wheel from `dist/` into a temporary virtual
environment, verifies `curiator` imports from that installed wheel, initializes a temporary collection,
lists templates, runs `curiator smoke`, and rewrites the temporary collection into a minimal hosted
phase-0 config so `curiator playground-backup-smoke --no-smoke --json` proves the restore-copy gate is
available from the installed package too. Its JSON evidence is written to
`release-evidence/release-package-smoke.json`.

## 6. Configure external release services

Before pushing the tag:

- Configure PyPI Trusted Publishing for this repository's GitHub Actions workflow:
  `LearnedResponse/curIAtor`, workflow `release.yml`, environment `pypi`.
- Enable the GitHub to Zenodo integration for `LearnedResponse/curIAtor`.
- Confirm repository secrets are not needed for PyPI publication; the workflow uses OIDC
  (`id-token: write`) through Trusted Publishing.

After Zenodo creates the concept DOI, add it to `CITATION.cff` and add the DOI badge to `README.md`.

## 7. Push the tag

The release workflow is tag-driven and checks that the tag version matches `pyproject.toml`, then runs
lint, tests, release-doc checks, package build, and `twine check` before publishing:

```bash
git tag v0.2.0
git push origin v0.2.0
```

After the tag is pushed, the final publication proof should also require the tag:

```bash
curiator release-preflight --fresh-clone --strict --require-public-remotes --require-published-head \
  --require-runner-public-remote --require-runner-published-head --require-release-tag v0.2.0
```

If those gates pass, the workflow attaches the wheel and sdist to the GitHub release and publishes to
PyPI via Trusted Publishing.

## 8. Post-release checks

From a clean environment:

```bash
python -m pip install --upgrade curiator
curiator --help
curiator init /tmp/curiator-smoke --git
cd /tmp/curiator-smoke
curiator app templates
curiator smoke
```

Then run the paper/release evidence commands from `docs/paper/reproducibility.md`, refresh the paper
release evidence snapshot, run `make paper-pdf`, review the generated
`release-evidence/curiator-paper.pdf`, update DOI metadata, and create/pin any public GitHub issues from
`docs/GOOD_FIRST_ISSUES.md` if new starter issues exist.
