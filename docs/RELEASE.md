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
curiator release-preflight --include-optional --fresh-clone --strict
curiator release-preflight --gallery curiator-aviato --http-smoke
```

`make release-check` runs lint, the full pytest suite, release-doc checks, strict fresh-clone preflight
for the three required public collections, `docs/demo.gif` presence validation, package build, and
`twine check`. It does not rewrite `docs/demo.gif`, so a recorded browser capture is not replaced by
the generated storyboard fallback. The optional preflight adds finance and phylogenetics. The HTTP-smoke variant starts
proxy apps briefly and polls configured `smoke_http` paths or default app URLs; it expects app
dependencies to be installed in the tree being checked, so use it against the nested workspace or a
fresh clone after dependency installation.

Clean local build artifacts after inspection if needed:

```bash
rm -rf dist build curiator.egg-info
```

## 4. Record the real demo GIF

`docs/demo.gif` currently has a generated storyboard fallback. Before public launch, replace it with a
real browser recording following `docs/DEMO_SCRIPT.md`: feedback on the broken `aviato`, the curator
fix lands, and the reply appears in the panel.

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

After pushing the collection repositories, verify from a separate fresh clone that the quickstart works
with the released package, not only the local checkout.

## 6. Configure external release services

Before pushing the tag:

- Configure PyPI Trusted Publishing for this repository's GitHub Actions workflow:
  `LearnedResponse/curiator`, workflow `release.yml`, environment `pypi`.
- Enable the GitHub to Zenodo integration for `LearnedResponse/curiator`.
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
TODOs that are release-blocked, and create/pin any public GitHub issues from
`docs/GOOD_FIRST_ISSUES.md` if new starter issues exist.
