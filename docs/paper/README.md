# curIAtor companion paper

This folder holds the Zenodo-first companion paper draft and the reproducibility notes for its
case-study numbers.

Current state:

- `curiator-paper.md` is a structured Markdown draft, not a publication-ready manuscript.
- `reproducibility.md` records the commands that must produce every quantitative table in the paper.
- `figures/feedback-loop.mmd` is the repo-native source for the feedback-loop diagram.
- `figures/provenance-log-excerpt.md` is the source for the git-as-memory provenance excerpt.
- `figures/shell-feedback-panel.png` is the generated shell and feedback-panel figure.
- `figures/render_shell_feedback_panel.py` regenerates the shell and feedback-panel figure.
- `figures/ot-rainbow-before-after.png` is the generated OT rainbow-to-HP-HMI before/after figure.
- `figures/render_ot_before_after.py` regenerates the OT rainbow-to-HP-HMI before/after figure.
- Public-collection numbers are placeholders until the example repositories are published and verified
  from fresh clones.

Release-time checklist:

1. Publish the three example collections.
2. Run the commands in `reproducibility.md` from fresh clones of those public repositories.
3. Replace every `TODO(release)` placeholder in `curiator-paper.md` with command-backed evidence.
4. Render or embed `figures/feedback-loop.mmd` without hand-redrawing a divergent copy.
5. Refresh `figures/provenance-log-excerpt.md` from a published example collection if the release
   evidence set changes.
6. Regenerate `figures/shell-feedback-panel.png` if the shell layout changes before release.
7. Regenerate `figures/ot-rainbow-before-after.png` from the release OT collection commit.
8. Build/export the PDF for Zenodo.
9. Add the Zenodo concept DOI to `CITATION.cff` and the README badge.

`python scripts/check_release_docs.py --strict-launch` fails while `curiator-paper.md` still contains
`TODO(release)` placeholders; the normal release-doc check allows them until the public evidence exists.
