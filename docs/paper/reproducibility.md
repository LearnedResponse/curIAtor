# Reproducibility notes

Every quantitative claim in `curiator-paper.md` should be generated from a public collection ledger and
git history. Do not hand-enter case-study counts without recording the command that produced them.

## Release-time commands

Run these from a fresh clone of the runner repository after the public example collections are published
or checked out under `galleries/`:

```bash
curiator release-preflight --fresh-clone
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --json
```

The compare table includes direct-fix, proposal, no-dispatch, and human-intervention rates derived
from ledger statuses; do not recalculate those columns by hand.

For per-collection appendix tables:

```bash
CURIATOR_GALLERY=galleries/curiator-aviato/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=galleries/curiator-ot/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator stats --markdown
```

Use `--csv` when building figures or spreadsheets:

```bash
CURIATOR_GALLERY=galleries/curiator-geometry/gallery.yaml curiator stats --csv
```

## Figures

`figures/feedback-loop.mmd` is the source for the feedback-loop diagram. Regenerate or embed it from
the Mermaid source at release time; do not hand-redraw a divergent copy.

`figures/provenance-log-excerpt.md` is the source for the git-as-memory excerpt. Refresh it from a
published collection with:

```bash
git -C galleries/curiator-phylogenetics log --format='%h %s%n%b----' -3
```

## Local pre-publication snapshot

The current local nested galleries are useful for draft shaping, but they are not publication evidence
until the repositories are public and verified from fresh clones.

As of this draft scaffold, the local command shape is:

```bash
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown
```

Copy final numbers into the paper only after rerunning the command at release time and recording the
runner commit plus each collection commit.
