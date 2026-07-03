# Reproducibility notes

Every quantitative claim in `curiator-paper.md` should be generated from a public collection ledger and
git history. Do not hand-enter case-study counts without recording the command that produced them.

## Release-time commands

Run these from the release-candidate runner checkout after the public example collection heads are
published and checked out under `galleries/`. The runner tree should be clean before
`make paper-stats`; it refuses to write a paper snapshot marked `dirty` unless explicitly overridden
for draft work:

```bash
curiator release-preflight --fresh-clone
# optional shell-render gate when app dependencies and Brave/Chromium are installed:
curiator release-preflight --gallery curiator-aviato --browser-smoke
make release-evidence
make paper-stats
make paper-pdf
curiator release-preflight --fresh-clone --json --output release-evidence/release-preflight.json
curiator release-preflight --include-optional --fresh-clone --json \
  --output release-evidence/release-preflight-optional.json
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --json
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry \
  --markdown --output docs/paper/figures/case-study-stats.md
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry \
  --json --output release-evidence/case-study-stats.json
```

The compare report includes the runner version/git head and each collection's git branch/head plus
direct-fix, proposal, no-dispatch, and human-intervention rates derived from ledger statuses; do not
recalculate those columns by hand. The `--output` form is preferred for the final paper evidence
snapshot because it records the exact command product without shell-specific redirection. Keep raw JSON
snapshots under the gitignored `release-evidence/` directory because they include local checkout and
clone paths; commit only the portable Markdown/table excerpts that the paper actually cites.
`make release-evidence` refreshes the standard local bundle under `release-evidence/`; `make
paper-stats` reruns that bundle and refreshes the marked case-study summary block in
`curiator-paper.md` from the generated Markdown table. `make paper-pdf` regenerates the loop and
git-log provenance PNG figures, then exports `release-evidence/curiator-paper.pdf` from the tracked
Markdown draft with Pandoc/XeLaTeX; keep that PDF out of git and attach/review it as the Zenodo
manuscript artifact.

For per-collection appendix tables:

```bash
CURIATOR_GALLERY=galleries/curiator-aviato/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=galleries/curiator-ot/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml \
  curiator stats --markdown --output docs/paper/figures/curiator-geometry-stats.md
```

Use `--csv` when building figures or spreadsheets:

```bash
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator stats --csv
```

## Figures

`figures/feedback-loop.mmd` is the source for the feedback-loop diagram.
`figures/render_feedback_loop.py` renders it to `figures/feedback-loop.png`; `make paper-pdf` runs this
renderer before export. Do not hand-redraw a divergent copy.

Regenerate the shell and feedback-panel figure with:

```bash
python docs/paper/figures/render_shell_feedback_panel.py
```

`figures/provenance-log-excerpt.md` is the source for the git-as-memory excerpt.
`figures/render_provenance_log_excerpt.py` renders the first excerpted commit to
`figures/provenance-log-excerpt.png`; `make paper-pdf` runs this renderer before export. Refresh the
Markdown source from a published collection with:

```bash
git -C galleries/curiator-phylogenetics log --grep='^curator' --format='%h %s%n%b----' -3
```

Regenerate the OT/HMI rainbow-to-HP-HMI before/after figure with:

```bash
python docs/paper/figures/render_ot_before_after.py
```

## Current release-candidate snapshot

The current tracked paper summary is a release-candidate evidence snapshot: the required collection
heads are public, and the release preflight verifies their published heads from fresh temporary clones.
It is still not DOI evidence until the tagged GitHub release is archived by Zenodo.

Refresh the tracked Markdown summary with:

```bash
make paper-stats
```

Before publishing, rerun the public-head gate and confirm the collection heads in the paper summary still
match the release repositories:

```bash
curiator release-preflight --include-optional --fresh-clone --strict --require-public-remotes \
  --require-published-head --require-runner-public-remote --require-runner-published-head --no-smoke
```
