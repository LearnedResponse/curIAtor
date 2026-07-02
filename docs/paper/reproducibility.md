# Reproducibility notes

Every quantitative claim in `curiator-paper.md` should be generated from a public collection ledger and
git history. Do not hand-enter case-study counts without recording the command that produced them.

## Release-time commands

Run these from a fresh clone of the runner repository after the public example collections are published
or checked out under `galleries/`. The runner tree should be clean before `make paper-stats`; it refuses
to write a paper snapshot marked `dirty` unless explicitly overridden for draft work:

```bash
curiator release-preflight --fresh-clone
make release-evidence
make paper-stats
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
paper-stats` reruns that bundle and refreshes the marked case-study stats block in
`curiator-paper.md` from the generated Markdown table.

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

`figures/feedback-loop.mmd` is the source for the feedback-loop diagram. Regenerate or embed it from
the Mermaid source at release time; do not hand-redraw a divergent copy.

Regenerate the shell and feedback-panel figure with:

```bash
python docs/paper/figures/render_shell_feedback_panel.py
```

`figures/provenance-log-excerpt.md` is the source for the git-as-memory excerpt. Refresh it from a
published collection with:

```bash
git -C galleries/curiator-phylogenetics log --format='%h %s%n%b----' -3
```

Regenerate the OT/HMI rainbow-to-HP-HMI before/after figure with:

```bash
python docs/paper/figures/render_ot_before_after.py
```

## Local pre-publication snapshot

The current local nested galleries are useful for draft shaping, but they are not publication evidence
until the repositories are public and verified from fresh clones.

As of this draft scaffold, the local command shape is:

```bash
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry \
  --markdown --output /tmp/curiator-local-case-study-stats.md
```

Copy final numbers into the paper only after rerunning the command at release time and recording the
runner commit plus each collection commit.
