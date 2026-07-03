# curIAtor companion paper

This folder holds the Zenodo-first companion paper draft and the reproducibility notes for its
case-study numbers.

Current state:

- `curiator-paper.md` is a structured Markdown release-candidate draft, not a publication-ready
  manuscript.
- `reproducibility.md` records the commands that must produce every quantitative claim in the paper.
- `figures/feedback-loop.mmd` is the repo-native source for the feedback-loop diagram.
- `figures/feedback-loop.png` is the generated paper figure rendered from that Mermaid source.
- `figures/render_feedback_loop.py` regenerates the feedback-loop figure without requiring Mermaid CLI.
- `figures/provenance-log-excerpt.md` is the source for the git-as-memory provenance excerpt.
- `figures/provenance-log-excerpt.png` is the generated paper figure rendered from that excerpt.
- `figures/render_provenance_log_excerpt.py` regenerates the git-as-memory excerpt figure.
- `figures/shell-feedback-panel.png` is the generated shell and feedback-panel figure.
- `figures/render_shell_feedback_panel.py` regenerates the shell and feedback-panel figure.
- `figures/ot-rainbow-before-after.png` is the generated OT rainbow-to-HP-HMI before/after figure.
- `figures/render_ot_before_after.py` regenerates the OT rainbow-to-HP-HMI before/after figure.
- Public-collection numbers are a dated release-candidate snapshot backed by public-head
  fresh-clone preflight; they are not DOI/publication evidence until the tagged release is archived.

Release-time checklist:

1. Keep the three example collection heads and runner branch published.
2. Run the commands in `reproducibility.md` from the release-candidate checkout and verify public-head
   fresh-clone preflight.
3. Run `make paper-stats` to refresh the marked case-study summary in `curiator-paper.md` with
   command-backed evidence from the public release repositories.
4. Run `make paper-pdf`, which regenerates the generated loop/provenance paper figures before export.
5. Refresh `figures/provenance-log-excerpt.md` from a published example collection if the release
   evidence set changes.
6. Regenerate `figures/shell-feedback-panel.png` if the shell layout changes before release.
7. Regenerate `figures/ot-rainbow-before-after.png` from the release OT collection commit.
8. Review `release-evidence/curiator-paper.pdf` before Zenodo deposit.
9. Add the Zenodo concept DOI to `CITATION.cff` and the README badge.

`python scripts/check_release_docs.py --strict-launch` rejects release-time placeholders and the
generated storyboard demo GIF; it should stay green before publishing.
